from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditEventType(StrEnum):
    JOB_CREATED = "job_created"
    JOB_COMPLETED = "job_completed"
    JOB_REPROCESSED = "job_reprocessed"
    DUPLICATES_RESOLVED = "duplicates_resolved"
    AUTH_LOGIN_FAILED = "auth_login_failed"
    INITIAL_SETUP_FAILED = "initial_setup_failed"
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
    AUTHORIZATION_DENIED = "authorization_denied"


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: AuditEventType
    tenant_id: str
    job_id: str | None = None
    api_key_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)
