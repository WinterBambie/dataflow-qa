

import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "etl-api"))

import main
from main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health_endpoint():
    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "connected",
    }

def test_etl_run_returns_json(tmp_path, monkeypatch):
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text(
        "transaction_id,sale_date,customer_id,product,amount\n"
        "TX001,2026-10-20,C001,Keyboard,120.00\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(main, "run_etl", lambda file_path: {
        "run_id": 99,
        "records_read": 1,
        "records_validated": 1,
        "records_processed": 1,
        "records_rejected": 0,
        "rejected_records_saved": 0,
        "rejected": pd.DataFrame(
            columns=[
                "transaction_id",
                "sale_date",
                "customer_id",
                "product",
                "amount",
                "rejection_reason",
            ]
        ),
    })

    monkeypatch.setattr(main.app.state, "etl_file_path", csv_file, raising=False)

    response = client.post("/etl/run")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 99
    assert body["records_read"] == 1
    assert body["records_rejected"] == 0
    assert body["rejected"] == []


def test_etl_run_returns_404_when_file_is_missing(tmp_path, monkeypatch):
    missing_file = tmp_path / "missing.csv"

    monkeypatch.setattr(
        main.app.state,
        "etl_file_path",
        missing_file,
        raising=False,
    )

    response = client.post("/etl/run")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No se encontró el archivo de ventas."
    }
    
def test_etl_run_returns_500_when_etl_fails(tmp_path, monkeypatch):
    csv_file = tmp_path / "sales.csv"
    csv_file.write_text(
        "transaction_id,sale_date,customer_id,product,amount\n"
        "TX001,2026-10-20,C001,Keyboard,120.00\n",
        encoding="utf-8",
    )

    def failing_etl(file_path):
        raise RuntimeError("Simulated ETL failure")

    monkeypatch.setattr(main, "run_etl", failing_etl)
    monkeypatch.setattr(
        main.app.state,
        "etl_file_path",
        csv_file,
        raising=False,
    )

    response = client.post("/etl/run")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Falló la ejecución del proceso ETL."
    }

