from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from app.core.tenant_config import TenantConfig

RUNTIME_ENV_ENV = "VALIDATOR_ENV"
PRODUCTION_ENV_VALUES = frozenset({"production", "prod"})
ALLOW_LEGACY_API_KEYS_IN_PRODUCTION_ENV = (
    "VALIDATOR_ALLOW_LEGACY_API_KEYS_IN_PRODUCTION"
)
ALLOW_SEED_OPERATORS_IN_PRODUCTION_ENV = (
    "VALIDATOR_ALLOW_SEED_OPERATORS_IN_PRODUCTION"
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class AuthRuntimePolicy:
    production_mode: bool
    legacy_api_keys_enabled: bool
    seed_operators_enabled: bool
    legacy_api_keys_exception: bool
    seed_operators_exception: bool


def _environment(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _env_flag(name: str, *, env: Mapping[str, str] | None = None) -> bool:
    return _environment(env).get(name, "").strip().casefold() in _TRUE_VALUES


def is_production_mode(env: Mapping[str, str] | None = None) -> bool:
    return (
        _environment(env).get(RUNTIME_ENV_ENV, "").strip().casefold()
        in PRODUCTION_ENV_VALUES
    )


def get_auth_runtime_policy(
    env: Mapping[str, str] | None = None,
) -> AuthRuntimePolicy:
    production_mode = is_production_mode(env)
    legacy_exception = _env_flag(
        ALLOW_LEGACY_API_KEYS_IN_PRODUCTION_ENV,
        env=env,
    )
    seed_exception = _env_flag(
        ALLOW_SEED_OPERATORS_IN_PRODUCTION_ENV,
        env=env,
    )
    return AuthRuntimePolicy(
        production_mode=production_mode,
        legacy_api_keys_enabled=not production_mode or legacy_exception,
        seed_operators_enabled=not production_mode or seed_exception,
        legacy_api_keys_exception=production_mode and legacy_exception,
        seed_operators_exception=production_mode and seed_exception,
    )


def legacy_api_keys_enabled(env: Mapping[str, str] | None = None) -> bool:
    return get_auth_runtime_policy(env).legacy_api_keys_enabled


def seed_operators_enabled(env: Mapping[str, str] | None = None) -> bool:
    return get_auth_runtime_policy(env).seed_operators_enabled


def describe_insecure_production_auth_exceptions(
    tenants: list[TenantConfig],
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    policy = get_auth_runtime_policy(env)
    if not policy.production_mode:
        return []

    issues: list[str] = []
    if policy.legacy_api_keys_exception:
        tenant_ids = sorted(
            tenant.tenant_id for tenant in tenants if tenant.api_keys
        )
        if tenant_ids:
            issues.append(
                "legacy YAML API keys enabled in production for tenants: "
                + ", ".join(tenant_ids)
            )

    if policy.seed_operators_exception:
        tenant_ids = sorted(
            tenant.tenant_id for tenant in tenants if tenant.operators
        )
        if tenant_ids:
            issues.append(
                "seed YAML operators enabled in production for tenants: "
                + ", ".join(tenant_ids)
            )

    return issues
