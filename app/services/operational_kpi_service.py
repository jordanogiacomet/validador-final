from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.job import JobRecord, JobStatus
from app.core.llm_pricing import (
    LLMModelPricing,
    estimate_llm_cost_usd,
    load_llm_model_pricing,
)
from app.core.tenant_loader import canonicalize_tenant_id
from app.services.job_service import JobService


@dataclass(frozen=True)
class LLMModelUsageSnapshot:
    model: str
    provider_requests: int
    cache_hits: int
    successful_requests: int
    failed_requests: int
    findings: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class LLMUsageSnapshot:
    audited_rows: int
    provider_requests: int
    cache_hits: int
    successful_requests: int
    failed_requests: int
    findings: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    models: list[LLMModelUsageSnapshot]


@dataclass(frozen=True)
class OperationalTenantKPISnapshot:
    tenant_id: str | None
    total_jobs: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    canceled_jobs: int
    validated_rows: int
    source_rows: int
    rows_with_errors: int
    rows_with_warnings: int
    error_issue_count: int
    warning_issue_count: int
    error_rate: float
    warning_rate: float
    average_duration_ms: float | None
    llm: LLMUsageSnapshot


@dataclass(frozen=True)
class OperationalKPISnapshot:
    tenant_id: str | None
    created_from: datetime | None
    created_to: datetime | None
    generated_at: datetime
    summary: OperationalTenantKPISnapshot
    tenants: list[OperationalTenantKPISnapshot]


@dataclass
class _MutableLLMModelUsage:
    provider_requests: int = 0
    cache_hits: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    findings: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _MutableLLMUsage:
    audited_rows: int = 0
    provider_requests: int = 0
    cache_hits: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    findings: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    models: dict[str, _MutableLLMModelUsage] = field(default_factory=dict)


@dataclass
class _MutableTenantKPIs:
    tenant_id: str | None
    total_jobs: int = 0
    queued_jobs: int = 0
    running_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    canceled_jobs: int = 0
    validated_rows: int = 0
    source_rows: int = 0
    rows_with_errors: int = 0
    rows_with_warnings: int = 0
    error_issue_count: int = 0
    warning_issue_count: int = 0
    completed_duration_total_ms: float = 0.0
    completed_duration_count: int = 0
    llm: _MutableLLMUsage = field(default_factory=_MutableLLMUsage)


class OperationalKPIService:
    def __init__(
        self,
        *,
        job_service: JobService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._job_service = job_service
        self._clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        *,
        tenant_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> OperationalKPISnapshot:
        resolved_tenant_id = (
            canonicalize_tenant_id(tenant_id) if tenant_id is not None else None
        )
        normalized_created_from = _normalize_datetime(created_from)
        normalized_created_to = _normalize_datetime(created_to)
        pricing = load_llm_model_pricing()

        tenant_buckets: dict[str, _MutableTenantKPIs] = {}
        summary_bucket = _MutableTenantKPIs(tenant_id=resolved_tenant_id)

        for job in self._job_service.list_jobs(tenant_id=resolved_tenant_id):
            if not _job_in_window(
                job,
                created_from=normalized_created_from,
                created_to=normalized_created_to,
            ):
                continue

            bucket = tenant_buckets.setdefault(
                job.tenant_id,
                _MutableTenantKPIs(tenant_id=job.tenant_id),
            )
            result_payload = _load_job_result_payload(job)
            _accumulate_job(bucket, job=job, result_payload=result_payload)
            _accumulate_job(summary_bucket, job=job, result_payload=result_payload)

        tenant_snapshots = [
            _build_tenant_snapshot(bucket, pricing=pricing)
            for _tenant_id, bucket in sorted(tenant_buckets.items())
        ]

        return OperationalKPISnapshot(
            tenant_id=resolved_tenant_id,
            created_from=normalized_created_from,
            created_to=normalized_created_to,
            generated_at=self._clock(),
            summary=_build_tenant_snapshot(summary_bucket, pricing=pricing),
            tenants=tenant_snapshots,
        )


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _job_in_window(
    job: JobRecord,
    *,
    created_from: datetime | None,
    created_to: datetime | None,
) -> bool:
    created_at = _normalize_datetime(job.created_at)
    if created_from is not None and created_at is not None and created_at < created_from:
        return False
    if created_to is not None and created_at is not None and created_at > created_to:
        return False
    return True


def _load_job_result_payload(job: JobRecord) -> dict[str, Any] | None:
    if not job.result_path:
        return None
    result_path = Path(job.result_path)
    if not result_path.exists():
        return None
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _accumulate_job(
    bucket: _MutableTenantKPIs,
    *,
    job: JobRecord,
    result_payload: dict[str, Any] | None,
) -> None:
    bucket.total_jobs += 1
    if job.status is JobStatus.QUEUED:
        bucket.queued_jobs += 1
        return
    if job.status is JobStatus.RUNNING:
        bucket.running_jobs += 1
        return
    if job.status is JobStatus.FAILED:
        bucket.failed_jobs += 1
        return
    if job.status is JobStatus.CANCELED:
        bucket.canceled_jobs += 1
        return
    if job.status is not JobStatus.COMPLETED:
        return

    bucket.completed_jobs += 1
    duration_ms = _job_duration_ms(job)
    if duration_ms is not None:
        bucket.completed_duration_total_ms += duration_ms
        bucket.completed_duration_count += 1

    summary = _read_result_summary(result_payload)
    if summary is not None:
        bucket.validated_rows += summary["validated_rows"]
        bucket.source_rows += summary["source_rows"]
        bucket.error_issue_count += summary["error_issue_count"]
        bucket.warning_issue_count += summary["warning_issue_count"]
    else:
        bucket.validated_rows += _coerce_non_negative_int(job.total_rows)
        bucket.source_rows += _coerce_non_negative_int(
            job.source_total_rows or job.total_rows
        )

    row_counts = _read_result_row_counts(result_payload)
    if row_counts is not None:
        bucket.rows_with_errors += row_counts["rows_with_errors"]
        bucket.rows_with_warnings += row_counts["rows_with_warnings"]

    llm_usage = _read_result_llm_usage(result_payload)
    if llm_usage is not None:
        _accumulate_llm_usage(bucket.llm, llm_usage)


def _job_duration_ms(job: JobRecord) -> float | None:
    if job.updated_at is None or job.created_at is None:
        return None
    return max((job.updated_at - job.created_at).total_seconds() * 1000.0, 0.0)


def _read_result_summary(result_payload: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(result_payload, dict):
        return None
    summary = result_payload.get("summary")
    if not isinstance(summary, dict):
        return None
    validated_rows = _coerce_non_negative_int(
        summary.get("validated_rows", summary.get("total_rows", 0))
    )
    source_rows = _coerce_non_negative_int(
        summary.get("source_total_rows", summary.get("total_rows", validated_rows))
    )
    return {
        "validated_rows": validated_rows,
        "source_rows": source_rows,
        "error_issue_count": _coerce_non_negative_int(summary.get("error_count", 0)),
        "warning_issue_count": _coerce_non_negative_int(
            summary.get("warning_count", 0)
        ),
    }


def _read_result_row_counts(
    result_payload: dict[str, Any] | None,
) -> dict[str, int] | None:
    if not isinstance(result_payload, dict):
        return None
    row_results = result_payload.get("row_results")
    if not isinstance(row_results, list):
        return None
    rows_with_errors = 0
    rows_with_warnings = 0
    for row in row_results:
        if not isinstance(row, dict):
            continue
        if bool(row.get("has_errors")):
            rows_with_errors += 1
        if bool(row.get("has_warnings")):
            rows_with_warnings += 1
    return {
        "rows_with_errors": rows_with_errors,
        "rows_with_warnings": rows_with_warnings,
    }


def _read_result_llm_usage(
    result_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(result_payload, dict):
        return None
    llm_audit = result_payload.get("llm_audit")
    if not isinstance(llm_audit, dict):
        return None
    usage = llm_audit.get("usage")
    if not isinstance(usage, dict):
        return None
    return usage


def _accumulate_llm_usage(target: _MutableLLMUsage, usage: dict[str, Any]) -> None:
    target.audited_rows += _coerce_non_negative_int(usage.get("audited_rows", 0))
    target.provider_requests += _coerce_non_negative_int(
        usage.get("provider_requests", 0)
    )
    target.cache_hits += _coerce_non_negative_int(usage.get("cache_hits", 0))
    target.successful_requests += _coerce_non_negative_int(
        usage.get("successful_requests", 0)
    )
    target.failed_requests += _coerce_non_negative_int(
        usage.get("failed_requests", 0)
    )
    target.findings += _coerce_non_negative_int(usage.get("findings", 0))
    target.input_tokens += _coerce_non_negative_int(usage.get("input_tokens", 0))
    target.output_tokens += _coerce_non_negative_int(usage.get("output_tokens", 0))

    model_entries = usage.get("models")
    if not isinstance(model_entries, list):
        return

    for raw_entry in model_entries:
        if not isinstance(raw_entry, dict):
            continue
        model = str(raw_entry.get("model", "")).strip()
        if not model:
            continue
        model_bucket = target.models.setdefault(model, _MutableLLMModelUsage())
        model_bucket.provider_requests += _coerce_non_negative_int(
            raw_entry.get("provider_requests", 0)
        )
        model_bucket.cache_hits += _coerce_non_negative_int(
            raw_entry.get("cache_hits", 0)
        )
        model_bucket.successful_requests += _coerce_non_negative_int(
            raw_entry.get("successful_requests", 0)
        )
        model_bucket.failed_requests += _coerce_non_negative_int(
            raw_entry.get("failed_requests", 0)
        )
        model_bucket.findings += _coerce_non_negative_int(raw_entry.get("findings", 0))
        model_bucket.input_tokens += _coerce_non_negative_int(
            raw_entry.get("input_tokens", 0)
        )
        model_bucket.output_tokens += _coerce_non_negative_int(
            raw_entry.get("output_tokens", 0)
        )


def _build_tenant_snapshot(
    bucket: _MutableTenantKPIs,
    *,
    pricing: Mapping[str, LLMModelPricing],
) -> OperationalTenantKPISnapshot:
    validated_rows = bucket.validated_rows
    average_duration_ms = (
        round(bucket.completed_duration_total_ms / bucket.completed_duration_count, 2)
        if bucket.completed_duration_count
        else None
    )
    llm_snapshot = _build_llm_usage_snapshot(bucket.llm, pricing=pricing)
    return OperationalTenantKPISnapshot(
        tenant_id=bucket.tenant_id,
        total_jobs=bucket.total_jobs,
        queued_jobs=bucket.queued_jobs,
        running_jobs=bucket.running_jobs,
        completed_jobs=bucket.completed_jobs,
        failed_jobs=bucket.failed_jobs,
        canceled_jobs=bucket.canceled_jobs,
        validated_rows=validated_rows,
        source_rows=bucket.source_rows,
        rows_with_errors=bucket.rows_with_errors,
        rows_with_warnings=bucket.rows_with_warnings,
        error_issue_count=bucket.error_issue_count,
        warning_issue_count=bucket.warning_issue_count,
        error_rate=_safe_rate(bucket.rows_with_errors, validated_rows),
        warning_rate=_safe_rate(bucket.rows_with_warnings, validated_rows),
        average_duration_ms=average_duration_ms,
        llm=llm_snapshot,
    )


def _build_llm_usage_snapshot(
    usage: _MutableLLMUsage,
    *,
    pricing: Mapping[str, LLMModelPricing],
) -> LLMUsageSnapshot:
    model_snapshots = [
        _build_llm_model_snapshot(model, bucket, pricing=pricing)
        for model, bucket in sorted(usage.models.items())
    ]
    return LLMUsageSnapshot(
        audited_rows=usage.audited_rows,
        provider_requests=usage.provider_requests,
        cache_hits=usage.cache_hits,
        successful_requests=usage.successful_requests,
        failed_requests=usage.failed_requests,
        findings=usage.findings,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=_estimate_total_llm_cost_usd(model_snapshots),
        models=model_snapshots,
    )


def _build_llm_model_snapshot(
    model: str,
    usage: _MutableLLMModelUsage,
    *,
    pricing: Mapping[str, LLMModelPricing],
) -> LLMModelUsageSnapshot:
    return LLMModelUsageSnapshot(
        model=model,
        provider_requests=usage.provider_requests,
        cache_hits=usage.cache_hits,
        successful_requests=usage.successful_requests,
        failed_requests=usage.failed_requests,
        findings=usage.findings,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=estimate_llm_cost_usd(
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            pricing=pricing,
        ),
    )


def _estimate_total_llm_cost_usd(
    models: list[LLMModelUsageSnapshot],
) -> float | None:
    if not models:
        return 0.0

    total = 0.0
    has_provider_usage = False
    for model in models:
        if model.provider_requests > 0:
            has_provider_usage = True
            if model.estimated_cost_usd is None:
                return None
        if model.estimated_cost_usd is not None:
            total += model.estimated_cost_usd

    if not has_provider_usage:
        return 0.0
    return round(total, 8)


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _coerce_non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0
