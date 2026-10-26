
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from database import engine
from etl import run_etl

app = FastAPI(
    title="DataFlow QA API",
    description="API para la validación y el procesamiento de datos.",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database", tags=["Health"])
def database_health_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {"status": "ok", "database": "connected"}

    except SQLAlchemyError:
        return {"status": "error", "database": "disconnected"}



@app.post("/etl/run", tags=["ETL"])
def execute_etl() -> dict:
    file_path = Path("/app/data/sales.csv")

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No se encontró el archivo de ventas.",
        )

    try:
        result = run_etl(file_path)

        # Convertir el DataFrame a una estructura compatible con JSON.
        result["rejected"] = result["rejected"].to_dict(orient="records")

        return result

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Falló la ejecución del proceso ETL.",
        ) from error
