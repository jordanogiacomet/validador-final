import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator

from app.api.auth import (
    API_KEY_HEADER,
    auth_service,
    get_authenticated_tenant,
    resolve_request_tenant_id,
)
from app.core.audit import AuditEvent, AuditPrincipal
from app.core.llm_cache import LLM_FORCE_REFRESH_PARAM
from app.core.retention import RetentionPolicy
from app.core.tenant_config import DEFAULT_TENANT_ID, OperatorRole
from app.core.tenant_loader import list_tenants, load_tenant_config, tenant_ids_match
from app.core.tenant_profile import (
    ValidationProfileData,
    ValidationProfileDraftRecord,
    ValidationProfileVersionRecord,
)
from app.core.validation_scope import (
    DEFAULT_VALIDATION_SCOPE,
    VALIDATION_SCOPE_PARAM,
    ValidationScope,
    parse_validation_scope,
)
from app.services.auth_service import AuthServiceError, EffectiveOperator
from app.services.correction_history_service import (
    CorrectionHistoryConflictError,
    get_job_result_payload_with_history,
    resolve_duplicate_rows_with_history,
    revert_job_correction,
    set_job_row_review_flag_with_history,
    update_job_row_with_history,
)
from app.services.operational_kpi_service import (
    LLMModelUsageSnapshot,
    LLMUsageSnapshot,
    OperationalKPIService,
    OperationalKPISnapshot,
    OperationalTenantKPISnapshot,
)
from app.services.runtime import (
    build_audit_service,
    build_job_service,
    build_retention_service,
)
from app.services.tenant_admin_service import (
    TenantAdminRecord,
    TenantAdminService,
    TenantAdminServiceError,
    TenantSource,
)
from app.services.tenant_profile_service import (
    TenantProfileService,
    TenantProfileServiceError,
)
from app.services.validation_service import (
    OperationalExportKind,
    UploadPreflightError,
    build_job_upload_path,
    build_tenant_upload_template_xlsx,
    create_reprocess_job,
    get_job_csv_download,
    get_job_operational_export,
    get_job_report_download,
    get_job_xlsx_export,
    prepare_upload_content_for_job,
    read_job_csv_row,
    run_upload_preflight,
    run_validation_job,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JOB_EXECUTION_MODE_ENV = "VALIDATOR_JOB_EXECUTION_MODE"
JOB_EXECUTION_MODE_BACKGROUND = "background"
JOB_EXECUTION_MODE_WORKER = "worker"

router = APIRouter()


audit_service = build_audit_service()
auth_service.set_audit_service(audit_service)


def _build_tenant_admin_service() -> TenantAdminService:
    return TenantAdminService(audit_service=audit_service)


def _build_tenant_profile_service() -> TenantProfileService:
    return TenantProfileService(audit_service=audit_service)


tenant_admin_service = _build_tenant_admin_service()
tenant_profile_service = _build_tenant_profile_service()
job_service = build_job_service(audit_service=audit_service)
retention_service = build_retention_service(
    job_service=job_service,
    audit_service=audit_service,
)
operational_kpi_service = OperationalKPIService(job_service=job_service)

LOGIN_TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
LOGIN_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@-]+$")


def _get_job_execution_mode() -> str:
    configured_value = (
        os.getenv(JOB_EXECUTION_MODE_ENV, JOB_EXECUTION_MODE_BACKGROUND)
        .strip()
        .lower()
    )
    if configured_value in {
        JOB_EXECUTION_MODE_BACKGROUND,
        JOB_EXECUTION_MODE_WORKER,
    }:
        return configured_value
    raise RuntimeError(
        f"Unsupported {JOB_EXECUTION_MODE_ENV} value: {configured_value}"
    )


def _schedule_validation_execution(
    *,
    background_tasks: BackgroundTasks,
    job_id: str,
) -> None:
    execution_mode = _get_job_execution_mode()
    if execution_mode == JOB_EXECUTION_MODE_WORKER:
        if not job_service.supports_worker_claims:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Worker execution mode requires SQLite-backed operational storage."
                ),
            )
        return

    background_tasks.add_task(run_validation_job, job_id, job_service)


class UploadResponse(BaseModel):
    job_id: str
    status: str
    tenant_id: str
    validation_scope: ValidationScope


class UploadPreflightIssueResponse(BaseModel):
    code: str
    message: str


class UploadPreflightResponse(BaseModel):
    file_name: str
    file_size_bytes: int
    detected_columns: list[str] = Field(default_factory=list)
    missing_columns: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    issues: list[UploadPreflightIssueResponse] = Field(default_factory=list)


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
    must_change_password: bool = False
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
    must_change_password: bool = False
    is_seed: bool


class TenantAdminResponse(BaseModel):
    tenant_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    disabled: bool
    source: TenantSource
    is_default: bool = False


class ValidationProfileDraftResponse(BaseModel):
    tenant_id: str
    profile: ValidationProfileData
    updated_at: datetime
    updated_by_operator_id: str | None = None
    updated_by_username: str | None = None
    updated_by_role: str | None = None


class ValidationProfileVersionResponse(BaseModel):
    tenant_id: str
    version_id: str
    version_number: int
    profile: ValidationProfileData
    published_at: datetime
    published_by_operator_id: str | None = None
    published_by_username: str | None = None
    published_by_role: str | None = None
    source: str
    rollback_source_version_id: str | None = None


class TenantValidationProfileResponse(BaseModel):
    tenant_id: str
    source: str
    current_profile: ValidationProfileData
    draft: ValidationProfileDraftResponse | None = None
    published_version: ValidationProfileVersionResponse | None = None
    versions: list[ValidationProfileVersionResponse] = Field(default_factory=list)


class TenantValidationProfileDraftRequest(BaseModel):
    profile: ValidationProfileData


class TenantValidationProfileRollbackRequest(BaseModel):
    version_id: str = Field(min_length=1)


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
    require_password_change: bool = True

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError("username contains invalid characters")
        return normalized_value


class OperatorDisableRequest(TenantScopedRequest):
    pass


class OperatorRoleUpdateRequest(TenantScopedRequest):
    role: OperatorRole


class OperatorPasswordResetRequest(TenantScopedRequest):
    new_password: str = Field(min_length=1)
    require_password_change: bool = True


class PasswordSetupCompletionRequest(BaseModel):
    new_password: str = Field(min_length=1)


class OperatorInvitationCreateRequest(TenantScopedRequest):
    username: str = Field(min_length=1)
    role: OperatorRole = OperatorRole.OPERATOR
    expires_in_hours: int = Field(default=48, ge=1, le=24 * 30)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized_value = value.strip()
        if not LOGIN_USERNAME_PATTERN.fullmatch(normalized_value):
            raise ValueError("username contains invalid characters")
        return normalized_value


class OperatorInvitationAcceptRequest(BaseModel):
    invite_token: str = Field(min_length=1)
    password: str = Field(min_length=1)


class OperatorInvitationResponse(BaseModel):
    tenant_id: str
    invite_id: str
    username: str
    role: OperatorRole
    expires_at: datetime
    invite_token: str


class OperatorPasswordResetTokenCreateRequest(TenantScopedRequest):
    expires_in_minutes: int = Field(default=60, ge=5, le=240)


class OperatorPasswordResetTokenResponse(BaseModel):
    tenant_id: str
    operator_id: str
    reset_id: str
    expires_at: datetime
    reset_token: str


class OperatorPasswordResetCompletionRequest(BaseModel):
    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


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


class CorrectionFieldDiffResponse(BaseModel):
    field: str
    source_column: str | None = None
    before: str
    after: str


class CorrectionRowSnapshotResponse(BaseModel):
    row_index: int
    row: dict[str, str]


class CorrectionHistoryEntryResponse(BaseModel):
    event_id: str
    event_type: str
    action: str
    tenant_id: str
    job_id: str
    api_key_id: str | None = None
    created_at: datetime
    actor_operator_id: str | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    row_index: int | None = None
    row_indices: list[int] = Field(default_factory=list)
    kept_row_index: int | None = None
    current_kept_row_index: int | None = None
    deleted_row_indices: list[int] = Field(default_factory=list)
    merged_columns: list[str] = Field(default_factory=list)
    field_diffs: list[CorrectionFieldDiffResponse] = Field(default_factory=list)
    before_status: str | None = None
    after_status: str | None = None
    before_rows: list[CorrectionRowSnapshotResponse] = Field(default_factory=list)
    after_rows: list[CorrectionRowSnapshotResponse] = Field(default_factory=list)
    is_reverted: bool = False
    reverted_at: datetime | None = None
    reverted_by_event_id: str | None = None
    can_revert: bool = False
    revert_blocked_reason: str | None = None


class CorrectionRevertResponse(BaseModel):
    job_id: str
    reverted_event_id: str
    revert_event_id: str
    action: str


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


class OperationalKPILLMModelResponse(BaseModel):
    model: str
    provider_requests: int
    cache_hits: int
    successful_requests: int
    failed_requests: int
    findings: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None = None


class OperationalKPILLMResponse(BaseModel):
    audited_rows: int
    provider_requests: int
    cache_hits: int
    successful_requests: int
    failed_requests: int
    findings: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None = None
    models: list[OperationalKPILLMModelResponse] = Field(default_factory=list)


class OperationalKPITenantResponse(BaseModel):
    tenant_id: str | None = None
    total_jobs: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    canceled_jobs: int
    validated_rows: int
    source_rows: int
    rows_with_errors: int
    rows_with_warnings: int
    error_issue_count: int
    warning_issue_count: int
    error_rate: float
    warning_rate: float
    average_duration_ms: float | None = None
    llm: OperationalKPILLMResponse


class OperationalKPIResponse(BaseModel):
    tenant_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    generated_at: datetime
    summary: OperationalKPITenantResponse
    tenants: list[OperationalKPITenantResponse] = Field(default_factory=list)


class RetentionArtifactResponse(BaseModel):
    kind: str
    path: str
    tenant_id: str | None = None
    job_id: str | None = None
    size_bytes: int = 0
    reference_time: datetime | None = None


class RetentionRunResponse(BaseModel):
    tenant_id: str
    dry_run: bool
    policy: dict[str, int | None]
    scanned_jobs: int
    protected_artifacts: int
    retained_artifacts: int
    artifact_count: int
    artifacts: list[RetentionArtifactResponse] = Field(default_factory=list)
    llm_cache_entries_removed: int = 0
    llm_cache_entries_remaining: int = 0
    started_at: datetime
    finished_at: datetime


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


def _build_upload_preflight_response(
    result,
) -> UploadPreflightResponse:
    return UploadPreflightResponse(
        file_name=result.file_name,
        file_size_bytes=result.file_size_bytes,
        detected_columns=result.detected_columns,
        missing_columns=result.missing_columns,
        guidance=result.guidance,
        issues=[
            UploadPreflightIssueResponse(code=issue.code, message=issue.message)
            for issue in result.issues
        ],
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


def _build_operational_kpi_llm_model_response(
    snapshot: LLMModelUsageSnapshot,
) -> OperationalKPILLMModelResponse:
    return OperationalKPILLMModelResponse(
        model=snapshot.model,
        provider_requests=snapshot.provider_requests,
        cache_hits=snapshot.cache_hits,
        successful_requests=snapshot.successful_requests,
        failed_requests=snapshot.failed_requests,
        findings=snapshot.findings,
        input_tokens=snapshot.input_tokens,
        output_tokens=snapshot.output_tokens,
        estimated_cost_usd=snapshot.estimated_cost_usd,
    )


def _build_operational_kpi_llm_response(
    snapshot: LLMUsageSnapshot,
) -> OperationalKPILLMResponse:
    return OperationalKPILLMResponse(
        audited_rows=snapshot.audited_rows,
        provider_requests=snapshot.provider_requests,
        cache_hits=snapshot.cache_hits,
        successful_requests=snapshot.successful_requests,
        failed_requests=snapshot.failed_requests,
        findings=snapshot.findings,
        input_tokens=snapshot.input_tokens,
        output_tokens=snapshot.output_tokens,
        estimated_cost_usd=snapshot.estimated_cost_usd,
        models=[
            _build_operational_kpi_llm_model_response(model)
            for model in snapshot.models
        ],
    )


def _build_operational_kpi_tenant_response(
    snapshot: OperationalTenantKPISnapshot,
) -> OperationalKPITenantResponse:
    return OperationalKPITenantResponse(
        tenant_id=snapshot.tenant_id,
        total_jobs=snapshot.total_jobs,
        queued_jobs=snapshot.queued_jobs,
        running_jobs=snapshot.running_jobs,
        completed_jobs=snapshot.completed_jobs,
        failed_jobs=snapshot.failed_jobs,
        canceled_jobs=snapshot.canceled_jobs,
        validated_rows=snapshot.validated_rows,
        source_rows=snapshot.source_rows,
        rows_with_errors=snapshot.rows_with_errors,
        rows_with_warnings=snapshot.rows_with_warnings,
        error_issue_count=snapshot.error_issue_count,
        warning_issue_count=snapshot.warning_issue_count,
        error_rate=snapshot.error_rate,
        warning_rate=snapshot.warning_rate,
        average_duration_ms=snapshot.average_duration_ms,
        llm=_build_operational_kpi_llm_response(snapshot.llm),
    )


def _build_operational_kpi_response(
    snapshot: OperationalKPISnapshot,
) -> OperationalKPIResponse:
    return OperationalKPIResponse(
        tenant_id=snapshot.tenant_id,
        created_from=snapshot.created_from,
        created_to=snapshot.created_to,
        generated_at=snapshot.generated_at,
        summary=_build_operational_kpi_tenant_response(snapshot.summary),
        tenants=[
            _build_operational_kpi_tenant_response(tenant)
            for tenant in snapshot.tenants
        ],
    )


def _build_retention_run_response(result) -> RetentionRunResponse:
    return RetentionRunResponse(
        tenant_id=result.tenant_id,
        dry_run=result.dry_run,
        policy=result.policy.as_dict(),
        scanned_jobs=result.scanned_jobs,
        protected_artifacts=result.protected_artifacts,
        retained_artifacts=result.retained_artifacts,
        artifact_count=result.artifact_count,
        artifacts=[
            RetentionArtifactResponse(**artifact.as_dict())
            for artifact in result.artifacts
        ],
        llm_cache_entries_removed=result.llm_cache_entries_removed,
        llm_cache_entries_remaining=result.llm_cache_entries_remaining,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


def _build_operator_response(operator: EffectiveOperator) -> OperatorResponse:
    return OperatorResponse(
        tenant_id=operator.tenant_id,
        operator_id=operator.operator_id,
        username=operator.username,
        role=operator.role,
        disabled=operator.disabled,
        must_change_password=operator.must_change_password,
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


def _build_profile_draft_response(
    draft: ValidationProfileDraftRecord,
) -> ValidationProfileDraftResponse:
    return ValidationProfileDraftResponse(
        tenant_id=draft.tenant_id,
        profile=draft.profile,
        updated_at=draft.updated_at,
        updated_by_operator_id=draft.updated_by_operator_id,
        updated_by_username=draft.updated_by_username,
        updated_by_role=draft.updated_by_role,
    )


def _build_profile_version_response(
    version: ValidationProfileVersionRecord,
) -> ValidationProfileVersionResponse:
    return ValidationProfileVersionResponse(
        tenant_id=version.tenant_id,
        version_id=version.version_id,
        version_number=version.version_number,
        profile=version.profile,
        published_at=version.published_at,
        published_by_operator_id=version.published_by_operator_id,
        published_by_username=version.published_by_username,
        published_by_role=version.published_by_role,
        source=version.source,
        rollback_source_version_id=version.rollback_source_version_id,
    )


def _build_tenant_validation_profile_response(
    state,
) -> TenantValidationProfileResponse:
    return TenantValidationProfileResponse(
        tenant_id=state.tenant_id,
        source=state.source,
        current_profile=state.current_profile,
        draft=(
            _build_profile_draft_response(state.draft)
            if state.draft is not None
            else None
        ),
        published_version=(
            _build_profile_version_response(state.published_version)
            if state.published_version is not None
            else None
        ),
        versions=[
            _build_profile_version_response(version)
            for version in state.versions
        ],
    )


def _request_origin(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


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


def _authorize_validation_profile_management(
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


def _build_request_audit_actor(request: Request) -> AuditPrincipal | None:
    auth = get_authenticated_tenant(request)
    if auth.operator_id is None:
        return None

    operator = auth_service.get_operator(
        tenant_id=auth.tenant_id,
        operator_id=auth.operator_id,
    )
    if operator is None:
        return None

    return AuditPrincipal(
        tenant_id=operator.tenant_id,
        operator_id=operator.operator_id,
        username=operator.username,
        role=operator.role.value,
    )


def _authorize_audit_read(
    request: Request,
    *,
    tenant_id: str | None,
):
    auth = get_authenticated_tenant(request)
    try:
        return auth_service.authorize_audit_read(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            requested_tenant_id=tenant_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


def _authorize_operational_kpi_read(
    request: Request,
    *,
    tenant_id: str | None,
) -> str | None:
    auth = get_authenticated_tenant(request)
    try:
        return auth_service.authorize_operational_kpi_read(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            requested_tenant_id=tenant_id,
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
async def create_initial_admin(
    request: Request,
    payload: InitialAdminSetupRequest,
) -> OperatorResponse:
    try:
        operator = auth_service.create_initial_admin(
            username=payload.username,
            password=payload.password,
            setup_token=payload.setup_token,
            origin=_request_origin(request),
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return _build_operator_response(operator)


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, payload: LoginRequest) -> LoginResponse:
    try:
        issued_key = auth_service.issue_api_key(
            tenant_id=payload.tenant_id,
            username=payload.username,
            password=payload.password,
            origin=_request_origin(request),
        )
    except AuthServiceError as exc:
        if exc.status_code == 429:
            raise HTTPException(status_code=429, detail=exc.detail) from None
        if exc.status_code in {401, 403, 404}:
            raise HTTPException(status_code=401, detail="Invalid credentials") from None
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return LoginResponse(
        tenant_id=issued_key.record.tenant_id,
        operator_id=issued_key.record.operator_id,
        role=issued_key.record.role,
        api_key_id=issued_key.record.key_id,
        x_api_key=issued_key.raw_api_key,
        expires_at=issued_key.record.expires_at or issued_key.record.created_at,
        must_change_password=issued_key.must_change_password,
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
    actor = _build_request_audit_actor(request)
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
            actor=actor,
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
    actor = _build_request_audit_actor(request)
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
            actor=actor,
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
    actor = _build_request_audit_actor(request)
    _authorize_tenant_administration(
        request,
        action="tenants.disable",
        target_tenant_id=tenant_id,
    )
    try:
        tenant = tenant_admin_service.disable_tenant(
            tenant_id=tenant_id,
            api_key_id=auth.api_key_id,
            actor=actor,
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
    actor = _build_request_audit_actor(request)
    _authorize_tenant_administration(
        request,
        action="tenants.reactivate",
        target_tenant_id=tenant_id,
    )
    try:
        tenant = tenant_admin_service.reactivate_tenant(
            tenant_id=tenant_id,
            api_key_id=auth.api_key_id,
            actor=actor,
        )
    except TenantAdminServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_admin_response(tenant)


@router.get(
    "/admin/tenants/{tenant_id}/validation-profile",
    response_model=TenantValidationProfileResponse,
)
async def admin_get_tenant_validation_profile(
    request: Request,
    tenant_id: str,
) -> TenantValidationProfileResponse:
    resolved_tenant_id = _authorize_validation_profile_management(
        request,
        target_tenant_id=tenant_id,
        action="validation_profiles.read",
    )
    try:
        state = tenant_profile_service.get_profile_state(resolved_tenant_id)
    except TenantProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_validation_profile_response(state)


@router.put(
    "/admin/tenants/{tenant_id}/validation-profile/draft",
    response_model=TenantValidationProfileResponse,
)
async def admin_save_tenant_validation_profile_draft(
    request: Request,
    tenant_id: str,
    payload: TenantValidationProfileDraftRequest,
) -> TenantValidationProfileResponse:
    auth = get_authenticated_tenant(request)
    actor = _build_request_audit_actor(request)
    resolved_tenant_id = _authorize_validation_profile_management(
        request,
        target_tenant_id=tenant_id,
        action="validation_profiles.save_draft",
    )
    try:
        state = tenant_profile_service.save_draft(
            tenant_id=resolved_tenant_id,
            profile=payload.profile,
            api_key_id=auth.api_key_id,
            actor=actor,
        )
    except TenantProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_validation_profile_response(state)


@router.post(
    "/admin/tenants/{tenant_id}/validation-profile/publish",
    response_model=TenantValidationProfileResponse,
)
async def admin_publish_tenant_validation_profile_draft(
    request: Request,
    tenant_id: str,
) -> TenantValidationProfileResponse:
    auth = get_authenticated_tenant(request)
    actor = _build_request_audit_actor(request)
    resolved_tenant_id = _authorize_validation_profile_management(
        request,
        target_tenant_id=tenant_id,
        action="validation_profiles.publish",
    )
    try:
        state = tenant_profile_service.publish_draft(
            tenant_id=resolved_tenant_id,
            api_key_id=auth.api_key_id,
            actor=actor,
        )
    except TenantProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_validation_profile_response(state)


@router.post(
    "/admin/tenants/{tenant_id}/validation-profile/rollback",
    response_model=TenantValidationProfileResponse,
)
async def admin_rollback_tenant_validation_profile(
    request: Request,
    tenant_id: str,
    payload: TenantValidationProfileRollbackRequest,
) -> TenantValidationProfileResponse:
    auth = get_authenticated_tenant(request)
    actor = _build_request_audit_actor(request)
    resolved_tenant_id = _authorize_validation_profile_management(
        request,
        target_tenant_id=tenant_id,
        action="validation_profiles.rollback",
    )
    try:
        state = tenant_profile_service.rollback_to_version(
            tenant_id=resolved_tenant_id,
            version_id=payload.version_id,
            api_key_id=auth.api_key_id,
            actor=actor,
        )
    except TenantProfileServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_tenant_validation_profile_response(state)


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


@router.get("/tenants/{tenant_id}/template")
async def download_tenant_upload_template(request: Request, tenant_id: str) -> Response:
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    tenant_config = load_tenant_config(resolved_tenant_id)
    xlsx_bytes, download_name = build_tenant_upload_template_xlsx(tenant_config)
    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers=headers,
    )


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
            require_password_change=payload.require_password_change,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.post(
    "/operators/invitations",
    response_model=OperatorInvitationResponse,
    status_code=201,
)
async def create_operator_invitation(
    request: Request,
    payload: OperatorInvitationCreateRequest,
) -> OperatorInvitationResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.invite",
    )
    try:
        auth_service.authorize_operator_role_assignment(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            target_tenant_id=resolved_tenant_id,
            requested_role=payload.role,
            action="operators.invite.platform_admin",
        )
        invitation = auth_service.create_operator_invitation(
            tenant_id=resolved_tenant_id,
            username=payload.username,
            role=payload.role,
            expires_in=timedelta(hours=payload.expires_in_hours),
            created_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return OperatorInvitationResponse(
        tenant_id=invitation.record.tenant_id,
        invite_id=invitation.record.invite_id,
        username=invitation.record.username,
        role=invitation.record.role,
        expires_at=invitation.record.expires_at,
        invite_token=invitation.raw_invite_token,
    )


@router.post(
    "/operators/{operator_id}/password-reset-token",
    response_model=OperatorPasswordResetTokenResponse,
    status_code=201,
)
async def create_operator_password_reset_token(
    request: Request,
    operator_id: str,
    payload: OperatorPasswordResetTokenCreateRequest,
) -> OperatorPasswordResetTokenResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.issue_password_reset_token",
    )
    try:
        reset_token = auth_service.create_operator_password_reset_token(
            tenant_id=resolved_tenant_id,
            operator_id=operator_id,
            expires_in=timedelta(minutes=payload.expires_in_minutes),
            created_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return OperatorPasswordResetTokenResponse(
        tenant_id=reset_token.record.tenant_id,
        operator_id=reset_token.record.operator_id,
        reset_id=reset_token.record.reset_id,
        expires_at=reset_token.record.expires_at,
        reset_token=reset_token.raw_reset_token,
    )


@router.post(
    "/operators/invitations/accept",
    response_model=OperatorResponse,
    status_code=201,
)
async def accept_operator_invitation(
    payload: OperatorInvitationAcceptRequest,
) -> OperatorResponse:
    try:
        operator = auth_service.accept_operator_invitation(
            invite_token=payload.invite_token,
            password=payload.password,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.post(
    "/operators/password-reset/complete",
    response_model=OperatorResponse,
)
async def complete_operator_password_reset(
    payload: OperatorPasswordResetCompletionRequest,
) -> OperatorResponse:
    try:
        operator = auth_service.complete_operator_password_reset(
            reset_token=payload.reset_token,
            new_password=payload.new_password,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.patch("/operators/{operator_id}", response_model=OperatorResponse)
async def update_operator_role(
    request: Request,
    operator_id: str,
    payload: OperatorRoleUpdateRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.update_role",
    )
    try:
        auth_service.authorize_operator_role_assignment(
            actor_tenant_id=auth.tenant_id,
            actor_operator_id=auth.operator_id,
            api_key_id=auth.api_key_id,
            target_tenant_id=resolved_tenant_id,
            requested_role=payload.role,
            action="operators.update_role.platform_admin",
        )
        operator = auth_service.change_operator_role(
            tenant_id=resolved_tenant_id,
            operator_id=operator_id,
            role=payload.role,
            changed_by_api_key_id=auth.api_key_id,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None
    return _build_operator_response(operator)


@router.post(
    "/operators/{operator_id}/reset-password",
    response_model=OperatorResponse,
)
async def reset_operator_password(
    request: Request,
    operator_id: str,
    payload: OperatorPasswordResetRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = _authorize_operator_management(
        request,
        target_tenant_id=payload.tenant_id,
        action="operators.reset_password",
    )
    try:
        operator = auth_service.reset_operator_password(
            tenant_id=resolved_tenant_id,
            operator_id=operator_id,
            new_password=payload.new_password,
            reset_by_api_key_id=auth.api_key_id,
            require_password_change=payload.require_password_change,
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
    "/operators/me/complete-password-setup",
    response_model=OperatorResponse,
)
async def complete_password_setup(
    request: Request,
    payload: PasswordSetupCompletionRequest,
) -> OperatorResponse:
    auth = get_authenticated_tenant(request)
    if auth.operator_id is None:
        raise HTTPException(status_code=403, detail="Password setup requires an operator session")
    try:
        operator = auth_service.complete_password_setup(
            tenant_id=auth.tenant_id,
            operator_id=auth.operator_id,
            new_password=payload.new_password,
            completed_by_api_key_id=auth.api_key_id,
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
    actor_operator_id: str | None = Query(default=None, min_length=1),
    target_operator_id: str | None = Query(default=None, min_length=1),
    event_type: Annotated[list[str] | None, Query()] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditEventResponse]:
    authorization = _authorize_audit_read(request, tenant_id=tenant_id)
    events = audit_service.list_events(
        tenant_id=authorization.tenant_id,
        actor_operator_id=actor_operator_id,
        target_operator_id=target_operator_id,
        event_types=event_type,
        created_from=created_from,
        created_to=created_to,
        include_administrative=authorization.include_administrative,
        limit=limit,
    )
    return [_build_audit_event_response(event) for event in events]


@router.get("/admin/kpis/operational", response_model=OperationalKPIResponse)
async def get_operational_kpis(
    request: Request,
    tenant_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> OperationalKPIResponse:
    resolved_tenant_id = _authorize_operational_kpi_read(
        request,
        tenant_id=tenant_id,
    )
    if (
        created_from is not None
        and created_to is not None
        and created_from > created_to
    ):
        raise HTTPException(
            status_code=400,
            detail="created_from must be before or equal to created_to",
        )
    snapshot = operational_kpi_service.collect(
        tenant_id=resolved_tenant_id,
        created_from=created_from,
        created_to=created_to,
    )
    return _build_operational_kpi_response(snapshot)


@router.get("/retention/plan", response_model=RetentionRunResponse)
async def inspect_retention_cleanup(
    request: Request,
    tenant_id: str | None = None,
) -> RetentionRunResponse:
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        policy = RetentionPolicy.from_env()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    result = retention_service.inspect(
        tenant_id=resolved_tenant_id,
        policy=policy,
    )
    return _build_retention_run_response(result)


@router.post("/retention/cleanup", response_model=RetentionRunResponse)
async def run_retention_cleanup(
    request: Request,
    tenant_id: str | None = None,
) -> RetentionRunResponse:
    auth = get_authenticated_tenant(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        policy = RetentionPolicy.from_env()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    result = retention_service.cleanup(
        tenant_id=resolved_tenant_id,
        policy=policy,
        api_key_id=auth.api_key_id,
    )
    return _build_retention_run_response(result)


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
    uploaded_file_name = Path(file.filename or "lote.csv").name or "lote.csv"
    content = await file.read()
    tenant_config = load_tenant_config(resolved_tenant_id)

    try:
        run_upload_preflight(
            file_name=uploaded_file_name,
            content=content,
            tenant_config=tenant_config,
        )
    except UploadPreflightError as exc:
        preflight = _build_upload_preflight_response(exc.result)
        return JSONResponse(
            status_code=400,
            content={
                "detail": exc.detail,
                "preflight": preflight.model_dump(mode="json"),
            },
        )

    try:
        stored_file_name, stored_content = prepare_upload_content_for_job(
            file_name=uploaded_file_name,
            content=content,
            tenant_config=tenant_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    job = job_service.create_job(
        tenant_id=resolved_tenant_id,
        file_name=uploaded_file_name,
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
    file_path.write_bytes(stored_content)

    job.file_path = str(file_path)
    job.file_name = uploaded_file_name
    job_service.save_job(job.job_id)

    _schedule_validation_execution(
        background_tasks=background_tasks,
        job_id=job.job_id,
    )

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
        return get_job_result_payload_with_history(
            job_id,
            job_service,
            audit_service,
        )
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
    auth = get_authenticated_tenant(request)
    try:
        updated_row = update_job_row_with_history(
            job_id,
            job_service,
            audit_service,
            row_index=row_index,
            updates=payload.updates,
            api_key_id=auth.api_key_id,
            actor=_build_request_audit_actor(request),
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
    auth = get_authenticated_tenant(request)
    try:
        update = set_job_row_review_flag_with_history(
            job_id,
            job_service,
            audit_service,
            row_index=row_index,
            status=payload.status,
            api_key_id=auth.api_key_id,
            actor=_build_request_audit_actor(request),
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
    _get_authorized_job(request, job_id)
    auth = get_authenticated_tenant(request)
    normalized_indices = sorted(set(payload.row_indices))
    if payload.keep_row_index not in normalized_indices:
        raise HTTPException(
            status_code=400,
            detail="keep_row_index must be one of the duplicate row_indices",
        )

    try:
        resolution = resolve_duplicate_rows_with_history(
            job_id,
            job_service,
            row_indices=normalized_indices,
            audit_service=audit_service,
            api_key_id=auth.api_key_id,
            actor=_build_request_audit_actor(request),
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


@router.post(
    "/jobs/{job_id}/corrections/{event_id}/revert",
    response_model=CorrectionRevertResponse,
)
async def revert_job_correction_route(
    request: Request,
    job_id: str,
    event_id: str,
) -> CorrectionRevertResponse:
    _get_authorized_job(request, job_id)
    auth = get_authenticated_tenant(request)
    try:
        result = revert_job_correction(
            job_id,
            event_id=event_id,
            job_service=job_service,
            audit_service=audit_service,
            api_key_id=auth.api_key_id,
            actor=_build_request_audit_actor(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CorrectionHistoryConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    return CorrectionRevertResponse(
        job_id=result.job_id,
        reverted_event_id=result.reverted_event_id,
        revert_event_id=result.revert_event_id,
        action=result.action.value,
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

    _schedule_validation_execution(
        background_tasks=background_tasks,
        job_id=new_job.job_id,
    )

    return UploadResponse(
        job_id=new_job.job_id,
        status=new_job.status.value,
        tenant_id=new_job.tenant_id,
        validation_scope=_get_job_validation_scope_value(new_job),
    )
