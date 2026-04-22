import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.job_service import JobService
from app.services.operational_kpi_service import OperationalKPIService


def _write_result_payload(
    path: Path,
    *,
    total_rows: int,
    source_total_rows: int,
    error_count: int,
    warning_count: int,
    row_results: list[dict],
    llm_usage: dict | None = None,
) -> None:
    payload = {
        "summary": {
            "total_rows": total_rows,
            "validated_rows": total_rows,
            "source_total_rows": source_total_rows,
            "rows_with_issues": sum(
                1
                for row in row_results
                if row.get("has_errors") or row.get("has_warnings")
            ),
            "total_issues": error_count + warning_count,
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "row_results": row_results,
        "duplicates": [],
        "grouped_problems": {},
    }
    if llm_usage is not None:
        payload["llm_audit"] = {
            "prompt_versions": ["empresa_exemplo-v1"],
            "models": [model["model"] for model in llm_usage.get("models", [])],
            "usage": llm_usage,
        }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _finalize_completed_job(
    service: JobService,
    *,
    tenant_id: str,
    result_path: Path,
    created_at: datetime,
    duration_seconds: int,
    total_rows: int,
    source_total_rows: int,
    rows_with_issues: int,
    total_issues: int,
) -> None:
    job = service.create_job(
        tenant_id=tenant_id,
        file_name=f"{tenant_id}.csv",
    )
    service.start_job(job.job_id)
    service.complete_job(
        job.job_id,
        result_path=str(result_path),
        total_rows=total_rows,
        source_total_rows=source_total_rows,
        rows_with_issues=rows_with_issues,
        total_issues=total_issues,
    )
    persisted = service.get_job(job.job_id)
    assert persisted is not None
    persisted.created_at = created_at
    persisted.updated_at = created_at + timedelta(seconds=duration_seconds)
    service.save_job(job.job_id)


def _finalize_failed_job(
    service: JobService,
    *,
    tenant_id: str,
    created_at: datetime,
) -> None:
    job = service.create_job(
        tenant_id=tenant_id,
        file_name=f"{tenant_id}-failed.csv",
    )
    service.fail_job(job.job_id, "boom")
    persisted = service.get_job(job.job_id)
    assert persisted is not None
    persisted.created_at = created_at
    persisted.updated_at = created_at + timedelta(seconds=5)
    service.save_job(job.job_id)


def test_collect_operational_kpis_aggregates_tenant_metrics_and_llm_costs(
    tmp_path,
    monkeypatch,
):
    service = JobService()

    default_result_path = tmp_path / "default-result.json"
    _write_result_payload(
        default_result_path,
        total_rows=2,
        source_total_rows=3,
        error_count=1,
        warning_count=1,
        row_results=[
            {"row_index": 0, "has_errors": True, "has_warnings": False},
            {"row_index": 1, "has_errors": False, "has_warnings": True},
        ],
        llm_usage={
            "audited_rows": 2,
            "provider_requests": 1,
            "cache_hits": 1,
            "successful_requests": 1,
            "failed_requests": 0,
            "findings": 1,
            "input_tokens": 1000,
            "output_tokens": 500,
            "models": [
                {
                    "model": "claude-sonnet-4-20250514",
                    "provider_requests": 1,
                    "cache_hits": 1,
                    "successful_requests": 1,
                    "failed_requests": 0,
                    "findings": 1,
                    "input_tokens": 1000,
                    "output_tokens": 500,
                }
            ],
        },
    )
    _finalize_completed_job(
        service,
        tenant_id="default",
        result_path=default_result_path,
        created_at=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
        duration_seconds=10,
        total_rows=2,
        source_total_rows=3,
        rows_with_issues=2,
        total_issues=2,
    )
    _finalize_failed_job(
        service,
        tenant_id="default",
        created_at=datetime(2026, 4, 20, 11, 0, tzinfo=UTC),
    )

    redesim_result_path = tmp_path / "redesim-result.json"
    _write_result_payload(
        redesim_result_path,
        total_rows=1,
        source_total_rows=1,
        error_count=0,
        warning_count=1,
        row_results=[
            {"row_index": 0, "has_errors": False, "has_warnings": True},
        ],
    )
    _finalize_completed_job(
        service,
        tenant_id="redesim",
        result_path=redesim_result_path,
        created_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        duration_seconds=20,
        total_rows=1,
        source_total_rows=1,
        rows_with_issues=1,
        total_issues=1,
    )

    monkeypatch.setenv(
        "VALIDATOR_LLM_PRICING_JSON",
        json.dumps(
            {
                "claude-sonnet-4-20250514": {
                    "input_per_million_tokens_usd": 3.0,
                    "output_per_million_tokens_usd": 15.0,
                }
            }
        ),
    )
    kpi_service = OperationalKPIService(
        job_service=service,
        clock=lambda: datetime(2026, 4, 22, 15, 0, tzinfo=UTC),
    )

    snapshot = kpi_service.collect(
        created_from=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
        created_to=datetime(2026, 4, 20, 23, 59, tzinfo=UTC),
    )

    assert snapshot.summary.total_jobs == 3
    assert snapshot.summary.completed_jobs == 2
    assert snapshot.summary.failed_jobs == 1
    assert snapshot.summary.validated_rows == 3
    assert snapshot.summary.source_rows == 4
    assert snapshot.summary.rows_with_errors == 1
    assert snapshot.summary.rows_with_warnings == 2
    assert snapshot.summary.error_issue_count == 1
    assert snapshot.summary.warning_issue_count == 2
    assert snapshot.summary.average_duration_ms == 15000.0
    assert snapshot.summary.llm.audited_rows == 2
    assert snapshot.summary.llm.provider_requests == 1
    assert snapshot.summary.llm.cache_hits == 1
    assert snapshot.summary.llm.input_tokens == 1000
    assert snapshot.summary.llm.output_tokens == 500
    assert snapshot.summary.llm.estimated_cost_usd == 0.0105

    default_snapshot = next(
        tenant for tenant in snapshot.tenants if tenant.tenant_id == "default"
    )
    assert default_snapshot.total_jobs == 2
    assert default_snapshot.completed_jobs == 1
    assert default_snapshot.failed_jobs == 1
    assert default_snapshot.validated_rows == 2
    assert default_snapshot.error_rate == 0.5
    assert default_snapshot.warning_rate == 0.5
    assert default_snapshot.average_duration_ms == 10000.0
    assert default_snapshot.llm.models[0].model == "claude-sonnet-4-20250514"
    assert default_snapshot.llm.models[0].estimated_cost_usd == 0.0105

    redesim_snapshot = next(
        tenant for tenant in snapshot.tenants if tenant.tenant_id == "redesim"
    )
    assert redesim_snapshot.total_jobs == 1
    assert redesim_snapshot.completed_jobs == 1
    assert redesim_snapshot.validated_rows == 1
    assert redesim_snapshot.rows_with_warnings == 1
    assert redesim_snapshot.llm.provider_requests == 0
    assert redesim_snapshot.llm.estimated_cost_usd == 0.0


def test_collect_operational_kpis_keeps_job_volume_when_result_artifact_is_missing(
    tmp_path,
):
    service = JobService()
    missing_result_path = tmp_path / "missing-result.json"
    _finalize_completed_job(
        service,
        tenant_id="default",
        result_path=missing_result_path,
        created_at=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
        duration_seconds=7,
        total_rows=8,
        source_total_rows=10,
        rows_with_issues=3,
        total_issues=5,
    )

    snapshot = OperationalKPIService(job_service=service).collect(tenant_id="default")

    assert snapshot.summary.total_jobs == 1
    assert snapshot.summary.completed_jobs == 1
    assert snapshot.summary.validated_rows == 8
    assert snapshot.summary.source_rows == 10
    assert snapshot.summary.rows_with_errors == 0
    assert snapshot.summary.rows_with_warnings == 0
    assert snapshot.summary.error_issue_count == 0
    assert snapshot.summary.warning_issue_count == 0
