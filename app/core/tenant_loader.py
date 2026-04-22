from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.auth_policy import legacy_api_keys_enabled
from app.core.tenant_config import DEFAULT_TENANT_ID, APIKeyConfig, TenantConfig
from app.core.tenant_profile import (
    apply_validation_profile_to_tenant_config,
    load_published_validation_profile,
)
from app.core.tenant_runtime import RuntimeTenantRecord, load_runtime_tenant_records

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"


class TenantDisabledError(Exception):
    def __init__(self, tenant_id: str) -> None:
        super().__init__(f"Tenant is disabled: {tenant_id}")
        self.tenant_id = tenant_id


@dataclass(frozen=True)
class TenantAPIKeyMatch:
    tenant: TenantConfig
    api_key: APIKeyConfig


def _iter_tenant_files() -> list[Path]:
    if not TENANTS_DIR.is_dir():
        return []
    return sorted(
        tenant_dir / "tenant.yaml"
        for tenant_dir in TENANTS_DIR.iterdir()
        if tenant_dir.is_dir() and (tenant_dir / "tenant.yaml").exists()
    )


def _read_tenant_config(tenant_file: Path) -> TenantConfig:
    with tenant_file.open("r", encoding="utf-8") as file:
        raw_data = yaml.safe_load(file)
    return TenantConfig.model_validate(raw_data)


def _runtime_record_map(
    runtime_records: list[RuntimeTenantRecord] | None = None,
) -> dict[str, RuntimeTenantRecord]:
    records = load_runtime_tenant_records() if runtime_records is None else runtime_records
    return {
        record.tenant_id: record
        for record in records
    }


def _apply_runtime_record(
    config: TenantConfig,
    record: RuntimeTenantRecord | None,
) -> TenantConfig:
    if record is None:
        return config
    return config.model_copy(
        deep=True,
        update={
            "display_name": record.display_name,
            "aliases": record.aliases,
            "disabled": record.disabled,
        },
    )


def _build_runtime_tenant_config(record: RuntimeTenantRecord) -> TenantConfig:
    default_path = TENANTS_DIR / DEFAULT_TENANT_ID / "tenant.yaml"
    if default_path.exists():
        base_config = _read_tenant_config(default_path)
        return base_config.model_copy(
            deep=True,
            update={
                "tenant_id": record.tenant_id,
                "display_name": record.display_name,
                "aliases": record.aliases,
                "disabled": record.disabled,
                "api_keys": [],
                "operators": [],
            },
        )

    return TenantConfig(
        tenant_id=record.tenant_id,
        display_name=record.display_name,
        aliases=record.aliases,
        disabled=record.disabled,
    )


def _iter_effective_tenant_configs(
    runtime_records: list[RuntimeTenantRecord] | None = None,
) -> list[TenantConfig]:
    runtime_records_by_id = _runtime_record_map(runtime_records)
    file_configs = {
        config.tenant_id: config
        for config in (_read_tenant_config(tenant_file) for tenant_file in _iter_tenant_files())
    }

    configs = [
        _apply_runtime_record(config, runtime_records_by_id.get(config.tenant_id))
        for config in file_configs.values()
    ]
    runtime_only_records = [
        record
        for record in runtime_records_by_id.values()
        if record.tenant_id not in file_configs
    ]
    configs.extend(_build_runtime_tenant_config(record) for record in runtime_only_records)
    return configs


def load_tenant_config(
    tenant_id: str,
    *,
    include_disabled: bool = False,
    include_profile: bool = True,
    runtime_records: list[RuntimeTenantRecord] | None = None,
) -> TenantConfig:
    normalized_tenant_id = tenant_id.strip()
    matches: list[TenantConfig] = []
    missing_path = TENANTS_DIR / normalized_tenant_id / "tenant.yaml"

    for config in _iter_effective_tenant_configs(runtime_records):
        if (
            normalized_tenant_id == config.tenant_id
            or normalized_tenant_id in config.aliases
        ):
            matches.append(config)

    if not matches:
        raise FileNotFoundError(f"Tenant config not found: {missing_path}")

    if len(matches) > 1:
        raise ValueError(f"Multiple tenant configs match identifier '{normalized_tenant_id}'")

    match = matches[0]
    if match.disabled and not include_disabled:
        raise TenantDisabledError(match.tenant_id)

    if include_profile:
        published_profile = load_published_validation_profile(match.tenant_id)
        if published_profile is not None:
            match = apply_validation_profile_to_tenant_config(match, published_profile)

    return match


def load_default_tenant_config() -> TenantConfig:
    return load_tenant_config(DEFAULT_TENANT_ID)


def list_tenants(
    *,
    include_disabled: bool = False,
    runtime_records: list[RuntimeTenantRecord] | None = None,
) -> list[str]:
    return sorted(
        {
            config.tenant_id
            for config in _iter_effective_tenant_configs(runtime_records)
            if include_disabled or not config.disabled
        }
    )


def canonicalize_tenant_id(tenant_id: str) -> str:
    normalized_tenant_id = tenant_id.strip()
    try:
        return load_tenant_config(
            normalized_tenant_id,
            include_disabled=True,
        ).tenant_id
    except FileNotFoundError:
        return normalized_tenant_id


def tenant_ids_match(left_tenant_id: str, right_tenant_id: str) -> bool:
    return canonicalize_tenant_id(left_tenant_id) == canonicalize_tenant_id(
        right_tenant_id
    )


def resolve_tenant_api_key(
    raw_api_key: str,
    *,
    enforce_runtime_policy: bool = True,
) -> TenantAPIKeyMatch | None:
    if enforce_runtime_policy and not legacy_api_keys_enabled():
        return None

    matches: list[TenantAPIKeyMatch] = []
    for tenant_id in list_tenants():
        tenant = load_tenant_config(tenant_id)
        for api_key in tenant.api_keys:
            if api_key.value == raw_api_key:
                matches.append(TenantAPIKeyMatch(tenant=tenant, api_key=api_key))

    if not matches:
        return None

    if len(matches) > 1:
        raise ValueError("Duplicate API key values configured across tenants")

    return matches[0]
