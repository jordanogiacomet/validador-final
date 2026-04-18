from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from app.core.operational_sqlite import OperationalSQLiteStore, is_sqlite_path
from app.core.tenant_config import TenantConfig
from app.core.tenant_loader import list_tenants, load_tenant_config
from app.rules.llm_audit import probe_llm_provider

HEALTH_STATUS_OK = "ok"
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_STATUS_FAILED = "failed"
LLM_HEALTHCHECK_TIMEOUT_ENV = "VALIDATOR_HEALTHCHECK_LLM_TIMEOUT_MS"
DEFAULT_LLM_HEALTHCHECK_TIMEOUT_MS = 500


class HealthCheckResult(BaseModel):
    name: str
    ok: bool
    latency_ms: float
    detail: str | None = None


class HealthReport(BaseModel):
    status: str
    checks: list[HealthCheckResult] = Field(default_factory=list)


class _SkipHealthCheck(Exception):
    pass


def get_llm_healthcheck_timeout_ms() -> int:
    raw_timeout = os.getenv(
        LLM_HEALTHCHECK_TIMEOUT_ENV,
        str(DEFAULT_LLM_HEALTHCHECK_TIMEOUT_MS),
    ).strip()
    try:
        timeout_ms = int(raw_timeout)
    except ValueError:
        return DEFAULT_LLM_HEALTHCHECK_TIMEOUT_MS
    return max(timeout_ms, 1)


def probe_directory_storage(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    probe_path = path / f".healthcheck-{os.getpid()}-{time.time_ns()}"
    payload = b"ok"
    try:
        probe_path.write_bytes(payload)
        if probe_path.read_bytes() != payload:
            raise OSError("storage probe round-trip failed")
    finally:
        probe_path.unlink(missing_ok=True)
    return str(path)


def probe_job_store_storage(storage_path: Path | None) -> str:
    if storage_path is None:
        return "in-memory"

    probe_directory_storage(storage_path.parent)
    if is_sqlite_path(storage_path):
        return OperationalSQLiteStore(storage_path).probe()

    if storage_path.exists():
        payload = json.loads(storage_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Job storage payload must be a list")

    return str(storage_path)


def _run_check(
    name: str,
    probe: Callable[[], str | None],
) -> HealthCheckResult | None:
    started_at = time.perf_counter()
    try:
        detail = probe()
    except _SkipHealthCheck:
        return None
    except Exception as exc:
        return HealthCheckResult(
            name=name,
            ok=False,
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            detail=f"{type(exc).__name__}: {exc}",
        )

    return HealthCheckResult(
        name=name,
        ok=True,
        latency_ms=(time.perf_counter() - started_at) * 1000.0,
        detail=detail,
    )


def _probe_tenant_llm(
    tenant_id: str,
    *,
    timeout_ms: int,
    tenant_loader: Callable[[str], TenantConfig],
) -> str:
    tenant = tenant_loader(tenant_id)
    if not tenant.llm.enabled or not tenant.llm.healthcheck_enabled:
        raise _SkipHealthCheck
    if not tenant.llm.model.strip():
        raise ValueError("LLM model not configured")
    return probe_llm_provider(tenant.llm.model, timeout_ms=timeout_ms)


def build_health_report(
    *,
    uploads_dir: Path,
    results_dir: Path,
    job_store_path: Path | None,
    tenant_lister: Callable[[], list[str]] | None = None,
    tenant_loader: Callable[[str], TenantConfig] | None = None,
) -> HealthReport:
    resolved_tenant_lister = tenant_lister or list_tenants
    resolved_tenant_loader = tenant_loader or load_tenant_config
    checks_with_criticality: list[tuple[HealthCheckResult, bool]] = []

    for name, critical, probe in (
        ("uploads", True, lambda: probe_directory_storage(uploads_dir)),
        ("results", True, lambda: probe_directory_storage(results_dir)),
        ("job_store", True, lambda: probe_job_store_storage(job_store_path)),
    ):
        result = _run_check(name, probe)
        if result is not None:
            checks_with_criticality.append((result, critical))

    llm_timeout_ms = get_llm_healthcheck_timeout_ms()
    llm_tenant_ids_result = _run_check(
        "llm_config",
        lambda: ",".join(resolved_tenant_lister()),
    )
    llm_tenant_ids: list[str] = []
    if llm_tenant_ids_result is not None:
        if llm_tenant_ids_result.ok:
            detail = llm_tenant_ids_result.detail or ""
            llm_tenant_ids = [tenant_id for tenant_id in detail.split(",") if tenant_id]
        else:
            checks_with_criticality.append((llm_tenant_ids_result, False))

    for tenant_id in llm_tenant_ids:
        result = _run_check(
            f"llm:{tenant_id}",
            lambda tenant_id=tenant_id: _probe_tenant_llm(
                tenant_id,
                timeout_ms=llm_timeout_ms,
                tenant_loader=resolved_tenant_loader,
            ),
        )
        if result is not None:
            checks_with_criticality.append((result, False))

    status = HEALTH_STATUS_OK
    if any(not result.ok and critical for result, critical in checks_with_criticality):
        status = HEALTH_STATUS_FAILED
    elif any(not result.ok for result, _ in checks_with_criticality):
        status = HEALTH_STATUS_DEGRADED

    return HealthReport(
        status=status,
        checks=[result for result, _ in checks_with_criticality],
    )


def get_health_status_code(report: HealthReport) -> int:
    if report.status == HEALTH_STATUS_FAILED:
        return 503
    return 200
