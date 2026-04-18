import json

import pytest

from app.services.auth_service import AuthService, AuthServiceError, verify_password

DEFAULT_PASSWORD_HASH = (
    "pbkdf2_sha256$120000$default-local-operator$"
    "a4856b6371a4e299050012d2f1bb2ab6f31da83a80558f5de69f3c98b7df1e43"
)


def test_verify_password_accepts_seed_operator_hash() -> None:
    assert verify_password("default-password", DEFAULT_PASSWORD_HASH) is True
    assert verify_password("wrong-password", DEFAULT_PASSWORD_HASH) is False


def test_issue_api_key_persists_only_hashed_secret_and_resolves_after_reload(tmp_path):
    storage_path = tmp_path / "issued_keys.json"
    service = AuthService(storage_path=storage_path)

    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password="default-password",
    )

    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    assert payload[0]["tenant_id"] == "default"
    assert payload[0]["operator_id"] == "default-local-operator"
    assert payload[0]["key_id"] == issued_key.record.key_id
    assert payload[0]["key_hash"] != issued_key.raw_api_key
    assert issued_key.raw_api_key not in storage_path.read_text(encoding="utf-8")

    reloaded = AuthService(storage_path=storage_path)
    resolved = reloaded.resolve_api_key(issued_key.raw_api_key)

    assert resolved is not None
    assert resolved.tenant_id == "default"
    assert resolved.api_key_id == issued_key.record.key_id
    assert resolved.operator_id == "default-local-operator"


def test_issue_api_key_rejects_invalid_credentials() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="default",
            username="default.operator",
            password="wrong-password",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


def test_issue_api_key_rejects_unknown_tenant() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="missing",
            username="default.operator",
            password="default-password",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Tenant not found"


def test_issue_api_key_rejects_operator_for_wrong_tenant() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="redesim",
            username="default.operator",
            password="default-password",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is not allowed for this tenant"
