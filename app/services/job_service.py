from app.core.job import JobRecord, JobStatus


class JobService:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def create_job(
        self,
        tenant_id: str,
        file_path: str | None = None,
        file_name: str | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> JobRecord:
        job = JobRecord(
            tenant_id=tenant_id,
            file_path=file_path,
            file_name=file_name,
            params=params or {},
        )
        self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list_jobs(
        self,
        tenant_id: str | None = None,
        *,
        active_only: bool = False,
    ) -> list[JobRecord]:
        jobs = list(self._jobs.values())
        if tenant_id is not None:
            jobs = [j for j in jobs if j.tenant_id == tenant_id]
        if active_only:
            jobs = [
                j
                for j in jobs
                if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                or j.cancel_requested
            ]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def start_job(self, job_id: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_running()
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
        return job

    def fail_job(self, job_id: str, error_message: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_failed(error_message)
        return job

    def request_job_cancellation(self, job_id: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        if job.status == JobStatus.QUEUED:
            job.mark_canceled("O lote foi cancelado antes do início do processamento.")
            return job
        if job.status == JobStatus.RUNNING:
            job.request_cancellation()
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

        return job

    def _get_or_raise(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job
