import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import protected_path

client = TestClient(app)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/incidents", True),
        ("/incidents/12", True),
        ("/runs/5/steps", True),
        ("/metrics", True),
        ("/approvals/pending", False),
        ("/health", False),
        ("/incidentally", False),
    ],
)
def test_protected_path(path: str, expected: bool) -> None:
    assert protected_path(path) is expected


def test_api_access_key_guards_incident_routes_and_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_ACCESS_KEY", "local-test-key")

    assert client.post("/incidents", json={}).status_code == 401
    assert client.get("/metrics").status_code == 401
    assert (
        client.post(
            "/incidents", json={}, headers={"X-API-Key": "wrong-key"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/incidents", json={}, headers={"X-API-Key": "local-test-key"}
        ).status_code
        == 422
    )
    assert client.get("/health").status_code == 200


def test_create_incident_rejects_oversized_description() -> None:
    response = client.post(
        "/incidents",
        json={
            "title": "Long description",
            "service": "checkout",
            "severity": "low",
            "description": "x" * 4001,
        },
    )

    assert response.status_code == 422


def test_update_incident_rejects_oversized_description() -> None:
    response = client.patch(
        "/incidents/0", json={"description": "x" * 4001}
    )

    assert response.status_code == 422
