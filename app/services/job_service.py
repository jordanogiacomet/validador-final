from app.core.job import JobRecord


class JobService:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def create_job(
        self,
        tenant_id: str,
        file_path: str | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
    ) -> JobRecord:
        job = JobRecord(
            tenant_id=tenant_id,
            file_path=file_path,
            params=params or {},
        )
        self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list_jobs(self, tenant_id: str | None = None) -> list[JobRecord]:
        jobs = list(self._jobs.values())
        if tenant_id is not None:
            jobs = [j for j in jobs if j.tenant_id == tenant_id]
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
        rows_with_issues: int = 0,
        total_issues: int = 0,
    ) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_completed(
            result_path=result_path,
            report_path=report_path,
            total_rows=total_rows,
            rows_with_issues=rows_with_issues,
            total_issues=total_issues,
        )
        return job

    def fail_job(self, job_id: str, error_message: str) -> JobRecord:
        job = self._get_or_raise(job_id)
        job.mark_failed(error_message)
        return job

    def _get_or_raise(self, job_id: str) -> JobRecord:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        return job
