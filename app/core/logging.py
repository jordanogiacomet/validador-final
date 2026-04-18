"""Structured JSON logging with tenant/job/request correlation.

Kept intentionally thin so every layer (API, services, workers) can emit the
same event shape without coupling to FastAPI, the job store, or a specific
tenant. Context (``request_id``) flows through a contextvar so log sites do not
have to thread it manually.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

LOGGER_NAMESPACE = "validator"
LOG_FORMAT_JSON = "json"
LOG_FORMAT_TEXT = "text"

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "validator_request_id",
    default=None,
)

_configured = False


def get_log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO").upper()


def get_log_format() -> str:
    value = os.getenv("LOG_FORMAT", LOG_FORMAT_JSON).lower()
    return value if value in (LOG_FORMAT_JSON, LOG_FORMAT_TEXT) else LOG_FORMAT_JSON


def _format_ts(created: float) -> str:
    return datetime.fromtimestamp(created, tz=UTC).isoformat()


def _record_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = getattr(record, "fields", None)
    if isinstance(fields, Mapping):
        return {k: v for k, v in fields.items() if v is not None}
    return {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _format_ts(record.created),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.getMessage()),
        }
        payload.update(_record_fields(record))
        if record.exc_info and "error" not in payload:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = _record_fields(record)
        parts = [
            _format_ts(record.created),
            record.levelname,
            getattr(record, "event", record.getMessage()),
        ]
        parts.extend(f"{key}={value}" for key, value in fields.items())
        return " | ".join(parts)


def configure_logging(*, force: bool = False) -> None:
    global _configured
    if _configured and not force:
        return

    level = getattr(logging, get_log_level(), logging.INFO)
    log_format = get_log_format()

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = JsonFormatter() if log_format == LOG_FORMAT_JSON else TextFormatter()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger(LOGGER_NAMESPACE)
    root_logger.handlers = [handler]
    root_logger.setLevel(level)
    root_logger.propagate = False

    _configured = True


def reset_logging_configuration() -> None:
    global _configured
    _configured = False
    logger = logging.getLogger(LOGGER_NAMESPACE)
    logger.handlers = []


def get_logger(name: str | None = None) -> logging.Logger:
    configure_logging()
    if not name:
        return logging.getLogger(LOGGER_NAMESPACE)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")


def generate_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(request_id: str | None) -> contextvars.Token:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: str = "info",
    tenant_id: str | None = None,
    job_id: str | None = None,
    duration_ms: float | None = None,
    error: str | None = None,
    **extra: Any,
) -> None:
    configure_logging()
    level_value = getattr(logging, level.upper(), logging.INFO)

    fields: dict[str, Any] = {}
    if tenant_id is not None:
        fields["tenant_id"] = tenant_id
    if job_id is not None:
        fields["job_id"] = job_id
    if duration_ms is not None:
        fields["duration_ms"] = duration_ms
    if error is not None:
        fields["error"] = error

    request_id = _request_id_var.get()
    if request_id is not None:
        fields["request_id"] = request_id

    for key, value in extra.items():
        if value is not None:
            fields[key] = value

    logger.log(level_value, event, extra={"event": event, "fields": fields})
