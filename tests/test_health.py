from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.core import health
from app.core.auth_policy import (
    ALLOW_LEGACY_API_KEYS_IN_PRODUCTION_ENV,
    RUNTIME_ENV_ENV,
)
from app.core.tenant_config import APIKeyConfig, LLMConfig, TenantConfig
from app.main import app
from app.services import validation_service
from app.services.job_service import JobService

client = TestClient(app)


def _configure_health_dependencies(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    uploads_dir = tmp_path / "uploads"
    results_dir = tmp_path / "results"
    monkeypatch.setattr(validation_service, "UPLOADS_DIR", uploads_dir)
    monkeypatch.setattr(validation_service, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(
        "app.api.routes.job_service",
        JobService(storage_path=tmp_path / "state" / "jobs.json"),
    )
    return uploads_dir, results_dir


def test_health_reports_storage_and_llm_checks(tmp_path: Path, monkeypatch) -> None:
    _configure_health_dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(health, "list_tenants", lambda: ["default", "empresa"])

    def fake_load_tenant_config(tenant_id: str) -> TenantConfig:
        if tenant_id == "empresa":
            return TenantConfig(
                tenant_id=tenant_id,
                display_name="Empresa",
                llm=LLMConfig(
                    enabled=True,
                    healthcheck_enabled=True,
                    model="claude-sonnet-4-20250514",
                ),
            )
        return TenantConfig(tenant_id=tenant_id, display_name="Default")

    monkeypatch.setattr(health, "load_tenant_config", fake_load_tenant_config)
    monkeypatch.setattr(
        health,
        "probe_llm_provider",
        lambda model, timeout_ms=500: "api.anthropic.com:443",
    )

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [check["name"] for check in payload["checks"]] == [
        "uploads",
        "results",
        "job_store",
        "llm:empresa",
    ]
    assert all(check["ok"] is True for check in payload["checks"])
    assert all(check["latency_ms"] >= 0 for check in payload["checks"])


def test_readyz_uses_structured_health_report(tmp_path: Path, monkeypatch) -> None:
    _configure_health_dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(health, "list_tenants", lambda: [])

    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [check["name"] for check in payload["checks"]] == [
        "uploads",
        "results",
        "job_store",
    ]


def test_livez_is_lightweight_and_public(monkeypatch) -> None:
    def fail_readiness_probe(*args, **kwargs):
        raise AssertionError("liveness should not run readiness probes")

    monkeypatch.setattr(main, "build_health_report", fail_readiness_probe)

    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_503_when_storage_check_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uploads_dir, _ = _configure_health_dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(health, "list_tenants", lambda: [])

    def fake_probe_directory_storage(path: Path) -> str:
        if path == uploads_dir:
            raise OSError("uploads volume unavailable")
        return str(path)

    monkeypatch.setattr(health, "probe_directory_storage", fake_probe_directory_storage)

    response = client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "failed"
    uploads_check = next(check for check in payload["checks"] if check["name"] == "uploads")
    assert uploads_check["ok"] is False
    assert "uploads volume unavailable" in (uploads_check["detail"] or "")


def test_health_skips_llm_probe_when_tenant_opt_in_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_health_dependencies(tmp_path, monkeypatch)
    monkeypatch.setattr(health, "list_tenants", lambda: ["empresa"])
    monkeypatch.setattr(
        health,
        "load_tenant_config",
        lambda tenant_id: TenantConfig(
            tenant_id=tenant_id,
            display_name="Empresa",
            llm=LLMConfig(
                enabled=True,
                healthcheck_enabled=False,
                model="claude-sonnet-4-20250514",
            ),
        ),
    )

    def fail_probe(model: str, timeout_ms: int = 500) -> str:
        raise AssertionError("LLM probe should not run")

    monkeypatch.setattr(health, "probe_llm_provider", fail_probe)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert all(not check["name"].startswith("llm:") for check in payload["checks"])


def test_health_fails_when_insecure_production_auth_exception_is_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_health_dependencies(tmp_path, monkeypatch)
    monkeypatch.setenv(RUNTIME_ENV_ENV, "production")
    monkeypatch.setenv(ALLOW_LEGACY_API_KEYS_IN_PRODUCTION_ENV, "true")
    monkeypatch.setattr(health, "list_tenants", lambda: ["default"])
    monkeypatch.setattr(
        health,
        "load_tenant_config",
        lambda tenant_id: TenantConfig(
            tenant_id=tenant_id,
            display_name="Default",
            api_keys=[APIKeyConfig(key_id="default-local", value="secret")],
        ),
    )

    response = client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "failed"
    auth_check = next(
        check for check in payload["checks"] if check["name"] == "auth_policy"
    )
    assert auth_check["ok"] is False
    assert "legacy YAML API keys enabled in production" in auth_check["detail"]
