from datetime import UTC, datetime
from pathlib import Path

from app.core.audit import AuditEventType
from app.core.job import JobRecord, JobStatus
from app.core.logging import get_logger, log_event
from app.core.metrics import record_job_duration, record_job_status_transition
from app.core.operational_sqlite import (
    OperationalSQLiteStore,
    resolve_operational_sqlite_path,
)
from app.core.tenant_loader import canonicalize_tenant_id
from app.services.audit_service import AuditService

_logger = get_logger("job_service")


def _job_duration_ms(job: JobRecord) -> float:
    now = datetime.now(UTC)
    return (now - job.created_at).total_seconds() * 1000.0


class JobService:
    def __init__(
        self,
        storage_path: Path | str | None = None,
        *,
        sqlite_path: Path | str | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._jobs: dict[str, JobRecord] = {}
        resolved_sqlite_path = resolve_operational_sqlite_path(sqlite_path, storage_path)
        self._sqlite_store = (
            OperationalSQLiteStore(resolved_sqlite_path)
            if resolved_sqlite_path is not None
            else None
        )
        self._storage_path = (
            resolved_sqlite_path
            if resolved_sqlite_path is not None
            else Path(storage_path)
            if storage_path is not None
            else None
        )
        self._audit_service = audit_service
        self._load_jobs()

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

    def create_job(
        self,
        tenant_id: str,
        file_path: str | None = None,
        file_name: str | None = None,
        api_key_id: str | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
        parent_job_id: str | None = None,
    ) -> JobRecord:
        resolved_tenant_id = canonicalize_tenant_id(tenant_id)
        job = JobRecord(
            tenant_id=resolved_tenant_id,
            file_path=file_path,
            file_name=file_name,
            api_key_id=api_key_id,
            params=params or {},
            parent_job_id=parent_job_id,
        )
        self._jobs[job.job_id] = job
        self._persist_jobs()
        self._record_audit_event(
            AuditEventType.JOB_CREATED,
            job,
            details={
                "file_name": job.file_name,
                "validation_scope": job.params.get("validation_scope"),
                "parent_job_id": job.parent_job_id,
            },
        )
        record_job_status_transition(job.tenant_id, job.status.value)
        log_event(
            _logger,
            "job.created",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            file_name=job.file_name,
        )
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        tenant_id: str | None = None,
        *,
        active_only: bool = False,
        limit: int | None = None,
    ) -> list[JobRecord]:
        jobs = list(self._jobs.values())
        if tenant_id is not None:
            resolved_tenant_id = canonicalize_tenant_id(tenant_id)
            jobs = [j for j in jobs if j.tenant_id == resolved_tenant_id]
        if active_only:
            jobs = [
                j
                for j in jobs
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                or j.cancel_requested
            ]
        sorted_jobs = sorted(jobs, key=lambda j: j.created_at, reverse=True)
        if limit is not None:
            return sorted_jobs[:limit]
        return sorted_jobs

    def start_job(self, job_id: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_running()
        self._persist_jobs()
        record_job_status_transition(job.tenant_id, job.status.value)
        log_event(
            _logger,
            "job.started",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
        )
        return job

    def complete_job(
        self,
        job_id: str,
        result_path: str | None = None,
        report_path: str | None = None,
        total_rows: int = 0,
        source_total_rows: int | None = None,
        rows_with_issues: int = 0,
        total_issues: int = 0,
    ) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_completed(
            result_path=result_path,
            report_path=report_path,
            total_rows=total_rows,
            source_total_rows=source_total_rows,
            rows_with_issues=rows_with_issues,
            total_issues=total_issues,
        )
        self._persist_jobs()
        self._record_audit_event(
            AuditEventType.JOB_COMPLETED,
            job,
            details={
                "total_rows": job.total_rows,
                "source_total_rows": job.source_total_rows,
                "rows_with_issues": job.rows_with_issues,
                "total_issues": job.total_issues,
                "validation_scope": job.params.get("validation_scope"),
            },
        )
        record_job_status_transition(job.tenant_id, job.status.value)
        record_job_duration(job.tenant_id, job.status.value, _job_duration_ms(job))
        log_event(
            _logger,
            "job.completed",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            duration_ms=_job_duration_ms(job),
            total_rows=job.total_rows,
            rows_with_issues=job.rows_with_issues,
            total_issues=job.total_issues,
        )
        return job

    def fail_job(self, job_id: str, error_message: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_failed(error_message)
        self._persist_jobs()
        record_job_status_transition(job.tenant_id, job.status.value)
        record_job_duration(job.tenant_id, job.status.value, _job_duration_ms(job))
        log_event(
            _logger,
            "job.failed",
            level="error",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            duration_ms=_job_duration_ms(job),
            error=error_message,
        )
        return job

    def request_job_cancellation(self, job_id: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        if job.status == JobStatus.QUEUED:
            job.mark_canceled("O lote foi cancelado antes do início do processamento.")
            self._persist_jobs()
            record_job_status_transition(job.tenant_id, job.status.value)
            record_job_duration(job.tenant_id, job.status.value, _job_duration_ms(job))
            return job
        if job.status == JobStatus.RUNNING:
            job.request_cancellation()
            self._persist_jobs()
            return job
        if job.status == JobStatus.CANCELED:
            return job
        raise ValueError("Only queued or running jobs can be canceled")

    def cancel_job(self, job_id: str, detail: str | None = None) -> JobRecord:
        job = self._get_or_raise(job_id)
        if job.status == JobStatus.CANCELED:
            return job
        if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise ValueError("Only queued or running jobs can be canceled")
        job.mark_canceled(detail)
        self._persist_jobs()
        record_job_status_transition(job.tenant_id, job.status.value)
        record_job_duration(job.tenant_id, job.status.value, _job_duration_ms(job))
        log_event(
            _logger,
            "job.canceled",
            level="warning",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            duration_ms=_job_duration_ms(job),
            detail=detail,
        )
        return job

    def update_progress(
        self,
        job_id: str,
        current_step: str,
        status_title: str,
        status_detail: str,
    ) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.set_progress(
            current_step=current_step,
            status_title=status_title,
            status_detail=status_detail,
        )
        self._persist_jobs()
        return job

    def update_partial_result(
        self,
        job_id: str,
        *,
        total_rows: int,
        source_total_rows: int | None = None,
        processed_rows: int,
        batch_size: int,
        partial_summary: dict | None = None,
        partial_grouped_problems: dict | None = None,
        partial_duplicates: list | None = None,
        row_results_preview: list | None = None,
        is_partial_result_available: bool | None = None,
        current_step: str | None = None,
        status_title: str | None = None,
        status_detail: str | None = None,
    ) -> JobRecord:
        job = self._get_or_raise(job_id)

        job.set_partial_result(
            total_rows=total_rows,
            source_total_rows=source_total_rows,
            processed_rows=processed_rows,
            batch_size=batch_size,
            partial_summary=partial_summary,
            partial_grouped_problems=partial_grouped_problems,
            partial_duplicates=partial_duplicates,
            row_results_preview=row_results_preview,
            is_partial_result_available=is_partial_result_available,
        )

        if (
            current_step is not None
            and status_title is not None
            and status_detail is not None
        ):
            job.set_progress(
                current_step=current_step,
                status_title=status_title,
                status_detail=status_detail,
            )

        self._persist_jobs()
        return job

    def save_job(self, job_id: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        self._persist_jobs()
        return job

    def register_reprocess_link(
        self,
        *,
        source_job_id: str,
        new_job_id: str,
    ) -> JobRecord:
        source_job = self._get_or_raise(source_job_id)
        new_job = self._get_or_raise(new_job_id)
        if new_job.tenant_id != source_job.tenant_id:
            raise ValueError(
                "Reprocess link must keep the same tenant for source and new job"
            )
        source_job.latest_retry_job_id = new_job.job_id
        source_job.updated_at = datetime.now(UTC)
        if new_job.parent_job_id is None:
            new_job.parent_job_id = source_job.job_id
        self._persist_jobs()
        self._record_audit_event(
            AuditEventType.JOB_REPROCESSED,
            source_job,
            details={
                "parent_job_id": source_job.job_id,
                "new_job_id": new_job.job_id,
            },
        )
        return source_job

    def _get_or_raise(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job

    def _load_jobs(self) -> None:
        if self._storage_path is None:
            return

        if self._sqlite_store is not None:
            payload = self._sqlite_store.load_jobs()
        else:
            if not self._storage_path.exists():
                return
            import json

            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Job storage payload must be a list")

        self._jobs = {}
        updated = False
        for item in payload:
            job = JobRecord.model_validate(item)
            resolved_tenant_id = canonicalize_tenant_id(job.tenant_id)
            if job.tenant_id != resolved_tenant_id:
                job.tenant_id = resolved_tenant_id
                updated = True
            if job.status == JobStatus.RUNNING and job.cancel_requested:
                job.mark_canceled(
                    "O cancelamento solicitado anteriormente foi finalizado ao "
                    "recarregar o serviço."
                )
                updated = True
            self._jobs[job.job_id] = job

        if updated:
            self._persist_jobs()

    def _persist_jobs(self) -> None:
        if self._storage_path is None:
            return

        payload = [
            job.model_dump(mode="json")
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at)
        ]
        if self._sqlite_store is not None:
            self._sqlite_store.replace_jobs(payload)
            return

        import json

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)

    def _record_audit_event(
        self,
        event_type: AuditEventType,
        job: JobRecord,
        *,
        details: dict[str, object | None] | None = None,
    ) -> None:
        if self._audit_service is None:
            return

        payload = {
            key: value for key, value in (details or {}).items() if value is not None
        }
        self._audit_service.record_event(
            event_type,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            api_key_id=job.api_key_id,
            details=payload,
        )
