from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from app.core.audit import AuditEventType
from app.core.tenant_config import DEFAULT_TENANT_ID, TenantConfig
from app.core.tenant_loader import (
    TenantDisabledError,
    list_tenants,
    load_tenant_config,
)
from app.core.tenant_runtime import (
    RuntimeTenantRecord,
    load_runtime_tenant_records,
    replace_runtime_tenant_records,
    resolve_runtime_tenant_storage_path,
)

TENANT_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}[a-z0-9]$")
DISPLAY_NAME_MAX_LENGTH = 120


class TenantAdminServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TenantSource(StrEnum):
    FILE = "file"
    RUNTIME = "runtime"


@dataclass(frozen=True)
class TenantAdminRecord:
    tenant_id: str
    display_name: str
    aliases: list[str]
    disabled: bool
    source: TenantSource
    is_default: bool = False


class TenantAdminService:
    def __init__(
        self,
        *,
        storage_path: Path | str | None = None,
        sqlite_path: Path | str | None = None,
        audit_service=None,
    ) -> None:
        self._storage_path = resolve_runtime_tenant_storage_path(
            storage_path=storage_path,
            sqlite_path=sqlite_path,
        )
        self._explicit_storage_path = Path(storage_path) if storage_path is not None else None
        self._explicit_sqlite_path = Path(sqlite_path) if sqlite_path is not None else None
        self._audit_service = audit_service

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

    def set_audit_service(self, audit_service) -> None:
        self._audit_service = audit_service

    def list_tenants(self) -> list[TenantAdminRecord]:
        runtime_records = self._load_runtime_records()
        return [
            self._build_admin_record(
                load_tenant_config(
                    tenant_id,
                    include_disabled=True,
                    runtime_records=runtime_records,
                ),
                runtime_records=runtime_records,
            )
            for tenant_id in list_tenants(
                include_disabled=True,
                runtime_records=runtime_records,
            )
        ]

    def create_tenant(
        self,
        *,
        tenant_id: str,
        display_name: str,
        aliases: list[str] | None = None,
        api_key_id: str | None = None,
    ) -> TenantAdminRecord:
        self._ensure_storage_configured()
        normalized_tenant_id = self._validate_identifier(tenant_id, field_name="tenant_id")
        normalized_display_name = self._validate_display_name(display_name)
        normalized_aliases = self._validate_aliases(aliases or [], normalized_tenant_id)
        self._validate_no_collisions(
            tenant_id=normalized_tenant_id,
            display_name=normalized_display_name,
            aliases=normalized_aliases,
            existing_tenant_id=None,
        )

        now = datetime.now(UTC)
        record = RuntimeTenantRecord(
            tenant_id=normalized_tenant_id,
            display_name=normalized_display_name,
            aliases=normalized_aliases,
            created_at=now,
            updated_at=now,
        )
        runtime_records = self._load_runtime_records()
        runtime_records.append(record)
        self._persist_runtime_records(runtime_records)
        admin_record = self._build_admin_record(
            load_tenant_config(
                normalized_tenant_id,
                include_disabled=True,
                runtime_records=runtime_records,
            ),
            runtime_records=runtime_records,
        )
        self._record_tenant_event(
            AuditEventType.TENANT_CREATED,
            admin_record,
            api_key_id=api_key_id,
        )
        return admin_record

    def update_tenant(
        self,
        *,
        tenant_id: str,
        display_name: str | None = None,
        aliases: list[str] | None = None,
        api_key_id: str | None = None,
    ) -> TenantAdminRecord:
        self._ensure_storage_configured()
        current_config = self._load_existing_tenant(tenant_id)
        if display_name is None and aliases is None:
            raise TenantAdminServiceError(422, "No tenant changes provided")

        normalized_display_name = (
            self._validate_display_name(display_name)
            if display_name is not None
            else current_config.display_name
        )
        normalized_aliases = self._validate_aliases(
            aliases if aliases is not None else current_config.aliases,
            current_config.tenant_id,
        )
        self._validate_no_collisions(
            tenant_id=current_config.tenant_id,
            display_name=normalized_display_name,
            aliases=normalized_aliases,
            existing_tenant_id=current_config.tenant_id,
        )

        record = self._upsert_runtime_record(
            current_config,
            display_name=normalized_display_name,
            aliases=normalized_aliases,
            disabled=current_config.disabled,
        )
        admin_record = self._build_admin_record(
            load_tenant_config(
                record.tenant_id,
                include_disabled=True,
                runtime_records=self._load_runtime_records(),
            )
        )
        self._record_tenant_event(
            AuditEventType.TENANT_UPDATED,
            admin_record,
            api_key_id=api_key_id,
        )
        return admin_record

    def disable_tenant(
        self,
        *,
        tenant_id: str,
        api_key_id: str | None = None,
    ) -> TenantAdminRecord:
        self._ensure_storage_configured()
        current_config = self._load_existing_tenant(tenant_id)
        if current_config.tenant_id == DEFAULT_TENANT_ID:
            raise TenantAdminServiceError(409, "Cannot disable the default tenant")

        record = self._upsert_runtime_record(
            current_config,
            display_name=current_config.display_name,
            aliases=current_config.aliases,
            disabled=True,
        )
        admin_record = self._build_admin_record(
            load_tenant_config(
                record.tenant_id,
                include_disabled=True,
                runtime_records=self._load_runtime_records(),
            )
        )
        self._record_tenant_event(
            AuditEventType.TENANT_DISABLED,
            admin_record,
            api_key_id=api_key_id,
        )
        return admin_record

    def reactivate_tenant(
        self,
        *,
        tenant_id: str,
        api_key_id: str | None = None,
    ) -> TenantAdminRecord:
        self._ensure_storage_configured()
        current_config = self._load_existing_tenant(tenant_id)
        record = self._upsert_runtime_record(
            current_config,
            display_name=current_config.display_name,
            aliases=current_config.aliases,
            disabled=False,
        )
        admin_record = self._build_admin_record(
            load_tenant_config(
                record.tenant_id,
                include_disabled=True,
                runtime_records=self._load_runtime_records(),
            )
        )
        self._record_tenant_event(
            AuditEventType.TENANT_REACTIVATED,
            admin_record,
            api_key_id=api_key_id,
        )
        return admin_record

    def _ensure_storage_configured(self) -> None:
        if self._storage_path is None:
            raise TenantAdminServiceError(
                503,
                "Tenant administration requires persistent operational storage",
            )

    def _load_runtime_records(self) -> list[RuntimeTenantRecord]:
        return load_runtime_tenant_records(
            storage_path=self._explicit_storage_path,
            sqlite_path=self._explicit_sqlite_path,
        )

    def _persist_runtime_records(self, records: list[RuntimeTenantRecord]) -> None:
        replace_runtime_tenant_records(
            records,
            storage_path=self._explicit_storage_path,
            sqlite_path=self._explicit_sqlite_path,
        )

    def _load_existing_tenant(self, tenant_id: str) -> TenantConfig:
        try:
            return load_tenant_config(
                tenant_id,
                include_disabled=True,
                runtime_records=self._load_runtime_records(),
            )
        except FileNotFoundError as exc:
            raise TenantAdminServiceError(404, "Tenant not found") from exc
        except TenantDisabledError as exc:
            raise TenantAdminServiceError(404, "Tenant not found") from exc

    def _upsert_runtime_record(
        self,
        current_config: TenantConfig,
        *,
        display_name: str,
        aliases: list[str],
        disabled: bool,
    ) -> RuntimeTenantRecord:
        runtime_records = self._load_runtime_records()
        existing_record = next(
            (
                record
                for record in runtime_records
                if record.tenant_id == current_config.tenant_id
            ),
            None,
        )
        now = datetime.now(UTC)
        if existing_record is None:
            record = RuntimeTenantRecord(
                tenant_id=current_config.tenant_id,
                display_name=display_name,
                aliases=aliases,
                disabled=disabled,
                created_at=now,
                updated_at=now,
            )
            runtime_records.append(record)
        else:
            existing_record.display_name = display_name
            existing_record.aliases = aliases
            existing_record.disabled = disabled
            existing_record.updated_at = now
            record = existing_record

        self._persist_runtime_records(runtime_records)
        return record

    def _build_admin_record(
        self,
        config: TenantConfig,
        *,
        runtime_records: list[RuntimeTenantRecord] | None = None,
    ) -> TenantAdminRecord:
        records = self._load_runtime_records() if runtime_records is None else runtime_records
        runtime_tenant_ids = {record.tenant_id for record in records}
        source = (
            TenantSource.RUNTIME
            if config.tenant_id in runtime_tenant_ids
            and config.tenant_id not in self._file_tenant_ids()
            else TenantSource.FILE
        )
        return TenantAdminRecord(
            tenant_id=config.tenant_id,
            display_name=config.display_name,
            aliases=list(config.aliases),
            disabled=config.disabled,
            source=source,
            is_default=config.tenant_id == DEFAULT_TENANT_ID,
        )

    def _validate_no_collisions(
        self,
        *,
        tenant_id: str,
        display_name: str,
        aliases: list[str],
        existing_tenant_id: str | None,
    ) -> None:
        runtime_records = self._load_runtime_records()
        existing_configs = [
            load_tenant_config(
                existing_id,
                include_disabled=True,
                runtime_records=runtime_records,
            )
            for existing_id in list_tenants(
                include_disabled=True,
                runtime_records=runtime_records,
            )
        ]
        claimed_identifiers = {tenant_id, *aliases}
        for config in existing_configs:
            if config.tenant_id == existing_tenant_id:
                continue

            existing_identifiers = {config.tenant_id, *config.aliases}
            collision = claimed_identifiers.intersection(existing_identifiers)
            if collision:
                value = sorted(collision)[0]
                raise TenantAdminServiceError(
                    409,
                    f"Tenant identifier or alias already exists: {value}",
                )

            if config.display_name.casefold() == display_name.casefold():
                raise TenantAdminServiceError(
                    409,
                    "Tenant display name already exists",
                )

    @staticmethod
    def _validate_identifier(value: str, *, field_name: str) -> str:
        normalized_value = value.strip()
        if not TENANT_IDENTIFIER_PATTERN.fullmatch(normalized_value):
            raise TenantAdminServiceError(
                422,
                f"{field_name} must use lowercase letters, numbers, dot, underscore, or hyphen",
            )
        return normalized_value

    @classmethod
    def _validate_aliases(cls, aliases: list[str], tenant_id: str) -> list[str]:
        normalized_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in aliases:
            normalized_alias = cls._validate_identifier(alias, field_name="alias")
            if normalized_alias == tenant_id:
                raise TenantAdminServiceError(422, "Tenant alias cannot equal tenant_id")
            if normalized_alias in seen_aliases:
                raise TenantAdminServiceError(422, "Tenant aliases must be unique")
            normalized_aliases.append(normalized_alias)
            seen_aliases.add(normalized_alias)
        return normalized_aliases

    @staticmethod
    def _validate_display_name(value: str) -> str:
        normalized_value = " ".join(value.strip().split())
        if not normalized_value:
            raise TenantAdminServiceError(422, "display_name is required")
        if len(normalized_value) > DISPLAY_NAME_MAX_LENGTH:
            raise TenantAdminServiceError(422, "display_name is too long")
        if any(character.isprintable() is False for character in normalized_value):
            raise TenantAdminServiceError(422, "display_name contains invalid characters")
        return normalized_value

    @staticmethod
    def _file_tenant_ids() -> set[str]:
        from app.core import tenant_loader

        return {
            tenant_file.parent.name
            for tenant_file in tenant_loader._iter_tenant_files()
        }

    def _record_tenant_event(
        self,
        event_type: AuditEventType,
        tenant: TenantAdminRecord,
        *,
        api_key_id: str | None,
    ) -> None:
        if self._audit_service is None:
            return

        self._audit_service.record_event(
            event_type,
            tenant_id=tenant.tenant_id,
            api_key_id=api_key_id,
            details={
                "tenant_id": tenant.tenant_id,
                "display_name": tenant.display_name,
                "aliases": tenant.aliases,
                "disabled": tenant.disabled,
                "source": tenant.source.value,
            },
        )
