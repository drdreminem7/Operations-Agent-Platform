from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from main import app

client = TestClient(app)


def test_read_root() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"Health": "Ok"}

def test_ready_returns_200_when_database_is_available() -> None:
    with patch("main.engine.connect") as connect:
        connection = connect.return_value.__enter__.return_value
        response = client.get("/ready")

    connect.assert_called_once_with()
    connection.execute.assert_called_once()
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

def test_ready_returns_503_when_database_is_unavailable() -> None:
    with patch(
        "main.engine.connect",
        side_effect=SQLAlchemyError("database unavailable"),
    ):
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "not_ready",
            "database": "unavailable"
        }
    }
