import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.audit import AuditEventType
from app.services.audit_service import AuditService
from app.services.auth_service import (
    AuthService,
    AuthServiceError,
    IssuedAPIKeyStatus,
    verify_password,
)

DEFAULT_PASSWORD_HASH = (
    "pbkdf2_sha256$120000$default-local-operator$"
    "d4b33a7accf06812fa29bc7c9557eadf30d0f93fbb60d937a163f57943c7ebc0"
)
DEFAULT_PASSWORD = "Validador@2026!"


def test_verify_password_accepts_seed_operator_hash() -> None:
    assert verify_password(DEFAULT_PASSWORD, DEFAULT_PASSWORD_HASH) is True
    assert verify_password("wrong-password", DEFAULT_PASSWORD_HASH) is False


def test_issue_api_key_persists_only_hashed_secret_and_resolves_after_reload(tmp_path):
    storage_path = tmp_path / "issued_keys.json"
    service = AuthService(storage_path=storage_path)

    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    assert payload[0]["tenant_id"] == "default"
    assert payload[0]["operator_id"] == "default-local-operator"
    assert payload[0]["key_id"] == issued_key.record.key_id
    assert payload[0]["key_hash"] != issued_key.raw_api_key
    assert payload[0]["issued_ttl_seconds"] == 28800
    assert payload[0]["expires_at"] is not None
    assert issued_key.raw_api_key not in storage_path.read_text(encoding="utf-8")

    reloaded = AuthService(storage_path=storage_path)
    resolved = reloaded.resolve_api_key(issued_key.raw_api_key)

    assert resolved is not None
    assert resolved.tenant_id == "default"
    assert resolved.api_key_id == issued_key.record.key_id
    assert resolved.operator_id == "default-local-operator"


def test_issue_api_key_records_audit_event_and_expiration_metadata() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)

    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    assert issued_key.record.issued_ttl_seconds == 28800
    assert issued_key.record.expires_at is not None
    assert issued_key.record.expires_at - issued_key.record.created_at == timedelta(
        seconds=28800
    )

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events] == [AuditEventType.API_KEY_ISSUED]
    assert events[0].api_key_id == issued_key.record.key_id
    assert events[0].details["operator_id"] == "default-local-operator"
    assert events[0].details["issued_ttl_seconds"] == 28800


def test_expired_api_key_records_single_audit_event_and_stops_resolving() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )
    inspection_time = datetime.now(UTC)
    issued_key.record.expires_at = inspection_time - timedelta(seconds=1)

    first_resolution = service.inspect_issued_api_key(
        issued_key.raw_api_key,
        now=inspection_time,
    )
    second_resolution = service.inspect_issued_api_key(
        issued_key.raw_api_key,
        now=inspection_time + timedelta(seconds=30),
    )

    assert first_resolution.status is IssuedAPIKeyStatus.EXPIRED
    assert second_resolution.status is IssuedAPIKeyStatus.EXPIRED
    assert service.resolve_api_key(issued_key.raw_api_key) is None

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events] == [
        AuditEventType.API_KEY_EXPIRED,
        AuditEventType.API_KEY_ISSUED,
    ]
    assert issued_key.record.expired_at == inspection_time


def test_revoke_api_key_records_audit_event_and_blocks_resolution() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    revoked = service.revoke_api_key(
        tenant_id="default",
        api_key_id=issued_key.record.key_id,
        revoked_by_api_key_id=issued_key.record.key_id,
    )
    resolution = service.inspect_issued_api_key(issued_key.raw_api_key)

    assert revoked.revoked_at is not None
    assert resolution.status is IssuedAPIKeyStatus.REVOKED
    assert service.resolve_api_key(issued_key.raw_api_key) is None

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events] == [
        AuditEventType.API_KEY_REVOKED,
        AuditEventType.API_KEY_ISSUED,
    ]
    assert events[0].details["actor"] == "self"


def test_renew_api_key_issues_new_key_and_invalidates_previous() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    original_record = issued_key.record
    original_raw_api_key = issued_key.raw_api_key

    renewed = service.renew_api_key(
        tenant_id="default",
        api_key_id=original_record.key_id,
    )

    assert renewed.record.key_id != original_record.key_id
    assert renewed.record.operator_id == original_record.operator_id
    assert renewed.record.tenant_id == original_record.tenant_id
    assert renewed.raw_api_key != original_raw_api_key
    assert renewed.record.expires_at is not None
    assert renewed.record.revoked_at is None

    assert service.resolve_api_key(original_raw_api_key) is None
    previous_resolution = service.inspect_issued_api_key(original_raw_api_key)
    assert previous_resolution.status is IssuedAPIKeyStatus.REVOKED

    new_resolution = service.inspect_issued_api_key(renewed.raw_api_key)
    assert new_resolution.status is IssuedAPIKeyStatus.ACTIVE
    assert new_resolution.resolved_api_key is not None
    assert new_resolution.resolved_api_key.api_key_id == renewed.record.key_id

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events] == [
        AuditEventType.API_KEY_RENEWED,
        AuditEventType.API_KEY_ISSUED,
    ]
    renewal_event = events[0]
    assert renewal_event.api_key_id == original_record.key_id
    assert renewal_event.details["successor_api_key_id"] == renewed.record.key_id
    assert renewal_event.details["operator_id"] == original_record.operator_id


def test_renew_api_key_rejects_expired_key() -> None:
    service = AuthService()
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )
    issued_key.record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(AuthServiceError) as exc_info:
        service.renew_api_key(
            tenant_id="default",
            api_key_id=issued_key.record.key_id,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Expired API key"


def test_renew_api_key_rejects_revoked_key() -> None:
    service = AuthService()
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )
    service.revoke_api_key(
        tenant_id="default",
        api_key_id=issued_key.record.key_id,
    )

    with pytest.raises(AuthServiceError) as exc_info:
        service.renew_api_key(
            tenant_id="default",
            api_key_id=issued_key.record.key_id,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Revoked API key"


def test_renew_api_key_rejects_unknown_api_key_id() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.renew_api_key(
            tenant_id="default",
            api_key_id="issued-missing",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Issued API key not found"


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
            password=DEFAULT_PASSWORD,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Tenant not found"


def test_issue_api_key_rejects_operator_for_wrong_tenant() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="redesim",
            username="default.operator",
            password=DEFAULT_PASSWORD,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is not allowed for this tenant"


def test_issue_api_key_accepts_redesim_v2_alias_and_returns_canonical_tenant() -> None:
    service = AuthService()

    issued_key = service.issue_api_key(
        tenant_id="redesim_v2",
        username="redesim.operator",
        password="redesim-password",
    )

    assert issued_key.record.tenant_id == "redesim"


def test_create_operator_persists_only_hashed_password_and_supports_login_after_reload(
    tmp_path,
):
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)

    operator = service.create_operator(
        tenant_id="default",
        username="novo.operador",
        password="NovaSenha@2026",
    )

    payload = json.loads(operator_storage_path.read_text(encoding="utf-8"))
    assert payload[0]["tenant_id"] == "default"
    assert payload[0]["operator_id"] == operator.operator_id
    assert payload[0]["username"] == "novo.operador"
    assert payload[0]["password_hash"] != "NovaSenha@2026"
    assert "NovaSenha@2026" not in operator_storage_path.read_text(encoding="utf-8")

    reloaded = AuthService(operator_storage_path=operator_storage_path)
    issued_key = reloaded.issue_api_key(
        tenant_id="default",
        username="novo.operador",
        password="NovaSenha@2026",
    )

    assert issued_key.record.tenant_id == "default"
    assert issued_key.record.operator_id == operator.operator_id


def test_disable_operator_blocks_login_and_revokes_active_api_keys() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    operator = service.create_operator(
        tenant_id="default",
        username="ativo.operador",
        password="SenhaAtiva@2026",
        created_by_api_key_id="default-local",
    )
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="ativo.operador",
        password="SenhaAtiva@2026",
    )

    disabled = service.disable_operator(
        tenant_id="default",
        operator_id=operator.operator_id,
        disabled_by_api_key_id="default-local",
    )

    assert disabled.disabled is True
    resolution = service.inspect_issued_api_key(issued_key.raw_api_key)
    assert resolution.status is IssuedAPIKeyStatus.REVOKED

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="default",
            username="ativo.operador",
            password="SenhaAtiva@2026",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is disabled"

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events[:2]] == [
        AuditEventType.OPERATOR_DISABLED,
        AuditEventType.API_KEY_REVOKED,
    ]
    assert events[0].details["operator_id"] == operator.operator_id
    assert events[0].details["revoked_api_key_count"] == 1


def test_disable_operator_rejects_last_active_operator() -> None:
    service = AuthService()

    with pytest.raises(AuthServiceError) as exc_info:
        service.disable_operator(
            tenant_id="default",
            operator_id="default-local-operator",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Cannot disable the last active operator"


def test_rotate_seed_operator_password_replaces_bootstrap_credentials() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)

    rotated = service.rotate_seed_operator_password(
        tenant_id="default",
        new_password="NovaSeed@2026",
        rotated_by_api_key_id="default-local",
    )

    assert rotated.operator_id == "default-local-operator"
    assert rotated.is_seed is True
    events = audit_service.list_events(tenant_id="default")
    assert events[0].event_type == AuditEventType.OPERATOR_PASSWORD_ROTATED
    assert events[0].details["operator_id"] == "default-local-operator"
    assert events[0].details["is_seed"] is True

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="default",
            username="default.operator",
            password=DEFAULT_PASSWORD,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"

    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password="NovaSeed@2026",
    )
    assert issued_key.record.operator_id == "default-local-operator"
