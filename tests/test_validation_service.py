import copy
import json
from pathlib import Path

import app.services.validation_service as validation_service
from app.core.job import JobStatus
from app.services.job_service import JobService
from app.services.validation_service import (
    read_job_csv_row,
    run_validation_job,
    update_job_csv_row,
)

CSV_CONTENT = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,PA-100,Mesa,MarcaX,ModeloY,SN1,Sala1,CC1,Detalhe completo,Obs\n"
    "001,,Cadeira,MarcaZ,ModeloW,SN2,Sala2,CC2,,\n"
    "001,,Armario,MarcaA,ModeloB,SN3,Sala3,CC3,,\n"
)

REDESIM_DUPLICATE_CONTENT_WITH_HEADER_VARIATION = (
    "Item,Placa Anterior,Descrição,Marca,Modelo,NS,Local,CC,Complemento,Observação\n"
    "001,,MONITOR,Dell,P2419H,SN1,Sala1,CC1,LED 19 POL,\n"
    "001,,MESA,,,SN2,Sala2,CC2,,\n"
)

REDESIM_V2_DUPLICATE_CONTENT = (
    "especie_id;base_id;;item_anterior;item;descricao;marca;modelo;ns;complemento;observacao;cc;cc_descricao;local;latitude;longitude;gps;usuario;foto_complementar_memento;\n"
    "1;144;uuid-1;;001;MONITOR;Dell;P2419H;SN1;;AÇÃO;8327;A27;MATRIZ;;;;Letícia;;\n"
    "1;144;uuid-2;;001;MESA;;;;;;8327;A27;MATRIZ;;;;Letícia;;\n"
)


class RecordingJobService(JobService):
    def __init__(self) -> None:
        super().__init__()
        self.partial_snapshots: list[dict] = []

    def update_partial_result(self, job_id: str, **kwargs):
        self.partial_snapshots.append(copy.deepcopy(kwargs))
        return super().update_partial_result(job_id, **kwargs)


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
    assert last_snapshot["row_results_preview"][-1]["row_index"] == 2

    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["summary"]["total_rows"] == 2
    assert payload["summary"]["source_total_rows"] == 3
    assert payload["summary"]["rows_with_issues"] == 2
    assert payload["duplicates"][0]["item"] == "001"


def test_run_validation_job_keeps_redesim_descricao_in_preview_and_final_duplicates(
    tmp_path,
    monkeypatch,
):
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)

    csv_path = tmp_path / "redesim.csv"
    csv_path.write_text(REDESIM_DUPLICATE_CONTENT_WITH_HEADER_VARIATION, encoding="utf-8")

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
    assert last_snapshot["row_results_preview"][0]["descricao"] == "MONITOR"
    assert last_snapshot["row_results_preview"][1]["descricao"] == "MESA"

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["row_results"][0]["descricao"] == "MONITOR"
    assert payload["row_results"][1]["descricao"] == "MESA"
    assert payload["duplicates"][0]["descricao"] == "MONITOR / MESA"
    duplicate_group = payload["grouped_problems"]["DUPLICATE_ITEM"]
    assert duplicate_group[0]["descricao"] == "MONITOR"
    assert duplicate_group[1]["descricao"] == "MESA"


def test_run_validation_job_supports_redesim_v2_semicolon_csv(
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

    run_validation_job(job.job_id, service)

    updated_job = service.get_job(job.job_id)
    assert updated_job is not None
    assert updated_job.status == JobStatus.COMPLETED

    assert len(service.partial_snapshots) >= 2
    last_snapshot = service.partial_snapshots[-1]
    assert last_snapshot["partial_duplicates"][0]["descricao"] == "MONITOR / MESA"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][0]["descricao"] == "MONITOR"
    assert last_snapshot["partial_grouped_problems"]["DUPLICATE_ITEM"][1]["descricao"] == "MESA"
    assert last_snapshot["row_results_preview"][0]["descricao"] == "MONITOR"
    assert last_snapshot["row_results_preview"][1]["descricao"] == "MESA"

    assert updated_job.result_path is not None
    payload = json.loads(Path(updated_job.result_path).read_text(encoding="utf-8"))
    assert payload["row_results"][0]["descricao"] == "MONITOR"
    assert payload["row_results"][1]["descricao"] == "MESA"
    assert payload["duplicates"][0]["descricao"] == "MONITOR / MESA"


def test_job_csv_read_and_update_preserve_redesim_v2_csv_format(tmp_path):
    csv_path = tmp_path / "redesim.csv"
    csv_path.write_text(REDESIM_V2_DUPLICATE_CONTENT, encoding="iso-8859-1")

    service = JobService()
    job = service.create_job(
        tenant_id="redesim_v2",
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
