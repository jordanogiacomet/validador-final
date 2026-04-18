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
        password="default-password",
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
        password="default-password",
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
        password="default-password",
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
