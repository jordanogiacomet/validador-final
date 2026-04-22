from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.canonical_fields import DEFAULT_TENANT_COLUMNS
from app.core.operational_sqlite import (
    OPERATIONAL_SQLITE_PATH_ENV,
    OperationalSQLiteStore,
    is_sqlite_path,
    resolve_operational_sqlite_path,
)
from app.core.tenant_config import (
    CategoryConfig,
    LLMConfig,
    NormalizationConfig,
    SuspiciousPatternsConfig,
    TenantConfig,
)

TENANT_PROFILE_STORE_PATH_ENV = "VALIDATOR_TENANT_PROFILE_STORE_PATH"

PROFILE_FIELD_NAMES = (
    "columns",
    "enabled_rules",
    "disabled_rules",
    "thresholds",
    "categories",
    "normalization",
    "suspicious_patterns",
    "llm",
)

CANONICAL_PROFILE_FIELD_KEYS = frozenset(DEFAULT_TENANT_COLUMNS)


class ValidationProfileData(BaseModel):
    columns: dict[str, str] = Field(default_factory=dict)
    enabled_rules: list[str] = Field(default_factory=list)
    disabled_rules: list[str] = Field(default_factory=list)
    thresholds: dict[str, int | float | str | bool] = Field(default_factory=dict)
    categories: list[CategoryConfig] = Field(default_factory=list)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)
    suspicious_patterns: SuspiciousPatternsConfig = Field(
        default_factory=SuspiciousPatternsConfig
    )
    llm: LLMConfig = Field(default_factory=LLMConfig)


class ValidationProfileDraftRecord(BaseModel):
    tenant_id: str
    profile: ValidationProfileData
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by_operator_id: str | None = None
    updated_by_username: str | None = None
    updated_by_role: str | None = None


class ValidationProfileVersionRecord(BaseModel):
    tenant_id: str
    version_id: str = Field(default_factory=lambda: f"profile-{uuid4().hex}")
    version_number: int = Field(ge=1)
    profile: ValidationProfileData
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    published_by_operator_id: str | None = None
    published_by_username: str | None = None
    published_by_role: str | None = None
    source: Literal["publish", "rollback"] = "publish"
    rollback_source_version_id: str | None = None


class ValidationProfileStorePayload(BaseModel):
    drafts: list[ValidationProfileDraftRecord] = Field(default_factory=list)
    versions: list[ValidationProfileVersionRecord] = Field(default_factory=list)


def build_validation_profile_from_tenant_config(
    config: TenantConfig,
) -> ValidationProfileData:
    return ValidationProfileData(
        **{
            field_name: getattr(config, field_name)
            for field_name in PROFILE_FIELD_NAMES
        }
    )


def apply_validation_profile_to_tenant_config(
    config: TenantConfig,
    profile: ValidationProfileData,
) -> TenantConfig:
    profile_payload = profile.model_dump(mode="python")
    return config.model_copy(deep=True, update=profile_payload)


def validate_profile_against_base_config(
    base_config: TenantConfig,
    profile: ValidationProfileData,
) -> None:
    """Validate schema plus cross-field consistency before publishing a profile."""
    profile_payload = profile.model_dump(mode="python")
    TenantConfig.model_validate(
        base_config.model_dump(mode="python") | profile_payload
    )

    errors: list[str] = []
    column_keys = set(profile.columns)
    unknown_column_keys = sorted(column_keys - CANONICAL_PROFILE_FIELD_KEYS)
    if unknown_column_keys:
        errors.append(
            "Unknown canonical column keys: " + ", ".join(unknown_column_keys)
        )

    duplicated_enabled_rules = _collect_duplicates(profile.enabled_rules)
    if duplicated_enabled_rules:
        errors.append(
            "Duplicate enabled rules: " + ", ".join(duplicated_enabled_rules)
        )

    duplicated_disabled_rules = _collect_duplicates(profile.disabled_rules)
    if duplicated_disabled_rules:
        errors.append(
            "Duplicate disabled rules: " + ", ".join(duplicated_disabled_rules)
        )

    overlapping_rules = sorted(set(profile.enabled_rules).intersection(profile.disabled_rules))
    if overlapping_rules:
        errors.append(
            "Rules cannot be both enabled and disabled: " + ", ".join(overlapping_rules)
        )

    category_names = [category.name for category in profile.categories]
    duplicated_category_names = _collect_duplicates(category_names)
    if duplicated_category_names:
        errors.append(
            "Duplicate category names: " + ", ".join(duplicated_category_names)
        )

    for category in profile.categories:
        _validate_category_fields(category, errors)

    prompt_file = profile.llm.prompt_file.strip()
    if prompt_file:
        prompt_path = Path(prompt_file)
        if prompt_path.is_absolute() or ".." in prompt_path.parts:
            errors.append("LLM prompt_file must be a tenant-relative prompt path")

    if errors:
        raise ValueError("; ".join(errors))


def load_published_validation_profile(
    tenant_id: str,
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> ValidationProfileData | None:
    store = load_validation_profile_store(
        storage_path=storage_path,
        sqlite_path=sqlite_path,
    )
    latest = get_latest_published_validation_profile_version(store, tenant_id)
    return latest.profile if latest is not None else None


def get_latest_published_validation_profile_version(
    store: ValidationProfileStorePayload,
    tenant_id: str,
) -> ValidationProfileVersionRecord | None:
    versions = [
        version
        for version in store.versions
        if version.tenant_id == tenant_id
    ]
    if not versions:
        return None
    return max(versions, key=lambda version: version.version_number)


def resolve_validation_profile_storage_path(
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> Path | None:
    explicit_sqlite_path = sqlite_path
    if explicit_sqlite_path is None:
        raw_sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV, "").strip()
        explicit_sqlite_path = raw_sqlite_path or None

    explicit_storage_path = storage_path
    if explicit_storage_path is None:
        raw_storage_path = os.getenv(TENANT_PROFILE_STORE_PATH_ENV, "").strip()
        explicit_storage_path = raw_storage_path or None

    resolved_sqlite_path = resolve_operational_sqlite_path(
        explicit_sqlite_path,
        explicit_storage_path,
    )
    if resolved_sqlite_path is not None:
        return resolved_sqlite_path

    if explicit_storage_path is None:
        return None
    return Path(explicit_storage_path)


def load_validation_profile_store(
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> ValidationProfileStorePayload:
    resolved_path = resolve_validation_profile_storage_path(
        storage_path=storage_path,
        sqlite_path=sqlite_path,
    )
    if resolved_path is None:
        return ValidationProfileStorePayload()

    sqlite_store = _build_sqlite_store(resolved_path, sqlite_path)
    if sqlite_store is not None:
        return ValidationProfileStorePayload(
            drafts=[
                ValidationProfileDraftRecord.model_validate(payload)
                for payload in sqlite_store.load_validation_profile_drafts()
            ],
            versions=[
                ValidationProfileVersionRecord.model_validate(payload)
                for payload in sqlite_store.load_validation_profile_versions()
            ],
        )

    if not resolved_path.exists():
        return ValidationProfileStorePayload()

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Tenant validation profile storage payload must be an object")
    return ValidationProfileStorePayload.model_validate(payload)


def replace_validation_profile_store(
    store: ValidationProfileStorePayload,
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> None:
    resolved_path = resolve_validation_profile_storage_path(
        storage_path=storage_path,
        sqlite_path=sqlite_path,
    )
    if resolved_path is None:
        raise ValueError("Tenant validation profile storage is not configured")

    normalized_store = ValidationProfileStorePayload(
        drafts=sorted(store.drafts, key=lambda draft: draft.tenant_id),
        versions=sorted(
            store.versions,
            key=lambda version: (version.tenant_id, version.version_number),
        ),
    )
    sqlite_store = _build_sqlite_store(resolved_path, sqlite_path)
    if sqlite_store is not None:
        sqlite_store.replace_validation_profile_drafts(
            [
                draft.model_dump(mode="json")
                for draft in normalized_store.drafts
            ]
        )
        sqlite_store.replace_validation_profile_versions(
            [
                version.model_dump(mode="json")
                for version in normalized_store.versions
            ]
        )
        return

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(
            normalized_store.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp_path.replace(resolved_path)


def _collect_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_category_fields(
    category: CategoryConfig,
    errors: list[str],
) -> None:
    required_fields = set(category.required_fields)
    unknown_required_fields = sorted(required_fields - CANONICAL_PROFILE_FIELD_KEYS)
    if unknown_required_fields:
        errors.append(
            f"Category {category.name} has unknown required_fields: "
            + ", ".join(unknown_required_fields)
        )

    for check_name, field_names in category.critical_check_fields.items():
        unknown_fields = sorted(set(field_names) - CANONICAL_PROFILE_FIELD_KEYS)
        if unknown_fields:
            errors.append(
                f"Category {category.name} check {check_name} has unknown fields: "
                + ", ".join(unknown_fields)
            )


def _build_sqlite_store(
    resolved_path: Path,
    explicit_sqlite_path: Path | str | None,
) -> OperationalSQLiteStore | None:
    if explicit_sqlite_path is not None:
        return OperationalSQLiteStore(resolved_path)

    raw_sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV, "").strip()
    if raw_sqlite_path and Path(raw_sqlite_path) == resolved_path:
        return OperationalSQLiteStore(resolved_path)

    if is_sqlite_path(resolved_path):
        return OperationalSQLiteStore(resolved_path)

    return None
