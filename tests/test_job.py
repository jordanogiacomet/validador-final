import pytest

from app.core.job import JobRecord, JobStatus
from app.services.job_service import JobService


class TestJobRecord:
    def test_default_status_is_queued(self):
        job = JobRecord(tenant_id="default")
        assert job.status == JobStatus.QUEUED

    def test_job_id_is_generated(self):
        job = JobRecord(tenant_id="default")
        assert job.job_id
        assert len(job.job_id) == 32

    def test_tenant_id_is_persisted(self):
        job = JobRecord(tenant_id="empresa_exemplo")
        assert job.tenant_id == "empresa_exemplo"

    def test_file_path_persisted(self):
        job = JobRecord(tenant_id="default", file_path="/tmp/inventory.csv")
        assert job.file_path == "/tmp/inventory.csv"

    def test_file_name_persisted(self):
        job = JobRecord(tenant_id="default", file_name="inventory.csv")
        assert job.file_name == "inventory.csv"

    def test_params_persisted(self):
        job = JobRecord(tenant_id="default", params={"skip_llm": True})
        assert job.params == {"skip_llm": True}

    def test_default_progress_copy(self):
        job = JobRecord(tenant_id="default")
        assert job.current_step == "file_received"
        assert job.status_title == "Arquivo recebido"
        assert "aguarda processamento" in job.status_detail

    def test_default_preview_state(self):
        job = JobRecord(tenant_id="default")
        assert job.processed_rows == 0
        assert job.batch_size == 0
        assert job.partial_summary == {}
        assert job.is_partial_result_available is False
        assert job.partial_grouped_problems == {}
        assert job.partial_duplicates == []
        assert job.row_results_preview == []

    def test_transition_queued_to_running(self):
        job = JobRecord(tenant_id="default")
        job.mark_running()
        assert job.status == JobStatus.RUNNING
        assert job.current_step == "reading_lot"
        assert job.status_title == "Leitura do lote em andamento"

    def test_transition_running_to_completed(self):
        job = JobRecord(tenant_id="default")
        job.mark_running()
        job.set_partial_result(
            total_rows=100,
            processed_rows=40,
            batch_size=20,
            partial_summary={"total_rows": 100, "processed_rows": 40},
            partial_grouped_problems={"DUPLICATE_ITEM": [{"row_index": 0}]},
            partial_duplicates=[{"item": "001"}],
            row_results_preview=[{"row_index": 0}],
            is_partial_result_available=True,
        )
        job.mark_completed(
            result_path="/tmp/result.json",
            report_path="/tmp/report.pdf",
            total_rows=100,
            rows_with_issues=5,
            total_issues=8,
        )
        assert job.status == JobStatus.COMPLETED
        assert job.result_path == "/tmp/result.json"
        assert job.report_path == "/tmp/report.pdf"
        assert job.total_rows == 100
        assert job.rows_with_issues == 5
        assert job.total_issues == 8
        assert job.processed_rows == 100
        assert job.partial_summary == {}
        assert job.is_partial_result_available is False
        assert job.current_step == "report_ready"
        assert job.status_title == "Relatório pronto"

    def test_transition_running_to_failed(self):
        job = JobRecord(tenant_id="default")
        job.mark_running()
        job.mark_failed("timeout")
        assert job.status == JobStatus.FAILED
        assert job.error_message == "timeout"
        assert job.current_step == "failed"
        assert job.status_title == "Falha no processamento"

    def test_transition_queued_to_failed(self):
        job = JobRecord(tenant_id="default")
        job.mark_failed("bad file")
        assert job.status == JobStatus.FAILED

    def test_invalid_transition_completed_to_running(self):
        job = JobRecord(tenant_id="default")
        job.mark_running()
        job.mark_completed()
        with pytest.raises(ValueError, match="Invalid transition"):
            job.mark_running()

    def test_invalid_transition_failed_to_running(self):
        job = JobRecord(tenant_id="default")
        job.mark_failed("error")
        with pytest.raises(ValueError, match="Invalid transition"):
            job.mark_running()

    def test_invalid_transition_queued_to_completed(self):
        job = JobRecord(tenant_id="default")
        with pytest.raises(ValueError, match="Invalid transition"):
            job.mark_completed()

    def test_updated_at_changes_on_transition(self):
        job = JobRecord(tenant_id="default")
        original = job.updated_at
        job.mark_running()
        assert job.updated_at >= original

    def test_set_partial_result_updates_preview_payload(self):
        job = JobRecord(tenant_id="default")
        job.set_partial_result(
            total_rows=50,
            processed_rows=10,
            batch_size=5,
            partial_summary={"total_rows": 50, "processed_rows": 10},
            partial_grouped_problems={"FLAG": [{"row_index": 1}]},
            partial_duplicates=[{"item": "A001"}],
            row_results_preview=[{"row_index": 1}],
        )

        assert job.total_rows == 50
        assert job.processed_rows == 10
        assert job.batch_size == 5
        assert job.partial_summary["processed_rows"] == 10
        assert "FLAG" in job.partial_grouped_problems
        assert job.partial_duplicates[0]["item"] == "A001"
        assert job.row_results_preview[0]["row_index"] == 1
        assert job.is_partial_result_available is True

    def test_created_at_set(self):
        job = JobRecord(tenant_id="default")
        assert job.created_at is not None


class TestJobService:
    def setup_method(self):
        self.service = JobService()

    def test_create_job(self):
        job = self.service.create_job(tenant_id="default", file_path="/tmp/test.csv")
        assert job.tenant_id == "default"
        assert job.file_path == "/tmp/test.csv"
        assert job.status == JobStatus.QUEUED

    def test_get_job(self):
        job = self.service.create_job(tenant_id="default")
        retrieved = self.service.get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_get_job_not_found(self):
        assert self.service.get_job("nonexistent") is None

    def test_list_jobs(self):
        self.service.create_job(tenant_id="default")
        self.service.create_job(tenant_id="empresa_exemplo")
        assert len(self.service.list_jobs()) == 2

    def test_list_jobs_filter_by_tenant(self):
        self.service.create_job(tenant_id="default")
        self.service.create_job(tenant_id="empresa_exemplo")
        self.service.create_job(tenant_id="default")
        default_jobs = self.service.list_jobs(tenant_id="default")
        assert len(default_jobs) == 2
        assert all(j.tenant_id == "default" for j in default_jobs)

    def test_start_job(self):
        job = self.service.create_job(tenant_id="default")
        updated = self.service.start_job(job.job_id)
        assert updated.status == JobStatus.RUNNING

    def test_update_progress(self):
        job = self.service.create_job(tenant_id="default")
        updated = self.service.update_progress(
            job.job_id,
            current_step="validating_rules",
            status_title="Validação das regras em andamento",
            status_detail="Agrupando problemas do lote.",
        )
        assert updated.current_step == "validating_rules"
        assert updated.status_title == "Validação das regras em andamento"
        assert updated.status_detail == "Agrupando problemas do lote."

    def test_update_partial_result(self):
        job = self.service.create_job(tenant_id="default")
        updated = self.service.update_partial_result(
            job.job_id,
            total_rows=20,
            processed_rows=5,
            batch_size=5,
            partial_summary={"total_rows": 20, "processed_rows": 5},
            partial_grouped_problems={"FLAG": [{"row_index": 0}]},
            partial_duplicates=[{"item": "A001"}],
            row_results_preview=[{"row_index": 0}],
            current_step="validating_batches",
            status_title="Prévia operacional em atualização",
            status_detail="5 de 20 linhas já foram validadas.",
        )
        assert updated.total_rows == 20
        assert updated.processed_rows == 5
        assert updated.batch_size == 5
        assert updated.is_partial_result_available is True
        assert updated.partial_grouped_problems["FLAG"][0]["row_index"] == 0
        assert updated.current_step == "validating_batches"

    def test_complete_job(self):
        job = self.service.create_job(tenant_id="default")
        self.service.start_job(job.job_id)
        updated = self.service.complete_job(
            job.job_id,
            result_path="/tmp/result.json",
            total_rows=50,
            rows_with_issues=3,
            total_issues=5,
        )
        assert updated.status == JobStatus.COMPLETED
        assert updated.total_rows == 50

    def test_fail_job(self):
        job = self.service.create_job(tenant_id="default")
        self.service.start_job(job.job_id)
        updated = self.service.fail_job(job.job_id, "parse error")
        assert updated.status == JobStatus.FAILED
        assert updated.error_message == "parse error"

    def test_start_nonexistent_job_raises(self):
        with pytest.raises(KeyError, match="Job not found"):
            self.service.start_job("nonexistent")

    def test_complete_nonexistent_job_raises(self):
        with pytest.raises(KeyError, match="Job not found"):
            self.service.complete_job("nonexistent")

    def test_fail_nonexistent_job_raises(self):
        with pytest.raises(KeyError, match="Job not found"):
            self.service.fail_job("nonexistent", "error")

    def test_job_lifecycle_full(self):
        job = self.service.create_job(
            tenant_id="empresa_exemplo",
            file_path="/uploads/inv.csv",
            params={"use_llm": True},
        )
        assert job.status == JobStatus.QUEUED
        self.service.start_job(job.job_id)
        assert job.status == JobStatus.RUNNING
        self.service.complete_job(
            job.job_id,
            result_path="/results/inv_result.json",
            report_path="/results/inv_report.pdf",
            total_rows=200,
            rows_with_issues=15,
            total_issues=22,
        )
        assert job.status == JobStatus.COMPLETED
        assert job.total_issues == 22
