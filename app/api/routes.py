import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.api.auth import get_authenticated_tenant, resolve_request_tenant_id
from app.api.frontend import build_frontend_html
from app.core.job import JobStatus
from app.core.tenant_config import DEFAULT_TENANT_ID
from app.core.tenant_loader import load_tenant_config
from app.core.validation_scope import (
    DEFAULT_VALIDATION_SCOPE,
    VALIDATION_SCOPE_PARAM,
    ValidationScope,
    parse_validation_scope,
)
from app.services.job_service import JobService
from app.services.validation_service import (
    UPLOADS_DIR,
    OperationalExportKind,
    create_reprocess_job,
    get_job_csv_download,
    get_job_operational_export,
    read_job_csv_row,
    resolve_duplicate_csv_rows_and_refresh,
    run_validation_job,
    update_job_csv_row,
)

router = APIRouter()


def _build_job_service() -> JobService:
    storage_path = os.getenv("VALIDATOR_JOB_STORE_PATH")
    return JobService(storage_path=Path(storage_path) if storage_path else None)


job_service = _build_job_service()


class UploadResponse(BaseModel):
    job_id: str
    status: str
    tenant_id: str
    validation_scope: ValidationScope


class TenantListItemResponse(BaseModel):
    tenant_id: str
    display_name: str
    is_default: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    tenant_id: str
    validation_scope: ValidationScope
    status: str
    total_rows: int
    source_total_rows: int = 0
    rows_with_issues: int
    total_issues: int
    processed_rows: int = 0
    batch_size: int = 0
    error_message: str | None = None
    partial_summary: dict[str, Any] = Field(default_factory=dict)
    is_partial_result_available: bool = False
    partial_grouped_problems: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict
    )
    partial_duplicates: list[dict[str, Any]] = Field(default_factory=list)
    row_results_preview: list[dict[str, Any]] = Field(default_factory=list)
    current_step: str | None = None
    status_title: str | None = None
    status_detail: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    file_name: str | None = None
    cancel_requested: bool = False


class JobListItemResponse(BaseModel):
    job_id: str
    tenant_id: str
    validation_scope: ValidationScope
    status: str
    file_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    current_step: str | None = None
    status_title: str | None = None
    status_detail: str | None = None
    processed_rows: int = 0
    total_rows: int = 0
    source_total_rows: int = 0
    cancel_requested: bool = False


class RowUpdateRequest(BaseModel):
    updates: dict[str, str]


class RowUpdateResponse(BaseModel):
    job_id: str
    row_index: int
    updated_row: dict[str, str]


class RowReadResponse(BaseModel):
    job_id: str
    row_index: int
    row: dict[str, str]
    resolved_columns: dict[str, str]


class DuplicateResolutionRequest(BaseModel):
    row_indices: list[int]
    keep_row_index: int


class DuplicateResolutionResponse(BaseModel):
    job_id: str
    kept_row_index: int
    deleted_row_indices: list[int]
    remaining_rows: int
    merged_columns: list[str] = Field(default_factory=list)


def _get_job_validation_scope_value(job) -> ValidationScope:
    return parse_validation_scope(job.params.get(VALIDATION_SCOPE_PARAM))


def _build_job_status_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        validation_scope=_get_job_validation_scope_value(job),
        status=job.status.value,
        total_rows=job.total_rows,
        source_total_rows=job.source_total_rows,
        rows_with_issues=job.rows_with_issues,
        total_issues=job.total_issues,
        processed_rows=job.processed_rows,
        batch_size=job.batch_size,
        error_message=job.error_message,
        partial_summary=job.partial_summary,
        is_partial_result_available=job.is_partial_result_available,
        partial_grouped_problems=job.partial_grouped_problems,
        partial_duplicates=job.partial_duplicates,
        row_results_preview=job.row_results_preview,
        current_step=job.current_step,
        status_title=job.status_title,
        status_detail=job.status_detail,
        created_at=job.created_at,
        updated_at=job.updated_at,
        file_name=job.file_name,
        cancel_requested=job.cancel_requested,
    )


def _build_job_list_item_response(job) -> JobListItemResponse:
    return JobListItemResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        validation_scope=_get_job_validation_scope_value(job),
        status=job.status.value,
        file_name=job.file_name,
        created_at=job.created_at,
        updated_at=job.updated_at,
        current_step=job.current_step,
        status_title=job.status_title,
        status_detail=job.status_detail,
        processed_rows=job.processed_rows,
        total_rows=job.total_rows,
        source_total_rows=job.source_total_rows,
        cancel_requested=job.cancel_requested,
    )


def _build_tenant_list_item_response(tenant_id: str) -> TenantListItemResponse:
    tenant = load_tenant_config(tenant_id)
    return TenantListItemResponse(
        tenant_id=tenant.tenant_id,
        display_name=tenant.display_name,
        is_default=tenant.tenant_id == DEFAULT_TENANT_ID,
    )


def _get_authorized_job(request: Request, job_id: str):
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    auth = get_authenticated_tenant(request)
    if job.tenant_id != auth.tenant_id:
        raise HTTPException(
            status_code=403,
            detail=f"API key does not grant access to tenant '{job.tenant_id}'",
        )

    return job


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def frontend() -> HTMLResponse:
    return HTMLResponse(build_frontend_html())


@router.get("/tenants", response_model=list[TenantListItemResponse])
async def get_tenants(request: Request) -> list[TenantListItemResponse]:
    auth = get_authenticated_tenant(request)
    return [_build_tenant_list_item_response(auth.tenant_id)]


@router.post("/validate", response_model=UploadResponse)
async def upload_and_validate(
    request: Request,
    file: UploadFile,
    tenant_id: str | None = None,
    validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
) -> UploadResponse:
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    job = job_service.create_job(
        tenant_id=resolved_tenant_id,
        file_name=file.filename,
        params={VALIDATION_SCOPE_PARAM: validation_scope.value},
    )
    file_path = UPLOADS_DIR / f"{job.job_id}_{file.filename}"

    content = await file.read()
    file_path.write_bytes(content)

    job.file_path = str(file_path)
    job.file_name = file.filename
    job_service.save_job(job.job_id)

    background_tasks.add_task(run_validation_job, job.job_id, job_service)

    return UploadResponse(
        job_id=job.job_id,
        status=job.status.value,
        tenant_id=job.tenant_id,
        validation_scope=validation_scope,
    )


@router.get("/jobs", response_model=list[JobListItemResponse])
async def list_jobs(request: Request, active_only: bool = False) -> list[JobListItemResponse]:
    auth = get_authenticated_tenant(request)
    jobs = job_service.list_jobs(tenant_id=auth.tenant_id, active_only=active_only)
    return [_build_job_list_item_response(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(request: Request, job_id: str) -> JobStatusResponse:
    job = _get_authorized_job(request, job_id)
    return _build_job_status_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(request: Request, job_id: str) -> JobStatusResponse:
    _get_authorized_job(request, job_id)
    try:
        job = job_service.request_job_cancellation(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return _build_job_status_response(job)


@router.get("/jobs/{job_id}/result")
async def download_result(request: Request, job_id: str) -> dict:
    job = _get_authorized_job(request, job_id)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not completed: {job.status.value}")

    if not job.result_path or not Path(job.result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    import json

    return json.loads(Path(job.result_path).read_text())


@router.get("/jobs/{job_id}/report")
async def download_report(request: Request, job_id: str):
    job = _get_authorized_job(request, job_id)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not completed: {job.status.value}")

    if not job.report_path or not Path(job.report_path).exists():
        raise HTTPException(status_code=404, detail="Report file not found")

    from fastapi.responses import FileResponse

    return FileResponse(
        path=job.report_path,
        media_type="application/pdf",
        filename=f"report_{job_id}.pdf",
    )


@router.get("/jobs/{job_id}/csv")
async def download_job_csv(request: Request, job_id: str):
    _get_authorized_job(request, job_id)
    try:
        csv_path, download_name = get_job_csv_download(job_id, job_service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    from fastapi.responses import FileResponse

    return FileResponse(
        path=csv_path,
        media_type="text/csv",
        filename=download_name,
    )


@router.get("/jobs/{job_id}/exports/csv")
async def download_job_operational_export(
    request: Request,
    job_id: str,
    kind: OperationalExportKind,
    problem_code: str | None = None,
) -> Response:
    _get_authorized_job(request, job_id)
    try:
        csv_content, download_name = get_job_operational_export(
            job_id,
            job_service,
            export_kind=kind,
            problem_code=problem_code,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(content=csv_content, media_type="text/csv", headers=headers)


@router.patch("/jobs/{job_id}/rows/{row_index}", response_model=RowUpdateResponse)
async def update_job_row(
    request: Request,
    job_id: str,
    row_index: int,
    payload: RowUpdateRequest,
) -> RowUpdateResponse:
    _get_authorized_job(request, job_id)
    try:
        updated_row = update_job_csv_row(
            job_id,
            job_service,
            row_index=row_index,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return RowUpdateResponse(
        job_id=job_id,
        row_index=row_index,
        updated_row={k: "" if v is None else str(v) for k, v in updated_row.items()},
    )


@router.get("/jobs/{job_id}/rows/{row_index}", response_model=RowReadResponse)
async def get_job_row(request: Request, job_id: str, row_index: int) -> RowReadResponse:
    _get_authorized_job(request, job_id)
    try:
        row, resolved_columns = read_job_csv_row(
            job_id,
            job_service,
            row_index=row_index,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return RowReadResponse(
        job_id=job_id,
        row_index=row_index,
        row=row,
        resolved_columns=resolved_columns,
    )


@router.post(
    "/jobs/{job_id}/duplicates/resolve",
    response_model=DuplicateResolutionResponse,
)
async def resolve_duplicate_rows(
    request: Request,
    job_id: str,
    payload: DuplicateResolutionRequest,
) -> DuplicateResolutionResponse:
    _get_authorized_job(request, job_id)
    normalized_indices = sorted(set(payload.row_indices))
    if payload.keep_row_index not in normalized_indices:
        raise HTTPException(
            status_code=400,
            detail="keep_row_index must be one of the duplicate row_indices",
        )

    try:
        resolution = resolve_duplicate_csv_rows_and_refresh(
            job_id,
            job_service,
            row_indices=normalized_indices,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return DuplicateResolutionResponse(
        job_id=job_id,
        kept_row_index=resolution.kept_row_index,
        deleted_row_indices=resolution.deleted_row_indices,
        remaining_rows=resolution.remaining_rows,
        merged_columns=resolution.merged_columns,
    )


@router.post("/jobs/{job_id}/reprocess", response_model=UploadResponse)
async def reprocess_job(
    request: Request,
    job_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
) -> UploadResponse:
    _get_authorized_job(request, job_id)
    try:
        new_job = create_reprocess_job(job_id, job_service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    background_tasks.add_task(run_validation_job, new_job.job_id, job_service)

    return UploadResponse(
        job_id=new_job.job_id,
        status=new_job.status.value,
        tenant_id=new_job.tenant_id,
        validation_scope=_get_job_validation_scope_value(new_job),
    )
