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
    API_KEY_ISSUED = "api_key_issued"
    API_KEY_EXPIRED = "api_key_expired"
    API_KEY_REVOKED = "api_key_revoked"
    API_KEY_RENEWED = "api_key_renewed"
    OPERATOR_CREATED = "operator_created"
    OPERATOR_DISABLED = "operator_disabled"
    OPERATOR_PASSWORD_ROTATED = "operator_password_rotated"


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: AuditEventType
    tenant_id: str
    job_id: str | None = None
    api_key_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)
