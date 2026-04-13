import json
import tempfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import job_service
from app.main import app

client = TestClient(app)


def setup_function():
    job_service._jobs.clear()


CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "002,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_and_validate_creates_job():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate?tenant_id=default", files=files)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["tenant_id"] == "default"
    assert data["status"] == "queued"


def test_upload_default_tenant():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate", files=files)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "default"


def test_upload_invalid_tenant():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate?tenant_id=nonexistent", files=files)
    assert response.status_code == 404
    assert "Tenant not found" in response.json()["detail"]


def test_get_job_status():
    job = job_service.create_job(tenant_id="default")
    response = client.get(f"/jobs/{job.job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.job_id
    assert data["status"] == "queued"
    assert data["tenant_id"] == "default"


def test_get_job_not_found():
    response = client.get("/jobs/nonexistent")
    assert response.status_code == 404


def test_download_result_not_completed():
    job = job_service.create_job(tenant_id="default")
    response = client.get(f"/jobs/{job.job_id}/result")
    assert response.status_code == 400
    assert "not completed" in response.json()["detail"]


def test_download_result_completed():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({"summary": {"total_rows": 1}}, f)
        result_path = f.name

    job.mark_completed(result_path=result_path, total_rows=1)

    response = client.get(f"/jobs/{job.job_id}/result")
    assert response.status_code == 200
    assert response.json()["summary"]["total_rows"] == 1

    Path(result_path).unlink(missing_ok=True)


def test_download_report_not_completed():
    job = job_service.create_job(tenant_id="default")
    response = client.get(f"/jobs/{job.job_id}/report")
    assert response.status_code == 400


def test_download_report_file_missing():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(report_path="/nonexistent/report.pdf")

    response = client.get(f"/jobs/{job.job_id}/report")
    assert response.status_code == 404
    assert "Report file not found" in response.json()["detail"]


def test_download_report_completed():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake content")
        report_path = f.name

    job.mark_completed(report_path=report_path)

    response = client.get(f"/jobs/{job.job_id}/report")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"

    Path(report_path).unlink(missing_ok=True)


def test_download_result_not_found():
    response = client.get("/jobs/nonexistent/result")
    assert response.status_code == 404


def test_download_report_not_found():
    response = client.get("/jobs/nonexistent/report")
    assert response.status_code == 404


def test_upload_saves_file():
    files = {"file": ("inventory.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate?tenant_id=default", files=files)
    data = response.json()
    job = job_service.get_job(data["job_id"])
    assert job is not None
    assert job.file_path is not None
    assert Path(job.file_path).name.endswith("inventory.csv")

    Path(job.file_path).unlink(missing_ok=True)


def test_job_status_shows_counters_after_completion():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(total_rows=10, rows_with_issues=3, total_issues=5)

    response = client.get(f"/jobs/{job.job_id}")
    data = response.json()
    assert data["total_rows"] == 10
    assert data["rows_with_issues"] == 3
    assert data["total_issues"] == 5


def test_job_status_shows_error_after_failure():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_failed("Something went wrong")

    response = client.get(f"/jobs/{job.job_id}")
    data = response.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "Something went wrong"
