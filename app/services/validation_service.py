import csv
import json
import math
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pandas as pd

from app.core.canonical_fields import (
    DEFAULT_TENANT_COLUMNS,
    resolve_source_column_name,
)
from app.core.engine import ValidationEngine
from app.core.job import JobRecord, JobStatus
from app.core.logging import get_logger, log_event
from app.core.registry import register_rule
from app.core.tenant_config import TenantConfig
from app.core.tenant_loader import load_tenant_config
from app.core.validation_scope import (
    VALIDATION_SCOPE_PARAM,
    ValidationScope,
    parse_validation_scope,
)
from app.rules.category_rules import CategoryCriticalCheckRule, CategoryRequiredFieldsRule
from app.rules.integrity import DuplicateItemRule, FlagConsistencyRule
from app.rules.llm_audit import LLMAuditRule
from app.rules.zero_item_quality import ZeroItemQualityRule
from app.services.job_service import JobService
from app.services.report_service import (
    build_duplicate_section,
    build_duplicates_export_csv,
    build_full_report,
    build_partial_report,
    build_problem_group_export_csv,
    generate_pdf_report,
)

UPLOADS_DIR = Path("uploads")
RESULTS_DIR = Path("results")
DEFAULT_BATCH_SIZE = 200
TARGET_PREVIEW_BATCHES = 10

_logger = get_logger("validation_service")


@dataclass
class _CachedJobCsvContext:
    tenant_id: str
    file_path: Path
    signature: tuple[int, int]
    tenant_config: TenantConfig
    df: pd.DataFrame


_JOB_CSV_CONTEXT_CACHE: dict[str, _CachedJobCsvContext] = {}

MEDIA_COLUMN_NAMES = {
    "foto",
    "foto_complementar",
    "foto_complementar_memento",
    "imagem",
    "image",
    "photo",
    "media",
    "midia",
}
MEDIA_COLUMN_TOKENS = {
    "foto",
    "imagem",
    "image",
    "photo",
    "media",
    "midia",
    "memento",
}
DATE_TIME_COLUMN_TOKENS = {
    "data",
    "date",
    "hora",
    "hour",
    "time",
    "timestamp",
    "datetime",
    "dt",
    "dh",
}
DATE_TIME_VALUE_PATTERNS = (
    re.compile(
        r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)?"
        r"(?:Z|[+-]\d{2}:\d{2})?$"
    ),
    re.compile(r"^\d{2}/\d{2}/\d{4}(?: \d{2}:\d{2}(?::\d{2})?)?$"),
    re.compile(r"^\d{2}-\d{2}-\d{4}(?: \d{2}:\d{2}(?::\d{2})?)?$"),
    re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$"),
)


def _build_csv_read_kwargs(tenant_config: TenantConfig) -> dict[str, str | bool]:
    return {
        "sep": tenant_config.csv.delimiter,
        "encoding": tenant_config.csv.encoding,
        "keep_default_na": False,
    }


def _read_raw_csv_headers(file_path: Path, tenant_config: TenantConfig) -> list[str]:
    with file_path.open("r", encoding=tenant_config.csv.encoding, newline="") as file:
        reader = csv.reader(file, delimiter=tenant_config.csv.delimiter)
        try:
            return next(reader)
        except StopIteration:
            return []


def _read_tenant_csv(file_path: Path, tenant_config: TenantConfig) -> pd.DataFrame:
    df = pd.read_csv(
        file_path,
        dtype=str,
        **_build_csv_read_kwargs(tenant_config),
    )
    raw_headers = _read_raw_csv_headers(file_path, tenant_config)
    if raw_headers and len(raw_headers) == len(df.columns):
        df.columns = raw_headers
    return df


def _write_tenant_csv(
    df: pd.DataFrame,
    file_path: Path,
    tenant_config: TenantConfig,
) -> None:
    df.to_csv(
        file_path,
        index=False,
        sep=tenant_config.csv.delimiter,
        encoding=tenant_config.csv.encoding,
    )


def _dataframe_to_raw_rows(df: pd.DataFrame) -> list[dict[str, object]]:
    return [
        dict(zip(df.columns, row, strict=False))
        for row in df.itertuples(index=False, name=None)
    ]


class JobCancellationRequestedError(Exception):
    pass


class OperationalExportKind(StrEnum):
    DUPLICATES = "duplicates"
    PROBLEM_GROUP = "problem_group"


@dataclass(frozen=True)
class DuplicateCsvResolution:
    kept_row_index: int
    deleted_row_indices: list[int]
    remaining_rows: int
    merged_columns: list[str]


def _get_job_csv_file(
    job_id: str,
    job_service: JobService,
) -> tuple[JobRecord, Path]:
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")

    if not job.file_path:
        raise FileNotFoundError("Job does not contain a CSV file path")

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise FileNotFoundError("CSV file not found for this job")

    return job, file_path


def _get_job_csv_context(
    job_id: str,
    job_service: JobService,
) -> tuple[JobRecord, Path, TenantConfig, pd.DataFrame]:
    job, file_path = _get_job_csv_file(job_id, job_service)
    signature = _get_job_csv_signature(file_path)
    cached_context = _JOB_CSV_CONTEXT_CACHE.get(job_id)
    if (
        cached_context
        and cached_context.tenant_id == job.tenant_id
        and cached_context.file_path == file_path
        and cached_context.signature == signature
    ):
        return job, file_path, cached_context.tenant_config, cached_context.df

    tenant_config = load_tenant_config(job.tenant_id)
    df = _read_tenant_csv(file_path, tenant_config)
    _store_job_csv_context(job_id, job, file_path, tenant_config, df)
    return job, file_path, tenant_config, df


def _get_job_csv_signature(file_path: Path) -> tuple[int, int]:
    file_stat = file_path.stat()
    return file_stat.st_mtime_ns, file_stat.st_size


def _store_job_csv_context(
    job_id: str,
    job: JobRecord,
    file_path: Path,
    tenant_config: TenantConfig,
    df: pd.DataFrame,
) -> None:
    _JOB_CSV_CONTEXT_CACHE[job_id] = _CachedJobCsvContext(
        tenant_id=job.tenant_id,
        file_path=file_path,
        signature=_get_job_csv_signature(file_path),
        tenant_config=tenant_config,
        df=df,
    )


def _build_corrected_csv_name(job: JobRecord, file_path: Path) -> str:
    original_name = job.file_name or file_path.name
    original_path = Path(original_name)
    suffix = original_path.suffix or ".csv"
    stem = original_path.stem or "lote"

    if stem.endswith("_corrigido"):
        return f"{stem}{suffix}"

    return f"{stem}_corrigido{suffix}"


def get_job_csv_download(
    job_id: str,
    job_service: JobService,
) -> tuple[Path, str]:
    job, file_path = _get_job_csv_file(job_id, job_service)
    return file_path, _build_corrected_csv_name(job, file_path)


def _get_job_result_data(
    job_id: str,
    job_service: JobService,
) -> tuple[JobRecord, dict]:
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")

    if job.status != JobStatus.COMPLETED:
        raise ValueError(f"Job not completed: {job.status.value}")

    if not job.result_path or not Path(job.result_path).exists():
        raise FileNotFoundError("Result file not found")

    return job, json.loads(Path(job.result_path).read_text(encoding="utf-8"))


def _sanitize_export_token(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return sanitized or "grupo"


def _build_operational_export_name(
    job: JobRecord,
    export_kind: OperationalExportKind,
    problem_code: str | None = None,
) -> str:
    original_name = job.file_name or "lote.csv"
    original_path = Path(original_name)
    stem = original_path.stem or "lote"
    suffix = original_path.suffix or ".csv"

    if export_kind == OperationalExportKind.DUPLICATES:
        return f"{stem}_duplicados{suffix}"

    if problem_code is None:
        raise ValueError("problem_code is required for problem_group exports")

    return f"{stem}_{_sanitize_export_token(problem_code)}{suffix}"


def get_job_operational_export(
    job_id: str,
    job_service: JobService,
    *,
    export_kind: OperationalExportKind,
    problem_code: str | None = None,
) -> tuple[str, str]:
    job, report_data = _get_job_result_data(job_id, job_service)

    if export_kind == OperationalExportKind.DUPLICATES:
        duplicates = report_data.get("duplicates") or []
        if not duplicates:
            raise KeyError("No duplicate rows available for export")
        return (
            build_duplicates_export_csv(duplicates),
            _build_operational_export_name(job, export_kind),
        )

    if problem_code is None:
        raise ValueError("problem_code is required for problem_group exports")

    grouped_problems = report_data.get("grouped_problems") or {}
    occurrences = grouped_problems.get(problem_code)
    if not occurrences:
        raise KeyError(f"Problem group not found: {problem_code}")

    return (
        build_problem_group_export_csv(problem_code, occurrences),
        _build_operational_export_name(job, export_kind, problem_code),
    )


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

    job, file_path, tenant_config, df = _get_job_csv_context(job_id, job_service)
    if row_index >= len(df):
        raise ValueError(f"Row index out of range: {row_index}")

    for field_name, new_value in updates.items():
        column_name = _resolve_source_column(
            field_name, tenant_config.columns, df.columns.tolist()
        )
        df.at[row_index, column_name] = new_value

    _write_tenant_csv(df, file_path, tenant_config)
    _store_job_csv_context(job_id, job, file_path, tenant_config, df)
    return df.iloc[row_index].to_dict()  # type: ignore[return-value]


def delete_job_csv_rows(
    job_id: str,
    job_service: JobService,
    *,
    row_indices: list[int],
) -> int:
    normalized_indices = sorted(set(row_indices))
    if not normalized_indices:
        raise ValueError("At least one row index must be provided")
    if normalized_indices[0] < 0:
        raise ValueError(f"Invalid row index: {normalized_indices[0]}")

    job, file_path, tenant_config, df = _get_job_csv_context(job_id, job_service)
    if normalized_indices[-1] >= len(df):
        raise ValueError(f"Row index out of range: {normalized_indices[-1]}")

    df = df.drop(index=normalized_indices).reset_index(drop=True)
    _write_tenant_csv(df, file_path, tenant_config)
    _store_job_csv_context(job_id, job, file_path, tenant_config, df)
    return len(df)


def _is_missing_csv_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()

    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _normalize_csv_column_name(column_name: object) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(column_name or ""))
    normalized = unicodedata.normalize("NFD", text.strip().lower())
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _get_normalized_csv_column_tokens(column_name: object) -> set[str]:
    normalized_name = _normalize_csv_column_name(column_name)
    if not normalized_name:
        return set()
    return {token for token in normalized_name.split("_") if token}


def _is_media_like_column(column_name: object) -> bool:
    normalized_name = _normalize_csv_column_name(column_name)
    if not normalized_name:
        return False
    if normalized_name in MEDIA_COLUMN_NAMES:
        return True

    tokens = _get_normalized_csv_column_tokens(column_name)
    return any(token in MEDIA_COLUMN_TOKENS for token in tokens)


def _looks_like_date_or_time_value(value: object) -> bool:
    if _is_missing_csv_value(value):
        return False

    text = str(value).strip()
    if not text:
        return False

    return any(pattern.fullmatch(text) for pattern in DATE_TIME_VALUE_PATTERNS)


def _is_date_or_time_like_column(
    column_name: object,
    sample_values: list[object],
) -> bool:
    normalized_name = _normalize_csv_column_name(column_name)
    if not normalized_name:
        return False

    if normalized_name.endswith("_at"):
        return True

    tokens = _get_normalized_csv_column_tokens(column_name)
    if any(token in DATE_TIME_COLUMN_TOKENS for token in tokens):
        return True

    non_empty_values = [value for value in sample_values if not _is_missing_csv_value(value)]
    if not non_empty_values:
        return False

    inspected_values = non_empty_values[:5]
    return len(inspected_values) >= 2 and all(
        _looks_like_date_or_time_value(value) for value in inspected_values
    )


def _get_same_name_merge_skipped_columns(
    df: pd.DataFrame,
    row_indices: list[int],
) -> set[str]:
    skipped_columns: set[str] = set()

    for column_name in df.columns:
        sample_values = [df.at[row_index, column_name] for row_index in row_indices]
        if _is_media_like_column(column_name) or _is_date_or_time_like_column(
            column_name,
            sample_values,
        ):
            skipped_columns.add(str(column_name))

    return skipped_columns


def _has_duplicate_description_conflict(
    df: pd.DataFrame,
    tenant_config: TenantConfig,
    row_indices: list[int],
) -> bool:
    try:
        description_column = _resolve_source_column(
            "descricao",
            tenant_config.columns,
            df.columns.tolist(),
        )
    except ValueError:
        return True

    description_values: list[str] = []
    seen_values: set[str] = set()
    for row_index in row_indices:
        description_value = df.at[row_index, description_column]
        if _is_missing_csv_value(description_value):
            continue

        description_text = str(description_value).strip()
        if not description_text or description_text in seen_values:
            continue

        seen_values.add(description_text)
        description_values.append(description_text)
        if len(description_values) > 1:
            return True

    return False


def _merge_missing_duplicate_values(
    df: pd.DataFrame,
    *,
    keep_row_index: int,
    source_row_indices: list[int],
    skipped_columns: set[str] | None = None,
) -> list[str]:
    merged_columns: list[str] = []
    source_indices = sorted(set(source_row_indices), reverse=True)
    skipped = skipped_columns or set()

    for column_name in df.columns:
        if str(column_name) in skipped:
            continue

        current_value = df.at[keep_row_index, column_name]
        if not _is_missing_csv_value(current_value):
            continue

        for source_index in source_indices:
            source_value = df.at[source_index, column_name]
            if _is_missing_csv_value(source_value):
                continue

            df.at[keep_row_index, column_name] = source_value
            merged_columns.append(str(column_name))
            break

    return merged_columns


def rerun_job_validation(
    job_id: str,
    job_service: JobService,
) -> JobRecord:
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")
    if job.status != JobStatus.COMPLETED:
        raise ValueError("Only completed jobs can be revalidated in place")

    run_validation_job(job_id, job_service)

    refreshed_job = job_service.get_job(job_id)
    if refreshed_job is None:
        raise KeyError(f"Job not found: {job_id}")
    if refreshed_job.status != JobStatus.COMPLETED:
        raise RuntimeError(
            refreshed_job.error_message
            or "Failed to rebuild the current job artifacts"
        )
    return refreshed_job


def delete_job_csv_rows_and_refresh(
    job_id: str,
    job_service: JobService,
    *,
    row_indices: list[int],
) -> int:
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")
    if job.status != JobStatus.COMPLETED:
        raise ValueError("Only completed jobs can delete rows and refresh the job")

    remaining_rows = delete_job_csv_rows(
        job_id,
        job_service,
        row_indices=row_indices,
    )
    rerun_job_validation(job_id, job_service)
    return remaining_rows


def resolve_duplicate_csv_rows_and_refresh(
    job_id: str,
    job_service: JobService,
    *,
    row_indices: list[int],
) -> DuplicateCsvResolution:
    normalized_indices = sorted(set(row_indices))
    if not normalized_indices:
        raise ValueError("At least one row index must be provided")
    if normalized_indices[0] < 0:
        raise ValueError(f"Invalid row index: {normalized_indices[0]}")

    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")
    if job.status != JobStatus.COMPLETED:
        raise ValueError("Only completed jobs can resolve duplicates and refresh the job")

    keep_row_index = normalized_indices[-1]
    deleted_row_indices = [
        row_index for row_index in normalized_indices if row_index != keep_row_index
    ]
    if not deleted_row_indices:
        raise ValueError("At least one duplicate row must be removed")

    job, file_path, tenant_config, df = _get_job_csv_context(job_id, job_service)
    if normalized_indices[-1] >= len(df):
        raise ValueError(f"Row index out of range: {normalized_indices[-1]}")

    has_description_conflict = _has_duplicate_description_conflict(
        df,
        tenant_config,
        normalized_indices,
    )
    skipped_columns: set[str] | None = None
    if not has_description_conflict:
        skipped_columns = _get_same_name_merge_skipped_columns(df, normalized_indices)

    merged_columns = _merge_missing_duplicate_values(
        df,
        keep_row_index=keep_row_index,
        source_row_indices=deleted_row_indices,
        skipped_columns=skipped_columns,
    )

    df = df.drop(index=deleted_row_indices).reset_index(drop=True)
    _write_tenant_csv(df, file_path, tenant_config)
    _store_job_csv_context(job_id, job, file_path, tenant_config, df)

    rerun_job_validation(job_id, job_service)
    return DuplicateCsvResolution(
        kept_row_index=keep_row_index,
        deleted_row_indices=deleted_row_indices,
        remaining_rows=len(df),
        merged_columns=merged_columns,
    )


def read_job_csv_row(
    job_id: str,
    job_service: JobService,
    *,
    row_index: int,
) -> tuple[dict[str, str], dict[str, str]]:
    if row_index < 0:
        raise ValueError(f"Invalid row index: {row_index}")

    _, _, tenant_config, df = _get_job_csv_context(job_id, job_service)
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
    source_job, source_file_path, _, _ = _get_job_csv_context(job_id, job_service)
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
    job_service.save_job(new_job.job_id)
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
    validation_scope: ValidationScope,
) -> str:
    if validated_rows == 0:
        if validation_scope == ValidationScope.ALL_ITEMS:
            return (
                "A indexação global foi concluída. O arquivo foi lido, mas não "
                "há linhas de dados para validar neste lote."
            )
        if validation_scope == ValidationScope.DUPLICATE_ITEMS:
            return (
                "A indexação global foi concluída. O arquivo foi lido, mas nenhuma "
                "linha entrou no escopo operacional porque não há grupos de "
                "duplicidade no lote."
            )
        return (
            "A indexação global foi concluída. O arquivo foi lido, mas nenhuma linha "
            "entrou no escopo operacional porque não há itens cadastrados do zero."
        )

    if validation_scope == ValidationScope.ALL_ITEMS:
        return (
            "A indexação global foi concluída. O arquivo tem "
            f"{source_total_rows} linhas e todas entrarão na validação operacional "
            "e na prévia."
        )

    if validation_scope == ValidationScope.DUPLICATE_ITEMS:
        return (
            "A indexação global foi concluída. O arquivo tem "
            f"{source_total_rows} linhas e {validated_rows} linhas pertencentes a "
            "grupos com Item duplicado entrarão na validação operacional e na prévia."
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


def _get_job_validation_scope(job: JobRecord) -> ValidationScope:
    return parse_validation_scope(job.params.get(VALIDATION_SCOPE_PARAM))


def _build_scope_indexing_detail(validation_scope: ValidationScope) -> str:
    if validation_scope == ValidationScope.ALL_ITEMS:
        return (
            "O sistema está mapeando o conjunto completo do arquivo para "
            "confirmar que todas as linhas do lote entram no resultado "
            "operacional e liberar apenas prévias compatíveis com esse escopo."
        )

    if validation_scope == ValidationScope.DUPLICATE_ITEMS:
        return (
            "O sistema está mapeando o conjunto completo do arquivo para "
            "identificar quais linhas pertencem a grupos com Item duplicado e "
            "liberar apenas prévias compatíveis com esse escopo."
        )

    return (
        "O sistema está mapeando o conjunto completo do arquivo para "
        "identificar quais itens cadastrados do zero entram no resultado "
        "operacional e liberar apenas prévias compatíveis com esse escopo."
    )


def _build_scope_artifact_detail(validation_scope: ValidationScope) -> str:
    if validation_scope == ValidationScope.ALL_ITEMS:
        return (
            "O sistema está montando o resumo executivo, os dados estruturados "
            "e o relatório PDF com todas as linhas que entraram no escopo "
            "validado deste lote."
        )

    if validation_scope == ValidationScope.DUPLICATE_ITEMS:
        return (
            "O sistema está montando o resumo executivo, os dados estruturados "
            "e o relatório PDF apenas com as linhas que pertencem a grupos com "
            "Item duplicado e entraram no escopo validado."
        )

    return (
        "O sistema está montando o resumo executivo, os dados estruturados "
        "e o relatório PDF apenas com os itens cadastrados do zero que "
        "entraram no escopo validado."
    )


def _raise_if_cancellation_requested(
    job_id: str,
    job_service: JobService,
) -> None:
    job = job_service.get_job(job_id)
    if job is None:
        raise JobCancellationRequestedError(
            "O lote foi interrompido porque o job deixou de existir."
        )
    if job.status == JobStatus.CANCELED or job.cancel_requested:
        raise JobCancellationRequestedError(
            "O processamento foi cancelado por solicitação do usuário."
        )


def run_validation_job(job_id: str, job_service: JobService) -> None:
    job = job_service.get_job(job_id)
    if job is None or job.status == JobStatus.CANCELED:
        return

    started_at = datetime.now(UTC)
    log_event(
        _logger,
        "validation.started",
        tenant_id=job.tenant_id,
        job_id=job_id,
    )

    try:
        _raise_if_cancellation_requested(job_id, job_service)
        job_service.start_job(job_id)
        _raise_if_cancellation_requested(job_id, job_service)

        ensure_rules_registered()

        tenant_config = load_tenant_config(job.tenant_id)
        engine = ValidationEngine(tenant=tenant_config)
        validation_scope = _get_job_validation_scope(job)

        file_path = Path(job.file_path)  # type: ignore[arg-type]
        df = _read_tenant_csv(file_path, tenant_config)
        raw_rows = _dataframe_to_raw_rows(df)

        job_service.update_progress(
            job_id=job_id,
            current_step="indexing_global",
            status_title="Indexação global do lote",
            status_detail=_build_scope_indexing_detail(validation_scope),
        )
        _raise_if_cancellation_requested(job_id, job_service)
        normalized_rows = engine.normalize_rows(raw_rows)
        source_total_rows = len(normalized_rows)
        scoped_row_indices = engine.get_scoped_row_indices(
            normalized_rows,
            validation_scope=validation_scope,
        )
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
            status_detail=_build_indexing_status_detail(
                total_rows,
                source_total_rows,
                validation_scope,
            ),
        )
        _raise_if_cancellation_requested(job_id, job_service)

        for start in range(0, total_rows, batch_size):
            _raise_if_cancellation_requested(job_id, job_service)
            stop = min(start + batch_size, total_rows)
            batch_indices = scoped_row_indices[start:stop]

            for idx in batch_indices:
                _raise_if_cancellation_requested(job_id, job_service)
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
                include_row_results_preview=False,
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
                    len(processed_row_indices) > 0
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
            _raise_if_cancellation_requested(job_id, job_service)

        report_data = build_full_report(
            normalized_rows,
            validation_results,
            validated_row_indices=scoped_row_indices,
            source_total_rows=source_total_rows,
        )
        _raise_if_cancellation_requested(job_id, job_service)

        job_service.update_progress(
            job_id=job_id,
            current_step="building_artifacts",
            status_title="Consolidação dos artefatos",
            status_detail=_build_scope_artifact_detail(validation_scope),
        )
        _raise_if_cancellation_requested(job_id, job_service)

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
            validation_scope=validation_scope,
        )
        _raise_if_cancellation_requested(job_id, job_service)

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
        log_event(
            _logger,
            "validation.completed",
            tenant_id=job.tenant_id,
            job_id=job_id,
            duration_ms=(datetime.now(UTC) - started_at).total_seconds() * 1000.0,
            total_rows=summary["total_rows"],
        )

    except JobCancellationRequestedError as exc:
        current_job = job_service.get_job(job_id)
        if current_job is not None and current_job.status != JobStatus.CANCELED:
            job_service.cancel_job(job_id, str(exc))
        log_event(
            _logger,
            "validation.canceled",
            level="warning",
            tenant_id=job.tenant_id,
            job_id=job_id,
            duration_ms=(datetime.now(UTC) - started_at).total_seconds() * 1000.0,
            detail=str(exc),
        )
    except Exception as exc:
        current_job = job_service.get_job(job_id)
        if current_job is not None and current_job.status != JobStatus.CANCELED:
            job_service.fail_job(job_id, str(exc))
        log_event(
            _logger,
            "validation.failed",
            level="error",
            tenant_id=job.tenant_id,
            job_id=job_id,
            duration_ms=(datetime.now(UTC) - started_at).total_seconds() * 1000.0,
            error=str(exc),
        )
