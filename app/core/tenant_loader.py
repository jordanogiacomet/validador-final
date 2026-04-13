from pathlib import Path

import yaml

from app.core.tenant_config import TenantConfig

TENANTS_DIR = Path("app/tenants")


def load_tenant_config(tenant_id: str) -> TenantConfig:
    tenant_file = TENANTS_DIR / tenant_id / "tenant.yaml"

    if not tenant_file.exists():
        raise FileNotFoundError(f"Tenant config not found: {tenant_file}")

    with tenant_file.open("r", encoding="utf-8") as file:
        raw_data = yaml.safe_load(file)

    return TenantConfig.model_validate(raw_data)