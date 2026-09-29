import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://operations:operations@localhost:5433/operations",
)
engine = create_engine(database_url)
