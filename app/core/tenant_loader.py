from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.tenant_config import DEFAULT_TENANT_ID, APIKeyConfig, TenantConfig

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"


@dataclass(frozen=True)
class TenantAPIKeyMatch:
    tenant: TenantConfig
    api_key: APIKeyConfig


def load_tenant_config(tenant_id: str) -> TenantConfig:
    tenant_file = TENANTS_DIR / tenant_id / "tenant.yaml"

    if not tenant_file.exists():
        raise FileNotFoundError(f"Tenant config not found: {tenant_file}")

    with tenant_file.open("r", encoding="utf-8") as file:
        raw_data = yaml.safe_load(file)

    return TenantConfig.model_validate(raw_data)


def load_default_tenant_config() -> TenantConfig:
    return load_tenant_config(DEFAULT_TENANT_ID)


def list_tenants() -> list[str]:
    if not TENANTS_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in TENANTS_DIR.iterdir()
        if d.is_dir() and (d / "tenant.yaml").exists()
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
