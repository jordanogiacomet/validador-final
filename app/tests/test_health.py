from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [check["name"] for check in payload["checks"]] == [
        "uploads",
        "results",
        "job_store",
    ]
