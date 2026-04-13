import json
from pathlib import Path

import pandas as pd

from app.core.canonical_fields import normalize_row
from app.core.engine import ValidationEngine
from app.core.registry import register_rule
from app.core.tenant_loader import load_tenant_config
from app.rules.category_rules import CategoryCriticalCheckRule
from app.rules.integrity import DuplicateItemRule, FlagConsistencyRule
from app.rules.llm_audit import LLMAuditRule
from app.rules.zero_item_quality import ZeroItemQualityRule
from app.services.job_service import JobService
from app.services.report_service import (
    build_full_report,
    generate_pdf_report,
)

UPLOADS_DIR = Path("uploads")
RESULTS_DIR = Path("results")


def ensure_rules_registered() -> None:
    from app.core.registry import RULE_REGISTRY

    if RULE_REGISTRY:
        return
    register_rule(DuplicateItemRule())
    register_rule(FlagConsistencyRule())
    register_rule(ZeroItemQualityRule())
    register_rule(CategoryCriticalCheckRule())
    register_rule(LLMAuditRule())


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

        validation_results = engine.validate_all(raw_rows)

        normalized_rows = [normalize_row(row) for row in raw_rows]
        report_data = build_full_report(normalized_rows, validation_results)

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        result_path = RESULTS_DIR / f"{job_id}_result.json"
        result_path.write_text(json.dumps(report_data, ensure_ascii=False, default=str))

        pdf_path = RESULTS_DIR / f"{job_id}_report.pdf"
        generate_pdf_report(normalized_rows, validation_results, pdf_path)

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
