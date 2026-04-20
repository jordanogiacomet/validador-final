import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator

from app.api.auth import (
    API_KEY_HEADER,
    auth_service,
    get_authenticated_tenant,
    resolve_request_tenant_id,
)
from app.core.audit import AuditEvent, AuditEventType
from app.core.llm_cache import LLM_FORCE_REFRESH_PARAM
from app.core.operational_sqlite import OPERATIONAL_SQLITE_PATH_ENV
from app.core.tenant_config import DEFAULT_TENANT_ID, OperatorRole
from app.core.tenant_loader import list_tenants, load_tenant_config, tenant_ids_match
from app.core.validation_scope import (
    DEFAULT_VALIDATION_SCOPE,
    VALIDATION_SCOPE_PARAM,
    ValidationScope,
    parse_validation_scope,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthServiceError, EffectiveOperator
from app.services.job_service import JobService
from app.services.tenant_admin_service import (
    TenantAdminRecord,
    TenantAdminService,
    TenantAdminServiceError,
    TenantSource,
)
from app.services.validation_service import (
    OperationalExportKind,
    build_job_upload_path,
    create_reprocess_job,
    get_job_csv_download,
    get_job_operational_export,
    get_job_report_download,
    get_job_result_payload,
    get_job_xlsx_export,
    read_job_csv_row,
    resolve_duplicate_csv_rows_and_refresh,
    run_validation_job,
    set_job_row_review_flag,
    update_job_csv_row,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter()


def _build_audit_service() -> AuditService:
    sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV)
    storage_path = os.getenv("VALIDATOR_AUDIT_STORE_PATH")
    return AuditService(
        storage_path=Path(storage_path) if storage_path else None,
        sqlite_path=Path(sqlite_path) if sqlite_path else None,
    )


def _build_job_service() -> JobService:
    sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV)
    storage_path = os.getenv("VALIDATOR_JOB_STORE_PATH")
    return JobService(
        storage_path=Path(storage_path) if storage_path else None,
        sqlite_path=Path(sqlite_path) if sqlite_path else None,
        audit_service=audit_service,
    )


audit_service = _build_audit_service()
auth_service.set_audit_service(audit_service)


def _build_tenant_admin_service() -> TenantAdminService:
    return TenantAdminService(audit_service=audit_service)


tenant_admin_service = _build_tenant_admin_service()
job_service = _build_job_service()

LOGIN_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
LOGIN_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@-]+$")


class UploadResponse(BaseModel):
    job_id: str
    status: str
    tenant_id: str
    validation_scope: ValidationScope


class TenantListItemResponse(BaseModel):
    tenant_id: str
    display_name: str
    is_default: bool = False
    disabled: bool = False


class TenantScopedRequest(BaseModel):
    tenant_id: str = Field(min_length=1)

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_TENANT_ID_PATTERN.fullmatch(normalized_value):
            raise ValueError("tenant_id contains invalid characters")
        return normalized_value


class LoginRequest(TenantScopedRequest):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError("username contains invalid characters")
        return normalized_value


class LoginResponse(BaseModel):
    tenant_id: str
    operator_id: str
    role: OperatorRole
    api_key_id: str
    x_api_key: str
    expires_at: datetime
    header_name: str = API_KEY_HEADER


class InitialSetupStateResponse(BaseModel):
    available: bool
    storage_configured: bool
    requires_setup_token: bool
    tenant_id: str | None = None


class InitialAdminSetupRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    setup_token: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError("username contains invalid characters")
        return normalized_value


class OperatorResponse(BaseModel):
    tenant_id: str
    operator_id: str
    username: str
    role: OperatorRole
    disabled: bool
    is_seed: bool


class TenantAdminResponse(BaseModel):
    tenant_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    disabled: bool
    source: TenantSource
    is_default: bool = False


class TenantAdminCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class TenantAdminUpdateRequest(BaseModel):
    display_name: str | None = None
    aliases: list[str] | None = None


class OperatorCreateRequest(TenantScopedRequest):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: OperatorRole = OperatorRole.OPERATOR

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError("username contains invalid characters")
        return normalized_value


class OperatorDisableRequest(TenantScopedRequest):
    pass


class SeedOperatorPasswordRotationRequest(TenantScopedRequest):
    new_password: str = Field(min_length=1)


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
    parent_job_id: str | None = None
    latest_retry_job_id: str | None = None


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
    parent_job_id: str | None = None
    latest_retry_job_id: str | None = None


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


class RowReviewFlagRequest(BaseModel):
    status: Literal["review", "clear"]


class ReviewFlagPayload(BaseModel):
    row_index: int
    status: str


class RowReviewFlagResponse(BaseModel):
    job_id: str
    row_index: int
    status: str
    review_flags: list[ReviewFlagPayload]


class DuplicateResolutionRequest(BaseModel):
    row_indices: list[int]
    keep_row_index: int


class DuplicateResolutionResponse(BaseModel):
    job_id: str
    kept_row_index: int
    deleted_row_indices: list[int]
    remaining_rows: int
    merged_columns: list[str] = Field(default_factory=list)


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    tenant_id: str
    job_id: str | None = None
    api_key_id: str | None = None
    created_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class APIKeyRevocationResponse(BaseModel):
    tenant_id: str
    api_key_id: str
    revoked_at: datetime


class APIKeyRenewalResponse(BaseModel):
    tenant_id: str
    operator_id: str
    role: OperatorRole
    api_key_id: str
    previous_api_key_id: str
    x_api_key: str
    expires_at: datetime
    header_name: str = API_KEY_HEADER


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
        parent_job_id=job.parent_job_id,
        latest_retry_job_id=job.latest_retry_job_id,
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
        parent_job_id=job.parent_job_id,
        latest_retry_job_id=job.latest_retry_job_id,
    )


def _build_tenant_list_item_response(tenant_id: str) -> TenantListItemResponse:
    tenant = load_tenant_config(tenant_id)
    return TenantListItemResponse(
        tenant_id=tenant.tenant_id,
        display_name=tenant.display_name,
        is_default=tenant.tenant_id == DEFAULT_TENANT_ID,
        disabled=tenant.disabled,
    )


def _build_audit_event_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        tenant_id=event.tenant_id,
        job_id=event.job_id,
        api_key_id=event.api_key_id,
        created_at=event.created_at,
        details=event.details,
    )


def _build_operator_response(operator: EffectiveOperator) -> OperatorResponse:
    return OperatorResponse(
        tenant_id=operator.tenant_id,
        operator_id=operator.operator_id,
        username=operator.username,
        role=operator.role,
        disabled=operator.disabled,
        is_seed=operator.is_seed,
    )


def _build_tenant_admin_response(tenant: TenantAdminRecord) -> TenantAdminResponse:
    return TenantAdminResponse(
        tenant_id=tenant.tenant_id,
        display_name=tenant.display_name,
        aliases=tenant.aliases,
        disabled=tenant.disabled,
        source=tenant.source,
        is_default=tenant.is_default,
    )


def _get_authorized_job(request: Request, job_id: str):
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    auth = get_authenticated_tenant(request)
    if not tenant_ids_match(job.tenant_id, auth.tenant_id):
        raise HTTPException(
            status_code=403,
            detail=f"API key does not grant access to tenant '{job.tenant_id}'",
        )

    return job


def _authorize_operator_management(
    request: Request,
    *,
    target_tenant_id: str,
    action: str,
) -> str:
    auth = get_authenticated_tenant(request)
    try:
        return auth_service.authorize_operator_management(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            target_tenant_id=target_tenant_id,
            action=action,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


def _authorize_tenant_administration(
    request: Request,
    *,
    action: str,
    target_tenant_id: str | None = None,
) -> None:
    auth = get_authenticated_tenant(request)
    try:
        auth_service.authorize_tenant_administration(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            action=action,
            target_tenant_id=target_tenant_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


@router.get("/", include_in_schema=False, response_model=None)
async def frontend() -> Response:
    frontend_url = os.getenv("VALIDATOR_FRONTEND_URL", "").strip()
    if frontend_url:
        return RedirectResponse(frontend_url)

    return JSONResponse(
        {
            "service": "validador-final-api",
            "status": "ok",
            "ui": "Configure VALIDATOR_FRONTEND_URL to redirect operators to the frontend.",
            "health": "/health",
            "docs": "/docs",
        }
    )


@router.get("/setup", response_model=InitialSetupStateResponse)
async def get_initial_setup_state() -> InitialSetupStateResponse:
    state = auth_service.get_initial_setup_state()
    return InitialSetupStateResponse(
        available=state.available,
        storage_configured=state.storage_configured,
        requires_setup_token=state.requires_setup_token,
        tenant_id=state.tenant_id,
    )


@router.post("/setup", response_model=OperatorResponse, status_code=201)
async def create_initial_admin(payload: InitialAdminSetupRequest) -> OperatorResponse:
    try:
        operator = auth_service.create_initial_admin(
            username=payload.username,
            password=payload.password,
            setup_token=payload.setup_token,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return _build_operator_response(operator)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    try:
        issued_key = auth_service.issue_api_key(
            tenant_id=payload.tenant_id,
            username=payload.username,
            password=payload.password,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return LoginResponse(
        tenant_id=issued_key.record.tenant_id,
        operator_id=issued_key.record.operator_id,
        role=issued_key.record.role,
        api_key_id=issued_key.record.key_id,
        x_api_key=issued_key.raw_api_key,
        expires_at=issued_key.record.expires_at or issued_key.record.created_at,
    )


@router.post("/api-keys/renew", response_model=APIKeyRenewalResponse)
async def renew_api_key(request: Request) -> APIKeyRenewalResponse:
    auth = get_authenticated_tenant(request)
    try:
        issued_key = auth_service.renew_api_key(
            tenant_id=auth.tenant_id,
            api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return APIKeyRenewalResponse(
        tenant_id=issued_key.record.tenant_id,
        operator_id=issued_key.record.operator_id,
        role=issued_key.record.role,
        api_key_id=issued_key.record.key_id,
        previous_api_key_id=auth.api_key_id,
        x_api_key=issued_key.raw_api_key,
        expires_at=issued_key.record.expires_at or issued_key.record.created_at,
    )


@router.post("/api-keys/revoke", response_model=APIKeyRevocationResponse)
async def revoke_api_key(
    request: Request,
    api_key_id: str | None = Query(default=None, min_length=1),
) -> APIKeyRevocationResponse:
    auth = get_authenticated_tenant(request)
    target_api_key_id = api_key_id or auth.api_key_id
    try:
        record = auth_service.revoke_api_key(
            tenant_id=auth.tenant_id,
            api_key_id=target_api_key_id,
            revoked_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return APIKeyRevocationResponse(
        tenant_id=record.tenant_id,
        api_key_id=record.key_id,
        revoked_at=record.revoked_at or record.created_at,
    )


@router.get("/admin/tenants", response_model=list[TenantAdminResponse])
async def admin_list_tenants(request: Request) -> list[TenantAdminResponse]:
    _authorize_tenant_administration(request, action="tenants.list")
    return [
        _build_tenant_admin_response(tenant)
        for tenant in tenant_admin_service.list_tenants()
    ]


@router.post(
    "/admin/tenants",
    response_model=TenantAdminResponse,
    status_code=201,
)
async def admin_create_tenant(
    request: Request,
    payload: TenantAdminCreateRequest,
) -> TenantAdminResponse:
    auth = get_authenticated_tenant(request)
    _authorize_tenant_administration(
        request,
        action="tenants.create",
        target_tenant_id=payload.tenant_id,
    )
    try:
        tenant = tenant_admin_service.create_tenant(
            tenant_id=payload.tenant_id,
            display_name=payload.display_name,
            aliases=payload.aliases,
            api_key_id=auth.api_key_id,
        )
    except TenantAdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_admin_response(tenant)


@router.patch(
    "/admin/tenants/{tenant_id}",
    response_model=TenantAdminResponse,
)
async def admin_update_tenant(
    request: Request,
    tenant_id: str,
    payload: TenantAdminUpdateRequest,
) -> TenantAdminResponse:
    auth = get_authenticated_tenant(request)
    _authorize_tenant_administration(
        request,
        action="tenants.update",
        target_tenant_id=tenant_id,
    )
    try:
        tenant = tenant_admin_service.update_tenant(
            tenant_id=tenant_id,
            display_name=payload.display_name,
            aliases=payload.aliases,
            api_key_id=auth.api_key_id,
        )
    except TenantAdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_admin_response(tenant)


@router.post(
    "/admin/tenants/{tenant_id}/disable",
    response_model=TenantAdminResponse,
)
async def admin_disable_tenant(
    request: Request,
    tenant_id: str,
) -> TenantAdminResponse:
    auth = get_authenticated_tenant(request)
    _authorize_tenant_administration(
        request,
        action="tenants.disable",
        target_tenant_id=tenant_id,
    )
    try:
        tenant = tenant_admin_service.disable_tenant(
            tenant_id=tenant_id,
            api_key_id=auth.api_key_id,
        )
    except TenantAdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_admin_response(tenant)


@router.post(
    "/admin/tenants/{tenant_id}/reactivate",
    response_model=TenantAdminResponse,
)
async def admin_reactivate_tenant(
    request: Request,
    tenant_id: str,
) -> TenantAdminResponse:
    auth = get_authenticated_tenant(request)
    _authorize_tenant_administration(
        request,
        action="tenants.reactivate",
        target_tenant_id=tenant_id,
    )
    try:
        tenant = tenant_admin_service.reactivate_tenant(
            tenant_id=tenant_id,
            api_key_id=auth.api_key_id,
        )
    except TenantAdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_admin_response(tenant)


@router.get("/tenants", response_model=list[TenantListItemResponse])
async def get_tenants(request: Request) -> list[TenantListItemResponse]:
    auth = get_authenticated_tenant(request)
    role = auth_service.get_operator_role(
        tenant_id=auth.tenant_id,
        operator_id=auth.operator_id,
    )
    tenant_ids = (
        list_tenants() if role is OperatorRole.PLATFORM_ADMIN else [auth.tenant_id]
    )
    return [_build_tenant_list_item_response(tenant_id) for tenant_id in tenant_ids]


@router.get("/operators", response_model=list[OperatorResponse])
async def list_operators(
    request: Request,
    tenant_id: str = Query(min_length=1),
) -> list[OperatorResponse]:
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=tenant_id,
        action="operators.list",
    )
    try:
        operators = auth_service.list_operators(tenant_id=resolved_tenant_id)
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return [_build_operator_response(operator) for operator in operators]


@router.post("/operators", response_model=OperatorResponse, status_code=201)
async def create_operator(
    request: Request,
    payload: OperatorCreateRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.create",
    )
    try:
        auth_service.authorize_operator_role_assignment(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            target_tenant_id=resolved_tenant_id,
            requested_role=payload.role,
        )
        operator = auth_service.create_operator(
            tenant_id=resolved_tenant_id,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            created_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.post("/operators/{operator_id}/disable", response_model=OperatorResponse)
async def disable_operator(
    request: Request,
    operator_id: str,
    payload: OperatorDisableRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.disable",
    )
    try:
        operator = auth_service.disable_operator(
            tenant_id=resolved_tenant_id,
            operator_id=operator_id,
            disabled_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.post(
    "/operators/seed/rotate-password",
    response_model=OperatorResponse,
)
async def rotate_seed_operator_password(
    request: Request,
    payload: SeedOperatorPasswordRotationRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.rotate_seed_password",
    )
    try:
        operator = auth_service.rotate_seed_operator_password(
            tenant_id=resolved_tenant_id,
            new_password=payload.new_password,
            rotated_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.get("/audit", response_model=list[AuditEventResponse])
async def list_audit_events(
    request: Request,
    tenant_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditEventResponse]:
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    events = audit_service.list_events(tenant_id=resolved_tenant_id, limit=limit)
    return [_build_audit_event_response(event) for event in events]


@router.post("/validate", response_model=UploadResponse)
async def upload_and_validate(
    request: Request,
    file: UploadFile,
    tenant_id: str | None = None,
    validation_scope: ValidationScope = DEFAULT_VALIDATION_SCOPE,
    force_refresh: bool = False,
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
) -> UploadResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)

    stored_file_name = Path(file.filename or "lote.csv").name or "lote.csv"
    job = job_service.create_job(
        tenant_id=resolved_tenant_id,
        file_name=stored_file_name,
        api_key_id=auth.api_key_id,
        params={
            VALIDATION_SCOPE_PARAM: validation_scope.value,
            LLM_FORCE_REFRESH_PARAM: force_refresh,
        },
    )
    file_path = build_job_upload_path(
        resolved_tenant_id,
        job.job_id,
        stored_file_name,
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    file_path.write_bytes(content)

    job.file_path = str(file_path)
    job.file_name = stored_file_name
    job_service.save_job(job.job_id)

    background_tasks.add_task(run_validation_job, job.job_id, job_service)

    return UploadResponse(
        job_id=job.job_id,
        status=job.status.value,
        tenant_id=job.tenant_id,
        validation_scope=validation_scope,
    )


@router.get("/jobs", response_model=list[JobListItemResponse])
async def list_jobs(
    request: Request,
    active_only: bool = False,
    limit: int | None = Query(default=None, ge=1, le=200),
) -> list[JobListItemResponse]:
    auth = get_authenticated_tenant(request)
    jobs = job_service.list_jobs(
        tenant_id=auth.tenant_id,
        active_only=active_only,
        limit=limit,
    )
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
    _get_authorized_job(request, job_id)

    try:
        return get_job_result_payload(job_id, job_service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/jobs/{job_id}/report")
async def download_report(request: Request, job_id: str):
    _get_authorized_job(request, job_id)

    from fastapi.responses import FileResponse

    try:
        report_path = get_job_report_download(job_id, job_service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    return FileResponse(
        path=report_path,
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


@router.get("/jobs/{job_id}/export")
async def download_job_export(
    request: Request,
    job_id: str,
    format: str = "xlsx",
) -> Response:
    _get_authorized_job(request, job_id)

    if format != "xlsx":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported export format: {format}",
        )

    try:
        xlsx_bytes, download_name = get_job_xlsx_export(job_id, job_service)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers=headers,
    )


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


@router.patch(
    "/jobs/{job_id}/rows/{row_index}/flag",
    response_model=RowReviewFlagResponse,
)
async def update_job_row_review_flag(
    request: Request,
    job_id: str,
    row_index: int,
    payload: RowReviewFlagRequest,
) -> RowReviewFlagResponse:
    _get_authorized_job(request, job_id)
    try:
        update = set_job_row_review_flag(
            job_id,
            job_service,
            row_index=row_index,
            status=payload.status,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return RowReviewFlagResponse(
        job_id=job_id,
        row_index=update.row_index,
        status=update.status,
        review_flags=update.review_flags,
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
    job = _get_authorized_job(request, job_id)
    auth = get_authenticated_tenant(request)
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

    audit_service.record_event(
        AuditEventType.DUPLICATES_RESOLVED,
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        api_key_id=auth.api_key_id,
        details={
            "row_indices": normalized_indices,
            "kept_row_index": resolution.kept_row_index,
            "deleted_row_indices": resolution.deleted_row_indices,
            "remaining_rows": resolution.remaining_rows,
            "merged_columns": resolution.merged_columns,
        },
    )

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
    force_refresh: bool | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
) -> UploadResponse:
    _get_authorized_job(request, job_id)
    auth = get_authenticated_tenant(request)
    try:
        new_job = create_reprocess_job(
            job_id,
            job_service,
            api_key_id=auth.api_key_id,
            force_refresh=force_refresh,
        )
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
