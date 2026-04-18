import json
import tempfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import audit_service, job_service
from app.core.audit import AuditEventType
from app.main import app
from app.services.validation_service import run_validation_job

client = TestClient(app)

DEFAULT_API_KEY = "default-local-test-key"
DEFAULT_API_KEY_ID = "default-local"
REDESIM_API_KEY = "redesim-local-test-key"


def setup_function():
    job_service._jobs.clear()
    audit_service.clear()


def auth_headers(api_key: str = DEFAULT_API_KEY) -> dict[str, str]:
    return {"X-API-Key": api_key}


CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "002,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
)

DUPLICATE_SCOPE_CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "002,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
    "001,,Armario,MarcaA,ModeloB,SN3,Sala3,CC3,Detalhe armario completo validado,\n"
)

REDESIM_CSV_CONTENT = (
    "Item,Descrição,Marca,Modelo,Complemento,NS\n"
    "001,MONITOR,Dell,P2419H,,SN1\n"
)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [check["name"] for check in payload["checks"]] == [
        "uploads",
        "results",
        "job_store",
    ]
    assert all(check["ok"] is True for check in payload["checks"])


def test_frontend_page_renders_friendly_form():
    response = client.get("/")
    assert response.status_code == 200
    assert "Central de Correção Patrimonial" in response.text
    assert "Trilha de processamento" in response.text
    assert "Processamentos em andamento" in response.text
    assert "Baixar CSV corrigido" in response.text
    assert "Carregar mais" in response.text
    assert "Exportações operacionais" in response.text
    assert "itens cadastrados do zero" in response.text
    assert "Todos os itens" in response.text
    assert 'name="validation_scope"' in response.text
    assert 'id="validation-form"' in response.text


def test_list_tenants_returns_display_names():
    response = client.get("/tenants", headers=auth_headers())
    assert response.status_code == 200

    payload = response.json()
    assert payload
    assert payload[0]["tenant_id"] == "default"
    assert payload[0]["display_name"] == "Default Tenant"
    assert payload[0]["is_default"] is True
    assert len(payload) == 1


def test_list_audit_events_returns_tenant_scoped_entries_in_reverse_chronological_order():
    first = audit_service.record_event(
        AuditEventType.JOB_CREATED,
        tenant_id="default",
        job_id="job-1",
        api_key_id="default",
        details={"file_name": "a.csv"},
    )
    audit_service.record_event(
        AuditEventType.JOB_COMPLETED,
        tenant_id="redesim",
        job_id="job-2",
        api_key_id="redesim",
    )
    latest = audit_service.record_event(
        AuditEventType.DUPLICATES_RESOLVED,
        tenant_id="default",
        job_id="job-3",
        api_key_id="default",
        details={"remaining_rows": 1},
    )

    response = client.get("/audit?tenant_id=default&limit=1", headers=auth_headers())
    assert response.status_code == 200

    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == latest.event_id
    assert payload[0]["event_type"] == "duplicates_resolved"
    assert payload[0]["tenant_id"] == "default"
    assert payload[0]["job_id"] == "job-3"
    assert payload[0]["api_key_id"] == "default"
    assert payload[0]["details"]["remaining_rows"] == 1
    assert payload[0]["event_id"] != first.event_id


def test_list_audit_events_rejects_other_tenant_hint():
    response = client.get("/audit?tenant_id=redesim", headers=auth_headers())
    assert response.status_code == 403
    assert "redesim" in response.json()["detail"]


def test_protected_routes_require_api_key():
    response = client.get("/jobs")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key header"


def test_invalid_api_key_is_rejected():
    response = client.get("/jobs", headers=auth_headers("invalid-api-key"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_upload_and_validate_creates_job():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["tenant_id"] == "default"
    assert data["validation_scope"] == "zero_items"
    assert data["status"] == "queued"

    audit_events = [
        event for event in audit_service.list_events() if event.job_id == data["job_id"]
    ]
    assert [event.event_type.value for event in audit_events] == [
        "job_completed",
        "job_created",
    ]
    assert audit_events[0].api_key_id == DEFAULT_API_KEY_ID
    assert audit_events[1].details["file_name"] == "test.csv"
    assert audit_events[1].details["validation_scope"] == "zero_items"


def test_upload_default_tenant():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate", files=files, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "default"
    assert response.json()["validation_scope"] == "zero_items"


def test_upload_uses_tenant_from_api_key_when_hint_missing():
    files = {"file": ("redesim.csv", BytesIO(REDESIM_CSV_CONTENT.encode()), "text/csv")}
    response = client.post("/validate", files=files, headers=auth_headers(REDESIM_API_KEY))
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "redesim"

    job = job_service.get_job(payload["job_id"])
    assert job is not None
    try:
        assert job.file_path is not None
        assert job.result_path is not None
        assert job.report_path is not None
        assert Path(job.file_path).parent.name == "redesim"
        assert Path(job.result_path).parent.name == "redesim"
        assert Path(job.report_path).parent.name == "redesim"
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_upload_can_request_all_items_scope():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default&validation_scope=all_items",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["validation_scope"] == "all_items"


def test_upload_can_request_duplicate_items_scope():
    files = {"file": ("test.csv", BytesIO(DUPLICATE_SCOPE_CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default&validation_scope=duplicate_items",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["validation_scope"] == "duplicate_items"


def test_upload_invalid_tenant():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=nonexistent",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 403
    assert "does not grant access" in response.json()["detail"]


def test_validate_rejects_tenant_conflict_with_api_key():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=redesim",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 403
    assert "redesim" in response.json()["detail"]


def test_get_job_status():
    job = job_service.create_job(tenant_id="default")
    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.job_id
    assert data["status"] == "queued"
    assert data["tenant_id"] == "default"
    assert data["validation_scope"] == "zero_items"
    assert data["current_step"] == "file_received"
    assert data["status_title"] == "Arquivo recebido"
    assert data["status_detail"]
    assert data["processed_rows"] == 0
    assert data["batch_size"] == 0
    assert data["source_total_rows"] == 0
    assert data["partial_summary"] == {}
    assert data["is_partial_result_available"] is False
    assert data["partial_grouped_problems"] == {}
    assert data["partial_duplicates"] == []
    assert data["row_results_preview"] == []
    assert data["created_at"]
    assert data["updated_at"]
    assert data["cancel_requested"] is False


def test_list_jobs_can_filter_active_only():
    queued_job = job_service.create_job(tenant_id="default", file_name="queued.csv")
    running_job = job_service.create_job(tenant_id="default", file_name="running.csv")
    completed_job = job_service.create_job(tenant_id="default", file_name="done.csv")
    job_service.create_job(tenant_id="redesim", file_name="other-tenant.csv")

    running_job.mark_running()
    completed_job.mark_running()
    completed_job.mark_completed(total_rows=1)

    response = client.get("/jobs?active_only=true", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()

    assert [job["job_id"] for job in payload] == [
        running_job.job_id,
        queued_job.job_id,
    ]
    assert all(job["status"] in {"queued", "running"} for job in payload)


def test_get_job_status_rejects_other_tenant_job():
    job = job_service.create_job(tenant_id="redesim")
    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    assert response.status_code == 403
    assert "redesim" in response.json()["detail"]


def test_cancel_job_marks_queued_job_as_canceled():
    job = job_service.create_job(tenant_id="default", file_name="lote.csv")

    response = client.post(f"/jobs/{job.job_id}/cancel", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "canceled"
    assert payload["cancel_requested"] is False
    assert payload["status_title"] == "Processamento cancelado"


def test_cancel_job_marks_running_job_as_cancel_requested():
    job = job_service.create_job(tenant_id="default", file_name="lote.csv")
    job.mark_running()

    response = client.post(f"/jobs/{job.job_id}/cancel", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "running"
    assert payload["cancel_requested"] is True
    assert payload["status_title"] == "Cancelamento solicitado"


def test_cancel_job_rejects_completed_job():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(total_rows=1)

    response = client.post(f"/jobs/{job.job_id}/cancel", headers=auth_headers())
    assert response.status_code == 400
    assert "queued or running" in response.json()["detail"]


def test_get_job_status_includes_file_name_metadata():
    job = job_service.create_job(tenant_id="default", file_name="lote.csv")
    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "lote.csv"


def test_get_job_status_includes_partial_preview_payload():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job_service.update_partial_result(
        job.job_id,
        total_rows=12,
        source_total_rows=20,
        processed_rows=4,
        batch_size=4,
        partial_summary={
            "total_rows": 12,
            "validated_rows": 12,
            "source_total_rows": 20,
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

    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["processed_rows"] == 4
    assert data["batch_size"] == 4
    assert data["source_total_rows"] == 20
    assert data["is_partial_result_available"] is True
    assert data["partial_summary"]["processed_rows"] == 4
    assert data["partial_summary"]["source_total_rows"] == 20
    assert data["partial_grouped_problems"]["DUPLICATE_ITEM"][0]["item"] == "001"
    assert data["partial_duplicates"][0]["count"] == 2
    assert data["row_results_preview"][0]["row_index"] == 0


def test_get_job_not_found():
    response = client.get("/jobs/nonexistent", headers=auth_headers())
    assert response.status_code == 404


def test_download_result_not_completed():
    job = job_service.create_job(tenant_id="default")
    response = client.get(f"/jobs/{job.job_id}/result", headers=auth_headers())
    assert response.status_code == 400
    assert "not completed" in response.json()["detail"]


def test_download_result_completed():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({"summary": {"total_rows": 1}}, f)
        result_path = f.name

    job.mark_completed(result_path=result_path, total_rows=1)

    response = client.get(f"/jobs/{job.job_id}/result", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["summary"]["total_rows"] == 1

    Path(result_path).unlink(missing_ok=True)


def test_validation_result_includes_item_and_descricao_metadata():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None
    try:
        assert job.result_path is not None
        assert job.report_path is not None
        assert job.file_path is not None

        result_response = client.get(f"/jobs/{job_id}/result", headers=auth_headers())
        assert result_response.status_code == 200

        payload = result_response.json()
        assert payload["summary"]["total_rows"] == 1
        assert payload["summary"]["source_total_rows"] == 2
        assert len(payload["row_results"]) == 1
        first_row = payload["row_results"][0]
        assert first_row["item"] == "002"
        assert first_row["descricao"] == "Cadeira"

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


def test_validation_result_can_include_all_items_scope():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default&validation_scope=all_items",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None
    try:
        result_response = client.get(f"/jobs/{job_id}/result", headers=auth_headers())
        assert result_response.status_code == 200

        payload = result_response.json()
        assert payload["summary"]["total_rows"] == 2
        assert payload["summary"]["source_total_rows"] == 2
        assert [row["item"] for row in payload["row_results"]] == ["001", "002"]
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_validation_result_can_include_duplicate_items_scope():
    files = {
        "file": (
            "test.csv",
            BytesIO(DUPLICATE_SCOPE_CSV_CONTENT.encode()),
            "text/csv",
        )
    }
    response = client.post(
        "/validate?tenant_id=default&validation_scope=duplicate_items",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None
    try:
        result_response = client.get(f"/jobs/{job_id}/result", headers=auth_headers())
        assert result_response.status_code == 200

        payload = result_response.json()
        assert payload["summary"]["total_rows"] == 2
        assert payload["summary"]["source_total_rows"] == 3
        assert [row["item"] for row in payload["row_results"]] == ["001", "001"]
        assert payload["duplicates"][0]["row_indices"] == [0, 2]
        assert "DUPLICATE_ITEM" in payload["grouped_problems"]
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_redesim_tenant_uses_configured_descricao_column_and_rules():
    files = {"file": ("redesim.csv", BytesIO(REDESIM_CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=redesim",
        files=files,
        headers=auth_headers(REDESIM_API_KEY),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None

    try:
        result_response = client.get(
            f"/jobs/{job_id}/result",
            headers=auth_headers(REDESIM_API_KEY),
        )
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
    response = client.get(f"/jobs/{job.job_id}/report", headers=auth_headers())
    assert response.status_code == 400


def test_download_report_file_missing():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(report_path="/nonexistent/report.pdf")

    response = client.get(f"/jobs/{job.job_id}/report", headers=auth_headers())
    assert response.status_code == 404
    assert "Report file not found" in response.json()["detail"]


def test_download_report_completed():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake content")
        report_path = f.name

    job.mark_completed(report_path=report_path)

    response = client.get(f"/jobs/{job.job_id}/report", headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"

    Path(report_path).unlink(missing_ok=True)


def test_download_job_csv_returns_current_corrected_file():
    job = job_service.create_job(tenant_id="default", file_name="inventario.csv")

    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa corrigida,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.get(f"/jobs/{job.job_id}/csv", headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="inventario_corrigido.csv"' in response.headers["content-disposition"]
    assert "Mesa corrigida" in response.text

    Path(csv_path).unlink(missing_ok=True)


def test_download_job_csv_file_missing():
    job = job_service.create_job(tenant_id="default", file_name="inventario.csv")
    job.file_path = "/nonexistent/inventario.csv"

    response = client.get(f"/jobs/{job.job_id}/csv", headers=auth_headers())
    assert response.status_code == 404
    assert "CSV file not found" in response.json()["detail"]


def test_download_duplicates_export_csv_for_completed_job():
    duplicate_csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
        "001,,Mesa reserva,MarcaX,ModeloY,SN2,Sala1,CC1,Detalhe,Obs\n"
    )
    files = {
        "file": (
            "duplicados.csv",
            BytesIO(duplicate_csv_content.encode()),
            "text/csv",
        )
    }
    response = client.post(
        "/validate?tenant_id=default&validation_scope=all_items",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None

    try:
        export_response = client.get(
            f"/jobs/{job_id}/exports/csv?kind=duplicates",
            headers=auth_headers(),
        )
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("text/csv")
        assert 'filename="duplicados_duplicados.csv"' in (
            export_response.headers["content-disposition"]
        )
        assert "Quantidade de Ocorrências" in export_response.text
        assert "001" in export_response.text
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_download_problem_group_export_csv_for_completed_job():
    files = {"file": ("test.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default",
        files=files,
        headers=auth_headers(),
    )
    assert response.status_code == 200

    job_id = response.json()["job_id"]
    job = job_service.get_job(job_id)
    assert job is not None

    try:
        export_response = client.get(
            f"/jobs/{job_id}/exports/csv?kind=problem_group&problem_code=ZERO_ITEM_COMPLEMENTO_EMPTY",
            headers=auth_headers(),
        )
        assert export_response.status_code == 200
        assert export_response.headers["content-type"].startswith("text/csv")
        assert 'filename="test_zero_item_complemento_empty.csv"' in (
            export_response.headers["content-disposition"]
        )
        assert "Código,Linha,Item,Descrição,Severidade,Campo,Mensagem" in export_response.text
        assert "ZERO_ITEM_COMPLEMENTO_EMPTY" in export_response.text
        assert "Cadeira" in export_response.text
    finally:
        if job.file_path:
            Path(job.file_path).unlink(missing_ok=True)
        if job.result_path:
            Path(job.result_path).unlink(missing_ok=True)
        if job.report_path:
            Path(job.report_path).unlink(missing_ok=True)


def test_download_result_not_found():
    response = client.get("/jobs/nonexistent/result", headers=auth_headers())
    assert response.status_code == 404


def test_download_report_not_found():
    response = client.get("/jobs/nonexistent/report", headers=auth_headers())
    assert response.status_code == 404


def test_download_job_csv_not_found():
    response = client.get("/jobs/nonexistent/csv", headers=auth_headers())
    assert response.status_code == 404


def test_upload_saves_file():
    files = {"file": ("inventory.csv", BytesIO(CSV_CONTENT.encode()), "text/csv")}
    response = client.post(
        "/validate?tenant_id=default",
        files=files,
        headers=auth_headers(),
    )
    data = response.json()
    job = job_service.get_job(data["job_id"])
    assert job is not None
    assert job.file_path is not None
    assert job.file_name == "inventory.csv"
    assert Path(job.file_path).parent.name == "default"
    assert Path(job.file_path).name.endswith("inventory.csv")

    Path(job.file_path).unlink(missing_ok=True)
    if job.result_path:
        Path(job.result_path).unlink(missing_ok=True)
    if job.report_path:
        Path(job.report_path).unlink(missing_ok=True)


def test_job_status_shows_counters_after_completion():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(
        total_rows=10,
        source_total_rows=15,
        rows_with_issues=3,
        total_issues=5,
    )

    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    data = response.json()
    assert data["total_rows"] == 10
    assert data["source_total_rows"] == 15
    assert data["rows_with_issues"] == 3
    assert data["total_issues"] == 5
    assert data["current_step"] == "report_ready"
    assert data["status_title"] == "Relatório pronto"


def test_job_status_shows_error_after_failure():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_failed("Something went wrong")

    response = client.get(f"/jobs/{job.job_id}", headers=auth_headers())
    data = response.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "Something went wrong"
    assert data["current_step"] == "failed"
    assert data["status_title"] == "Falha no processamento"


def test_update_job_row_updates_csv():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.patch(
        f"/jobs/{job.job_id}/rows/0",
        json={"updates": {"descricao": "Mesa executiva"}},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["row_index"] == 0
    assert payload["updated_row"]["Descrição"] == "Mesa executiva"

    updated_csv = Path(csv_path).read_text()
    assert "Mesa executiva" in updated_csv

    Path(csv_path).unlink(missing_ok=True)


def test_get_job_row_returns_current_value_and_mapping():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.get(f"/jobs/{job.job_id}/rows/0", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["row"]["Descrição"] == "Mesa"
    assert payload["resolved_columns"]["descricao"] == "Descrição"

    Path(csv_path).unlink(missing_ok=True)


def test_resolve_duplicate_rows_keeps_highest_occurrence_and_merges_missing_fields():
    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa antiga,MarcaAntiga,ModeloAntigo,SNAntigo,"
        "SalaAntiga,CCAntigo,DetalheAntigo,ObsAntiga\n"
        "001,,Mesa reserva,MarcaAnterior,ModeloAnterior,SNAnterior,"
        "SalaAnterior,CCAnterior,DetalheAnterior,ObsAnterior\n"
        "001,,Mesa atual,,ModeloAtual,,SalaAtual,CCAtual,,\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job = job_service.create_job(
        tenant_id="default",
        file_path=csv_path,
        file_name="duplicados.csv",
        params={"validation_scope": "all_items"},
    )
    run_validation_job(job.job_id, job_service)

    response = client.post(
        f"/jobs/{job.job_id}/duplicates/resolve",
        json={"row_indices": [0, 1, 2], "keep_row_index": 1},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kept_row_index"] == 2
    assert payload["deleted_row_indices"] == [0, 1]
    assert payload["remaining_rows"] == 1
    assert payload["merged_columns"] == [
        "Marca",
        "NS",
        "Complemento",
        "Observação",
    ]

    updated_csv = Path(csv_path).read_text(encoding="utf-8")
    assert "Mesa atual" in updated_csv
    assert "MarcaAnterior" in updated_csv
    assert "ModeloAtual" in updated_csv
    assert "SNAnterior" in updated_csv
    assert "CCAtual" in updated_csv
    assert "DetalheAnterior" in updated_csv
    assert "ObsAnterior" in updated_csv
    assert "Mesa antiga" not in updated_csv
    assert "Mesa reserva" not in updated_csv
    assert "ModeloAnterior" not in updated_csv
    assert "CCAnterior" not in updated_csv

    result_response = client.get(f"/jobs/{job.job_id}/result", headers=auth_headers())
    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["summary"]["total_rows"] == 1
    assert result_payload["duplicates"] == []
    assert [row["descricao"] for row in result_payload["row_results"]] == ["Mesa atual"]

    audit_events = [
        event for event in audit_service.list_events() if event.job_id == job.job_id
    ]
    assert [event.event_type.value for event in audit_events[:2]] == [
        "duplicates_resolved",
        "job_completed",
    ]
    assert audit_events[0].api_key_id == DEFAULT_API_KEY_ID
    assert audit_events[0].details["row_indices"] == [0, 1, 2]
    assert audit_events[0].details["kept_row_index"] == 2
    assert audit_events[0].details["deleted_row_indices"] == [0, 1]

    Path(csv_path).unlink(missing_ok=True)
    refreshed_job = job_service.get_job(job.job_id)
    if refreshed_job and refreshed_job.result_path:
        Path(refreshed_job.result_path).unlink(missing_ok=True)
    if refreshed_job and refreshed_job.report_path:
        Path(refreshed_job.report_path).unlink(missing_ok=True)


def test_resolve_duplicate_rows_same_name_skips_media_and_datetime_columns():
    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,"
        "Observação,foto_complementar_memento,data_inventario,hora_inventario,"
        "updated_at,registro,usuario\n"
        "001,,Mesa,Marca antiga,Modelo antigo,SN antigo,Sala antiga,CC antigo,"
        "Detalhe antigo,Obs antiga,https://example.com/foto-1.jpg,2026-01-01,"
        "08:00,2026-01-01T08:00:00,2026-02-01 10:15:00,Ana\n"
        "001,PA-100,Mesa,Marca intermediaria,Modelo intermediario,,"
        "Sala intermediaria,,Detalhe intermediario,,"
        "https://example.com/foto-2.jpg,2026-01-02,09:00,"
        "2026-01-02T09:00:00,2026-02-02 11:45:00,Bruno\n"
        "001,,Mesa,Marca atual,,SN atual,,CC atual,,Obs atual,,,,,,Carla\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job = job_service.create_job(
        tenant_id="default",
        file_path=csv_path,
        file_name="duplicados.csv",
        params={"validation_scope": "all_items"},
    )
    run_validation_job(job.job_id, job_service)

    response = client.post(
        f"/jobs/{job.job_id}/duplicates/resolve",
        json={"row_indices": [0, 1, 2], "keep_row_index": 2},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kept_row_index"] == 2
    assert payload["deleted_row_indices"] == [0, 1]
    assert payload["remaining_rows"] == 1
    assert payload["merged_columns"] == [
        "Placa Anterior",
        "Modelo",
        "Local",
        "Complemento",
    ]

    updated_csv = Path(csv_path).read_text(encoding="utf-8")
    assert "Marca atual" in updated_csv
    assert "Modelo intermediario" in updated_csv
    assert "PA-100" in updated_csv
    assert "Sala intermediaria" in updated_csv
    assert "Detalhe intermediario" in updated_csv
    assert "https://example.com/foto-1.jpg" not in updated_csv
    assert "2026-01-01T08:00:00" not in updated_csv
    assert "2026-01-02T09:00:00" not in updated_csv
    assert ",,,Carla" in updated_csv

    result_response = client.get(f"/jobs/{job.job_id}/rows/0", headers=auth_headers())
    assert result_response.status_code == 200
    row_payload = result_response.json()["row"]
    assert row_payload["foto_complementar_memento"] == ""
    assert row_payload["data_inventario"] == ""
    assert row_payload["hora_inventario"] == ""
    assert row_payload["updated_at"] == ""
    assert row_payload["registro"] == ""
    assert row_payload["usuario"] == "Carla"

    Path(csv_path).unlink(missing_ok=True)
    refreshed_job = job_service.get_job(job.job_id)
    if refreshed_job and refreshed_job.result_path:
        Path(refreshed_job.result_path).unlink(missing_ok=True)
    if refreshed_job and refreshed_job.report_path:
        Path(refreshed_job.report_path).unlink(missing_ok=True)


def test_resolve_duplicate_rows_requires_completed_job_for_in_place_refresh():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
        "001,,Mesa reserva,MarcaX,ModeloY,SN2,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.post(
        f"/jobs/{job.job_id}/duplicates/resolve",
        json={"row_indices": [0, 1], "keep_row_index": 1},
        headers=auth_headers(),
    )
    assert response.status_code == 400
    assert "completed jobs" in response.json()["detail"]

    unchanged_csv = Path(csv_path).read_text(encoding="utf-8")
    assert "Mesa reserva" in unchanged_csv
    assert "Mesa," in unchanged_csv

    Path(csv_path).unlink(missing_ok=True)


def test_resolve_duplicate_rows_rejects_keep_index_outside_group():
    job = job_service.create_job(tenant_id="default")
    job.mark_running()

    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
        "001,,Mesa reserva,MarcaX,ModeloY,SN2,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.post(
        f"/jobs/{job.job_id}/duplicates/resolve",
        json={"row_indices": [0, 1], "keep_row_index": 3},
        headers=auth_headers(),
    )
    assert response.status_code == 400
    assert "keep_row_index" in response.json()["detail"]

    Path(csv_path).unlink(missing_ok=True)


def test_reprocess_job_creates_new_job_from_corrected_csv():
    job = job_service.create_job(tenant_id="default", file_name="corrigido.csv")
    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa executiva,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.post(f"/jobs/{job.job_id}/reprocess", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] != job.job_id
    assert payload["tenant_id"] == "default"
    assert payload["validation_scope"] == "zero_items"

    new_job = job_service.get_job(payload["job_id"])
    assert new_job is not None
    assert new_job.file_path is not None
    assert new_job.file_path != csv_path
    assert Path(new_job.file_path).parent.name == "default"
    assert "Mesa executiva" in Path(new_job.file_path).read_text()

    Path(csv_path).unlink(missing_ok=True)
    Path(new_job.file_path).unlink(missing_ok=True)
    if new_job.result_path:
        Path(new_job.result_path).unlink(missing_ok=True)
    if new_job.report_path:
        Path(new_job.report_path).unlink(missing_ok=True)


def test_reprocess_job_preserves_validation_scope():
    job = job_service.create_job(
        tenant_id="default",
        file_name="corrigido.csv",
        params={"validation_scope": "all_items"},
    )
    csv_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
        "001,,Mesa executiva,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
    )
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        f.write(csv_content)
        csv_path = f.name

    job.file_path = csv_path

    response = client.post(f"/jobs/{job.job_id}/reprocess", headers=auth_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["validation_scope"] == "all_items"

    new_job = job_service.get_job(payload["job_id"])
    assert new_job is not None
    assert new_job.params["validation_scope"] == "all_items"

    Path(csv_path).unlink(missing_ok=True)
    if new_job.file_path:
        Path(new_job.file_path).unlink(missing_ok=True)
    if new_job.result_path:
        Path(new_job.result_path).unlink(missing_ok=True)
    if new_job.report_path:
        Path(new_job.report_path).unlink(missing_ok=True)
