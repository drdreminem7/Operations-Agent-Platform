from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app

client = TestClient(app)


def test_read_root() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"Health": "Ok"}


def test_ready_returns_200_when_database_is_available() -> None:
    with patch("app.routes.health.engine.connect") as connect:
        connection = connect.return_value.__enter__.return_value
        response = client.get("/ready")

    connect.assert_called_once_with()
    connection.execute.assert_called_once()
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_when_database_is_unavailable() -> None:
    with patch(
        "app.routes.health.engine.connect",
        side_effect=SQLAlchemyError("database unavailable"),
    ):
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"status": "not_ready", "database": "unavailable"}
    }


def test_create_incident_returns_created_incident() -> None:
    response = client.post(
        "/incidents",
        json={
            "title": "Checkout latency",
            "service": "checkout",
            "severity": "high",
            "description": "Requests are taking too long.",
        },
    )

    assert response.status_code == 201

    incident = response.json()
    assert isinstance(incident["id"], int)
    assert incident["title"] == "Checkout latency"
    assert incident["service"] == "checkout"
    assert incident["severity"] == "high"
    assert incident["description"] == "Requests are taking too long."
    assert incident["status"] == "open"
    assert incident["started_at"] is None
    assert isinstance(incident["created_at"], str)
    assert isinstance(incident["updated_at"], str)


def test_create_incident_without_title_returns_422() -> None:
    response = client.post(
        "/incidents",
        json={"service": "checkout", "severity": "high"},
    )

    assert response.status_code == 422


def test_get_incident_returns_exising_incident() -> None:
    create_response = client.post(
        "/incidents",
        json={
            "title": "Checkout latency for GET test",
            "service": "checkout",
            "severity": "high",
        },
    )

    incident_id = create_response.json()["id"]

    response = client.get(f"/incidents/{incident_id}")

    assert response.status_code == 200
    assert response.json()["id"] == incident_id
    assert response.json()["title"] == "Checkout latency for GET test"
    assert response.json()["status"] == "open"


def test_get_incident_returns_404_when_missing() -> None:
    response = client.get("/incidents/949509")

    assert response.status_code == 404
    assert response.json() == {"detail": "Incident not found"}


def test_list_incidents_includes_created_incident() -> None:
    create_response = client.post(
        "/incidents",
        json={
            "title": "Incident for list test",
            "service": "checkout",
            "severity": "high",
        },
    )

    incident_id = create_response.json()["id"]

    response = client.get("/incidents")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert any(incident["id"] == incident_id for incident in response.json())


def test_list_incidents_rejects_limit_over_100() -> None:
    response = client.get("/incidents?limit=101")
    assert response.status_code == 422


def test_update_incident_changes_only_sent_fields() -> None:
    create_response = client.post(
        "/incidents",
        json={
            "title": "Incident before update",
            "service": "checkout",
            "severity": "high",
        },
    )

    incident_id = create_response.json()["id"]

    response = client.patch(
        f"/incidents/{incident_id}",
        json={"title": "Incident after update", "description": None},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Incident after update"
    assert response.json()["service"] == "checkout"
    assert response.json()["status"] == "open"
    assert response.json()["description"] is None


def test_update_missing_incident_returns_404() -> None:
    response = client.patch("/incidents/0", json={"status": "resolved"})

    assert response.status_code == 404


def test_update_incident_rejects_null_title() -> None:
    response = client.patch("/incidents/0", json={"title": None})

    assert response.status_code == 422
