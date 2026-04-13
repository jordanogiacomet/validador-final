from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    tenant_id: str
    status: JobStatus = JobStatus.QUEUED
    file_path: str | None = None
    result_path: str | None = None
    report_path: str | None = None
    total_rows: int = 0
    rows_with_issues: int = 0
    total_issues: int = 0
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None

    def transition_to(self, new_status: JobStatus) -> None:
        valid_transitions: dict[JobStatus, list[JobStatus]] = {
            JobStatus.QUEUED: [JobStatus.RUNNING, JobStatus.FAILED],
            JobStatus.RUNNING: [JobStatus.COMPLETED, JobStatus.FAILED],
            JobStatus.COMPLETED: [],
            JobStatus.FAILED: [],
        }
        allowed = valid_transitions.get(self.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition from {self.status.value} to {new_status.value}"
            )
        self.status = new_status
        self.updated_at = datetime.now(UTC)

    def mark_running(self) -> None:
        self.transition_to(JobStatus.RUNNING)

    def mark_completed(
        self,
        result_path: str | None = None,
        report_path: str | None = None,
        total_rows: int = 0,
        rows_with_issues: int = 0,
        total_issues: int = 0,
    ) -> None:
        self.transition_to(JobStatus.COMPLETED)
        if result_path is not None:
            self.result_path = result_path
        if report_path is not None:
            self.report_path = report_path
        self.total_rows = total_rows
        self.rows_with_issues = rows_with_issues
        self.total_issues = total_issues

    def mark_failed(self, error_message: str) -> None:
        self.transition_to(JobStatus.FAILED)
        self.error_message = error_message
