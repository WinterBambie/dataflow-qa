import json
from pathlib import Path
import pandas as pd
from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert
from database import engine

EXPECTED_COLUMNS = [
    "transaction_id",
    "sale_date",
    "customer_id",
    "product",
    "amount",
]


def validate_sales_file(file_path: str | Path) -> dict:
    """Lee un CSV de ventas y separa registros válidos y rechazados."""
    df = pd.read_csv(
        file_path,
        dtype=str,
        keep_default_na=False,
    )

    missing_columns = set(EXPECTED_COLUMNS) - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Faltan columnas obligatorias: {sorted(missing_columns)}"
        )

    df = df[EXPECTED_COLUMNS].copy()

    # Limpiar espacios y normalizar campos de texto.
    for column in ["transaction_id", "customer_id", "product"]:
        df[column] = df[column].str.strip()

    df["sale_date"] = df["sale_date"].str.strip()
    df["amount"] = df["amount"].str.strip()

    # Validar fechas y valores numéricos.
    parsed_dates = pd.to_datetime(
        df["sale_date"],
        format="%Y-%m-%d",
        errors="coerce",
    )
    parsed_amounts = pd.to_numeric(df["amount"], errors="coerce")

    reasons = [[] for _ in range(len(df))]

    for position, (_, row) in enumerate(df.iterrows()):
        if not row["transaction_id"]:
            reasons[position].append("transaction_id vacío")

        if not row["customer_id"]:
            reasons[position].append("customer_id vacío")

        if not row["product"]:
            reasons[position].append("product vacío")

        if pd.isna(parsed_dates.iloc[position]):
            reasons[position].append("fecha inválida")

        amount = parsed_amounts.iloc[position]
        if pd.isna(amount):
            reasons[position].append("importe no numérico")
        elif amount <= 0:
            reasons[position].append("importe debe ser mayor que cero")

    # Rechazar todas las filas que compartan un identificador duplicado.
    duplicate_ids = set(
        df.loc[
            df["transaction_id"].ne("")
            & df["transaction_id"].duplicated(keep=False),
            "transaction_id",
        ]
    )

    for position, transaction_id in enumerate(df["transaction_id"]):
        if transaction_id in duplicate_ids:
            reasons[position].append("transaction_id duplicado")

    rejected_mask = pd.Series(
        [bool(row_reasons) for row_reasons in reasons],
        index=df.index,
    )

    valid = df.loc[~rejected_mask].copy()
    rejected = df.loc[rejected_mask].copy()

    valid["sale_date"] = parsed_dates.loc[valid.index].dt.date
    valid["amount"] = parsed_amounts.loc[valid.index]

    rejected["rejection_reason"] = [
        "; ".join(reasons[position])
        for position, is_rejected in enumerate(rejected_mask)
        if is_rejected
    ]

    return {
        "records_read": len(df),
        "records_processed": len(valid),
        "records_rejected": len(rejected),
        "valid": valid,
        "rejected": rejected,
    }

def load_valid_sales(valid_records: pd.DataFrame) -> int:
    """Guarda las ventas válidas y devuelve el número de filas insertadas."""
    if valid_records.empty:
        return 0

    metadata = MetaData()
    sales_table = Table(
        "sales",
        metadata,
        autoload_with=engine,
    )

    records = valid_records.to_dict(orient="records")

    statement = (
        insert(sales_table)
        .values(records)
        .on_conflict_do_nothing(
            index_elements=["transaction_id"]
        )
        .returning(sales_table.c.transaction_id)
    )

    with engine.begin() as connection:
        inserted_ids = connection.execute(statement).fetchall()

    return len(inserted_ids)




def run_etl(file_path: str | Path) -> dict:
    """Valida, carga los datos y registra el resultado de la ejecución."""
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                INSERT INTO etl_runs (status)
                VALUES ('running')
                RETURNING id
                """
            )
        )
        run_id = result.scalar_one()

    try:
        validation_result = validate_sales_file(file_path)

        inserted = load_valid_sales(validation_result["valid"])

        rejected_saved = save_rejected_records(
            validation_result["rejected"], run_id,
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE etl_runs
                    SET finished_at = CURRENT_TIMESTAMP,
                        status = 'success',
                        records_read = :records_read,
                        records_processed = :records_processed,
                        records_rejected = :records_rejected
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "records_read": validation_result["records_read"],
                    "records_processed": inserted,
                    "records_rejected": validation_result["records_rejected"],
                },
            )

        return {
            "run_id": run_id,
            "records_read": validation_result["records_read"],
            "records_processed": inserted,
            "records_rejected": validation_result["records_rejected"],
            "rejected_records_saved": rejected_saved,
            "rejected": validation_result["rejected"],
        }

    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE etl_runs
                    SET finished_at = CURRENT_TIMESTAMP,
                        status = 'failed',
                        error_message = :error_message
                    WHERE id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "error_message": str(error)[:2000],
                },
            )
        raise


def save_rejected_records(rejected_records: pd.DataFrame, run_id: int) -> int:
    """Guarda los registros rechazados y sus motivos en PostgreSQL."""
    if rejected_records.empty:
        return 0

    metadata = MetaData()
    rejected_table = Table(
        "rejected_records",
        metadata,
        autoload_with=engine,
    )

    records = []

    for _, row in rejected_records.iterrows():
        raw_record = {
            column: (
                value.isoformat()
                if hasattr(value, "isoformat")
                else str(value)
                if not isinstance(value, (str, int, float, bool))
                else value
            )
            for column, value in row.drop(
                labels=["rejection_reason"]
            ).items()
        }

        records.append(
            {
                "transaction_id": raw_record.get("transaction_id") or None,
                "raw_record": json.dumps(raw_record, ensure_ascii=False),
                "rejection_reason": row["rejection_reason"],
                "run_id": run_id,
            }
        )


    statement = (
        insert(rejected_table)
        .values(records)
        .returning(rejected_table.c.id)
    )

    with engine.begin() as connection:
        inserted_ids = connection.execute(statement).fetchall()

    return len(inserted_ids)
