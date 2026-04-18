from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.tenant_config import DEFAULT_TENANT_ID, APIKeyConfig, TenantConfig

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"


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


def load_tenant_config(tenant_id: str) -> TenantConfig:
    normalized_tenant_id = tenant_id.strip()
    matches: list[TenantConfig] = []
    missing_path = TENANTS_DIR / normalized_tenant_id / "tenant.yaml"

    for tenant_file in _iter_tenant_files():
        config = _read_tenant_config(tenant_file)
        if (
            normalized_tenant_id == config.tenant_id
            or normalized_tenant_id in config.aliases
        ):
            matches.append(config)

    if not matches:
        raise FileNotFoundError(f"Tenant config not found: {missing_path}")

    if len(matches) > 1:
        raise ValueError(f"Multiple tenant configs match identifier '{normalized_tenant_id}'")

    return matches[0]


def load_default_tenant_config() -> TenantConfig:
    return load_tenant_config(DEFAULT_TENANT_ID)


def list_tenants() -> list[str]:
    return sorted({config.tenant_id for config in map(_read_tenant_config, _iter_tenant_files())})


def canonicalize_tenant_id(tenant_id: str) -> str:
    normalized_tenant_id = tenant_id.strip()
    try:
        return load_tenant_config(normalized_tenant_id).tenant_id
    except FileNotFoundError:
        return normalized_tenant_id


def tenant_ids_match(left_tenant_id: str, right_tenant_id: str) -> bool:
    return canonicalize_tenant_id(left_tenant_id) == canonicalize_tenant_id(
        right_tenant_id
    )


def resolve_tenant_api_key(raw_api_key: str) -> TenantAPIKeyMatch | None:
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
