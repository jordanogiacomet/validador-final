from pathlib import Path

import yaml

from app.core.tenant_config import DEFAULT_TENANT_ID, TenantConfig

TENANTS_DIR = Path(__file__).resolve().parent.parent / "tenants"


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
