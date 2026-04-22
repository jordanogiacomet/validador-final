from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

import app.services.validation_service as validation_service
from app.api import routes
from app.core.job import JobStatus
from app.main import app
from app.services.job_service import JobService
from app.workers.validation_worker import ValidationWorker

DEFAULT_API_KEY = "default-local-test-key"
CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "002,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
)


def auth_headers() -> dict[str, str]:
    return {"X-API-Key": DEFAULT_API_KEY}


def test_validate_in_worker_mode_only_enqueues_job(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "operational.sqlite3"
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    service = JobService(sqlite_path=sqlite_path)

    monkeypatch.setenv("VALIDATOR_JOB_EXECUTION_MODE", "worker")
    monkeypatch.setattr(validation_service, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(routes, "job_service", service)

    client = TestClient(app)
    response = client.post(
        "/validate?tenant_id=default",
        files={"file": ("inventario.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"

    job = service.get_job(payload["job_id"])
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.file_path is not None
    assert Path(job.file_path).exists()
    assert job.result_path is None
    assert job.report_path is None


def test_claim_next_job_sets_running_owner_and_blocks_second_claim(tmp_path):
    sqlite_path = tmp_path / "operational.sqlite3"
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    service = JobService(sqlite_path=sqlite_path)
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    claimed_job = service.claim_next_job(worker_id="worker-a", lease_seconds=60)

    assert claimed_job is not None
    assert claimed_job.job_id == job.job_id
    assert claimed_job.status == JobStatus.RUNNING
    assert claimed_job.execution_owner_id == "worker-a"
    assert claimed_job.execution_expires_at is not None
    assert service.claim_next_job(worker_id="worker-b", lease_seconds=60) is None


def test_claim_next_job_reclaims_stale_running_job(tmp_path):
    sqlite_path = tmp_path / "operational.sqlite3"
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    service = JobService(sqlite_path=sqlite_path)
    service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    claimed_job = service.claim_next_job(worker_id="worker-a", lease_seconds=60)
    assert claimed_job is not None
    claimed_job.execution_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    service.save_job(claimed_job.job_id)

    other_service = JobService(sqlite_path=sqlite_path)
    reclaimed_job = other_service.claim_next_job(worker_id="worker-b", lease_seconds=60)

    assert reclaimed_job is not None
    assert reclaimed_job.job_id == claimed_job.job_id
    assert reclaimed_job.status == JobStatus.RUNNING
    assert reclaimed_job.execution_owner_id == "worker-b"
    assert reclaimed_job.execution_expires_at is not None
    assert reclaimed_job.execution_expires_at > datetime.now(UTC)


def test_competing_workers_cannot_claim_the_same_job_twice(tmp_path):
    sqlite_path = tmp_path / "operational.sqlite3"
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    creator_service = JobService(sqlite_path=sqlite_path)
    job = creator_service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    first_worker = JobService(sqlite_path=sqlite_path)
    second_worker = JobService(sqlite_path=sqlite_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                first_worker.claim_next_job,
                worker_id="worker-a",
                lease_seconds=60,
            ),
            executor.submit(
                second_worker.claim_next_job,
                worker_id="worker-b",
                lease_seconds=60,
            ),
        ]
    claims = [future.result() for future in futures]
    claimed_job_ids = [claim.job_id for claim in claims if claim is not None]

    assert claimed_job_ids == [job.job_id]


def test_validation_worker_run_once_processes_persisted_job(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "operational.sqlite3"
    results_dir = tmp_path / "results"
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    service = JobService(sqlite_path=sqlite_path)
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )
    worker = ValidationWorker(
        job_service=JobService(sqlite_path=sqlite_path),
        worker_id="worker-a",
        poll_interval_seconds=0.01,
        lease_seconds=30,
    )

    processed = worker.run_once()

    assert processed is True
    completed_job = service.get_job(job.job_id)
    assert completed_job is not None
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.result_path is not None
    assert completed_job.report_path is not None
    assert Path(completed_job.result_path).exists()
    assert Path(completed_job.report_path).exists()
