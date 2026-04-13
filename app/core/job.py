from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
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
    file_name: str | None = None
    result_path: str | None = None
    report_path: str | None = None
    total_rows: int = 0
    rows_with_issues: int = 0
    total_issues: int = 0
    processed_rows: int = 0
    batch_size: int = 0
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None
    partial_summary: dict[str, Any] = Field(default_factory=dict)
    is_partial_result_available: bool = False
    partial_grouped_problems: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict
    )
    partial_duplicates: list[dict[str, Any]] = Field(default_factory=list)
    row_results_preview: list[dict[str, Any]] = Field(default_factory=list)
    current_step: str | None = "file_received"
    status_title: str | None = "Arquivo recebido"
    status_detail: str | None = "O lote foi recebido e aguarda processamento."

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
        self._clear_partial_preview()
        self.set_progress(
            current_step="reading_lot",
            status_title="Leitura do lote em andamento",
            status_detail="O arquivo está sendo lido e preparado para validação.",
        )

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
        self.processed_rows = total_rows
        self.error_message = None
        self._clear_partial_preview(reset_progress_metrics=False)
        self.set_progress(
            current_step="report_ready",
            status_title="Relatório pronto",
            status_detail=(
                "O resumo executivo, os dados estruturados e o PDF estão disponíveis "
                "para consulta."
            ),
        )

    def mark_failed(self, error_message: str) -> None:
        self.transition_to(JobStatus.FAILED)
        self.error_message = error_message
        self._clear_partial_preview(reset_progress_metrics=False)
        self.set_progress(
            current_step="failed",
            status_title="Falha no processamento",
            status_detail=error_message or "Não foi possível concluir o processamento do lote.",
        )

    def set_partial_result(
        self,
        *,
        total_rows: int,
        processed_rows: int,
        batch_size: int,
        partial_summary: dict[str, Any] | None = None,
        partial_grouped_problems: dict[str, list[dict[str, Any]]] | None = None,
        partial_duplicates: list[dict[str, Any]] | None = None,
        row_results_preview: list[dict[str, Any]] | None = None,
        is_partial_result_available: bool | None = None,
    ) -> None:
        self.total_rows = total_rows
        self.processed_rows = processed_rows
        self.batch_size = batch_size

        if partial_summary is not None:
            self.partial_summary = partial_summary
        if partial_grouped_problems is not None:
            self.partial_grouped_problems = partial_grouped_problems
        if partial_duplicates is not None:
            self.partial_duplicates = partial_duplicates
        if row_results_preview is not None:
            self.row_results_preview = row_results_preview

        if is_partial_result_available is None:
            self.is_partial_result_available = bool(
                self.partial_grouped_problems
                or self.partial_duplicates
                or self.row_results_preview
            )
        else:
            self.is_partial_result_available = is_partial_result_available

        self.updated_at = datetime.now(UTC)

    def set_progress(
        self,
        current_step: str,
        status_title: str,
        status_detail: str,
    ) -> None:
        self.current_step = current_step
        self.status_title = status_title
        self.status_detail = status_detail
        self.updated_at = datetime.now(UTC)

    def _clear_partial_preview(self, reset_progress_metrics: bool = True) -> None:
        if reset_progress_metrics:
            self.processed_rows = 0
            self.batch_size = 0
        self.partial_summary = {}
        self.is_partial_result_available = False
        self.partial_grouped_problems = {}
        self.partial_duplicates = []
        self.row_results_preview = []
