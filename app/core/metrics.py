"""Prometheus metrics helpers for validator observability.

The registry lives in one place so the API layer can expose `/metrics` while
services and rules stay decoupled from Prometheus specifics. Instrumentation is
opt-in via environment variable and becomes a no-op when disabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

from app.core.issue import ValidationIssue

METRICS_ENABLED_ENV: Final[str] = "VALIDATOR_METRICS_ENABLED"
_TRUE_VALUES: Final[set[str]] = {"1", "true", "yes", "on"}

_JOB_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)
_RULE_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
)
_LLM_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
)
_LLM_RULE_NAME: Final[str] = "llm_audit"


@dataclass(slots=True)
class MetricsState:
    registry: CollectorRegistry
    job_status_total: Counter
    job_duration_seconds: Histogram
    rule_executions_total: Counter
    rule_duration_seconds: Histogram
    rule_issues_total: Counter
    llm_requests_total: Counter
    llm_request_duration_seconds: Histogram


_state: MetricsState | None = None


def metrics_enabled() -> bool:
    return os.getenv(METRICS_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def _normalize_label(value: str | None, *, default: str = "unknown") -> str:
    if value is None:
        return default
    normalized = value.strip().lower().replace(" ", "_")
    return normalized or default


def _seconds_from_ms(duration_ms: float | None) -> float:
    if duration_ms is None:
        return 0.0
    return max(duration_ms, 0.0) / 1000.0


def _build_state() -> MetricsState:
    registry = CollectorRegistry()
    return MetricsState(
        registry=registry,
        job_status_total=Counter(
            "validator_job_status_total",
            "Job lifecycle transitions by tenant and terminal or active status.",
            labelnames=("tenant_id", "status"),
            registry=registry,
        ),
        job_duration_seconds=Histogram(
            "validator_job_duration_seconds",
            "End-to-end validation job duration in seconds.",
            labelnames=("tenant_id", "status"),
            buckets=_JOB_DURATION_BUCKETS,
            registry=registry,
        ),
        rule_executions_total=Counter(
            "validator_rule_executions_total",
            "Validation rule executions by tenant and rule.",
            labelnames=("tenant_id", "rule"),
            registry=registry,
        ),
        rule_duration_seconds=Histogram(
            "validator_rule_duration_seconds",
            "Validation rule execution duration in seconds.",
            labelnames=("tenant_id", "rule"),
            buckets=_RULE_DURATION_BUCKETS,
            registry=registry,
        ),
        rule_issues_total=Counter(
            "validator_rule_issues_total",
            "Validation issues emitted by tenant, rule, and severity.",
            labelnames=("tenant_id", "rule", "severity"),
            registry=registry,
        ),
        llm_requests_total=Counter(
            "validator_llm_requests_total",
            "LLM audit requests by tenant, model, and outcome.",
            labelnames=("tenant_id", "rule", "model", "outcome"),
            registry=registry,
        ),
        llm_request_duration_seconds=Histogram(
            "validator_llm_request_duration_seconds",
            "LLM audit request duration in seconds.",
            labelnames=("tenant_id", "rule", "model", "outcome"),
            buckets=_LLM_DURATION_BUCKETS,
            registry=registry,
        ),
    )


def get_metrics_state() -> MetricsState:
    global _state
    if _state is None:
        _state = _build_state()
    return _state


def reset_metrics_state() -> None:
    global _state
    _state = None


def get_metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def render_metrics() -> bytes:
    return generate_latest(get_metrics_state().registry)


def record_job_status_transition(tenant_id: str, status: str) -> None:
    if not metrics_enabled():
        return

    get_metrics_state().job_status_total.labels(
        tenant_id=tenant_id,
        status=_normalize_label(status),
    ).inc()


def record_job_duration(tenant_id: str, status: str, duration_ms: float) -> None:
    if not metrics_enabled():
        return

    get_metrics_state().job_duration_seconds.labels(
        tenant_id=tenant_id,
        status=_normalize_label(status),
    ).observe(_seconds_from_ms(duration_ms))


def record_rule_execution(
    tenant_id: str,
    rule: str,
    duration_ms: float,
    issues: list[ValidationIssue],
) -> None:
    if not metrics_enabled():
        return

    state = get_metrics_state()
    labels = {
        "tenant_id": tenant_id,
        "rule": _normalize_label(rule),
    }
    state.rule_executions_total.labels(**labels).inc()
    state.rule_duration_seconds.labels(**labels).observe(_seconds_from_ms(duration_ms))

    for issue in issues:
        state.rule_issues_total.labels(
            tenant_id=tenant_id,
            rule=labels["rule"],
            severity=_normalize_label(issue.severity),
        ).inc()


def record_llm_request(
    tenant_id: str,
    model: str,
    duration_ms: float,
    *,
    outcome: str,
) -> None:
    if not metrics_enabled():
        return

    state = get_metrics_state()
    labels = {
        "tenant_id": tenant_id,
        "rule": _LLM_RULE_NAME,
        "model": _normalize_label(model),
        "outcome": _normalize_label(outcome),
    }
    state.llm_requests_total.labels(**labels).inc()
    state.llm_request_duration_seconds.labels(**labels).observe(
        _seconds_from_ms(duration_ms)
    )
