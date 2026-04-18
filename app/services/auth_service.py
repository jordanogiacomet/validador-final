from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.audit import AuditEventType
from app.core.tenant_config import (
    DEFAULT_ISSUED_API_KEY_TTL_SECONDS,
    OperatorConfig,
    TenantConfig,
)
from app.core.tenant_loader import list_tenants, load_tenant_config

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"

if TYPE_CHECKING:
    from app.services.audit_service import AuditService


class AuthServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class IssuedAPIKeyRecord(BaseModel):
    key_id: str = Field(default_factory=lambda: f"issued-{uuid4().hex}")
    tenant_id: str
    operator_id: str
    username: str
    key_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    issued_ttl_seconds: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    expired_at: datetime | None = None


@dataclass(frozen=True)
class IssuedAPIKey:
    raw_api_key: str
    record: IssuedAPIKeyRecord


@dataclass(frozen=True)
class ResolvedAPIKey:
    tenant_id: str
    api_key_id: str
    operator_id: str | None = None


class IssuedAPIKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    MISSING = "missing"


@dataclass(frozen=True)
class IssuedAPIKeyResolution:
    status: IssuedAPIKeyStatus
    resolved_api_key: ResolvedAPIKey | None = None
    detail: str = "Invalid API key"


def hash_api_key(raw_api_key: str) -> str:
    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_value, salt, expected_digest = password_hash.split("$", 3)
        iterations = int(iterations_value)
    except ValueError:
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM or iterations <= 0:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(digest, expected_digest)


class AuthService:
    def __init__(
        self,
        storage_path: Path | str | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._audit_service = audit_service
        self._records: dict[str, IssuedAPIKeyRecord] = {}
        self._load_records()

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

    def set_audit_service(self, audit_service: AuditService | None) -> None:
        self._audit_service = audit_service

    def issue_api_key(
        self,
        *,
        tenant_id: str,
        username: str,
        password: str,
    ) -> IssuedAPIKey:
        normalized_tenant_id = tenant_id.strip()
        normalized_username = username.strip()
        tenant = self._load_tenant_for_login(normalized_tenant_id)
        operator = self._find_operator(tenant, normalized_username)

        if operator is None:
            if self._operator_exists_for_other_tenant(
                normalized_username,
                normalized_tenant_id,
            ):
                raise AuthServiceError(403, "Operator is not allowed for this tenant")
            raise AuthServiceError(401, "Invalid credentials")

        if operator.disabled:
            raise AuthServiceError(403, "Operator is disabled")

        if not verify_password(password, operator.password_hash):
            raise AuthServiceError(401, "Invalid credentials")

        issued_ttl_seconds = tenant.auth.issued_api_key_ttl_seconds
        created_at = datetime.now(UTC)
        raw_api_key = f"vapi_{secrets.token_urlsafe(32)}"
        record = IssuedAPIKeyRecord(
            tenant_id=tenant.tenant_id,
            operator_id=operator.operator_id,
            username=operator.username,
            key_hash=hash_api_key(raw_api_key),
            created_at=created_at,
            issued_ttl_seconds=issued_ttl_seconds,
            expires_at=created_at + timedelta(seconds=issued_ttl_seconds),
        )
        self._records[record.key_id] = record
        self._persist_records()
        self._record_audit_event(
            AuditEventType.API_KEY_ISSUED,
            record,
            details={
                "operator_id": record.operator_id,
                "username": record.username,
                "issued_ttl_seconds": issued_ttl_seconds,
                "expires_at": record.expires_at.isoformat()
                if record.expires_at is not None
                else None,
            },
        )
        return IssuedAPIKey(raw_api_key=raw_api_key, record=record)

    def resolve_api_key(self, raw_api_key: str) -> ResolvedAPIKey | None:
        resolution = self.inspect_issued_api_key(raw_api_key)
        return resolution.resolved_api_key

    def inspect_issued_api_key(
        self,
        raw_api_key: str,
        *,
        now: datetime | None = None,
    ) -> IssuedAPIKeyResolution:
        api_key_hash = hash_api_key(raw_api_key.strip())
        record = self._find_record_by_hash(api_key_hash)
        if record is None:
            return IssuedAPIKeyResolution(status=IssuedAPIKeyStatus.MISSING)

        if self._backfill_record_expiration(record):
            self._persist_records()

        if record.revoked_at is not None:
            return IssuedAPIKeyResolution(
                status=IssuedAPIKeyStatus.REVOKED,
                detail="Revoked API key",
            )

        current_time = now or datetime.now(UTC)
        if record.expires_at is not None and current_time >= record.expires_at:
            self._mark_record_expired(record, current_time)
            return IssuedAPIKeyResolution(
                status=IssuedAPIKeyStatus.EXPIRED,
                detail="Expired API key",
            )

        return IssuedAPIKeyResolution(
            status=IssuedAPIKeyStatus.ACTIVE,
            resolved_api_key=ResolvedAPIKey(
                tenant_id=record.tenant_id,
                api_key_id=record.key_id,
                operator_id=record.operator_id,
            ),
            detail="Active API key",
        )

    def renew_api_key(
        self,
        *,
        tenant_id: str,
        api_key_id: str,
        now: datetime | None = None,
    ) -> IssuedAPIKey:
        record = self._records.get(api_key_id)
        if record is None or record.tenant_id != tenant_id:
            raise AuthServiceError(404, "Issued API key not found")

        current_time = now or datetime.now(UTC)
        if record.revoked_at is not None:
            raise AuthServiceError(401, "Revoked API key")

        self._backfill_record_expiration(record)
        if record.expires_at is not None and current_time >= record.expires_at:
            self._mark_record_expired(record, current_time)
            raise AuthServiceError(401, "Expired API key")

        issued_ttl_seconds = self._get_tenant_ttl_seconds(record.tenant_id)
        new_raw_api_key = f"vapi_{secrets.token_urlsafe(32)}"
        new_record = IssuedAPIKeyRecord(
            tenant_id=record.tenant_id,
            operator_id=record.operator_id,
            username=record.username,
            key_hash=hash_api_key(new_raw_api_key),
            created_at=current_time,
            issued_ttl_seconds=issued_ttl_seconds,
            expires_at=current_time + timedelta(seconds=issued_ttl_seconds),
        )
        record.revoked_at = current_time

        self._records[new_record.key_id] = new_record
        self._persist_records()

        self._record_audit_event(
            AuditEventType.API_KEY_RENEWED,
            record,
            details={
                "successor_api_key_id": new_record.key_id,
                "renewed_at": current_time.isoformat(),
                "operator_id": record.operator_id,
                "expires_at": new_record.expires_at.isoformat()
                if new_record.expires_at is not None
                else None,
            },
        )

        return IssuedAPIKey(raw_api_key=new_raw_api_key, record=new_record)

    def revoke_api_key(
        self,
        *,
        tenant_id: str,
        api_key_id: str,
        revoked_by_api_key_id: str | None = None,
        now: datetime | None = None,
    ) -> IssuedAPIKeyRecord:
        record = self._records.get(api_key_id)
        if record is None or record.tenant_id != tenant_id:
            raise AuthServiceError(404, "Issued API key not found")

        persist_required = self._backfill_record_expiration(record)
        new_revocation = False
        if record.revoked_at is None:
            record.revoked_at = now or datetime.now(UTC)
            persist_required = True
            new_revocation = True

        if persist_required:
            self._persist_records()

        if new_revocation and record.revoked_at is not None:
            self._record_audit_event(
                AuditEventType.API_KEY_REVOKED,
                record,
                details={
                    "revoked_at": record.revoked_at.isoformat(),
                    "revoked_by_api_key_id": revoked_by_api_key_id,
                    "actor": (
                        "self"
                        if revoked_by_api_key_id == api_key_id
                        else "tenant_operator"
                    ),
                },
            )

        return record

    def clear(self) -> None:
        self._records.clear()
        self._persist_records()

    def list_records(self) -> list[IssuedAPIKeyRecord]:
        return sorted(self._records.values(), key=lambda item: item.created_at)

    def _load_tenant_for_login(self, tenant_id: str) -> TenantConfig:
        try:
            return load_tenant_config(tenant_id)
        except FileNotFoundError as exc:
            raise AuthServiceError(404, "Tenant not found") from exc

    def _operator_exists_for_other_tenant(
        self,
        username: str,
        requested_tenant_id: str,
    ) -> bool:
        for tenant_id in list_tenants():
            if tenant_id == requested_tenant_id:
                continue
            try:
                tenant = load_tenant_config(tenant_id)
            except FileNotFoundError:
                continue
            if self._find_operator(tenant, username) is not None:
                return True
        return False

    @staticmethod
    def _find_operator(
        tenant: TenantConfig,
        username: str,
    ) -> OperatorConfig | None:
        return next(
            (operator for operator in tenant.operators if operator.username == username),
            None,
        )

    def _load_records(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return

        payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Auth key storage payload must be a list")

        self._records = {}
        updated = False
        for item in payload:
            record = IssuedAPIKeyRecord.model_validate(item)
            updated = self._backfill_record_expiration(record) or updated
            self._records[record.key_id] = record

        if updated:
            self._persist_records()

    def _persist_records(self) -> None:
        if self._storage_path is None:
            return

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            record.model_dump(mode="json")
            for record in sorted(self._records.values(), key=lambda item: item.created_at)
        ]
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)

    def _find_record_by_hash(self, api_key_hash: str) -> IssuedAPIKeyRecord | None:
        return next(
            (
                record
                for record in self._records.values()
                if hmac.compare_digest(record.key_hash, api_key_hash)
            ),
            None,
        )

    def _backfill_record_expiration(self, record: IssuedAPIKeyRecord) -> bool:
        ttl_seconds = record.issued_ttl_seconds or self._get_tenant_ttl_seconds(
            record.tenant_id
        )
        expires_at = record.expires_at or (
            record.created_at + timedelta(seconds=ttl_seconds)
        )

        updated = False
        if record.issued_ttl_seconds != ttl_seconds:
            record.issued_ttl_seconds = ttl_seconds
            updated = True
        if record.expires_at != expires_at:
            record.expires_at = expires_at
            updated = True
        return updated

    def _get_tenant_ttl_seconds(self, tenant_id: str) -> int:
        try:
            tenant = load_tenant_config(tenant_id)
        except FileNotFoundError:
            return DEFAULT_ISSUED_API_KEY_TTL_SECONDS
        return tenant.auth.issued_api_key_ttl_seconds

    def _mark_record_expired(
        self,
        record: IssuedAPIKeyRecord,
        current_time: datetime,
    ) -> None:
        if record.expired_at is not None:
            return

        record.expired_at = current_time
        self._persist_records()
        self._record_audit_event(
            AuditEventType.API_KEY_EXPIRED,
            record,
            details={
                "expired_at": current_time.isoformat(),
                "expires_at": record.expires_at.isoformat()
                if record.expires_at is not None
                else None,
            },
        )

    def _record_audit_event(
        self,
        event_type: AuditEventType,
        record: IssuedAPIKeyRecord,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._audit_service is None:
            return

        self._audit_service.record_event(
            event_type,
            tenant_id=record.tenant_id,
            api_key_id=record.key_id,
            details=details,
        )
