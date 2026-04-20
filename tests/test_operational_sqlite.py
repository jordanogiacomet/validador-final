from app.core.audit import AuditEventType
from app.core.health import probe_job_store_storage
from app.core.job import JobStatus
from app.core.tenant_runtime import (
    RuntimeTenantRecord,
    load_runtime_tenant_records,
    replace_runtime_tenant_records,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.job_service import JobService

DEFAULT_PASSWORD = "Validador@2026!"


def test_job_service_sqlite_persists_lifecycle_and_tenant_filters(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    service = JobService(sqlite_path=sqlite_path)

    default_job = service.create_job(
        tenant_id="default",
        file_name="default.csv",
        params={"validation_scope": "duplicate_items"},
    )
    other_job = service.create_job(
        tenant_id="empresa_exemplo",
        file_name="other.csv",
    )

    service.start_job(default_job.job_id)
    service.complete_job(
        default_job.job_id,
        result_path="/results/default.json",
        report_path="/results/default.pdf",
        total_rows=8,
        rows_with_issues=2,
        total_issues=3,
    )

    reloaded = JobService(sqlite_path=sqlite_path)
    reloaded_default = reloaded.get_job(default_job.job_id)

    assert sqlite_path.exists()
    assert reloaded_default is not None
    assert reloaded_default.status == JobStatus.COMPLETED
    assert reloaded_default.result_path == "/results/default.json"
    assert reloaded_default.report_path == "/results/default.pdf"
    assert reloaded_default.params["validation_scope"] == "duplicate_items"
    assert [job.job_id for job in reloaded.list_jobs(tenant_id="default")] == [
        default_job.job_id
    ]
    assert [job.job_id for job in reloaded.list_jobs(tenant_id="empresa_exemplo")] == [
        other_job.job_id
    ]


def test_auth_service_sqlite_persists_issued_keys_and_managed_operators(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    service = AuthService(sqlite_path=sqlite_path)

    operator = service.create_operator(
        tenant_id="default",
        username="sqlite.operator",
        password="NovaSenha@2026",
    )
    issued_key = service.issue_api_key(
        tenant_id="default",
        username="default.operator",
        password=DEFAULT_PASSWORD,
    )

    reloaded = AuthService(sqlite_path=sqlite_path)
    resolved = reloaded.resolve_api_key(issued_key.raw_api_key)
    operators = reloaded.list_operators(tenant_id="default")

    assert resolved is not None
    assert resolved.tenant_id == "default"
    assert resolved.api_key_id == issued_key.record.key_id
    assert any(candidate.operator_id == operator.operator_id for candidate in operators)

    managed_login = reloaded.issue_api_key(
        tenant_id="default",
        username="sqlite.operator",
        password="NovaSenha@2026",
    )
    assert managed_login.record.operator_id == operator.operator_id


def test_auth_service_sqlite_persists_operator_invitations(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    service = AuthService(sqlite_path=sqlite_path)

    invitation = service.create_operator_invitation(
        tenant_id="default",
        username="sqlite.invited",
    )

    reloaded = AuthService(sqlite_path=sqlite_path)
    accepted = reloaded.accept_operator_invitation(
        invite_token=invitation.raw_invite_token,
        password="SenhaConvite@2026",
    )

    assert accepted.username == "sqlite.invited"
    login = reloaded.issue_api_key(
        tenant_id="default",
        username="sqlite.invited",
        password="SenhaConvite@2026",
    )
    assert login.record.operator_id == accepted.operator_id


def test_shared_sqlite_store_keeps_audit_and_jobs_available_after_restart(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    audit_service = AuditService(sqlite_path=sqlite_path)
    job_service = JobService(sqlite_path=sqlite_path, audit_service=audit_service)

    job = job_service.create_job(
        tenant_id="default",
        file_name="lote.csv",
        api_key_id="issued-1",
        params={"validation_scope": "all_items"},
    )
    job_service.start_job(job.job_id)
    job_service.complete_job(
        job.job_id,
        result_path="/results/lote.json",
        report_path="/results/lote.pdf",
        total_rows=4,
        rows_with_issues=1,
        total_issues=2,
    )
    audit_service.record_event(
        AuditEventType.JOB_COMPLETED,
        tenant_id="empresa_exemplo",
        job_id="foreign-job",
    )

    reloaded_jobs = JobService(sqlite_path=sqlite_path)
    reloaded_audit = AuditService(sqlite_path=sqlite_path)

    assert reloaded_jobs.get_job(job.job_id) is not None
    assert [event.event_type for event in reloaded_audit.list_events(tenant_id="default")] == [
        AuditEventType.JOB_COMPLETED,
        AuditEventType.JOB_CREATED,
    ]
    assert [event.job_id for event in reloaded_audit.list_events(tenant_id="empresa_exemplo")] == [
        "foreign-job"
    ]


def test_probe_job_store_storage_accepts_sqlite_files(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    JobService(sqlite_path=sqlite_path).create_job(tenant_id="default")

    assert probe_job_store_storage(sqlite_path) == str(sqlite_path)


def test_runtime_tenant_records_sqlite_persist_runtime_metadata(tmp_path) -> None:
    sqlite_path = tmp_path / "state" / "operational.sqlite3"
    record = RuntimeTenantRecord(
        tenant_id="cliente_sqlite",
        display_name="Cliente SQLite",
        aliases=["cliente-sqlite"],
        disabled=True,
    )

    replace_runtime_tenant_records([record], sqlite_path=sqlite_path)
    reloaded = load_runtime_tenant_records(sqlite_path=sqlite_path)

    assert len(reloaded) == 1
    assert reloaded[0].tenant_id == "cliente_sqlite"
    assert reloaded[0].display_name == "Cliente SQLite"
    assert reloaded[0].aliases == ["cliente-sqlite"]
    assert reloaded[0].disabled is True
