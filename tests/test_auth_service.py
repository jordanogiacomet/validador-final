import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.core import tenant_loader
from app.core.audit import AuditEventType
from app.core.tenant_config import OperatorRole
from app.services.audit_service import AuditService
from app.services.auth_service import (
    BOOTSTRAP_ADMIN_FORCE_RESET_ENV,
    BOOTSTRAP_ADMIN_PASSWORD_ENV,
    BOOTSTRAP_ADMIN_USERNAME_ENV,
    INITIAL_SETUP_TOKEN_ENV,
    OFFICIAL_TENANT_ID_ENV,
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


def install_bootstrap_test_tenant(monkeypatch, tmp_path, tenant_id: str = "tenant_oficial") -> str:
    tenants_dir = tmp_path / "tenants"
    tenant_dir = tenants_dir / tenant_id
    tenant_dir.mkdir(parents=True)
    tenant_dir.joinpath("tenant.yaml").write_text(
        f"tenant_id: {tenant_id}\ndisplay_name: Tenant Oficial\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tenant_loader, "TENANTS_DIR", tenants_dir)
    return tenant_id


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


def test_inspect_issued_api_key_reloads_shared_storage_when_local_cache_is_stale(tmp_path):
    storage_path = tmp_path / "issued_keys.json"
    issuing_service = AuthService(storage_path=storage_path)
    validating_service = AuthService(storage_path=storage_path)

    issued_key = issuing_service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    resolution = validating_service.inspect_issued_api_key(issued_key.raw_api_key)

    assert resolution.status is IssuedAPIKeyStatus.ACTIVE
    assert resolution.resolved_api_key is not None
    assert resolution.resolved_api_key.tenant_id == "default"
    assert resolution.resolved_api_key.api_key_id == issued_key.record.key_id
    assert resolution.resolved_api_key.operator_id == "default-local-operator"


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


def test_bootstrap_admin_from_env_creates_first_operator_and_supports_login_after_reload(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)

    operator = service.bootstrap_admin_from_env(
        env={
            OFFICIAL_TENANT_ID_ENV: tenant_id,
            BOOTSTRAP_ADMIN_USERNAME_ENV: "admin.operacional",
            BOOTSTRAP_ADMIN_PASSWORD_ENV: "Bootstrap@2026",
        }
    )

    assert operator is not None
    assert operator.tenant_id == tenant_id
    assert operator.username == "admin.operacional"
    assert operator.is_seed is False

    payload = json.loads(operator_storage_path.read_text(encoding="utf-8"))
    assert payload == [
        {
            "tenant_id": tenant_id,
            "operator_id": operator.operator_id,
            "username": "admin.operacional",
            "password_hash": payload[0]["password_hash"],
            "role": "platform_admin",
            "disabled": False,
            "must_change_password": False,
        }
    ]
    assert payload[0]["password_hash"] != "Bootstrap@2026"
    assert "Bootstrap@2026" not in operator_storage_path.read_text(encoding="utf-8")

    reloaded = AuthService(operator_storage_path=operator_storage_path)
    issued_key = reloaded.issue_api_key(
        tenant_id=tenant_id,
        username="admin.operacional",
        password="Bootstrap@2026",
    )

    assert issued_key.record.tenant_id == tenant_id
    assert issued_key.record.operator_id == operator.operator_id


def test_bootstrap_admin_from_env_is_idempotent_without_overwriting_password(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)
    first = service.bootstrap_admin_from_env(
        env={
            OFFICIAL_TENANT_ID_ENV: tenant_id,
            BOOTSTRAP_ADMIN_USERNAME_ENV: "admin.operacional",
            BOOTSTRAP_ADMIN_PASSWORD_ENV: "Bootstrap@2026",
        }
    )
    payload_before = json.loads(operator_storage_path.read_text(encoding="utf-8"))

    second = service.bootstrap_admin_from_env(
        env={
            OFFICIAL_TENANT_ID_ENV: tenant_id,
            BOOTSTRAP_ADMIN_USERNAME_ENV: "admin.operacional",
            BOOTSTRAP_ADMIN_PASSWORD_ENV: "OutraSenha@2026",
        }
    )
    payload_after = json.loads(operator_storage_path.read_text(encoding="utf-8"))

    assert first is not None
    assert second is not None
    assert second.operator_id == first.operator_id
    assert payload_after == payload_before
    assert verify_password("Bootstrap@2026", payload_after[0]["password_hash"]) is True
    assert verify_password("OutraSenha@2026", payload_after[0]["password_hash"]) is False

    reloaded = AuthService(operator_storage_path=operator_storage_path)
    issued_key = reloaded.issue_api_key(
        tenant_id=tenant_id,
        username="admin.operacional",
        password="Bootstrap@2026",
    )
    assert issued_key.record.operator_id == first.operator_id

    with pytest.raises(AuthServiceError) as exc_info:
        reloaded.issue_api_key(
            tenant_id=tenant_id,
            username="admin.operacional",
            password="OutraSenha@2026",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


def test_bootstrap_admin_from_env_force_reset_updates_existing_operator_password(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)
    first = service.bootstrap_admin_from_env(
        env={
            OFFICIAL_TENANT_ID_ENV: tenant_id,
            BOOTSTRAP_ADMIN_USERNAME_ENV: "admin.operacional",
            BOOTSTRAP_ADMIN_PASSWORD_ENV: "Bootstrap@2026",
        }
    )

    updated = service.bootstrap_admin_from_env(
        env={
            OFFICIAL_TENANT_ID_ENV: tenant_id,
            BOOTSTRAP_ADMIN_USERNAME_ENV: "admin.operacional",
            BOOTSTRAP_ADMIN_PASSWORD_ENV: "SenhaAtualizada@2026",
            BOOTSTRAP_ADMIN_FORCE_RESET_ENV: "true",
        }
    )

    assert first is not None
    assert updated is not None
    assert updated.operator_id == first.operator_id

    reloaded = AuthService(operator_storage_path=operator_storage_path)
    with pytest.raises(AuthServiceError) as exc_info:
        reloaded.issue_api_key(
            tenant_id=tenant_id,
            username="admin.operacional",
            password="Bootstrap@2026",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"

    issued_key = reloaded.issue_api_key(
        tenant_id=tenant_id,
        username="admin.operacional",
        password="SenhaAtualizada@2026",
    )
    assert issued_key.record.operator_id == updated.operator_id


def test_initial_setup_state_requires_persistent_operator_storage(tmp_path, monkeypatch):
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    service = AuthService()

    state = service.get_initial_setup_state(env={OFFICIAL_TENANT_ID_ENV: tenant_id})

    assert state.available is False
    assert state.storage_configured is False
    assert state.tenant_id is None

    with pytest.raises(AuthServiceError) as exc_info:
        service.create_initial_admin(
            username="admin.inicial",
            password="Setup@2026",
            env={OFFICIAL_TENANT_ID_ENV: tenant_id},
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Initial setup requires persistent operator storage"


def test_initial_setup_creates_single_persisted_admin_and_closes_public_setup(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    operator_storage_path = tmp_path / "operators.json"
    audit_service = AuditService()
    service = AuthService(
        operator_storage_path=operator_storage_path,
        audit_service=audit_service,
    )
    setup_env = {OFFICIAL_TENANT_ID_ENV: tenant_id}

    state_before = service.get_initial_setup_state(env=setup_env)

    assert state_before.available is True
    assert state_before.storage_configured is True
    assert state_before.requires_setup_token is False
    assert state_before.tenant_id == tenant_id

    operator = service.create_initial_admin(
        username="admin.inicial",
        password="Setup@2026",
        env=setup_env,
    )

    assert operator.tenant_id == tenant_id
    assert operator.username == "admin.inicial"
    assert operator.is_seed is False

    payload = json.loads(operator_storage_path.read_text(encoding="utf-8"))
    assert payload == [
        {
            "tenant_id": tenant_id,
            "operator_id": operator.operator_id,
            "username": "admin.inicial",
            "password_hash": payload[0]["password_hash"],
            "role": "platform_admin",
            "disabled": False,
            "must_change_password": False,
        }
    ]
    assert payload[0]["password_hash"] != "Setup@2026"
    assert verify_password("Setup@2026", payload[0]["password_hash"]) is True
    assert "Setup@2026" not in operator_storage_path.read_text(encoding="utf-8")

    state_after = service.get_initial_setup_state(env=setup_env)
    assert state_after.available is False
    assert state_after.storage_configured is True

    with pytest.raises(AuthServiceError) as exc_info:
        service.create_initial_admin(
            username="outro.admin",
            password="Outra@2026",
            env=setup_env,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Initial setup is no longer available"

    events = audit_service.list_events(tenant_id=tenant_id)
    assert [event.event_type for event in events] == [
        AuditEventType.INITIAL_ADMIN_CREATED
    ]
    details = events[0].details
    assert details["operator_id"] == operator.operator_id
    assert details["username"] == "admin.inicial"
    assert details["initial_setup"] is True
    assert "Setup@2026" not in json.dumps(details)

    reloaded = AuthService(operator_storage_path=operator_storage_path)
    issued_key = reloaded.issue_api_key(
        tenant_id=tenant_id,
        username="admin.inicial",
        password="Setup@2026",
    )
    assert issued_key.record.operator_id == operator.operator_id


def test_initial_setup_optionally_requires_setup_token(tmp_path, monkeypatch) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    operator_storage_path = tmp_path / "operators.json"
    audit_service = AuditService()
    service = AuthService(
        operator_storage_path=operator_storage_path,
        audit_service=audit_service,
    )
    setup_env = {
        OFFICIAL_TENANT_ID_ENV: tenant_id,
        INITIAL_SETUP_TOKEN_ENV: "token-publicado",
    }

    state = service.get_initial_setup_state(env=setup_env)
    assert state.available is True
    assert state.requires_setup_token is True

    with pytest.raises(AuthServiceError) as exc_info:
        service.create_initial_admin(
            username="admin.inicial",
            password="Setup@2026",
            setup_token="token-incorreto",
            env=setup_env,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Invalid setup token"

    operator = service.create_initial_admin(
        username="admin.inicial",
        password="Setup@2026",
        setup_token="token-publicado",
        env=setup_env,
    )

    assert operator.username == "admin.inicial"
    event = audit_service.list_events(tenant_id=tenant_id)[0]
    assert event.event_type is AuditEventType.INITIAL_ADMIN_CREATED
    assert event.details["setup_token_required"] is True
    assert "token-publicado" not in json.dumps(event.details)


def test_initial_setup_concurrency_allows_only_one_persisted_admin(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = install_bootstrap_test_tenant(monkeypatch, tmp_path)
    sqlite_path = tmp_path / "operational.sqlite3"
    setup_env = {OFFICIAL_TENANT_ID_ENV: tenant_id}
    AuthService(sqlite_path=sqlite_path)
    attempt_count = 6
    barrier = threading.Barrier(attempt_count)

    def attempt_create(index: int) -> tuple[str, int | str]:
        service = AuthService(sqlite_path=sqlite_path)
        barrier.wait(timeout=5)
        try:
            operator = service.create_initial_admin(
                username=f"admin.inicial.{index}",
                password="Setup@2026",
                env=setup_env,
            )
            return ("created", operator.operator_id)
        except AuthServiceError as exc:
            return ("blocked", exc.status_code)

    with ThreadPoolExecutor(max_workers=attempt_count) as executor:
        results = list(executor.map(attempt_create, range(attempt_count)))

    created = [result for result in results if result[0] == "created"]
    blocked = [result for result in results if result[0] == "blocked"]

    assert len(created) == 1
    assert len(blocked) == attempt_count - 1
    assert {status_code for _status, status_code in blocked} == {409}

    reloaded = AuthService(sqlite_path=sqlite_path)
    persisted_operators = reloaded.list_operators(tenant_id=tenant_id)
    assert len(persisted_operators) == 1
    assert persisted_operators[0].operator_id == created[0][1]


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
    assert payload[0]["role"] == "operator"
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


def test_create_operator_persists_requested_role_and_issues_it_after_login(tmp_path):
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)

    operator = service.create_operator(
        tenant_id="default",
        username="admin.plataforma",
        password="AdminGlobal@2026",
        role=OperatorRole.PLATFORM_ADMIN,
    )
    reloaded = AuthService(operator_storage_path=operator_storage_path)
    issued_key = reloaded.issue_api_key(
        tenant_id="default",
        username="admin.plataforma",
        password="AdminGlobal@2026",
    )

    assert operator.role is OperatorRole.PLATFORM_ADMIN
    assert issued_key.record.role is OperatorRole.PLATFORM_ADMIN


def test_temporary_admin_password_requires_rotation_and_revokes_issued_key() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    operator = service.create_operator(
        tenant_id="default",
        username="temporario.operador",
        password="Temp@2026",
        require_password_change=True,
    )

    issued_key = service.issue_api_key(
        tenant_id="default",
        username="temporario.operador",
        password="Temp@2026",
    )

    assert issued_key.must_change_password is True

    rotated = service.complete_password_setup(
        tenant_id="default",
        operator_id=operator.operator_id,
        new_password="SenhaFinal@2026",
        completed_by_api_key_id=issued_key.record.key_id,
    )

    assert rotated.must_change_password is False
    resolution = service.inspect_issued_api_key(issued_key.raw_api_key)
    assert resolution.status is IssuedAPIKeyStatus.REVOKED

    with pytest.raises(AuthServiceError) as exc_info:
        service.issue_api_key(
            tenant_id="default",
            username="temporario.operador",
            password="Temp@2026",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events[:2]] == [
        AuditEventType.OPERATOR_PASSWORD_ROTATED,
        AuditEventType.API_KEY_REVOKED,
    ]
    assert events[0].details["completed_password_setup"] is True

    final_login = service.issue_api_key(
        tenant_id="default",
        username="temporario.operador",
        password="SenhaFinal@2026",
    )
    assert final_login.must_change_password is False
    assert final_login.record.operator_id == operator.operator_id


def test_operator_invitation_is_single_use_and_does_not_persist_raw_token(tmp_path) -> None:
    operator_storage_path = tmp_path / "operators.json"
    service = AuthService(operator_storage_path=operator_storage_path)

    invitation = service.create_operator_invitation(
        tenant_id="default",
        username="convidado.operador",
        role=OperatorRole.OPERATOR,
    )
    invite_storage_path = tmp_path / "operators.invites.json"

    assert invite_storage_path.exists()
    assert invitation.raw_invite_token not in invite_storage_path.read_text(encoding="utf-8")

    operator = service.accept_operator_invitation(
        invite_token=invitation.raw_invite_token,
        password="Convite@2026",
    )

    assert operator.username == "convidado.operador"

    with pytest.raises(AuthServiceError) as exc_info:
        service.accept_operator_invitation(
            invite_token=invitation.raw_invite_token,
            password="Outra@2026",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Invitation token already used"


def test_operator_invitation_rejects_expired_token() -> None:
    service = AuthService()
    issued_at = datetime.now(UTC)
    invitation = service.create_operator_invitation(
        tenant_id="default",
        username="convite.expirado",
        expires_in=timedelta(minutes=15),
        now=issued_at,
    )

    with pytest.raises(AuthServiceError) as exc_info:
        service.accept_operator_invitation(
            invite_token=invitation.raw_invite_token,
            password="Convite@2026",
            now=issued_at + timedelta(minutes=16),
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "Invitation token expired"


def test_reset_operator_password_revokes_active_api_keys_and_requires_new_rotation() -> None:
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    operator = service.create_operator(
        tenant_id="default",
        username="reset.operador",
        password="SenhaAtual@2026",
    )
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="reset.operador",
        password="SenhaAtual@2026",
    )

    reset_operator = service.reset_operator_password(
        tenant_id="default",
        operator_id=operator.operator_id,
        new_password="SenhaResetada@2026",
        reset_by_api_key_id="issued-admin",
        require_password_change=True,
    )

    assert reset_operator.must_change_password is True
    resolution = service.inspect_issued_api_key(issued_key.raw_api_key)
    assert resolution.status is IssuedAPIKeyStatus.REVOKED

    with pytest.raises(AuthServiceError) as old_password_exc:
        service.issue_api_key(
            tenant_id="default",
            username="reset.operador",
            password="SenhaAtual@2026",
        )

    assert old_password_exc.value.status_code == 401
    assert old_password_exc.value.detail == "Invalid credentials"

    events = audit_service.list_events(tenant_id="default")
    assert [event.event_type for event in events[:2]] == [
        AuditEventType.OPERATOR_PASSWORD_RESET,
        AuditEventType.API_KEY_REVOKED,
    ]
    assert events[0].details["revoked_api_key_count"] == 1

    reset_login = service.issue_api_key(
        tenant_id="default",
        username="reset.operador",
        password="SenhaResetada@2026",
    )
    assert reset_login.must_change_password is True


def test_authorize_operator_management_allows_platform_admin_cross_tenant():
    service = AuthService()
    platform_admin = service.create_operator(
        tenant_id="default",
        username="admin.plataforma",
        password="AdminGlobal@2026",
        role=OperatorRole.PLATFORM_ADMIN,
    )

    target_tenant_id = service.authorize_operator_management(
        actor_tenant_id="default",
        actor_operator_id=platform_admin.operator_id,
        api_key_id="issued-platform",
        target_tenant_id="redesim",
        action="operators.create",
    )

    assert target_tenant_id == "redesim"


def test_authorize_operator_management_allows_tenant_admin_for_own_tenant():
    service = AuthService()

    target_tenant_id = service.authorize_operator_management(
        actor_tenant_id="default",
        actor_operator_id="default-local-operator",
        api_key_id="issued-tenant-admin",
        target_tenant_id="default",
        action="operators.create",
    )

    assert target_tenant_id == "default"


def test_authorize_operator_management_rejects_operator_and_records_audit_event():
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)
    operator = service.create_operator(
        tenant_id="default",
        username="operador.comum",
        password="Operador@2026",
        role=OperatorRole.OPERATOR,
    )

    with pytest.raises(AuthServiceError) as exc_info:
        service.authorize_operator_management(
            actor_tenant_id="default",
            actor_operator_id=operator.operator_id,
            api_key_id="issued-operator",
            target_tenant_id="default",
            action="operators.create",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator is not allowed to manage this tenant"
    events = audit_service.list_events(tenant_id="default")
    assert events[0].event_type is AuditEventType.AUTHORIZATION_DENIED
    assert events[0].api_key_id == "issued-operator"
    assert events[0].details["operator_id"] == operator.operator_id
    assert events[0].details["role"] == "operator"
    assert events[0].details["action"] == "operators.create"


def test_authorize_operator_role_assignment_blocks_tenant_admin_platform_escalation():
    audit_service = AuditService()
    service = AuthService(audit_service=audit_service)

    with pytest.raises(AuthServiceError) as exc_info:
        service.authorize_operator_role_assignment(
            actor_tenant_id="default",
            actor_operator_id="default-local-operator",
            api_key_id="issued-tenant-admin",
            target_tenant_id="default",
            requested_role=OperatorRole.PLATFORM_ADMIN,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Only platform_admin can create platform administrators"
    event = audit_service.list_events(tenant_id="default")[0]
    assert event.event_type is AuditEventType.AUTHORIZATION_DENIED
    assert event.details["operator_id"] == "default-local-operator"
    assert event.details["role"] == "tenant_admin"
    assert event.details["action"] == "operators.create.platform_admin"


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
