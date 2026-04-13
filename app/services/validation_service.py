import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.core.canonical_fields import normalize_row
from app.core.engine import ValidationEngine
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


def _build_indexing_status_detail(total_rows: int) -> str:
    if total_rows == 0:
        return (
            "A indexação global foi concluída. O lote não contém linhas válidas para "
            "formar uma prévia operacional."
        )

    return (
        "A indexação global foi concluída. O lote inteiro já foi mapeado para que a "
        "prévia passe a exibir apenas dados consistentes com o conjunto completo."
    )


def _build_validation_status_detail(processed_rows: int, total_rows: int) -> str:
    return (
        "A prévia operacional está sendo atualizada em batches seguros após a "
        f"indexação global do lote. {processed_rows} de {total_rows} linhas já "
        "foram validadas com contexto completo."
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
                "O sistema está mapeando o conjunto completo do arquivo para liberar "
                "apenas prévias compatíveis com o lote inteiro."
            ),
        )
        normalized_rows = [
            normalize_row(row, tenant_config.columns) for row in raw_rows
        ]
        total_rows = len(normalized_rows)
        batch_size = _resolve_batch_size(total_rows)
        partial_duplicates = build_duplicate_section(normalized_rows, {})

        validation_results: dict[int, list] = {}
        processed_row_indices: list[int] = []
        shared_context: dict = {}

        job_service.update_partial_result(
            job_id=job_id,
            total_rows=total_rows,
            processed_rows=0,
            batch_size=batch_size,
            partial_summary={
                "total_rows": total_rows,
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
            status_detail=_build_indexing_status_detail(total_rows),
        )

        for start in range(0, total_rows, batch_size):
            stop = min(start + batch_size, total_rows)
            batch_indices = list(range(start, stop))

            for idx in batch_indices:
                validation_results[idx] = engine.validate_row(
                    row_index=idx,
                    normalized_row=normalized_rows[idx],
                    all_rows=normalized_rows,
                    shared_context=shared_context,
                )

            processed_row_indices.extend(batch_indices)
            partial_report = build_partial_report(
                normalized_rows,
                validation_results,
                processed_row_indices,
                partial_duplicates=partial_duplicates,
            )

            job_service.update_partial_result(
                job_id=job_id,
                total_rows=total_rows,
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
                ),
            )

        report_data = build_full_report(normalized_rows, validation_results)

        job_service.update_progress(
            job_id=job_id,
            current_step="building_artifacts",
            status_title="Consolidação dos artefatos",
            status_detail=(
                "O sistema está montando o resumo executivo, os dados estruturados "
                "e o relatório PDF do lote."
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
        )

        summary = report_data["summary"]
        job_service.complete_job(
            job_id=job_id,
            result_path=str(result_path),
            report_path=str(pdf_path),
            total_rows=summary["total_rows"],
            rows_with_issues=summary["rows_with_issues"],
            total_issues=summary["total_issues"],
        )

    except Exception as exc:
        job_service.fail_job(job_id, str(exc))
