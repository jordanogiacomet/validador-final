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

REDESIM_CSV_CONTENT = (
    "Espécie,Marca,Modelo,Complemento,NS\n"
    "MONITOR,Dell,P2419H,,SN1\n"
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_page_renders_friendly_form():
    response = client.get("/")
    assert response.status_code == 200
    assert "Central de Correção Patrimonial" in response.text
    assert "Trilha de processamento" in response.text
    assert 'id="validation-form"' in response.text


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
    assert data["current_step"] == "file_received"
    assert data["status_title"] == "Arquivo recebido"
    assert data["status_detail"]
    assert data["processed_rows"] == 0
    assert data["batch_size"] == 0
    assert data["partial_summary"] == {}
    assert data["is_partial_result_available"] is False
    assert data["partial_grouped_problems"] == {}
    assert data["partial_duplicates"] == []
    assert data["row_results_preview"] == []
    assert data["created_at"]
    assert data["updated_at"]


def test_get_job_status_includes_file_name_metadata():
    job = job_service.create_job(tenant_id="default", file_name="lote.csv")
    response = client.get(f"/jobs/{job.job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "lote.csv"


def test_get_job_status_includes_partial_preview_payload():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job_service.update_partial_result(
        job.job_id,
        total_rows=12,
        processed_rows=4,
        batch_size=4,
        partial_summary={
            "total_rows": 12,
            "processed_rows": 4,
            "rows_with_issues": 2,
            "total_issues": 3,
            "error_count": 1,
            "warning_count": 2,
        },
        partial_grouped_problems={"DUPLICATE_ITEM": [{"row_index": 0, "item": "001"}]},
        partial_duplicates=[{"item": "001", "row_indices": [0, 5], "count": 2}],
        row_results_preview=[{"row_index": 0, "item": "001", "issues": []}],
        current_step="validating_batches",
        status_title="Prévia operacional em atualização",
        status_detail="4 de 12 linhas já foram validadas.",
    )

    response = client.get(f"/jobs/{job.job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["processed_rows"] == 4
    assert data["batch_size"] == 4
    assert data["is_partial_result_available"] is True
    assert data["partial_summary"]["processed_rows"] == 4
    assert data["partial_grouped_problems"]["DUPLICATE_ITEM"][0]["item"] == "001"
    assert data["partial_duplicates"][0]["count"] == 2
    assert data["row_results_preview"][0]["row_index"] == 0


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


def test_validation_result_includes_item_and_descricao_metadata():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate?tenant_id=default", files=files)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None
    try:
        assert job.result_path is not None
        assert job.report_path is not None
        assert job.file_path is not None

        result_response = client.get(f"/jobs/{job_id}/result")
        assert result_response.status_code == 200

        payload = result_response.json()
        first_row = payload["row_results"][0]
        assert first_row["item"] == "001"
        assert first_row["descricao"] == "Mesa"

        grouped_issue = payload["grouped_problems"]["ZERO_ITEM_COMPLEMENTO_EMPTY"][0]
        assert grouped_issue["item"] == "002"
        assert grouped_issue["descricao"] == "Cadeira"
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_redesim_tenant_uses_species_column_and_rules():
    files = {"file": ("redesim.csv", BytesIO(REDESIM_CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate?tenant_id=redesim", files=files)
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None

    try:
        result_response = client.get(f"/jobs/{job_id}/result")
        assert result_response.status_code == 200

        payload = result_response.json()
        assert payload["row_results"][0]["descricao"] == "MONITOR"
        assert "CATEGORY_MONITOR_COMPLEMENTO_REQUIRED" in payload["grouped_problems"]
        assert "CATEGORY_MONITOR_INCHES_PATTERN_MISSING" in payload["grouped_problems"]
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


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
    assert job.file_name == "inventory.csv"
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
    assert data["current_step"] == "report_ready"
    assert data["status_title"] == "Relatório pronto"


def test_job_status_shows_error_after_failure():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_failed("Something went wrong")

    response = client.get(f"/jobs/{job.job_id}")
    data = response.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "Something went wrong"
    assert data["current_step"] == "failed"
    assert data["status_title"] == "Falha no processamento"
