import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import app.services.validation_service as validation_service
from app.core.audit import AuditEventType
from app.core.job import JobStatus
from app.core.llm_cache import LLM_CACHE_PATH_ENV
from app.core.retention import RETENTION_PRESERVE_ARTIFACTS_PARAM, RetentionPolicy
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.services.retention_service import RetentionService


def _write_old_file(path: Path, content: str = "artifact") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    old_timestamp = time.time() - 40 * 24 * 60 * 60
    os.utime(path, (old_timestamp, old_timestamp))
    return path


def _make_completed_job(
    job_service: JobService,
    *,
    file_path: Path | None = None,
    result_path: Path | None = None,
    report_path: Path | None = None,
    params: dict | None = None,
    updated_days_ago: int = 40,
):
    job = job_service.create_job(
        tenant_id="default",
        file_name="lote.csv",
        params=params,
    )
    job_service.start_job(job.job_id)
    job = job_service.complete_job(
        job.job_id,
        result_path=str(result_path) if result_path is not None else None,
        report_path=str(report_path) if report_path is not None else None,
        total_rows=1,
    )
    if file_path is not None:
        job.file_path = str(file_path)
    old_datetime = datetime.now(UTC) - timedelta(days=updated_days_ago)
    job.created_at = old_datetime
    job.updated_at = old_datetime
    job_service.save_job(job.job_id)
    return job


def test_retention_cleanup_removes_expired_artifacts_and_prunes_llm_cache(
    tmp_path,
    monkeypatch,
):
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)
    llm_cache_path = tmp_path / "llm_cache.json"
    monkeypatch.setenv(LLM_CACHE_PATH_ENV, str(llm_cache_path))

    audit_service = AuditService()
    job_service = JobService(audit_service=audit_service)
    service = RetentionService(
        job_service=job_service,
        audit_service=audit_service,
    )

    upload_path = _write_old_file(uploads_dir / "default" / "lote.csv")
    result_path = _write_old_file(results_dir / "default" / "result.json", "{}")
    report_path = _write_old_file(results_dir / "default" / "report.pdf", "%PDF")
    job = _make_completed_job(
        job_service,
        file_path=upload_path,
        result_path=result_path,
        report_path=report_path,
    )
    review_flags_path = _write_old_file(
        results_dir / "default" / job.job_id / "review_flags.json",
        "{}",
    )

    current_time = time.time()
    llm_cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "old": {
                        "created_at": current_time - 40 * 24 * 60 * 60,
                        "response_text": "old",
                    },
                    "fresh": {
                        "created_at": current_time,
                        "response_text": "fresh",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    policy = RetentionPolicy(
        upload_days=7,
        result_days=7,
        report_days=7,
        review_flags_days=7,
        llm_cache_days=7,
    )

    plan = service.inspect(tenant_id="default", policy=policy)

    assert plan.dry_run is True
    assert {artifact.kind for artifact in plan.artifacts} == {
        "upload",
        "result",
        "report",
        "review_flags",
    }
    assert plan.llm_cache_entries_removed == 1
    assert upload_path.exists()
    assert result_path.exists()
    assert report_path.exists()
    assert review_flags_path.exists()

    result = service.cleanup(tenant_id="default", policy=policy, api_key_id="key-1")

    assert result.dry_run is False
    assert result.artifact_count == 4
    assert result.llm_cache_entries_removed == 1
    assert not upload_path.exists()
    assert not result_path.exists()
    assert not report_path.exists()
    assert not review_flags_path.exists()
    assert not review_flags_path.parent.exists()

    llm_cache_payload = json.loads(llm_cache_path.read_text(encoding="utf-8"))
    assert set(llm_cache_payload["entries"]) == {"fresh"}

    retention_events = [
        event
        for event in audit_service.list_events(tenant_id="default")
        if event.event_type == AuditEventType.ARTIFACT_RETENTION_RUN
    ]
    assert len(retention_events) == 1
    assert retention_events[0].api_key_id == "key-1"
    assert retention_events[0].details["artifact_count"] == 4
    assert retention_events[0].details["llm_cache_entries_removed"] == 1


def test_retention_cleanup_keeps_active_recent_preserved_and_shared_artifacts(
    tmp_path,
    monkeypatch,
):
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    job_service = JobService()
    service = RetentionService(job_service=job_service)

    shared_upload_path = _write_old_file(uploads_dir / "default" / "shared.csv")
    active_job = job_service.create_job(
        tenant_id="default",
        file_path=str(shared_upload_path),
    )
    job_service.start_job(active_job.job_id)

    _make_completed_job(
        job_service,
        file_path=shared_upload_path,
        updated_days_ago=40,
    )

    preserved_path = _write_old_file(uploads_dir / "default" / "preserved.csv")
    _make_completed_job(
        job_service,
        file_path=preserved_path,
        params={RETENTION_PRESERVE_ARTIFACTS_PARAM: True},
        updated_days_ago=40,
    )

    recent_path = _write_old_file(uploads_dir / "default" / "recent.csv")
    _make_completed_job(
        job_service,
        file_path=recent_path,
        updated_days_ago=1,
    )

    expired_path = _write_old_file(uploads_dir / "default" / "expired.csv")
    _make_completed_job(
        job_service,
        file_path=expired_path,
        updated_days_ago=40,
    )

    policy = RetentionPolicy(
        upload_days=7,
        result_days=None,
        report_days=None,
        review_flags_days=None,
        llm_cache_days=None,
    )

    result = service.cleanup(tenant_id="default", policy=policy)

    assert active_job.status == JobStatus.RUNNING
    assert [artifact.path for artifact in result.artifacts] == [str(expired_path)]
    assert shared_upload_path.exists()
    assert preserved_path.exists()
    assert recent_path.exists()
    assert not expired_path.exists()
