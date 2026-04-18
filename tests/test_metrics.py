from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.api.routes import job_service
from app.core.metrics import (
    METRICS_ENABLED_ENV,
    get_metrics_content_type,
    reset_metrics_state,
)
from app.main import app
from app.rules.llm_audit import set_default_client

client = TestClient(app)

CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,,Cadeira,,,SN-1,Sala 1,CC-1,,Observação\n"
)


class _FakeLLMClient:
    def __init__(
        self,
        *,
        response_text: str = '[]',
        error: Exception | None = None,
    ) -> None:
        self._response_text = response_text
        self._error = error

    def complete(
        self,
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del model, prompt, temperature, max_tokens
        if self._error is not None:
            raise self._error
        return self._response_text


@pytest.fixture(autouse=True)
def reset_metrics_test_state(monkeypatch: pytest.MonkeyPatch):
    job_service._jobs.clear()
    monkeypatch.delenv(METRICS_ENABLED_ENV, raising=False)
    reset_metrics_state()
    set_default_client(None)
    yield
    job_service._jobs.clear()
    reset_metrics_state()
    set_default_client(None)


def test_metrics_endpoint_disabled_by_default():
    response = client.get("/metrics")

    assert response.status_code == 404
    assert response.json()["detail"] == "Metrics endpoint disabled"


def test_metrics_endpoint_exposes_prometheus_payload_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(METRICS_ENABLED_ENV, "true")
    set_default_client(
        _FakeLLMClient(
            response_text=(
                '[{"issue":"Descrição suspeita","severity":"warning","field":"descricao"}]'
            )
        )
    )

    response = client.post(
        "/validate",
        params={"tenant_id": "empresa_exemplo"},
        files={"file": ("inventario.csv", BytesIO(CSV_CONTENT.encode("utf-8")), "text/csv")},
    )

    assert response.status_code == 200
    job = job_service.get_job(response.json()["job_id"])
    assert job is not None
    assert job.status.value == "completed"

    metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"] == get_metrics_content_type()
    body = metrics_response.text
    assert "validator_job_status_total" in body
    assert 'tenant_id="empresa_exemplo"' in body
    assert 'status="completed"' in body
    assert "validator_rule_executions_total" in body
    assert 'rule="zero_item_quality"' in body
    assert "validator_rule_issues_total" in body
    assert 'severity="warning"' in body
    assert "validator_llm_requests_total" in body
    assert 'rule="llm_audit"' in body
    assert 'outcome="success"' in body
    assert "validator_llm_request_duration_seconds" in body


def test_metrics_endpoint_tracks_llm_failures(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(METRICS_ENABLED_ENV, "1")
    set_default_client(_FakeLLMClient(error=RuntimeError("boom")))

    response = client.post(
        "/validate",
        params={"tenant_id": "empresa_exemplo"},
        files={"file": ("inventario.csv", BytesIO(CSV_CONTENT.encode("utf-8")), "text/csv")},
    )

    assert response.status_code == 200
    job = job_service.get_job(response.json()["job_id"])
    assert job is not None
    assert job.status.value == "completed"

    metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "validator_llm_requests_total" in metrics_response.text
    assert 'outcome="error"' in metrics_response.text
    assert "validator_llm_request_duration_seconds" in metrics_response.text
