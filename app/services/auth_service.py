from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.tenant_config import OperatorConfig, TenantConfig
from app.core.tenant_loader import list_tenants, load_tenant_config

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"


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
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class IssuedAPIKey:
    raw_api_key: str
    record: IssuedAPIKeyRecord


@dataclass(frozen=True)
class ResolvedAPIKey:
    tenant_id: str
    api_key_id: str
    operator_id: str | None = None


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
    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._storage_path = Path(storage_path) if storage_path is not None else None
        self._records: dict[str, IssuedAPIKeyRecord] = {}
        self._load_records()

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

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

        raw_api_key = f"vapi_{secrets.token_urlsafe(32)}"
        record = IssuedAPIKeyRecord(
            tenant_id=tenant.tenant_id,
            operator_id=operator.operator_id,
            username=operator.username,
            key_hash=hash_api_key(raw_api_key),
        )
        self._records[record.key_id] = record
        self._persist_records()
        return IssuedAPIKey(raw_api_key=raw_api_key, record=record)

    def resolve_api_key(self, raw_api_key: str) -> ResolvedAPIKey | None:
        api_key_hash = hash_api_key(raw_api_key.strip())
        for record in self._records.values():
            if record.revoked_at is not None:
                continue
            if hmac.compare_digest(record.key_hash, api_key_hash):
                return ResolvedAPIKey(
                    tenant_id=record.tenant_id,
                    api_key_id=record.key_id,
                    operator_id=record.operator_id,
                )
        return None

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
        for item in payload:
            record = IssuedAPIKeyRecord.model_validate(item)
            self._records[record.key_id] = record

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
