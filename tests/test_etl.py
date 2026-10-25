import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etl-api"))
from etl import validate_sales_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SALES_FILE = PROJECT_ROOT / "data" / "sales.csv"


def test_sales_file_validation_counts():
    result = validate_sales_file(SALES_FILE)

    assert result["records_read"] == 8
    assert result["records_processed"] == 4
    assert result["records_rejected"] == 4


def test_duplicate_transactions_are_rejected():
    result = validate_sales_file(SALES_FILE)

    duplicate_records = result["rejected"][
        result["rejected"]["transaction_id"] == "TX002"
    ]

    assert len(duplicate_records) == 2
    assert duplicate_records["rejection_reason"].str.contains(
        "transaction_id duplicado"
    ).all()


def test_invalid_date_is_rejected():
    result = validate_sales_file(SALES_FILE)

    invalid_date = result["rejected"][
        result["rejected"]["transaction_id"] == "TX006"
    ]

    assert len(invalid_date) == 1
    assert invalid_date.iloc[0]["rejection_reason"] == "fecha inválida"


def test_negative_amount_is_rejected():
    result = validate_sales_file(SALES_FILE)

    negative_amount = result["rejected"][
        result["rejected"]["transaction_id"] == "TX007"
    ]

    assert len(negative_amount) == 1
    assert negative_amount.iloc[0]["rejection_reason"] == (
        "importe debe ser mayor que cero"
    )
