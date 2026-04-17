import copy
import json
from pathlib import Path

import app.services.validation_service as validation_service
from app.core.job import JobStatus
from app.services.job_service import JobService
from app.services.validation_service import (
    OperationalExportKind,
    delete_job_csv_rows,
    delete_job_csv_rows_and_refresh,
    get_job_operational_export,
    read_job_csv_row,
    resolve_duplicate_csv_rows_and_refresh,
    run_validation_job,
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


class CancelAfterProgressJobService(RecordingJobService):
    def update_partial_result(self, job_id: str, **kwargs):
        updated = super().update_partial_result(job_id, **kwargs)
        if kwargs.get("processed_rows", 0) > 0 and not updated.cancel_requested:
            self.request_job_cancellation(job_id)
        return updated


def setup_function():
    validation_service._JOB_CSV_CONTEXT_CACHE.clear()


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
    assert last_snapshot["row_results_preview"] == []

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
    assert last_snapshot["row_results_preview"] == []

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
