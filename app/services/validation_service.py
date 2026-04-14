import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.core.canonical_fields import (
    DEFAULT_TENANT_COLUMNS,
    resolve_source_column_name,
)
from app.core.engine import ValidationEngine
from app.core.job import JobRecord
from app.core.registry import register_rule
from app.core.tenant_loader import load_tenant_config
from app.rules.category_rules import CategoryCriticalCheckRule, CategoryRequiredFieldsRule
from app.rules.integrity import DuplicateItemRule, FlagConsistencyRule
from app.rules.llm_audit import LLMAuditRule
from app.rules.zero_item_quality import ZeroItemQualityRule
from app.services.job_service import JobService
from app.services.report_service import (
    build_duplicate_section,
    build_full_report,
    build_partial_report,
    generate_pdf_report,
)

UPLOADS_DIR = Path("uploads")
RESULTS_DIR = Path("results")
DEFAULT_BATCH_SIZE = 200
TARGET_PREVIEW_BATCHES = 10


def _get_job_csv_context(
    job_id: str,
    job_service: JobService,
) -> tuple[JobRecord, Path, pd.DataFrame]:
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")

    if not job.file_path:
        raise FileNotFoundError("Job does not contain a CSV file path")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise FileNotFoundError("CSV file not found for this job")

    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    return job, file_path, df


def _resolve_source_column(
    field_name: str,
    tenant_columns: dict[str, str],
    available_columns: list[str],
) -> str:
    candidate_columns = [
        tenant_columns.get(field_name),
        DEFAULT_TENANT_COLUMNS.get(field_name),
        field_name,
    ]

    for candidate in candidate_columns:
        if not candidate:
            continue
        resolved = resolve_source_column_name(candidate, available_columns)
        if resolved is not None:
            return resolved

    raise ValueError(f"Column not found for field: {field_name}")


def update_job_csv_row(
    job_id: str,
    job_service: JobService,
    *,
    row_index: int,
    updates: dict[str, str],
) -> dict[str, str]:
    if row_index < 0:
        raise ValueError(f"Invalid row index: {row_index}")

    job, file_path, df = _get_job_csv_context(job_id, job_service)
    tenant_config = load_tenant_config(job.tenant_id)
    if row_index >= len(df):
        raise ValueError(f"Row index out of range: {row_index}")

    for field_name, new_value in updates.items():
        column_name = _resolve_source_column(
            field_name, tenant_config.columns, df.columns.tolist()
        )
        df.at[row_index, column_name] = new_value

    df.to_csv(file_path, index=False)
    return df.iloc[row_index].to_dict()  # type: ignore[return-value]


def read_job_csv_row(
    job_id: str,
    job_service: JobService,
    *,
    row_index: int,
) -> tuple[dict[str, str], dict[str, str]]:
    if row_index < 0:
        raise ValueError(f"Invalid row index: {row_index}")

    job, _, df = _get_job_csv_context(job_id, job_service)
    tenant_config = load_tenant_config(job.tenant_id)
    if row_index >= len(df):
        raise ValueError(f"Row index out of range: {row_index}")

    row = {
        str(column): "" if value is None else str(value)
        for column, value in df.iloc[row_index].to_dict().items()
    }
    resolved_columns = {
        field_name: tenant_config.columns.get(field_name, field_name)
        for field_name in tenant_config.columns
    }
    return row, resolved_columns


def create_reprocess_job(
    job_id: str,
    job_service: JobService,
) -> JobRecord:
    source_job, source_file_path, _ = _get_job_csv_context(job_id, job_service)
    source_file_name = source_job.file_name or source_file_path.name

    new_job = job_service.create_job(
        tenant_id=source_job.tenant_id,
        file_name=source_file_name,
        params=source_job.params,
    )
    destination_path = UPLOADS_DIR / f"{new_job.job_id}_{source_file_name}"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_file_path, destination_path)

    new_job.file_path = str(destination_path)
    new_job.file_name = source_file_name
    return new_job


def ensure_rules_registered() -> None:
    from app.core.registry import RULE_REGISTRY

    if RULE_REGISTRY:
        return
    register_rule(DuplicateItemRule())
    register_rule(FlagConsistencyRule())
    register_rule(ZeroItemQualityRule())
    register_rule(CategoryRequiredFieldsRule())
    register_rule(CategoryCriticalCheckRule())
    register_rule(LLMAuditRule())


def _resolve_batch_size(total_rows: int) -> int:
    if total_rows <= 0:
        return 1

    target_size = math.ceil(total_rows / TARGET_PREVIEW_BATCHES)
    return max(1, min(DEFAULT_BATCH_SIZE, target_size))


def _build_indexing_status_detail(
    validated_rows: int,
    source_total_rows: int,
) -> str:
    if validated_rows == 0:
        return (
            "A indexação global foi concluída. O arquivo foi lido, mas nenhuma linha "
            "entrou no escopo operacional porque não há itens cadastrados do zero."
        )

    return (
        "A indexação global foi concluída. O arquivo tem "
        f"{source_total_rows} linhas e {validated_rows} itens cadastrados do zero "
        "entrarão na validação operacional e na prévia."
    )


def _build_validation_status_detail(
    processed_rows: int,
    validated_rows: int,
    source_total_rows: int,
) -> str:
    return (
        "A prévia operacional está sendo atualizada em batches seguros após a "
        "indexação global do lote. "
        f"{processed_rows} de {validated_rows} itens em escopo já foram validados "
        f"com contexto completo. O CSV original tem {source_total_rows} linhas."
    )


def run_validation_job(job_id: str, job_service: JobService) -> None:
    job = job_service.get_job(job_id)
    if job is None:
        return

    try:
        job_service.start_job(job_id)

        ensure_rules_registered()

        tenant_config = load_tenant_config(job.tenant_id)
        engine = ValidationEngine(tenant=tenant_config)

        file_path = Path(job.file_path)  # type: ignore[arg-type]
        df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        raw_rows: list[dict[str, object]] = df.to_dict(orient="records")

        job_service.update_progress(
            job_id=job_id,
            current_step="indexing_global",
            status_title="Indexação global do lote",
            status_detail=(
                "O sistema está mapeando o conjunto completo do arquivo para "
                "identificar quais itens cadastrados do zero entram no resultado "
                "operacional e liberar apenas prévias compatíveis com esse escopo."
            ),
        )
        normalized_rows = engine.normalize_rows(raw_rows)
        source_total_rows = len(normalized_rows)
        scoped_row_indices = engine.get_scoped_row_indices(normalized_rows)
        scoped_rows = [normalized_rows[idx] for idx in scoped_row_indices]
        total_rows = len(scoped_row_indices)
        batch_size = _resolve_batch_size(total_rows)
        partial_duplicates = build_duplicate_section(
            normalized_rows,
            {},
            row_indices=scoped_row_indices,
        )

        validation_results: dict[int, list] = {}
        processed_row_indices: list[int] = []
        shared_context: dict = {}

        job_service.update_partial_result(
            job_id=job_id,
            total_rows=total_rows,
            source_total_rows=source_total_rows,
            processed_rows=0,
            batch_size=batch_size,
            partial_summary={
                "total_rows": total_rows,
                "validated_rows": total_rows,
                "source_total_rows": source_total_rows,
                "processed_rows": 0,
                "rows_with_issues": 0,
                "total_issues": 0,
                "error_count": 0,
                "warning_count": 0,
            },
            partial_grouped_problems={},
            partial_duplicates=partial_duplicates,
            row_results_preview=[],
            is_partial_result_available=bool(partial_duplicates),
            current_step="validating_batches",
            status_title="Validação em batches iniciada",
            status_detail=_build_indexing_status_detail(total_rows, source_total_rows),
        )

        for start in range(0, total_rows, batch_size):
            stop = min(start + batch_size, total_rows)
            batch_indices = scoped_row_indices[start:stop]

            for idx in batch_indices:
                validation_results[idx] = engine.validate_row(
                    row_index=idx,
                    normalized_row=normalized_rows[idx],
                    all_rows=scoped_rows,
                    shared_context=shared_context,
                )

            processed_row_indices.extend(batch_indices)
            partial_report = build_partial_report(
                normalized_rows,
                validation_results,
                processed_row_indices,
                partial_duplicates=partial_duplicates,
                validated_row_indices=scoped_row_indices,
                source_total_rows=source_total_rows,
            )

            job_service.update_partial_result(
                job_id=job_id,
                total_rows=total_rows,
                source_total_rows=source_total_rows,
                processed_rows=len(processed_row_indices),
                batch_size=batch_size,
                partial_summary=partial_report["partial_summary"],
                partial_grouped_problems=partial_report["partial_grouped_problems"],
                partial_duplicates=partial_report["partial_duplicates"],
                row_results_preview=partial_report["row_results_preview"],
                is_partial_result_available=bool(
                    partial_report["row_results_preview"]
                    or partial_report["partial_grouped_problems"]
                    or partial_report["partial_duplicates"]
                ),
                current_step="validating_batches",
                status_title="Prévia operacional em atualização",
                status_detail=_build_validation_status_detail(
                    len(processed_row_indices),
                    total_rows,
                    source_total_rows,
                ),
            )

        report_data = build_full_report(
            normalized_rows,
            validation_results,
            validated_row_indices=scoped_row_indices,
            source_total_rows=source_total_rows,
        )

        job_service.update_progress(
            job_id=job_id,
            current_step="building_artifacts",
            status_title="Consolidação dos artefatos",
            status_detail=(
                "O sistema está montando o resumo executivo, os dados estruturados "
                "e o relatório PDF apenas com os itens cadastrados do zero que "
                "entraram no escopo validado."
            ),
        )

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        result_path = RESULTS_DIR / f"{job_id}_result.json"
        result_path.write_text(json.dumps(report_data, ensure_ascii=False, default=str))

        pdf_path = RESULTS_DIR / f"{job_id}_report.pdf"
        generate_pdf_report(
            normalized_rows,
            validation_results,
            pdf_path,
            metadata={
                "organization_name": tenant_config.display_name,
                "file_name": job.file_name,
                "job_id": job_id,
                "generated_at": datetime.now(UTC),
            },
            validated_row_indices=scoped_row_indices,
            source_total_rows=source_total_rows,
        )

        summary = report_data["summary"]
        job_service.complete_job(
            job_id=job_id,
            result_path=str(result_path),
            report_path=str(pdf_path),
            total_rows=summary["total_rows"],
            source_total_rows=summary["source_total_rows"],
            rows_with_issues=summary["rows_with_issues"],
            total_issues=summary["total_issues"],
        )

    except Exception as exc:
        job_service.fail_job(job_id, str(exc))
