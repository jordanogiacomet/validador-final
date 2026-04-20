from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.audit import AuditEventType
from app.core.operational_sqlite import (
    OperationalSQLiteStore,
    resolve_operational_sqlite_path,
)
from app.core.tenant_config import (
    DEFAULT_ISSUED_API_KEY_TTL_SECONDS,
    DEFAULT_TENANT_ID,
    OperatorConfig,
    OperatorRole,
    TenantConfig,
)
from app.core.tenant_loader import (
    TenantDisabledError,
    canonicalize_tenant_id,
    list_tenants,
    load_tenant_config,
    tenant_ids_match,
)

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 120_000
DEFAULT_OPERATOR_INVITE_TTL_HOURS = 48
OFFICIAL_TENANT_ID_ENV = "VALIDATOR_OFFICIAL_TENANT_ID"
BOOTSTRAP_ADMIN_USERNAME_ENV = "VALIDATOR_BOOTSTRAP_ADMIN_USERNAME"
BOOTSTRAP_ADMIN_PASSWORD_ENV = "VALIDATOR_BOOTSTRAP_ADMIN_PASSWORD"
BOOTSTRAP_ADMIN_FORCE_RESET_ENV = "VALIDATOR_BOOTSTRAP_ADMIN_FORCE_RESET"
INITIAL_SETUP_TOKEN_ENV = "VALIDATOR_SETUP_TOKEN"

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
    role: OperatorRole = OperatorRole.OPERATOR
    key_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    issued_ttl_seconds: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    expired_at: datetime | None = None


class StoredOperatorRecord(BaseModel):
    tenant_id: str
    operator_id: str
    username: str
    password_hash: str
    role: OperatorRole = OperatorRole.OPERATOR
    disabled: bool = False
    must_change_password: bool = False


class OperatorInvitationRecord(BaseModel):
    invite_id: str = Field(default_factory=lambda: f"invite-{uuid4().hex}")
    tenant_id: str
    username: str
    role: OperatorRole = OperatorRole.OPERATOR
    token_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    created_by_api_key_id: str | None = None
    used_at: datetime | None = None
    accepted_operator_id: str | None = None


@dataclass(frozen=True)
class EffectiveOperator:
    tenant_id: str
    operator_id: str
    username: str
    password_hash: str
    role: OperatorRole
    disabled: bool
    must_change_password: bool
    is_seed: bool


@dataclass(frozen=True)
class IssuedAPIKey:
    raw_api_key: str
    record: IssuedAPIKeyRecord
    must_change_password: bool = False


@dataclass(frozen=True)
class OperatorInvitation:
    raw_invite_token: str
    record: OperatorInvitationRecord


@dataclass(frozen=True)
class ResolvedAPIKey:
    tenant_id: str
    api_key_id: str
    operator_id: str | None = None
    role: OperatorRole | None = None


@dataclass(frozen=True)
class BootstrapAdminConfig:
    tenant_id: str
    username: str
    password: str
    force_password_reset: bool = False


@dataclass(frozen=True)
class InitialSetupState:
    available: bool
    storage_configured: bool
    requires_setup_token: bool
    tenant_id: str | None = None


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


def _derive_invite_storage_path(operator_storage_path: Path) -> Path:
    return operator_storage_path.with_name(
        f"{operator_storage_path.stem}.invites{operator_storage_path.suffix}"
    )


def hash_password(
    password: str,
    *,
    salt: str | None = None,
    iterations: int = PASSWORD_HASH_ITERATIONS,
) -> str:
    normalized_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        normalized_salt.encode("utf-8"),
        iterations,
    ).hex()
    return (
        f"{PASSWORD_HASH_ALGORITHM}${iterations}${normalized_salt}${digest}"
    )


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


def _parse_env_bool(raw_value: str) -> bool:
    return raw_value.strip().casefold() in {"1", "true", "yes", "on"}


def load_bootstrap_admin_config_from_env(
    env: Mapping[str, str] | None = None,
) -> BootstrapAdminConfig | None:
    environment = os.environ if env is None else env
    username = environment.get(BOOTSTRAP_ADMIN_USERNAME_ENV, "").strip()
    password = environment.get(BOOTSTRAP_ADMIN_PASSWORD_ENV, "")

    if not username and not password:
        return None

    if not username or not password:
        raise ValueError(
            "Bootstrap admin requires both "
            f"{BOOTSTRAP_ADMIN_USERNAME_ENV} and {BOOTSTRAP_ADMIN_PASSWORD_ENV}"
        )

    tenant_id = environment.get(OFFICIAL_TENANT_ID_ENV, "").strip()
    if not tenant_id:
        raise ValueError(
            "Bootstrap admin requires "
            f"{OFFICIAL_TENANT_ID_ENV} to identify the official tenant"
        )

    return BootstrapAdminConfig(
        tenant_id=tenant_id,
        username=username,
        password=password,
        force_password_reset=_parse_env_bool(
            environment.get(BOOTSTRAP_ADMIN_FORCE_RESET_ENV, "")
        ),
    )


class AuthService:
    def __init__(
        self,
        storage_path: Path | str | None = None,
        operator_storage_path: Path | str | None = None,
        invite_storage_path: Path | str | None = None,
        sqlite_path: Path | str | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        resolved_sqlite_path = resolve_operational_sqlite_path(
            sqlite_path,
            storage_path,
            operator_storage_path,
            invite_storage_path,
        )
        self._sqlite_store = (
            OperationalSQLiteStore(resolved_sqlite_path)
            if resolved_sqlite_path is not None
            else None
        )
        self._storage_path = (
            resolved_sqlite_path
            if resolved_sqlite_path is not None
            else Path(storage_path)
            if storage_path is not None
            else None
        )
        self._operator_storage_path = (
            resolved_sqlite_path
            if resolved_sqlite_path is not None
            else Path(operator_storage_path)
            if operator_storage_path is not None
            else None
        )
        self._invite_storage_path = (
            resolved_sqlite_path
            if resolved_sqlite_path is not None
            else Path(invite_storage_path)
            if invite_storage_path is not None
            else None
        )
        self._audit_service = audit_service
        self._records: dict[str, IssuedAPIKeyRecord] = {}
        self._operator_records: dict[tuple[str, str], StoredOperatorRecord] = {}
        self._invite_records: dict[str, OperatorInvitationRecord] = {}
        self._initial_setup_lock = Lock()
        self._load_records()
        self._load_operator_records()
        self._load_invite_records()

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

    @property
    def operator_storage_path(self) -> Path | None:
        return self._operator_storage_path

    @property
    def invite_storage_path(self) -> Path | None:
        return self._resolve_invite_storage_path()

    def set_audit_service(self, audit_service: AuditService | None) -> None:
        self._audit_service = audit_service

    def list_operators(self, *, tenant_id: str) -> list[EffectiveOperator]:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        self._load_tenant_for_login(normalized_tenant_id)
        return self._list_effective_operators(normalized_tenant_id)

    def get_operator(
        self,
        *,
        tenant_id: str,
        operator_id: str,
    ) -> EffectiveOperator | None:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        self._load_tenant_for_login(normalized_tenant_id)
        return self._find_operator_by_id(normalized_tenant_id, operator_id)

    def get_operator_role(
        self,
        *,
        tenant_id: str,
        operator_id: str | None,
    ) -> OperatorRole:
        if operator_id is None:
            return OperatorRole.OPERATOR

        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        operator = self._find_operator_by_id(normalized_tenant_id, operator_id)
        if operator is None or operator.disabled:
            return OperatorRole.OPERATOR
        return operator.role

    def authorize_operator_management(
        self,
        *,
        actor_tenant_id: str,
        actor_operator_id: str | None,
        api_key_id: str | None,
        target_tenant_id: str,
        action: str,
    ) -> str:
        normalized_actor_tenant_id = canonicalize_tenant_id(actor_tenant_id)
        normalized_target_tenant_id = canonicalize_tenant_id(target_tenant_id)
        actor = (
            self._find_operator_by_id(normalized_actor_tenant_id, actor_operator_id)
            if actor_operator_id is not None
            else None
        )

        if actor is not None and not actor.disabled:
            if actor.role is OperatorRole.PLATFORM_ADMIN:
                return normalized_target_tenant_id

            if actor.role is OperatorRole.TENANT_ADMIN and tenant_ids_match(
                normalized_actor_tenant_id,
                normalized_target_tenant_id,
            ):
                return normalized_target_tenant_id

        self._record_authorization_denied_event(
            tenant_id=normalized_actor_tenant_id,
            api_key_id=api_key_id,
            action=action,
            target_tenant_id=normalized_target_tenant_id,
            operator=actor,
        )
        raise AuthServiceError(403, "Operator is not allowed to manage this tenant")

    def authorize_tenant_administration(
        self,
        *,
        actor_tenant_id: str,
        actor_operator_id: str | None,
        api_key_id: str | None,
        action: str,
        target_tenant_id: str | None = None,
    ) -> None:
        normalized_actor_tenant_id = canonicalize_tenant_id(actor_tenant_id)
        normalized_target_tenant_id = (
            canonicalize_tenant_id(target_tenant_id)
            if target_tenant_id is not None
            else normalized_actor_tenant_id
        )
        actor = (
            self._find_operator_by_id(normalized_actor_tenant_id, actor_operator_id)
            if actor_operator_id is not None
            else None
        )

        if (
            actor is not None
            and not actor.disabled
            and actor.role is OperatorRole.PLATFORM_ADMIN
        ):
            return

        self._record_authorization_denied_event(
            tenant_id=normalized_actor_tenant_id,
            api_key_id=api_key_id,
            action=action,
            target_tenant_id=normalized_target_tenant_id,
            operator=actor,
        )
        raise AuthServiceError(403, "Only platform_admin can manage tenants")

    def authorize_operator_role_assignment(
        self,
        *,
        actor_tenant_id: str,
        actor_operator_id: str | None,
        api_key_id: str | None,
        target_tenant_id: str,
        requested_role: OperatorRole,
        action: str = "operators.create.platform_admin",
    ) -> None:
        if requested_role is not OperatorRole.PLATFORM_ADMIN:
            return

        normalized_actor_tenant_id = canonicalize_tenant_id(actor_tenant_id)
        normalized_target_tenant_id = canonicalize_tenant_id(target_tenant_id)
        actor = (
            self._find_operator_by_id(normalized_actor_tenant_id, actor_operator_id)
            if actor_operator_id is not None
            else None
        )
        if (
            actor is not None
            and not actor.disabled
            and actor.role is OperatorRole.PLATFORM_ADMIN
        ):
            return

        self._record_authorization_denied_event(
            tenant_id=normalized_actor_tenant_id,
            api_key_id=api_key_id,
            action=action,
            target_tenant_id=normalized_target_tenant_id,
            operator=actor,
        )
        raise AuthServiceError(
            403,
            "Only platform_admin can create platform administrators",
        )

    def bootstrap_admin_from_env(
        self,
        *,
        env: Mapping[str, str] | None = None,
    ) -> EffectiveOperator | None:
        config = load_bootstrap_admin_config_from_env(env)
        if config is None:
            return None
        return self.ensure_bootstrap_admin(config)

    def get_initial_setup_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
    ) -> InitialSetupState:
        environment = os.environ if env is None else env
        storage_configured = self._operator_storage_path is not None
        requires_setup_token = bool(environment.get(INITIAL_SETUP_TOKEN_ENV, "").strip())

        if not storage_configured:
            return InitialSetupState(
                available=False,
                storage_configured=False,
                requires_setup_token=requires_setup_token,
            )

        self._load_operator_records()
        if self._has_persisted_operator_records():
            return InitialSetupState(
                available=False,
                storage_configured=True,
                requires_setup_token=requires_setup_token,
            )

        tenant_id = self._resolve_initial_setup_tenant_id(environment)
        try:
            self._load_tenant_for_login(tenant_id)
        except AuthServiceError:
            return InitialSetupState(
                available=False,
                storage_configured=True,
                requires_setup_token=requires_setup_token,
            )

        return InitialSetupState(
            available=True,
            storage_configured=True,
            requires_setup_token=requires_setup_token,
            tenant_id=tenant_id,
        )

    def create_initial_admin(
        self,
        *,
        username: str,
        password: str,
        setup_token: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> EffectiveOperator:
        if self._operator_storage_path is None:
            raise AuthServiceError(
                503,
                "Initial setup requires persistent operator storage",
            )

        environment = os.environ if env is None else env
        expected_setup_token = environment.get(INITIAL_SETUP_TOKEN_ENV, "").strip()
        if expected_setup_token and not (
            setup_token
            and hmac.compare_digest(setup_token.strip(), expected_setup_token)
        ):
            raise AuthServiceError(403, "Invalid setup token")

        normalized_tenant_id = self._resolve_initial_setup_tenant_id(environment)
        normalized_username = username.strip()
        self._load_tenant_for_login(normalized_tenant_id)

        with self._initial_setup_lock:
            self._load_operator_records()
            if self._has_persisted_operator_records():
                raise AuthServiceError(409, "Initial setup is no longer available")

            if self._find_operator_by_username(normalized_tenant_id, normalized_username):
                raise AuthServiceError(409, "Operator username already exists")

            record = StoredOperatorRecord(
                tenant_id=normalized_tenant_id,
                operator_id=f"operator-{uuid4().hex}",
                username=normalized_username,
                password_hash=hash_password(password),
                role=OperatorRole.PLATFORM_ADMIN,
            )
            operator = self._persist_initial_admin_record(record)

        self._record_operator_audit_event(
            AuditEventType.INITIAL_ADMIN_CREATED,
            operator=operator,
            api_key_id=None,
            details={
                "initial_setup": True,
                "setup_token_required": bool(expected_setup_token),
            },
        )
        return operator

    def ensure_bootstrap_admin(
        self,
        config: BootstrapAdminConfig,
    ) -> EffectiveOperator:
        if self._operator_storage_path is None:
            raise AuthServiceError(
                500,
                "Bootstrap admin requires persistent operator storage",
            )

        normalized_tenant_id = canonicalize_tenant_id(config.tenant_id)
        normalized_username = config.username.strip()
        self._load_tenant_for_login(normalized_tenant_id)
        existing_operator = self._find_operator_by_username(
            normalized_tenant_id,
            normalized_username,
        )
        if existing_operator is not None:
            if not config.force_password_reset:
                return existing_operator

            updated_operator = self._store_effective_operator(
                existing_operator,
                password_hash=hash_password(config.password),
                must_change_password=False,
            )
            revoked_count = self._revoke_active_keys_for_operator(
                tenant_id=normalized_tenant_id,
                operator_id=existing_operator.operator_id,
            )
            self._record_operator_audit_event(
                AuditEventType.OPERATOR_PASSWORD_ROTATED,
                operator=updated_operator,
                api_key_id=None,
                details={
                    "bootstrap": True,
                    "revoked_api_key_count": revoked_count,
                },
            )
            return updated_operator

        if self._list_effective_operators(normalized_tenant_id):
            raise AuthServiceError(
                409,
                "Bootstrap admin cannot create a first operator for a tenant "
                "that already has operators",
            )

        return self.create_operator(
            tenant_id=normalized_tenant_id,
            username=normalized_username,
            password=config.password,
            role=OperatorRole.PLATFORM_ADMIN,
        )

    def create_operator(
        self,
        *,
        tenant_id: str,
        username: str,
        password: str,
        role: OperatorRole = OperatorRole.OPERATOR,
        created_by_api_key_id: str | None = None,
        require_password_change: bool = False,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        normalized_username = username.strip()
        self._load_tenant_for_login(normalized_tenant_id)
        self._load_operator_records()

        if self._find_operator_by_username(normalized_tenant_id, normalized_username):
            raise AuthServiceError(409, "Operator username already exists")

        record = StoredOperatorRecord(
            tenant_id=normalized_tenant_id,
            operator_id=f"operator-{uuid4().hex}",
            username=normalized_username,
            password_hash=hash_password(password),
            role=role,
            must_change_password=require_password_change,
        )
        self._operator_records[self._operator_record_key(record)] = record
        self._persist_operator_records()

        operator = self._operator_from_record(record, is_seed=False)
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_CREATED,
            operator=operator,
            api_key_id=created_by_api_key_id,
            details={"must_change_password": require_password_change},
        )
        return operator

    def create_operator_invitation(
        self,
        *,
        tenant_id: str,
        username: str,
        role: OperatorRole = OperatorRole.OPERATOR,
        expires_in: timedelta | None = None,
        created_by_api_key_id: str | None = None,
        now: datetime | None = None,
    ) -> OperatorInvitation:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        normalized_username = username.strip()
        self._load_tenant_for_login(normalized_tenant_id)
        self._load_operator_records()
        self._load_invite_records()

        if self._find_operator_by_username(normalized_tenant_id, normalized_username):
            raise AuthServiceError(409, "Operator username already exists")

        current_time = now or datetime.now(UTC)
        if self._find_pending_invitation_by_username(
            normalized_tenant_id,
            normalized_username,
            now=current_time,
        ):
            raise AuthServiceError(409, "Operator invitation already exists")

        ttl = expires_in or timedelta(hours=DEFAULT_OPERATOR_INVITE_TTL_HOURS)
        if ttl <= timedelta(0):
            raise AuthServiceError(400, "Invitation expiration must be greater than zero")

        raw_invite_token = f"vinv_{secrets.token_urlsafe(32)}"
        record = OperatorInvitationRecord(
            tenant_id=normalized_tenant_id,
            username=normalized_username,
            role=role,
            token_hash=hash_api_key(raw_invite_token),
            created_at=current_time,
            expires_at=current_time + ttl,
            created_by_api_key_id=created_by_api_key_id,
        )
        self._invite_records[record.invite_id] = record
        self._persist_invite_records()
        self._record_invitation_audit_event(
            AuditEventType.OPERATOR_INVITED,
            invite=record,
            api_key_id=created_by_api_key_id,
        )
        return OperatorInvitation(raw_invite_token=raw_invite_token, record=record)

    def accept_operator_invitation(
        self,
        *,
        invite_token: str,
        password: str,
        now: datetime | None = None,
    ) -> EffectiveOperator:
        current_time = now or datetime.now(UTC)
        invite = self._find_invitation_by_token(invite_token.strip())
        if invite is None:
            raise AuthServiceError(404, "Invitation token not found")

        if invite.used_at is not None:
            raise AuthServiceError(409, "Invitation token already used")

        if current_time >= invite.expires_at:
            raise AuthServiceError(410, "Invitation token expired")

        normalized_tenant_id = canonicalize_tenant_id(invite.tenant_id)
        self._load_tenant_for_login(normalized_tenant_id)
        self._load_operator_records()
        if self._find_operator_by_username(normalized_tenant_id, invite.username):
            raise AuthServiceError(409, "Operator username already exists")

        operator_record = StoredOperatorRecord(
            tenant_id=normalized_tenant_id,
            operator_id=f"operator-{uuid4().hex}",
            username=invite.username,
            password_hash=hash_password(password),
            role=invite.role,
        )
        self._operator_records[self._operator_record_key(operator_record)] = operator_record
        self._persist_operator_records()

        invite.used_at = current_time
        invite.accepted_operator_id = operator_record.operator_id
        self._persist_invite_records()

        operator = self._operator_from_record(operator_record, is_seed=False)
        self._record_invitation_audit_event(
            AuditEventType.OPERATOR_INVITE_ACCEPTED,
            invite=invite,
            api_key_id=None,
            details={"operator_id": operator.operator_id},
        )
        return operator

    def change_operator_role(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        role: OperatorRole,
        changed_by_api_key_id: str | None = None,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        operator = self._find_operator_by_id(normalized_tenant_id, operator_id)
        if operator is None:
            raise AuthServiceError(404, "Operator not found")

        if operator.role is role:
            return operator

        updated_operator = self._store_effective_operator(
            operator,
            role=role,
        )
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_ROLE_CHANGED,
            operator=updated_operator,
            api_key_id=changed_by_api_key_id,
            details={
                "previous_role": operator.role.value,
                "new_role": role.value,
            },
        )
        return updated_operator

    def reset_operator_password(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        new_password: str,
        reset_by_api_key_id: str | None = None,
        require_password_change: bool = True,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        operator = self._find_operator_by_id(normalized_tenant_id, operator_id)
        if operator is None:
            raise AuthServiceError(404, "Operator not found")

        updated_operator = self._store_effective_operator(
            operator,
            password_hash=hash_password(new_password),
            must_change_password=require_password_change,
        )
        revoked_count = self._revoke_active_keys_for_operator(
            tenant_id=normalized_tenant_id,
            operator_id=operator.operator_id,
            revoked_by_api_key_id=reset_by_api_key_id,
        )
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_PASSWORD_RESET,
            operator=updated_operator,
            api_key_id=reset_by_api_key_id,
            details={
                "require_password_change": require_password_change,
                "revoked_api_key_count": revoked_count,
            },
        )
        return updated_operator

    def complete_password_setup(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        new_password: str,
        completed_by_api_key_id: str | None = None,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        operator = self._find_operator_by_id(normalized_tenant_id, operator_id)
        if operator is None:
            raise AuthServiceError(404, "Operator not found")
        if operator.disabled:
            raise AuthServiceError(403, "Operator is disabled")
        if not operator.must_change_password:
            raise AuthServiceError(409, "Password setup is not required")

        updated_operator = self._store_effective_operator(
            operator,
            password_hash=hash_password(new_password),
            must_change_password=False,
        )
        revoked_count = self._revoke_active_keys_for_operator(
            tenant_id=normalized_tenant_id,
            operator_id=operator.operator_id,
            revoked_by_api_key_id=completed_by_api_key_id,
        )
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_PASSWORD_ROTATED,
            operator=updated_operator,
            api_key_id=completed_by_api_key_id,
            details={
                "completed_password_setup": True,
                "revoked_api_key_count": revoked_count,
            },
        )
        return updated_operator

    def disable_operator(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        disabled_by_api_key_id: str | None = None,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        operator = self._find_operator_by_id(normalized_tenant_id, operator_id)
        if operator is None:
            raise AuthServiceError(404, "Operator not found")

        if operator.disabled:
            return operator

        active_operator_count = sum(
            not candidate.disabled
            for candidate in self._list_effective_operators(normalized_tenant_id)
        )
        if active_operator_count <= 1:
            raise AuthServiceError(409, "Cannot disable the last active operator")

        updated_operator = self._store_effective_operator(
            operator,
            disabled=True,
        )
        revoked_count = self._revoke_active_keys_for_operator(
            tenant_id=normalized_tenant_id,
            operator_id=operator.operator_id,
            revoked_by_api_key_id=disabled_by_api_key_id,
        )
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_DISABLED,
            operator=updated_operator,
            api_key_id=disabled_by_api_key_id,
            details={"revoked_api_key_count": revoked_count},
        )
        return updated_operator

    def rotate_seed_operator_password(
        self,
        *,
        tenant_id: str,
        new_password: str,
        rotated_by_api_key_id: str | None = None,
    ) -> EffectiveOperator:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        seed_operators = [
            operator
            for operator in self._list_effective_operators(normalized_tenant_id)
            if operator.is_seed
        ]
        if not seed_operators:
            raise AuthServiceError(404, "Seed operator not found")
        if len(seed_operators) > 1:
            raise AuthServiceError(
                409,
                "Multiple seed operators configured for tenant",
            )

        updated_operator = self._store_effective_operator(
            seed_operators[0],
            password_hash=hash_password(new_password),
            must_change_password=False,
        )
        revoked_count = self._revoke_active_keys_for_operator(
            tenant_id=normalized_tenant_id,
            operator_id=seed_operators[0].operator_id,
            revoked_by_api_key_id=rotated_by_api_key_id,
        )
        self._record_operator_audit_event(
            AuditEventType.OPERATOR_PASSWORD_ROTATED,
            operator=updated_operator,
            api_key_id=rotated_by_api_key_id,
            details={
                "is_seed": True,
                "revoked_api_key_count": revoked_count,
            },
        )
        return updated_operator

    def issue_api_key(
        self,
        *,
        tenant_id: str,
        username: str,
        password: str,
    ) -> IssuedAPIKey:
        normalized_tenant_id = canonicalize_tenant_id(tenant_id)
        normalized_username = username.strip()
        tenant = self._load_tenant_for_login(normalized_tenant_id)
        operator = self._find_operator_by_username(
            normalized_tenant_id,
            normalized_username,
        )

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
            role=operator.role,
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
                "role": record.role.value,
                "issued_ttl_seconds": issued_ttl_seconds,
                "expires_at": record.expires_at.isoformat()
                if record.expires_at is not None
                else None,
            },
        )
        return IssuedAPIKey(
            raw_api_key=raw_api_key,
            record=record,
            must_change_password=operator.must_change_password,
        )

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
        if record is None and self._storage_path is not None:
            self._load_records()
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
                role=record.role,
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
        resolved_tenant_id = canonicalize_tenant_id(tenant_id)
        record = self._records.get(api_key_id)
        if record is None or record.tenant_id != resolved_tenant_id:
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
            role=self.get_operator_role(
                tenant_id=record.tenant_id,
                operator_id=record.operator_id,
            ),
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

        operator = self._find_operator_by_id(record.tenant_id, record.operator_id)
        return IssuedAPIKey(
            raw_api_key=new_raw_api_key,
            record=new_record,
            must_change_password=operator.must_change_password if operator else False,
        )

    def revoke_api_key(
        self,
        *,
        tenant_id: str,
        api_key_id: str,
        revoked_by_api_key_id: str | None = None,
        now: datetime | None = None,
    ) -> IssuedAPIKeyRecord:
        resolved_tenant_id = canonicalize_tenant_id(tenant_id)
        record = self._records.get(api_key_id)
        if record is None or record.tenant_id != resolved_tenant_id:
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
        self._operator_records.clear()
        self._invite_records.clear()
        self._persist_records()
        self._persist_operator_records()
        self._persist_invite_records()

    def list_records(self) -> list[IssuedAPIKeyRecord]:
        return sorted(self._records.values(), key=lambda item: item.created_at)

    def _load_tenant_for_login(self, tenant_id: str) -> TenantConfig:
        try:
            return load_tenant_config(tenant_id)
        except FileNotFoundError as exc:
            raise AuthServiceError(404, "Tenant not found") from exc
        except TenantDisabledError as exc:
            raise AuthServiceError(403, "Tenant is disabled") from exc

    def _operator_exists_for_other_tenant(
        self,
        username: str,
        requested_tenant_id: str,
    ) -> bool:
        resolved_requested_tenant_id = canonicalize_tenant_id(requested_tenant_id)
        for tenant_id in list_tenants():
            if tenant_id == resolved_requested_tenant_id:
                continue
            try:
                self._load_tenant_for_login(tenant_id)
            except AuthServiceError:
                continue
            if self._find_operator_by_username(tenant_id, username) is not None:
                return True
        return False

    def _find_operator_by_username(
        self,
        tenant_id: str,
        username: str,
    ) -> EffectiveOperator | None:
        return next(
            (
                operator
                for operator in self._list_effective_operators(tenant_id)
                if operator.username == username
            ),
            None,
        )

    def _find_operator_by_id(
        self,
        tenant_id: str,
        operator_id: str,
    ) -> EffectiveOperator | None:
        return next(
            (
                operator
                for operator in self._list_effective_operators(tenant_id)
                if operator.operator_id == operator_id
            ),
            None,
        )

    def _list_effective_operators(self, tenant_id: str) -> list[EffectiveOperator]:
        if self._operator_storage_path is not None:
            self._load_operator_records()

        tenant = self._load_tenant_for_login(tenant_id)
        stored_by_id = {
            record.operator_id: record
            for record in self._operator_records.values()
            if record.tenant_id == tenant_id
        }

        operators: list[EffectiveOperator] = []
        seen_operator_ids: set[str] = set()
        for operator in tenant.operators:
            stored_record = stored_by_id.get(operator.operator_id)
            if stored_record is None:
                operators.append(
                    self._operator_from_config(
                        tenant_id=tenant_id,
                        operator=operator,
                        is_seed=True,
                    )
                )
            else:
                operators.append(
                    self._operator_from_record(stored_record, is_seed=True)
                )
            seen_operator_ids.add(operator.operator_id)

        managed_records = sorted(
            (
                record
                for record in stored_by_id.values()
                if record.operator_id not in seen_operator_ids
            ),
            key=lambda item: (item.username.casefold(), item.operator_id),
        )
        operators.extend(
            self._operator_from_record(record, is_seed=False)
            for record in managed_records
        )
        return operators

    def _persist_initial_admin_record(
        self,
        record: StoredOperatorRecord,
    ) -> EffectiveOperator:
        if self._sqlite_store is not None:
            created = self._sqlite_store.try_insert_first_operator_record(
                record.model_dump(mode="json")
            )
            self._load_operator_records()
            if not created:
                raise AuthServiceError(409, "Initial setup is no longer available")
            return self._operator_from_record(record, is_seed=False)

        self._operator_records[self._operator_record_key(record)] = record
        self._persist_operator_records()
        return self._operator_from_record(record, is_seed=False)

    def _store_effective_operator(
        self,
        operator: EffectiveOperator,
        *,
        password_hash: str | None = None,
        disabled: bool | None = None,
        role: OperatorRole | None = None,
        must_change_password: bool | None = None,
    ) -> EffectiveOperator:
        stored_record = StoredOperatorRecord(
            tenant_id=operator.tenant_id,
            operator_id=operator.operator_id,
            username=operator.username,
            password_hash=password_hash or operator.password_hash,
            role=role or operator.role,
            disabled=operator.disabled if disabled is None else disabled,
            must_change_password=(
                operator.must_change_password
                if must_change_password is None
                else must_change_password
            ),
        )
        self._operator_records[self._operator_record_key(stored_record)] = stored_record
        self._persist_operator_records()
        return self._operator_from_record(stored_record, is_seed=operator.is_seed)

    def _load_records(self) -> None:
        if self._storage_path is None:
            return

        if self._sqlite_store is not None:
            payload = self._sqlite_store.load_issued_api_keys()
        else:
            if not self._storage_path.exists():
                return
            import json

            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Auth key storage payload must be a list")

        self._records = {}
        updated = False
        for item in payload:
            record = IssuedAPIKeyRecord.model_validate(item)
            resolved_tenant_id = canonicalize_tenant_id(record.tenant_id)
            if record.tenant_id != resolved_tenant_id:
                record.tenant_id = resolved_tenant_id
                updated = True
            updated = self._backfill_record_expiration(record) or updated
            self._records[record.key_id] = record

        if updated:
            self._persist_records()

    def _load_operator_records(self) -> None:
        if self._operator_storage_path is None:
            return

        if self._sqlite_store is not None:
            payload = self._sqlite_store.load_operator_records()
        else:
            if not self._operator_storage_path.exists():
                return
            import json

            payload = json.loads(self._operator_storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Operator storage payload must be a list")

        self._operator_records = {}
        updated = False
        payload_items = list(payload)
        for item in payload_items:
            item_payload = dict(item)
            if "role" not in item_payload:
                item_payload["role"] = self._resolve_legacy_operator_role(
                    item_payload,
                    is_only_persisted_operator=len(payload_items) == 1,
                ).value
                updated = True
            record = StoredOperatorRecord.model_validate(item_payload)
            resolved_tenant_id = canonicalize_tenant_id(record.tenant_id)
            if record.tenant_id != resolved_tenant_id:
                record.tenant_id = resolved_tenant_id
                updated = True
            self._operator_records[self._operator_record_key(record)] = record

        if updated:
            self._persist_operator_records()

    def _load_invite_records(self) -> None:
        invite_storage_path = self._resolve_invite_storage_path()
        if invite_storage_path is None:
            return

        if self._sqlite_store is not None:
            payload = self._sqlite_store.load_operator_invites()
        else:
            if not invite_storage_path.exists():
                return
            import json

            payload = json.loads(invite_storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Invite storage payload must be a list")

        self._invite_records = {}
        updated = False
        for item in payload:
            record = OperatorInvitationRecord.model_validate(item)
            resolved_tenant_id = canonicalize_tenant_id(record.tenant_id)
            if record.tenant_id != resolved_tenant_id:
                record.tenant_id = resolved_tenant_id
                updated = True
            self._invite_records[record.invite_id] = record

        if updated:
            self._persist_invite_records()

    def _has_persisted_operator_records(self) -> bool:
        return bool(self._operator_records)

    @staticmethod
    def _resolve_initial_setup_tenant_id(environment: Mapping[str, str]) -> str:
        tenant_id = environment.get(OFFICIAL_TENANT_ID_ENV, "").strip()
        return canonicalize_tenant_id(tenant_id or DEFAULT_TENANT_ID)

    def _resolve_legacy_operator_role(
        self,
        payload: dict[str, object],
        *,
        is_only_persisted_operator: bool,
    ) -> OperatorRole:
        if is_only_persisted_operator:
            return OperatorRole.PLATFORM_ADMIN

        tenant_id = str(payload.get("tenant_id", "")).strip()
        operator_id = str(payload.get("operator_id", "")).strip()
        try:
            tenant = load_tenant_config(canonicalize_tenant_id(tenant_id))
        except (FileNotFoundError, TenantDisabledError):
            return OperatorRole.OPERATOR

        seed_operator = next(
            (
                operator
                for operator in tenant.operators
                if operator.operator_id == operator_id
            ),
            None,
        )
        if seed_operator is not None:
            return seed_operator.role
        return OperatorRole.OPERATOR

    def _resolve_invite_storage_path(self) -> Path | None:
        if self._sqlite_store is not None:
            return self._invite_storage_path
        if self._invite_storage_path is not None:
            return self._invite_storage_path
        if self._operator_storage_path is None:
            return None
        return _derive_invite_storage_path(self._operator_storage_path)

    def _persist_records(self) -> None:
        if self._storage_path is None:
            return

        payload = [
            record.model_dump(mode="json")
            for record in sorted(self._records.values(), key=lambda item: item.created_at)
        ]
        if self._sqlite_store is not None:
            self._sqlite_store.replace_issued_api_keys(payload)
            return

        import json

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)

    def _persist_operator_records(self) -> None:
        if self._operator_storage_path is None:
            return

        payload = [
            record.model_dump(mode="json")
            for record in sorted(
                self._operator_records.values(),
                key=lambda item: (item.tenant_id, item.username.casefold(), item.operator_id),
            )
        ]
        if self._sqlite_store is not None:
            self._sqlite_store.replace_operator_records(payload)
            return

        import json

        self._operator_storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._operator_storage_path.with_suffix(
            f"{self._operator_storage_path.suffix}.tmp"
        )
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._operator_storage_path)

    def _persist_invite_records(self) -> None:
        invite_storage_path = self._resolve_invite_storage_path()
        if invite_storage_path is None:
            return

        payload = [
            record.model_dump(mode="json")
            for record in sorted(
                self._invite_records.values(),
                key=lambda item: (item.tenant_id, item.created_at, item.invite_id),
            )
        ]
        if self._sqlite_store is not None:
            self._sqlite_store.replace_operator_invites(payload)
            return

        import json

        invite_storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = invite_storage_path.with_suffix(f"{invite_storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(invite_storage_path)

    def _find_pending_invitation_by_username(
        self,
        tenant_id: str,
        username: str,
        *,
        now: datetime | None = None,
    ) -> OperatorInvitationRecord | None:
        current_time = now or datetime.now(UTC)
        return next(
            (
                invite
                for invite in self._invite_records.values()
                if invite.tenant_id == tenant_id
                and invite.username == username
                and invite.used_at is None
                and current_time < invite.expires_at
            ),
            None,
        )

    def _find_invitation_by_token(self, raw_invite_token: str) -> OperatorInvitationRecord | None:
        invite_token_hash = hash_api_key(raw_invite_token)
        invite = next(
            (
                candidate
                for candidate in self._invite_records.values()
                if hmac.compare_digest(candidate.token_hash, invite_token_hash)
            ),
            None,
        )
        if invite is not None:
            return invite

        if self._resolve_invite_storage_path() is None:
            return None

        self._load_invite_records()
        return next(
            (
                candidate
                for candidate in self._invite_records.values()
                if hmac.compare_digest(candidate.token_hash, invite_token_hash)
            ),
            None,
        )

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
        except (FileNotFoundError, TenantDisabledError):
            return DEFAULT_ISSUED_API_KEY_TTL_SECONDS
        return tenant.auth.issued_api_key_ttl_seconds

    def _revoke_active_keys_for_operator(
        self,
        *,
        tenant_id: str,
        operator_id: str,
        revoked_by_api_key_id: str | None = None,
    ) -> int:
        current_time = datetime.now(UTC)
        revoked_count = 0
        for record in list(self._records.values()):
            if record.tenant_id != tenant_id or record.operator_id != operator_id:
                continue
            self._backfill_record_expiration(record)
            if record.revoked_at is not None:
                continue
            if record.expires_at is not None and current_time >= record.expires_at:
                continue
            self.revoke_api_key(
                tenant_id=tenant_id,
                api_key_id=record.key_id,
                revoked_by_api_key_id=revoked_by_api_key_id,
                now=current_time,
            )
            revoked_count += 1
        return revoked_count

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

    @staticmethod
    def _operator_record_key(
        record: StoredOperatorRecord,
    ) -> tuple[str, str]:
        return (record.tenant_id, record.operator_id)

    @staticmethod
    def _operator_from_config(
        *,
        tenant_id: str,
        operator: OperatorConfig,
        is_seed: bool,
    ) -> EffectiveOperator:
        return EffectiveOperator(
            tenant_id=tenant_id,
            operator_id=operator.operator_id,
            username=operator.username,
            password_hash=operator.password_hash,
            role=operator.role,
            disabled=operator.disabled,
            must_change_password=operator.must_change_password,
            is_seed=is_seed,
        )

    @staticmethod
    def _operator_from_record(
        record: StoredOperatorRecord,
        *,
        is_seed: bool,
    ) -> EffectiveOperator:
        return EffectiveOperator(
            tenant_id=record.tenant_id,
            operator_id=record.operator_id,
            username=record.username,
            password_hash=record.password_hash,
            role=record.role,
            disabled=record.disabled,
            must_change_password=record.must_change_password,
            is_seed=is_seed,
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

    def _record_operator_audit_event(
        self,
        event_type: AuditEventType,
        *,
        operator: EffectiveOperator,
        api_key_id: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._audit_service is None:
            return

        payload = {
            "operator_id": operator.operator_id,
            "username": operator.username,
            "role": operator.role.value,
            "disabled": operator.disabled,
            "must_change_password": operator.must_change_password,
            "is_seed": operator.is_seed,
        }
        if details:
            payload.update(details)

        self._audit_service.record_event(
            event_type,
            tenant_id=operator.tenant_id,
            api_key_id=api_key_id,
            details=payload,
        )

    def _record_invitation_audit_event(
        self,
        event_type: AuditEventType,
        *,
        invite: OperatorInvitationRecord,
        api_key_id: str | None,
        details: dict[str, object] | None = None,
    ) -> None:
        if self._audit_service is None:
            return

        payload: dict[str, object] = {
            "invite_id": invite.invite_id,
            "username": invite.username,
            "role": invite.role.value,
            "expires_at": invite.expires_at.isoformat(),
            "used_at": invite.used_at.isoformat() if invite.used_at is not None else None,
        }
        if details:
            payload.update(details)

        self._audit_service.record_event(
            event_type,
            tenant_id=invite.tenant_id,
            api_key_id=api_key_id,
            details=payload,
        )

    def _record_authorization_denied_event(
        self,
        *,
        tenant_id: str,
        api_key_id: str | None,
        action: str,
        target_tenant_id: str,
        operator: EffectiveOperator | None,
    ) -> None:
        if self._audit_service is None:
            return

        details: dict[str, object] = {
            "action": action,
            "target_tenant_id": target_tenant_id,
            "operator_id": operator.operator_id if operator is not None else None,
            "username": operator.username if operator is not None else None,
            "role": operator.role.value if operator is not None else None,
        }
        self._audit_service.record_event(
            AuditEventType.AUTHORIZATION_DENIED,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            details=details,
        )
