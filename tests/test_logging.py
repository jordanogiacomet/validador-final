import json
import logging
import os
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.middleware import REQUEST_ID_HEADER
from app.core import logging as app_logging
from app.core.logging import (
    LOGGER_NAMESPACE,
    JsonFormatter,
    TextFormatter,
    configure_logging,
    generate_request_id,
    get_log_format,
    get_log_level,
    get_logger,
    get_request_id,
    log_event,
    reset_logging_configuration,
    reset_request_id,
    set_request_id,
)
from app.core.tenant_config import DEFAULT_TENANT_ID
from app.main import app


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def captured_records():
    reset_logging_configuration()
    handler = _RecordingHandler()
    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    app_logging._configured = True
    try:
        yield handler.records
    finally:
        logger.handlers = []
        reset_logging_configuration()


def _fields(record: logging.LogRecord) -> dict[str, object]:
    return getattr(record, "fields", {}) or {}


def _find_event(records, event: str) -> logging.LogRecord:
    for record in records:
        if getattr(record, "event", None) == event:
            return record
    raise AssertionError(f"Event not found: {event}")


def test_get_log_level_defaults_to_info():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LOG_LEVEL", None)
        assert get_log_level() == "INFO"


def test_get_log_level_respects_env():
    with patch.dict(os.environ, {"LOG_LEVEL": "debug"}):
        assert get_log_level() == "DEBUG"


def test_get_log_format_defaults_to_json():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LOG_FORMAT", None)
        assert get_log_format() == "json"


def test_get_log_format_falls_back_to_json_for_unknown_values():
    with patch.dict(os.environ, {"LOG_FORMAT": "yaml"}):
        assert get_log_format() == "json"


def test_get_log_format_accepts_text():
    with patch.dict(os.environ, {"LOG_FORMAT": "text"}):
        assert get_log_format() == "text"


def test_json_formatter_emits_standard_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="validator.job_service",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="job.created",
        args=(),
        exc_info=None,
    )
    record.event = "job.created"
    record.fields = {
        "tenant_id": "default",
        "job_id": "abc123",
        "request_id": "req-1",
    }

    payload = json.loads(formatter.format(record))
    assert payload["event"] == "job.created"
    assert payload["level"] == "info"
    assert payload["tenant_id"] == "default"
    assert payload["job_id"] == "abc123"
    assert payload["request_id"] == "req-1"
    assert "ts" in payload


def test_text_formatter_emits_key_value_pairs():
    formatter = TextFormatter()
    record = logging.LogRecord(
        name="validator",
        level=logging.WARNING,
        pathname=__file__,
        lineno=0,
        msg="job.failed",
        args=(),
        exc_info=None,
    )
    record.event = "job.failed"
    record.fields = {"tenant_id": "default", "error": "boom"}
    output = formatter.format(record)
    assert "job.failed" in output
    assert "tenant_id=default" in output
    assert "error=boom" in output


def test_log_event_includes_standard_fields(captured_records):
    logger = get_logger("test")
    log_event(
        logger,
        "custom.event",
        tenant_id="tenant-a",
        job_id="job-a",
        duration_ms=12.5,
        extra_field="value",
    )
    record = _find_event(captured_records, "custom.event")
    assert record.levelno == logging.INFO
    fields = _fields(record)
    assert fields["tenant_id"] == "tenant-a"
    assert fields["job_id"] == "job-a"
    assert fields["duration_ms"] == 12.5
    assert fields["extra_field"] == "value"


def test_log_event_picks_up_request_id_from_context(captured_records):
    logger = get_logger("test")
    token = set_request_id("req-test")
    try:
        log_event(logger, "custom.event", tenant_id="tenant-a")
    finally:
        reset_request_id(token)
    record = _find_event(captured_records, "custom.event")
    assert _fields(record)["request_id"] == "req-test"


def test_log_event_supports_warning_and_error_levels(captured_records):
    logger = get_logger("test")
    log_event(logger, "warn.event", level="warning")
    log_event(logger, "error.event", level="error", error="boom")
    assert _find_event(captured_records, "warn.event").levelno == logging.WARNING
    error_record = _find_event(captured_records, "error.event")
    assert error_record.levelno == logging.ERROR
    assert _fields(error_record)["error"] == "boom"


def test_configure_logging_respects_format_env(capsys):
    reset_logging_configuration()
    with patch.dict(os.environ, {"LOG_FORMAT": "json", "LOG_LEVEL": "INFO"}):
        configure_logging(force=True)
        logger = get_logger("env_test")
        log_event(logger, "env.event", tenant_id="tenant-x")
    captured = capsys.readouterr().out.strip().splitlines()
    assert captured
    payload = json.loads(captured[-1])
    assert payload["event"] == "env.event"
    assert payload["tenant_id"] == "tenant-x"
    reset_logging_configuration()


def test_generate_request_id_is_unique():
    first = generate_request_id()
    second = generate_request_id()
    assert first and second
    assert first != second


def test_request_id_context_round_trip():
    assert get_request_id() is None
    token = set_request_id("req-1")
    try:
        assert get_request_id() == "req-1"
    finally:
        reset_request_id(token)
    assert get_request_id() is None


def test_request_id_middleware_uses_incoming_header():
    client = TestClient(app)
    response = client.get("/health", headers={REQUEST_ID_HEADER: "req-abc"})
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER) == "req-abc"


def test_request_id_middleware_generates_request_id_when_missing():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assigned = response.headers.get(REQUEST_ID_HEADER)
    assert assigned
    assert len(assigned) >= 8


def test_job_service_emits_lifecycle_events(captured_records):
    from app.services.job_service import JobService

    service = JobService()
    job = service.create_job(tenant_id="tenant-a", file_name="lote.csv")
    service.start_job(job.job_id)
    service.complete_job(
        job_id=job.job_id,
        result_path="result.json",
        report_path="report.pdf",
        total_rows=10,
        rows_with_issues=3,
        total_issues=4,
    )

    created = _find_event(captured_records, "job.created")
    started = _find_event(captured_records, "job.started")
    completed = _find_event(captured_records, "job.completed")

    for record in (created, started, completed):
        fields = _fields(record)
        assert fields["tenant_id"] == "tenant-a"
        assert fields["job_id"] == job.job_id

    completed_fields = _fields(completed)
    assert "duration_ms" in completed_fields
    assert completed_fields["total_rows"] == 10


def test_job_service_emits_failure_event(captured_records):
    from app.services.job_service import JobService

    service = JobService()
    job = service.create_job(tenant_id="tenant-a", file_name="lote.csv")
    service.start_job(job.job_id)
    service.fail_job(job.job_id, "boom")

    failed = _find_event(captured_records, "job.failed")
    assert failed.levelno == logging.ERROR
    fields = _fields(failed)
    assert fields["tenant_id"] == "tenant-a"
    assert fields["job_id"] == job.job_id
    assert fields["error"] == "boom"
    assert "duration_ms" in fields


def test_validation_service_emits_started_and_completed_events(captured_records):
    from app.api.routes import job_service
    from app.services.validation_service import run_validation_job

    job_service._jobs.clear()
    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    )

    client = TestClient(app)
    response = client.post(
        "/validate",
        files={"file": ("inventario.csv", BytesIO(csv_content.encode("utf-8")), "text/csv")},
        params={"tenant_id": DEFAULT_TENANT_ID},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # Ensure the background task already ran — TestClient executes it synchronously.
    run_validation_job(job_id, job_service)

    started = _find_event(captured_records, "validation.started")
    completed = _find_event(captured_records, "validation.completed")

    started_fields = _fields(started)
    completed_fields = _fields(completed)

    assert started_fields["tenant_id"] == DEFAULT_TENANT_ID
    assert started_fields["job_id"] == job_id
    assert completed_fields["tenant_id"] == DEFAULT_TENANT_ID
    assert completed_fields["job_id"] == job_id
    assert "duration_ms" in completed_fields
