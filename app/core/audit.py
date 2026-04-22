from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditEventType(StrEnum):
    JOB_CREATED = "job_created"
    JOB_COMPLETED = "job_completed"
    JOB_REPROCESSED = "job_reprocessed"
    JOB_ROW_UPDATED = "job_row_updated"
    JOB_REVIEW_FLAG_UPDATED = "job_review_flag_updated"
    DUPLICATES_RESOLVED = "duplicates_resolved"
    JOB_CORRECTION_REVERTED = "job_correction_reverted"
    ARTIFACT_RETENTION_RUN = "artifact_retention_run"
    AUTH_LOGIN_FAILED = "auth_login_failed"
    LEGACY_API_KEY_REJECTED = "legacy_api_key_rejected"
    INITIAL_SETUP_FAILED = "initial_setup_failed"
    ADMIN_LOGIN_SUCCEEDED = "admin_login_succeeded"
    API_KEY_ISSUED = "api_key_issued"
    API_KEY_EXPIRED = "api_key_expired"
    API_KEY_REVOKED = "api_key_revoked"
    API_KEY_RENEWED = "api_key_renewed"
    INITIAL_ADMIN_CREATED = "initial_admin_created"
    OPERATOR_CREATED = "operator_created"
    OPERATOR_INVITED = "operator_invited"
    OPERATOR_INVITE_ACCEPTED = "operator_invite_accepted"
    OPERATOR_DISABLED = "operator_disabled"
    OPERATOR_PASSWORD_RESET = "operator_password_reset"
    OPERATOR_PASSWORD_RESET_TOKEN_ISSUED = "operator_password_reset_token_issued"
    OPERATOR_PASSWORD_RESET_COMPLETED = "operator_password_reset_completed"
    OPERATOR_PASSWORD_RESET_FAILED = "operator_password_reset_failed"
    OPERATOR_PASSWORD_ROTATED = "operator_password_rotated"
    OPERATOR_ROLE_CHANGED = "operator_role_changed"
    TENANT_CREATED = "tenant_created"
    TENANT_UPDATED = "tenant_updated"
    TENANT_DISABLED = "tenant_disabled"
    TENANT_REACTIVATED = "tenant_reactivated"
    TENANT_PROFILE_DRAFT_SAVED = "tenant_profile_draft_saved"
    TENANT_PROFILE_PUBLISHED = "tenant_profile_published"
    TENANT_PROFILE_ROLLED_BACK = "tenant_profile_rolled_back"
    AUTHORIZATION_DENIED = "authorization_denied"


class AuditEventResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True)
class AuditPrincipal:
    tenant_id: str | None = None
    operator_id: str | None = None
    username: str | None = None
    role: str | None = None


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: AuditEventType
    tenant_id: str
    job_id: str | None = None
    api_key_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)


ADMINISTRATIVE_AUDIT_EVENT_TYPES = frozenset(
    {
        AuditEventType.AUTH_LOGIN_FAILED,
        AuditEventType.LEGACY_API_KEY_REJECTED,
        AuditEventType.INITIAL_SETUP_FAILED,
        AuditEventType.ADMIN_LOGIN_SUCCEEDED,
        AuditEventType.INITIAL_ADMIN_CREATED,
        AuditEventType.OPERATOR_CREATED,
        AuditEventType.OPERATOR_INVITED,
        AuditEventType.OPERATOR_INVITE_ACCEPTED,
        AuditEventType.OPERATOR_DISABLED,
        AuditEventType.OPERATOR_PASSWORD_RESET,
        AuditEventType.OPERATOR_PASSWORD_RESET_TOKEN_ISSUED,
        AuditEventType.OPERATOR_PASSWORD_RESET_COMPLETED,
        AuditEventType.OPERATOR_PASSWORD_RESET_FAILED,
        AuditEventType.OPERATOR_PASSWORD_ROTATED,
        AuditEventType.OPERATOR_ROLE_CHANGED,
        AuditEventType.TENANT_CREATED,
        AuditEventType.TENANT_UPDATED,
        AuditEventType.TENANT_DISABLED,
        AuditEventType.TENANT_REACTIVATED,
        AuditEventType.TENANT_PROFILE_DRAFT_SAVED,
        AuditEventType.TENANT_PROFILE_PUBLISHED,
        AuditEventType.TENANT_PROFILE_ROLLED_BACK,
        AuditEventType.AUTHORIZATION_DENIED,
    }
)

_SAFE_AUDIT_DETAIL_KEYS = frozenset(
    {
        "completed_password_setup",
        "must_change_password",
        "require_password_change",
        "requires_setup_token",
        "setup_token_required",
    }
)


def is_administrative_audit_event(event: AuditEvent) -> bool:
    return event.event_type in ADMINISTRATIVE_AUDIT_EVENT_TYPES


def build_audit_principal_details(
    *,
    actor: AuditPrincipal | None = None,
    target: AuditPrincipal | None = None,
    result: AuditEventResult | str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(extra or {})
    _append_principal_details(payload, prefix="actor", principal=actor)
    _append_principal_details(payload, prefix="target", principal=target)
    if result is not None:
        payload["result"] = (
            result.value if isinstance(result, AuditEventResult) else str(result)
        )
    return payload


def sanitize_audit_details(details: dict[str, Any] | None) -> dict[str, Any]:
    return _sanitize_audit_value(details or {})


def _append_principal_details(
    payload: dict[str, Any],
    *,
    prefix: str,
    principal: AuditPrincipal | None,
) -> None:
    if principal is None:
        return

    payload[f"{prefix}_tenant_id"] = principal.tenant_id
    payload[f"{prefix}_operator_id"] = principal.operator_id
    payload[f"{prefix}_username"] = principal.username
    payload[f"{prefix}_role"] = principal.role


def _sanitize_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if _is_sensitive_audit_key(key)
                else _sanitize_audit_value(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [_sanitize_audit_value(item) for item in value]

    return value


def _is_sensitive_audit_key(key: str) -> bool:
    normalized_key = key.strip().casefold().replace("-", "_")

    if not normalized_key:
        return False

    if normalized_key in _SAFE_AUDIT_DETAIL_KEYS:
        return False

    if normalized_key.endswith("_id") or normalized_key.endswith("_ids"):
        return False

    if normalized_key.endswith("_required"):
        return False

    return (
        normalized_key in {"password", "token", "secret", "api_key", "x_api_key"}
        or normalized_key.endswith("_password")
        or normalized_key.endswith("_token")
        or normalized_key.endswith("_hash")
        or normalized_key.endswith("_secret")
        or "password" in normalized_key
        or "secret" in normalized_key
        or normalized_key in {"raw_api_key", "key_hash", "token_hash"}
    )
