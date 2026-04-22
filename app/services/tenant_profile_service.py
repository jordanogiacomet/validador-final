from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.audit import (
    AuditEventResult,
    AuditEventType,
    AuditPrincipal,
    build_audit_principal_details,
)
from app.core.tenant_loader import TenantDisabledError, load_tenant_config
from app.core.tenant_profile import (
    ValidationProfileData,
    ValidationProfileDraftRecord,
    ValidationProfileStorePayload,
    ValidationProfileVersionRecord,
    build_validation_profile_from_tenant_config,
    get_latest_published_validation_profile_version,
    load_validation_profile_store,
    replace_validation_profile_store,
    resolve_validation_profile_storage_path,
    validate_profile_against_base_config,
)


class TenantProfileServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class TenantValidationProfileState:
    tenant_id: str
    source: str
    current_profile: ValidationProfileData
    draft: ValidationProfileDraftRecord | None
    published_version: ValidationProfileVersionRecord | None
    versions: list[ValidationProfileVersionRecord]


class TenantProfileService:
    def __init__(
        self,
        *,
        storage_path: Path | str | None = None,
        sqlite_path: Path | str | None = None,
        audit_service=None,
    ) -> None:
        self._storage_path = resolve_validation_profile_storage_path(
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

    def get_profile_state(self, tenant_id: str) -> TenantValidationProfileState:
        base_config = self._load_existing_tenant_base_config(tenant_id)
        store = self._load_store()
        published_version = get_latest_published_validation_profile_version(
            store,
            base_config.tenant_id,
        )
        draft = self._get_draft(store, base_config.tenant_id)
        versions = self._list_versions(store, base_config.tenant_id)
        if published_version is not None:
            current_profile = published_version.profile
            source = "published"
        else:
            current_profile = build_validation_profile_from_tenant_config(base_config)
            source = "file"

        return TenantValidationProfileState(
            tenant_id=base_config.tenant_id,
            source=source,
            current_profile=current_profile,
            draft=draft,
            published_version=published_version,
            versions=versions,
        )

    def save_draft(
        self,
        *,
        tenant_id: str,
        profile: ValidationProfileData,
        api_key_id: str | None = None,
        actor: AuditPrincipal | None = None,
    ) -> TenantValidationProfileState:
        self._ensure_storage_configured()
        base_config = self._load_existing_tenant_base_config(tenant_id)
        store = self._load_store()
        draft = ValidationProfileDraftRecord(
            tenant_id=base_config.tenant_id,
            profile=profile,
            updated_at=datetime.now(UTC),
            updated_by_operator_id=actor.operator_id if actor is not None else None,
            updated_by_username=actor.username if actor is not None else None,
            updated_by_role=actor.role if actor is not None else None,
        )
        store.drafts = [
            existing_draft
            for existing_draft in store.drafts
            if existing_draft.tenant_id != base_config.tenant_id
        ]
        store.drafts.append(draft)
        self._persist_store(store)
        self._record_profile_event(
            AuditEventType.TENANT_PROFILE_DRAFT_SAVED,
            tenant_id=base_config.tenant_id,
            api_key_id=api_key_id,
            actor=actor,
            details={"version_number": None},
        )
        return self.get_profile_state(base_config.tenant_id)

    def publish_draft(
        self,
        *,
        tenant_id: str,
        api_key_id: str | None = None,
        actor: AuditPrincipal | None = None,
    ) -> TenantValidationProfileState:
        self._ensure_storage_configured()
        base_config = self._load_existing_tenant_base_config(tenant_id)
        store = self._load_store()
        draft = self._get_draft(store, base_config.tenant_id)
        if draft is None:
            raise TenantProfileServiceError(409, "No validation profile draft to publish")

        self._validate_profile_for_publication(base_config.tenant_id, draft.profile)
        version = self._build_next_version(
            store,
            tenant_id=base_config.tenant_id,
            profile=draft.profile,
            actor=actor,
            source="publish",
        )
        store.versions.append(version)
        store.drafts = [
            existing_draft
            for existing_draft in store.drafts
            if existing_draft.tenant_id != base_config.tenant_id
        ]
        self._persist_store(store)
        self._record_profile_event(
            AuditEventType.TENANT_PROFILE_PUBLISHED,
            tenant_id=base_config.tenant_id,
            api_key_id=api_key_id,
            actor=actor,
            details={
                "version_id": version.version_id,
                "version_number": version.version_number,
            },
        )
        return self.get_profile_state(base_config.tenant_id)

    def rollback_to_version(
        self,
        *,
        tenant_id: str,
        version_id: str,
        api_key_id: str | None = None,
        actor: AuditPrincipal | None = None,
    ) -> TenantValidationProfileState:
        self._ensure_storage_configured()
        base_config = self._load_existing_tenant_base_config(tenant_id)
        store = self._load_store()
        source_version = next(
            (
                version
                for version in store.versions
                if version.tenant_id == base_config.tenant_id
                and version.version_id == version_id
            ),
            None,
        )
        if source_version is None:
            raise TenantProfileServiceError(404, "Validation profile version not found")

        self._validate_profile_for_publication(base_config.tenant_id, source_version.profile)
        version = self._build_next_version(
            store,
            tenant_id=base_config.tenant_id,
            profile=source_version.profile,
            actor=actor,
            source="rollback",
            rollback_source_version_id=source_version.version_id,
        )
        store.versions.append(version)
        store.drafts = [
            existing_draft
            for existing_draft in store.drafts
            if existing_draft.tenant_id != base_config.tenant_id
        ]
        self._persist_store(store)
        self._record_profile_event(
            AuditEventType.TENANT_PROFILE_ROLLED_BACK,
            tenant_id=base_config.tenant_id,
            api_key_id=api_key_id,
            actor=actor,
            details={
                "version_id": version.version_id,
                "version_number": version.version_number,
                "rollback_source_version_id": source_version.version_id,
                "rollback_source_version_number": source_version.version_number,
            },
        )
        return self.get_profile_state(base_config.tenant_id)

    def _ensure_storage_configured(self) -> None:
        if self._storage_path is None:
            raise TenantProfileServiceError(
                503,
                "Validation profile administration requires persistent operational storage",
            )

    def _load_store(self) -> ValidationProfileStorePayload:
        return load_validation_profile_store(
            storage_path=self._explicit_storage_path,
            sqlite_path=self._explicit_sqlite_path,
        )

    def _persist_store(self, store: ValidationProfileStorePayload) -> None:
        replace_validation_profile_store(
            store,
            storage_path=self._explicit_storage_path,
            sqlite_path=self._explicit_sqlite_path,
        )

    @staticmethod
    def _get_draft(
        store: ValidationProfileStorePayload,
        tenant_id: str,
    ) -> ValidationProfileDraftRecord | None:
        return next(
            (draft for draft in store.drafts if draft.tenant_id == tenant_id),
            None,
        )

    @staticmethod
    def _list_versions(
        store: ValidationProfileStorePayload,
        tenant_id: str,
    ) -> list[ValidationProfileVersionRecord]:
        return sorted(
            [
                version
                for version in store.versions
                if version.tenant_id == tenant_id
            ],
            key=lambda version: version.version_number,
            reverse=True,
        )

    def _load_existing_tenant_base_config(self, tenant_id: str):
        try:
            return load_tenant_config(
                tenant_id,
                include_disabled=True,
                include_profile=False,
            )
        except (FileNotFoundError, TenantDisabledError) as exc:
            raise TenantProfileServiceError(404, "Tenant not found") from exc

    def _validate_profile_for_publication(
        self,
        tenant_id: str,
        profile: ValidationProfileData,
    ) -> None:
        base_config = self._load_existing_tenant_base_config(tenant_id)
        try:
            validate_profile_against_base_config(base_config, profile)
        except ValueError as exc:
            raise TenantProfileServiceError(
                422,
                f"Invalid validation profile: {exc}",
            ) from exc

    @staticmethod
    def _build_next_version(
        store: ValidationProfileStorePayload,
        *,
        tenant_id: str,
        profile: ValidationProfileData,
        actor: AuditPrincipal | None,
        source: Literal["publish", "rollback"],
        rollback_source_version_id: str | None = None,
    ) -> ValidationProfileVersionRecord:
        version_number = (
            max(
                (
                    version.version_number
                    for version in store.versions
                    if version.tenant_id == tenant_id
                ),
                default=0,
            )
            + 1
        )
        return ValidationProfileVersionRecord(
            tenant_id=tenant_id,
            version_number=version_number,
            profile=profile,
            published_at=datetime.now(UTC),
            published_by_operator_id=actor.operator_id if actor is not None else None,
            published_by_username=actor.username if actor is not None else None,
            published_by_role=actor.role if actor is not None else None,
            source=source,
            rollback_source_version_id=rollback_source_version_id,
        )

    def _record_profile_event(
        self,
        event_type: AuditEventType,
        *,
        tenant_id: str,
        api_key_id: str | None,
        actor: AuditPrincipal | None,
        details: dict[str, object],
    ) -> None:
        if self._audit_service is None:
            return

        self._audit_service.record_event(
            event_type,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            details=build_audit_principal_details(
                actor=actor,
                result=AuditEventResult.SUCCESS,
                extra={
                    "tenant_id": tenant_id,
                    **details,
                },
            ),
        )
