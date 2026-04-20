from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.operational_sqlite import (
    OPERATIONAL_SQLITE_PATH_ENV,
    OperationalSQLiteStore,
    is_sqlite_path,
    resolve_operational_sqlite_path,
)

TENANT_STORE_PATH_ENV = "VALIDATOR_TENANT_STORE_PATH"


class RuntimeTenantRecord(BaseModel):
    tenant_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    disabled: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def resolve_runtime_tenant_storage_path(
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
        raw_storage_path = os.getenv(TENANT_STORE_PATH_ENV, "").strip()
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


def load_runtime_tenant_records(
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> list[RuntimeTenantRecord]:
    resolved_path = resolve_runtime_tenant_storage_path(
        storage_path=storage_path,
        sqlite_path=sqlite_path,
    )
    if resolved_path is None:
        return []

    sqlite_store = _build_sqlite_store(resolved_path, sqlite_path)
    if sqlite_store is not None:
        payload = sqlite_store.load_runtime_tenants()
    else:
        if not resolved_path.exists():
            return []
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Tenant runtime storage payload must be a list")

    return [RuntimeTenantRecord.model_validate(item) for item in payload]


def replace_runtime_tenant_records(
    records: list[RuntimeTenantRecord],
    *,
    storage_path: Path | str | None = None,
    sqlite_path: Path | str | None = None,
) -> None:
    resolved_path = resolve_runtime_tenant_storage_path(
        storage_path=storage_path,
        sqlite_path=sqlite_path,
    )
    if resolved_path is None:
        raise ValueError("Tenant runtime storage is not configured")

    payload = [
        record.model_dump(mode="json")
        for record in sorted(records, key=lambda item: item.tenant_id)
    ]
    sqlite_store = _build_sqlite_store(resolved_path, sqlite_path)
    if sqlite_store is not None:
        sqlite_store.replace_runtime_tenants(payload)
        return

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = resolved_path.with_suffix(f"{resolved_path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(resolved_path)


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
