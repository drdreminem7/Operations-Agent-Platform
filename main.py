import os

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

app_name = os.getenv("APP_NAME", "Operations Agent Platform")
app = FastAPI(title=app_name)

database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://operations:operations@localhost:5433/operations"
)
engine = create_engine(database_url)


@app.get("/health")
def read_root() -> dict[str, str]:
    return {"Health": "Ok"}

@app.get("/ready")
def read_ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "unavailable"}
        ) from error

    return {"status": "ready"}

