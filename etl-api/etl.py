
from pathlib import Path
import pandas as pd
from sqlalchemy import MetaData, Table
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
    """Valida el CSV y carga las ventas válidas en PostgreSQL."""
    validation_result = validate_sales_file(file_path)

    inserted = load_valid_sales(validation_result["valid"])

    return {
        "records_read": validation_result["records_read"],
        "records_processed": inserted,
        "records_rejected": validation_result["records_rejected"],
        "rejected": validation_result["rejected"],
    }

