import copy
import csv
import json
import threading
import time
from io import BytesIO, StringIO
from pathlib import Path

import pytest
from openpyxl import Workbook

import app.services.validation_service as validation_service
from app.core.job import JobStatus
from app.core.llm_cache import LLM_CACHE_PATH_ENV
from app.core.tenant_loader import load_tenant_config
from app.rules.llm_audit import set_default_client
from app.services.job_service import JobService
from app.services.validation_service import (
    OperationalExportKind,
    UploadPreflightError,
    delete_job_csv_rows,
    delete_job_csv_rows_and_refresh,
    get_job_csv_download,
    get_job_operational_export,
    get_job_report_download,
    get_job_result_payload,
    get_job_review_flags_path,
    read_job_csv_row,
    resolve_duplicate_csv_rows_and_refresh,
    run_upload_preflight,
    run_validation_job,
    set_job_row_review_flag,
    update_job_csv_row,
)

CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "001,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
    "001,,Armario,MarcaA,ModeloB,SN3,Sala3,CC3,,\n"
)

DUPLICATE_SCOPE_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "002,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
    "001,,Armario,MarcaA,ModeloB,SN3,Sala3,CC3,Detalhe armario completo validado,\n"
)

REDESIM_V2_DUPLICATE_CONTENT = (
    "especie_id;base_id;;item_anterior;item;descricao;marca;modelo;ns;complemento;observacao;cc;cc_descricao;local;latitude;longitude;gps;usuario;foto_complementar_memento;\n"
    "1;144;uuid-1;;001;MONITOR;Dell;P2419H;SN1;;AÇÃO;8327;A27;MATRIZ;;;;Letícia;;\n"
    "1;144;uuid-2;;001;MESA;;;;;;8327;A27;MATRIZ;;;;Letícia;;\n"
)

EMPRESA_EXEMPLO_LLM_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "900,,Mesa,Acme,Model X,SN900,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
)

EMPRESA_EXEMPLO_LLM_BATCH_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "900,,Mesa,Acme,Model X,SN900,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
    "901,,Mesa,Acme,Model X,SN901,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
    "902,,Mesa,Acme,Model X,SN902,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
    "903,,Mesa,Acme,Model X,SN903,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
    "904,,Mesa,Acme,Model X,SN904,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
    "905,,Mesa,Acme,Model X,SN905,Sala 9,CC9,Detalhe completo com gavetas laterais cromadas,Obs\n"
)


def build_default_csv_content(row_count: int) -> str:
    rows = [
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação"
    ]
    for index in range(row_count):
        rows.append(
            f"{index:03},,Mesa,MarcaX,ModeloY,SN{index},Sala,CC,"
            f"Detalhe completo {index},Obs"
        )
    return "\n".join(rows) + "\n"


def build_xlsx_content_from_csv(csv_content: str) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    for row in csv.reader(StringIO(csv_content)):
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class RecordingJobService(JobService):
    def __init__(self) -> None:
        super().__init__()
        self.partial_snapshots: list[dict] = []

    def update_partial_result(self, job_id: str, **kwargs):
        self.partial_snapshots.append(copy.deepcopy(kwargs))
        return super().update_partial_result(job_id, **kwargs)


class CancelAfterProgressJobService(RecordingJobService):
    def update_partial_result(self, job_id: str, **kwargs):
        updated = super().update_partial_result(job_id, **kwargs)
        if kwargs.get("processed_rows", 0) > 0 and not updated.cancel_requested:
            self.request_job_cancellation(job_id)
        return updated


class FakeLLMClient:
    def __init__(self, response: str = "[]", *, delay_seconds: float = 0.0) -> None:
        self.response = response
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, object]] = []
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    def complete(self, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)

        try:
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
            with self._lock:
                self.calls.append(
                    {
                        "model": model,
                        "prompt": prompt,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                )
            return self.response
        finally:
            with self._lock:
                self._in_flight -= 1


def setup_function():
    validation_service._JOB_CSV_CONTEXT_CACHE.clear()


def _patch_empresa_exemplo_llm_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parallel_requests: int,
    cache_ttl_seconds: int = 0,
) -> None:
    original_load_tenant_config = validation_service.load_tenant_config

    def patched_load_tenant_config(tenant_id: str):
        config = original_load_tenant_config(tenant_id)
        if config.tenant_id != "empresa_exemplo":
            return config
        return config.model_copy(
            update={
                "llm": config.llm.model_copy(
                    update={
                        "parallel_requests": parallel_requests,
                        "cache_ttl_seconds": cache_ttl_seconds,
                    }
                )
            }
        )

    monkeypatch.setattr(
        validation_service,
        "load_tenant_config",
        patched_load_tenant_config,
    )


def _run_empresa_exemplo_llm_job(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    parallel_requests: int,
    delay_seconds: float = 0.0,
) -> tuple[dict, float, FakeLLMClient]:
    run_dir = tmp_path / f"run-{parallel_requests}"
    results_dir = run_dir / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)
    monkeypatch.setenv(LLM_CACHE_PATH_ENV, str(run_dir / "llm_cache.json"))
    _patch_empresa_exemplo_llm_config(
        monkeypatch,
        parallel_requests=parallel_requests,
        cache_ttl_seconds=0,
    )

    csv_path = run_dir / "empresa_exemplo.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(EMPRESA_EXEMPLO_LLM_BATCH_CONTENT, encoding="utf-8")

    client = FakeLLMClient(response="[]", delay_seconds=delay_seconds)
    set_default_client(client)
    try:
        service = RecordingJobService()
        job = service.create_job(
            tenant_id="empresa_exemplo",
            file_path=str(csv_path),
            file_name="empresa_exemplo.csv",
        )
        started_at = time.perf_counter()
        run_validation_job(job.job_id, service)
        elapsed = time.perf_counter() - started_at

        updated_job = service.get_job(job.job_id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.COMPLETED
        assert updated_job.result_path is not None

        payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
        return payload, elapsed, client
    finally:
        set_default_client(None)


def test_run_validation_job_publishes_incremental_preview_before_final_artifacts(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.processed_rows == 2
    assert updated_job.total_rows == 2
    assert updated_job.source_total_rows == 3
    assert updated_job.is_partial_result_available is False
    assert updated_job.result_path is not None
    assert updated_job.report_path is not None
    assert Path(updated_job.result_path).exists()
    assert Path(updated_job.report_path).exists()

    assert len(service.partial_snapshots) >= 2
    first_snapshot = service.partial_snapshots[0]
    assert first_snapshot["processed_rows"] == 0
    assert first_snapshot["batch_size"] == 1
    assert first_snapshot["current_step"] == "validating_batches"
    assert first_snapshot["source_total_rows"] == 3
    assert first_snapshot["partial_summary"]["total_rows"] == 2
    assert first_snapshot["partial_duplicates"][0]["item"] == "001"

    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["processed_rows"] == 2
    assert last_snapshot["partial_summary"]["processed_rows"] == 2
    assert last_snapshot["is_partial_result_available"] is True
    assert "DUPLICATE_ITEM" in last_snapshot["partial_grouped_problems"]
    assert last_snapshot["row_results_preview"] == []

    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["summary"]["total_rows"] == 2
    assert payload["summary"]["source_total_rows"] == 3
    assert payload["summary"]["rows_with_issues"] == 2
    assert payload["duplicates"][0]["item"] == "001"


def test_run_validation_job_can_include_all_items_when_scope_requests_it(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.processed_rows == 3
    assert updated_job.total_rows == 3
    assert updated_job.source_total_rows == 3

    assert len(service.partial_snapshots) >= 2
    first_snapshot = service.partial_snapshots[0]
    assert first_snapshot["processed_rows"] == 0
    assert first_snapshot["partial_summary"]["total_rows"] == 3

    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["processed_rows"] == 3
    assert last_snapshot["partial_summary"]["processed_rows"] == 3

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["summary"]["total_rows"] == 3
    assert payload["summary"]["source_total_rows"] == 3
    assert [row["row_index"] for row in payload["row_results"]] == [0, 1, 2]


def test_run_validation_job_can_include_only_duplicate_items_when_scope_requests_it(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(DUPLICATE_SCOPE_CONTENT, encoding="utf-8")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "duplicate_items"},
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.processed_rows == 2
    assert updated_job.total_rows == 2
    assert updated_job.source_total_rows == 3

    assert len(service.partial_snapshots) >= 2
    first_snapshot = service.partial_snapshots[0]
    assert first_snapshot["processed_rows"] == 0
    assert first_snapshot["partial_summary"]["total_rows"] == 2
    assert [group["item"] for group in first_snapshot["partial_duplicates"]] == ["001"]

    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["processed_rows"] == 2
    assert last_snapshot["partial_summary"]["processed_rows"] == 2

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["summary"]["total_rows"] == 2
    assert payload["summary"]["source_total_rows"] == 3
    assert [row["row_index"] for row in payload["row_results"]] == [0, 2]
    assert payload["duplicates"][0]["row_indices"] == [0, 2]
    assert "DUPLICATE_ITEM" in payload["grouped_problems"]


def test_run_validation_job_records_llm_prompt_version_in_result_and_pdf(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)
    monkeypatch.setenv(LLM_CACHE_PATH_ENV, str(tmp_path / "llm_cache.json"))

    csv_path = tmp_path / "empresa_exemplo.csv"
    csv_path.write_text(EMPRESA_EXEMPLO_LLM_CONTENT, encoding="utf-8")

    client = FakeLLMClient(response="[]")
    set_default_client(client)
    try:
        service = RecordingJobService()
        job = service.create_job(
            tenant_id="empresa_exemplo",
            file_path=str(csv_path),
            file_name="empresa_exemplo.csv",
        )

        run_validation_job(job.job_id, service)

        updated_job = service.get_job(job.job_id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.COMPLETED
        assert updated_job.result_path is not None
        assert updated_job.report_path is not None
        assert len(client.calls) == 1

        payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
        assert payload["llm_audit"] == {
            "prompt_versions": ["empresa_exemplo-v1"],
            "models": ["claude-sonnet-4-20250514"],
        }
        assert payload["row_results"][0]["issues"] == []

        report_content = Path(updated_job.report_path).read_bytes()
        assert b"empresa_exemplo-v1" in report_content
        assert b"claude-sonnet-4-20250514" in report_content
    finally:
        set_default_client(None)


def test_run_validation_job_parallel_llm_matches_serial_output(
    tmp_path,
    monkeypatch,
):
    serial_payload, _, serial_client = _run_empresa_exemplo_llm_job(
        tmp_path / "serial",
        monkeypatch,
        parallel_requests=1,
    )
    parallel_payload, _, parallel_client = _run_empresa_exemplo_llm_job(
        tmp_path / "parallel",
        monkeypatch,
        parallel_requests=3,
    )

    assert serial_payload == parallel_payload
    assert serial_payload["llm_audit"] == {
        "prompt_versions": ["empresa_exemplo-v1"],
        "models": ["claude-sonnet-4-20250514"],
    }
    assert len(serial_client.calls) == 6
    assert len(parallel_client.calls) == 6


def test_run_validation_job_parallel_llm_reduces_processing_time(
    tmp_path,
    monkeypatch,
):
    serial_payload, serial_elapsed, serial_client = _run_empresa_exemplo_llm_job(
        tmp_path / "serial-slow",
        monkeypatch,
        parallel_requests=1,
        delay_seconds=0.05,
    )
    parallel_payload, parallel_elapsed, parallel_client = _run_empresa_exemplo_llm_job(
        tmp_path / "parallel-slow",
        monkeypatch,
        parallel_requests=3,
        delay_seconds=0.05,
    )

    assert serial_payload == parallel_payload
    assert serial_client.max_in_flight == 1
    assert parallel_client.max_in_flight > 1
    assert parallel_elapsed < serial_elapsed * 0.75


def test_run_validation_job_keeps_redesim_descricao_in_preview_and_final_duplicates(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "redesim.csv"
    csv_path.write_text(REDESIM_V2_DUPLICATE_CONTENT, encoding="iso-8859-1")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="redesim",
        file_path=str(csv_path),
        file_name="redesim.csv",
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED

    assert len(service.partial_snapshots) >= 2
    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["partial_duplicates"][0]["descricao"] == "MONITOR / MESA"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][0]["descricao"] == "MONITOR"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][1]["descricao"] == "MESA"
    assert last_snapshot["row_results_preview"] == []

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["row_results"][0]["descricao"] == "MONITOR"
    assert payload["row_results"][1]["descricao"] == "MESA"
    assert payload["duplicates"][0]["descricao"] == "MONITOR / MESA"
    duplicate_group = payload["grouped_problems"]["DUPLICATE_ITEM"]
    assert duplicate_group[0]["descricao"] == "MONITOR"
    assert duplicate_group[1]["descricao"] == "MESA"


def test_run_validation_job_accepts_redesim_v2_alias_and_writes_redesim_artifacts(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "redesim_v2.csv"
    csv_path.write_text(REDESIM_V2_DUPLICATE_CONTENT, encoding="iso-8859-1")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="redesim_v2",
        file_path=str(csv_path),
        file_name="redesim_v2.csv",
    )
    assert job.tenant_id == "redesim"

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.tenant_id == "redesim"
    assert updated_job.result_path is not None
    assert Path(updated_job.result_path).parent.name == "redesim"

    assert len(service.partial_snapshots) >= 2
    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["partial_duplicates"][0]["descricao"] == "MONITOR / MESA"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][0]["descricao"] == "MONITOR"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][1]["descricao"] == "MESA"
    assert last_snapshot["row_results_preview"] == []

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["row_results"][0]["descricao"] == "MONITOR"
    assert payload["row_results"][1]["descricao"] == "MESA"
    assert payload["duplicates"][0]["descricao"] == "MONITOR / MESA"


@pytest.mark.parametrize(
    ("tenant_id", "file_name", "content", "encoding"),
    [
        ("default", "lote.csv", CSV_CONTENT, "utf-8"),
        ("redesim", "redesim.csv", REDESIM_V2_DUPLICATE_CONTENT, "iso-8859-1"),
    ],
)
def test_run_validation_job_writes_artifacts_to_tenant_scoped_results_directory(
    tmp_path,
    monkeypatch,
    tenant_id,
    file_name,
    content,
    encoding,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / file_name
    csv_path.write_text(content, encoding=encoding)

    service = JobService()
    job = service.create_job(
        tenant_id=tenant_id,
        file_path=str(csv_path),
        file_name=file_name,
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.result_path is not None
    assert updated_job.report_path is not None
    assert Path(updated_job.result_path) == (
        results_dir / tenant_id / f"{job.job_id}_result.json"
    )
    assert Path(updated_job.report_path) == (
        results_dir / tenant_id / f"{job.job_id}_report.pdf"
    )


def test_review_flags_persist_in_job_results_sidecar_and_survive_reload(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")
    job_store_path = tmp_path / "jobs.json"

    service = JobService(storage_path=job_store_path)
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )
    run_validation_job(job.job_id, service)

    update = set_job_row_review_flag(
        job.job_id,
        service,
        row_index=1,
        status="review",
    )

    flags_path = get_job_review_flags_path(job.job_id, service)
    assert flags_path == results_dir / "default" / job.job_id / "review_flags.json"
    assert flags_path.exists()
    assert json.loads(flags_path.read_text(encoding="utf-8"))["flags"] == {
        "1": "review"
    }
    assert update.review_flags == [{"row_index": 1, "status": "review"}]

    payload = get_job_result_payload(job.job_id, service)
    assert payload["review_flags"] == [{"row_index": 1, "status": "review"}]

    reloaded_service = JobService(storage_path=job_store_path)
    reloaded_payload = get_job_result_payload(job.job_id, reloaded_service)
    assert reloaded_payload["review_flags"] == [
        {"row_index": 1, "status": "review"}
    ]

    clear_update = set_job_row_review_flag(
        job.job_id,
        reloaded_service,
        row_index=1,
        status="clear",
    )
    assert clear_update.review_flags == []
    assert get_job_result_payload(job.job_id, reloaded_service)["review_flags"] == []


def test_review_flags_reject_rows_outside_the_current_result(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )
    run_validation_job(job.job_id, service)

    with pytest.raises(ValueError, match="Row index not found"):
        set_job_row_review_flag(
            job.job_id,
            service,
            row_index=99,
            status="review",
        )


def test_job_csv_read_and_update_preserve_redesim_csv_format(tmp_path):
    csv_path = tmp_path / "redesim.csv"
    csv_path.write_text(REDESIM_V2_DUPLICATE_CONTENT, encoding="iso-8859-1")

    service = JobService()
    job = service.create_job(
        tenant_id="redesim",
        file_path=str(csv_path),
        file_name="redesim.csv",
    )

    row, resolved_columns = read_job_csv_row(job.job_id, service, row_index=0)
    assert resolved_columns["descricao"] == "descricao"
    assert row["descricao"] == "MONITOR"

    updated_row = update_job_csv_row(
        job.job_id,
        service,
        row_index=0,
        updates={"descricao": "MONITOR AÇÃO", "observacao": "AÇÃO MANUAL"},
    )
    assert updated_row["descricao"] == "MONITOR AÇÃO"
    assert updated_row["observacao"] == "AÇÃO MANUAL"

    updated_csv = csv_path.read_text(encoding="iso-8859-1")
    assert updated_csv.splitlines()[0].startswith(
        "especie_id;base_id;;item_anterior;item;descricao;"
    )
    assert "MONITOR AÇÃO" in updated_csv
    assert "AÇÃO MANUAL" in updated_csv


def test_job_csv_context_cache_reuses_loaded_dataframe_across_row_reads_and_updates(
    tmp_path,
    monkeypatch,
):
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    read_calls = 0
    original_read = validation_service._read_tenant_csv

    def counting_read(*args, **kwargs):
        nonlocal read_calls
        read_calls += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(validation_service, "_read_tenant_csv", counting_read)

    first_row, _ = read_job_csv_row(job.job_id, service, row_index=0)
    second_row, _ = read_job_csv_row(job.job_id, service, row_index=1)
    assert first_row["Descrição"] == "Mesa"
    assert second_row["Descrição"] == "Cadeira"
    assert read_calls == 1

    updated_row = update_job_csv_row(
        job.job_id,
        service,
        row_index=1,
        updates={"descricao": "Cadeira revisada"},
    )
    assert updated_row["Descrição"] == "Cadeira revisada"
    assert read_calls == 1

    refreshed_row, _ = read_job_csv_row(job.job_id, service, row_index=1)
    assert refreshed_row["Descrição"] == "Cadeira revisada"
    assert read_calls == 1


def test_job_csv_context_cache_reloads_when_source_file_changes_outside_service(
    tmp_path,
    monkeypatch,
):
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    read_calls = 0
    original_read = validation_service._read_tenant_csv

    def counting_read(*args, **kwargs):
        nonlocal read_calls
        read_calls += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(validation_service, "_read_tenant_csv", counting_read)

    first_row, _ = read_job_csv_row(job.job_id, service, row_index=0)
    assert first_row["Descrição"] == "Mesa"
    assert read_calls == 1

    csv_path.write_text(
        CSV_CONTENT.replace("Mesa", "Mesa externa", 1),
        encoding="utf-8",
    )

    refreshed_row, _ = read_job_csv_row(job.job_id, service, row_index=0)
    assert refreshed_row["Descrição"] == "Mesa externa"
    assert read_calls == 2


def test_delete_job_csv_rows_removes_selected_duplicates_and_reindexes(tmp_path):
    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
    )

    remaining_rows = delete_job_csv_rows(
        job.job_id,
        service,
        row_indices=[2],
    )

    assert remaining_rows == 2
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 3
    assert "Armario" not in csv_path.read_text(encoding="utf-8")
    assert "Cadeira" in csv_path.read_text(encoding="utf-8")


def test_delete_job_csv_rows_and_refresh_rebuilds_artifacts_in_place(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(
        (
            "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
            "001,,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe,Obs\n"
            "001,,Mesa reserva,MarcaX,ModeloY,SN2,Sala1,CC1,Detalhe,Obs\n"
            "002,,Cadeira,MarcaZ,ModeloW,SN3,Sala2,CC2,,\n"
        ),
        encoding="utf-8",
    )

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )

    run_validation_job(job.job_id, service)

    initial_job = service.get_job(job.job_id)
    assert initial_job is not None
    assert initial_job.result_path is not None
    assert initial_job.report_path is not None
    initial_result_path = initial_job.result_path
    initial_report_path = initial_job.report_path
    initial_payload = json.loads(Path(initial_result_path).read_text(encoding="utf-8"))
    assert initial_payload["duplicates"][0]["count"] == 2

    remaining_rows = delete_job_csv_rows_and_refresh(
        job.job_id,
        service,
        row_indices=[1],
    )

    refreshed_job = service.get_job(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.COMPLETED
    assert refreshed_job.result_path == initial_result_path
    assert refreshed_job.report_path == initial_report_path
    assert Path(refreshed_job.result_path).exists()
    assert Path(refreshed_job.report_path).exists()
    assert remaining_rows == 2

    refreshed_payload = json.loads(
        Path(refreshed_job.result_path).read_text(encoding="utf-8")
    )
    assert refreshed_payload["summary"]["total_rows"] == 2
    assert refreshed_payload["duplicates"] == []
    assert [row["item"] for row in refreshed_payload["row_results"]] == ["001", "002"]
    assert [row["row_index"] for row in refreshed_payload["row_results"]] == [0, 1]


def test_resolve_duplicate_csv_rows_keeps_highest_row_and_merges_previous_values(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(
        (
            "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
            "001,,Mesa antiga,Marca antiga,Modelo antigo,SN antigo,"
            "Sala antiga,CC antiga,Detalhe antigo,Obs antiga\n"
            "001,,Mesa intermediaria,,Modelo intermediario,,Sala intermediaria,CC intermediario,,\n"
            "001,,Mesa atual,,Modelo atual,SN atual,,CC atual,,\n"
        ),
        encoding="utf-8",
    )

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )
    run_validation_job(job.job_id, service)

    resolution = resolve_duplicate_csv_rows_and_refresh(
        job.job_id,
        service,
        row_indices=[0, 1, 2],
    )

    assert resolution.kept_row_index == 2
    assert resolution.deleted_row_indices == [0, 1]
    assert resolution.remaining_rows == 1
    assert resolution.merged_columns == [
        "Marca",
        "Local",
        "Complemento",
        "Observação",
    ]

    row, _ = read_job_csv_row(job.job_id, service, row_index=0)
    assert row["Descrição"] == "Mesa atual"
    assert row["Marca"] == "Marca antiga"
    assert row["Modelo"] == "Modelo atual"
    assert row["NS"] == "SN atual"
    assert row["Local"] == "Sala intermediaria"
    assert row["CC"] == "CC atual"
    assert row["Complemento"] == "Detalhe antigo"
    assert row["Observação"] == "Obs antiga"

    refreshed_job = service.get_job(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.COMPLETED
    assert refreshed_job.result_path is not None
    refreshed_payload = json.loads(
        Path(refreshed_job.result_path).read_text(encoding="utf-8")
    )
    assert refreshed_payload["duplicates"] == []
    assert refreshed_payload["summary"]["total_rows"] == 1
    assert refreshed_payload["row_results"][0]["descricao"] == "Mesa atual"


def test_resolve_duplicate_csv_rows_same_name_skips_media_and_datetime_columns(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(
        (
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
        ),
        encoding="utf-8",
    )

    service = JobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )
    run_validation_job(job.job_id, service)

    resolution = resolve_duplicate_csv_rows_and_refresh(
        job.job_id,
        service,
        row_indices=[0, 1, 2],
    )

    assert resolution.kept_row_index == 2
    assert resolution.deleted_row_indices == [0, 1]
    assert resolution.remaining_rows == 1
    assert resolution.merged_columns == [
        "Placa Anterior",
        "Modelo",
        "Local",
        "Complemento",
    ]

    row, _ = read_job_csv_row(job.job_id, service, row_index=0)
    assert row["Descrição"] == "Mesa"
    assert row["Marca"] == "Marca atual"
    assert row["Modelo"] == "Modelo intermediario"
    assert row["NS"] == "SN atual"
    assert row["Placa Anterior"] == "PA-100"
    assert row["Local"] == "Sala intermediaria"
    assert row["CC"] == "CC atual"
    assert row["Complemento"] == "Detalhe intermediario"
    assert row["Observação"] == "Obs atual"
    assert row["usuario"] == "Carla"
    assert row["foto_complementar_memento"] == ""
    assert row["data_inventario"] == ""
    assert row["hora_inventario"] == ""
    assert row["updated_at"] == ""
    assert row["registro"] == ""

    refreshed_job = service.get_job(job.job_id)
    assert refreshed_job is not None
    assert refreshed_job.result_path is not None
    refreshed_payload = json.loads(
        Path(refreshed_job.result_path).read_text(encoding="utf-8")
    )
    assert refreshed_payload["duplicates"] == []
    assert refreshed_payload["summary"]["total_rows"] == 1


def test_run_validation_job_can_be_canceled_after_batch_checkpoint(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(CSV_CONTENT, encoding="utf-8")

    service = CancelAfterProgressJobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.CANCELED
    assert updated_job.cancel_requested is False
    assert updated_job.status_title == "Processamento cancelado"
    assert updated_job.result_path is None
    assert updated_job.report_path is None


def test_run_validation_job_can_be_canceled_during_batch_processing(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "lote.csv"
    csv_path.write_text(build_default_csv_content(25), encoding="utf-8")

    service = RecordingJobService()
    job = service.create_job(
        tenant_id="default",
        file_path=str(csv_path),
        file_name="lote.csv",
        params={"validation_scope": "all_items"},
    )
    original_validate_row = validation_service.ValidationEngine.validate_row
    cancellation_requested = False

    def cancel_after_first_row(self, *args, **kwargs):
        nonlocal cancellation_requested
        result = original_validate_row(self, *args, **kwargs)
        row_index = kwargs.get("row_index")
        if row_index is None and args:
            row_index = args[0]
        if row_index == 0 and not cancellation_requested:
            service.request_job_cancellation(job.job_id)
            cancellation_requested = True
        return result

    monkeypatch.setattr(
        validation_service.ValidationEngine,
        "validate_row",
        cancel_after_first_row,
    )

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.CANCELED
    assert updated_job.cancel_requested is False
    assert updated_job.total_rows == 25
    assert updated_job.source_total_rows == 25
    assert updated_job.result_path is None
    assert updated_job.report_path is None
    assert not any(results_dir.rglob("*_result.json"))
    assert not any(results_dir.rglob("*_report.pdf"))


def test_get_job_operational_export_builds_duplicates_csv_from_result(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "duplicates": [
                    {
                        "item": "A001",
                        "descricao": "Mesa",
                        "row_indices": [0, 2],
                        "count": 2,
                    }
                ],
                "grouped_problems": {},
            }
        ),
        encoding="utf-8",
    )

    service = JobService()
    job = service.create_job(tenant_id="default", file_name="inventario.csv")
    job.mark_running()
    job.mark_completed(result_path=str(result_path))

    csv_output, download_name = get_job_operational_export(
        job.job_id,
        service,
        export_kind=OperationalExportKind.DUPLICATES,
    )

    assert download_name == "inventario_duplicados.csv"
    assert "A001,Mesa,2,\"2, 4\"" in csv_output


def test_get_job_operational_export_builds_problem_group_csv_from_result(tmp_path):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "duplicates": [],
                "grouped_problems": {
                    "ZERO_ITEM_COMPLEMENTO_EMPTY": [
                        {
                            "row_index": 1,
                            "item": "A002",
                            "descricao": "Cadeira",
                            "severity": "warning",
                            "field": "complemento",
                            "message": "Complemento vazio",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    service = JobService()
    job = service.create_job(tenant_id="default", file_name="inventario.csv")
    job.mark_running()
    job.mark_completed(result_path=str(result_path))

    csv_output, download_name = get_job_operational_export(
        job.job_id,
        service,
        export_kind=OperationalExportKind.PROBLEM_GROUP,
        problem_code="ZERO_ITEM_COMPLEMENTO_EMPTY",
    )

    assert download_name == "inventario_zero_item_complemento_empty.csv"
    assert (
        "ZERO_ITEM_COMPLEMENTO_EMPTY,3,A002,Cadeira,warning,Complemento,"
        "Complemento vazio" in csv_output
    )


def test_get_job_csv_download_falls_back_to_legacy_upload_root(tmp_path, monkeypatch):
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(validation_service, "UPLOADS_DIR", uploads_dir)

    service = JobService()
    job = service.create_job(tenant_id="default", file_name="inventario.csv")

    legacy_path = uploads_dir / f"{job.job_id}_inventario.csv"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(CSV_CONTENT, encoding="utf-8")

    job.file_path = str(uploads_dir / "default" / f"{job.job_id}_inventario.csv")

    csv_path, download_name = get_job_csv_download(job.job_id, service)

    assert csv_path == legacy_path
    assert download_name == "inventario_corrigido.csv"


def test_get_job_result_payload_falls_back_to_legacy_results_root(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    service = JobService()
    job = service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(
        result_path=str(results_dir / "default" / f"{job.job_id}_result.json"),
        total_rows=1,
    )

    legacy_result_path = results_dir / f"{job.job_id}_result.json"
    legacy_result_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_result_path.write_text(
        json.dumps({"summary": {"total_rows": 1}}),
        encoding="utf-8",
    )

    payload = get_job_result_payload(job.job_id, service)

    assert payload["summary"]["total_rows"] == 1


def test_get_job_report_download_falls_back_to_legacy_results_root(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    service = JobService()
    job = service.create_job(tenant_id="default")
    job.mark_running()
    job.mark_completed(
        report_path=str(results_dir / "default" / f"{job.job_id}_report.pdf")
    )

    legacy_report_path = results_dir / f"{job.job_id}_report.pdf"
    legacy_report_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_report_path.write_bytes(b"%PDF-1.4 legacy report")

    report_path = get_job_report_download(job.job_id, service)

    assert report_path == legacy_report_path


def test_run_upload_preflight_accepts_valid_default_csv():
    tenant_config = load_tenant_config("default")

    result = run_upload_preflight(
        file_name="inventario.csv",
        content=CSV_CONTENT.encode("utf-8"),
        tenant_config=tenant_config,
    )

    assert result.file_name == "inventario.csv"
    assert "Item" in result.detected_columns
    assert result.missing_columns == []
    assert result.guidance == []


def test_run_upload_preflight_accepts_valid_default_xlsx():
    tenant_config = load_tenant_config("default")

    result = run_upload_preflight(
        file_name="inventario.xlsx",
        content=build_xlsx_content_from_csv(CSV_CONTENT),
        tenant_config=tenant_config,
    )

    assert result.file_name == "inventario.xlsx"
    assert "Item" in result.detected_columns
    assert result.missing_columns == []
    assert result.guidance == []


def test_run_upload_preflight_rejects_unsupported_extension():
    tenant_config = load_tenant_config("default")

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.txt",
            content=CSV_CONTENT.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert exc_info.value.detail == "Envie a planilha em CSV ou XLSX antes de iniciar o lote."
    assert exc_info.value.result.issues[0].code == "unsupported_extension"


def test_run_upload_preflight_rejects_empty_file():
    tenant_config = load_tenant_config("default")

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=b"",
            tenant_config=tenant_config,
        )

    assert exc_info.value.detail == "O arquivo enviado esta vazio."
    assert exc_info.value.result.issues[0].code == "file_empty"


def test_run_upload_preflight_rejects_file_larger_than_limit(monkeypatch):
    tenant_config = load_tenant_config("default")
    monkeypatch.setenv(validation_service.UPLOAD_MAX_BYTES_ENV, "8")

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=CSV_CONTENT.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert exc_info.value.detail == "O arquivo excede o tamanho maximo permitido para preflight."
    assert exc_info.value.result.issues[0].code == "file_too_large"


def test_run_upload_preflight_rejects_wrong_delimiter_and_reports_detected_columns():
    tenant_config = load_tenant_config("default")
    semicolon_content = CSV_CONTENT.replace(",", ";")

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=semicolon_content.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert (
        exc_info.value.detail
        == "O delimitador do CSV nao corresponde ao layout esperado para esta empresa."
    )
    assert exc_info.value.result.detected_columns[:3] == [
        "Item",
        "Placa Anterior",
        "Descrição",
    ]
    assert exc_info.value.result.issues[0].code == "delimiter_mismatch"


def test_run_upload_preflight_rejects_wrong_encoding():
    tenant_config = load_tenant_config("default")

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=CSV_CONTENT.encode("iso-8859-1"),
            tenant_config=tenant_config,
        )

    assert (
        exc_info.value.detail
        == "A codificacao do arquivo nao corresponde ao layout esperado para esta empresa."
    )
    assert exc_info.value.result.issues[0].code == "encoding_mismatch"


def test_run_upload_preflight_rejects_missing_header():
    tenant_config = load_tenant_config("default")
    missing_header_content = (
        "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    )

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=missing_header_content.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert (
        exc_info.value.detail
        == "A primeira linha nao contem um cabecalho compativel com o layout esperado."
    )
    assert exc_info.value.result.issues[0].code == "missing_header"


def test_run_upload_preflight_rejects_missing_required_columns():
    tenant_config = load_tenant_config("default")
    missing_columns_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Observação\n"
        "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Obs\n"
    )

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=missing_columns_content.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert exc_info.value.detail == "Faltam colunas obrigatorias no cabecalho do CSV."
    assert exc_info.value.result.missing_columns == ["Complemento"]
    assert exc_info.value.result.issues[0].code == "missing_columns"


def test_run_upload_preflight_rejects_header_only_csv():
    tenant_config = load_tenant_config("default")
    header_only_content = (
        "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    )

    with pytest.raises(UploadPreflightError) as exc_info:
        run_upload_preflight(
            file_name="inventario.csv",
            content=header_only_content.encode("utf-8"),
            tenant_config=tenant_config,
        )

    assert exc_info.value.detail == "O arquivo nao contem linhas de dados para validar."
    assert exc_info.value.result.issues[0].code == "missing_rows"


def test_prepare_upload_content_for_job_converts_xlsx_to_tenant_csv_equivalently(tmp_path):
    tenant_config = load_tenant_config("default")
    xlsx_content = build_xlsx_content_from_csv(CSV_CONTENT)

    stored_file_name, stored_content = validation_service.prepare_upload_content_for_job(
        file_name="inventario.xlsx",
        content=xlsx_content,
        tenant_config=tenant_config,
    )

    expected_path = tmp_path / "expected.csv"
    expected_path.write_text(CSV_CONTENT, encoding="utf-8")
    actual_path = tmp_path / stored_file_name
    actual_path.write_bytes(stored_content)

    expected_df = validation_service._read_tenant_csv(expected_path, tenant_config)
    actual_df = validation_service._read_tenant_csv(actual_path, tenant_config)

    assert stored_file_name == "inventario.csv"
    assert actual_df.columns.tolist() == expected_df.columns.tolist()
    assert actual_df.to_dict(orient="records") == expected_df.to_dict(orient="records")
