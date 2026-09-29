from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..database import engine

router = APIRouter()


@router.get("/health")
def read_root() -> dict[str, str]:
    return {"Health": "Ok"}


@router.get("/ready")
def read_ready() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "database": "unavailable"},
        ) from error

    return {"status": "ready"}
