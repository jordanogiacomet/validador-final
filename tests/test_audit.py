import json
from datetime import UTC, datetime, timedelta

from app.core.audit import AuditEventType
from app.services.audit_service import AuditService
from app.services.job_service import JobService


def test_audit_service_persists_events_to_json_storage(tmp_path):
    storage_path = tmp_path / "audit.json"
    service = AuditService(storage_path=storage_path)

    created = service.record_event(
        AuditEventType.JOB_CREATED,
        tenant_id="default",
        job_id="job-1",
        api_key_id="key-1",
        details={"file_name": "lote.csv"},
    )

    reloaded_service = AuditService(storage_path=storage_path)
    events = reloaded_service.list_events()

    assert len(events) == 1
    assert events[0].event_id == created.event_id
    assert events[0].event_type == AuditEventType.JOB_CREATED
    assert events[0].tenant_id == "default"
    assert events[0].job_id == "job-1"
    assert events[0].api_key_id == "key-1"
    assert events[0].details["file_name"] == "lote.csv"


def test_audit_service_can_filter_by_tenant_and_limit():
    service = AuditService()
    first = service.record_event(
        AuditEventType.JOB_CREATED,
        tenant_id="tenant-a",
        job_id="job-1",
    )
    service.record_event(
        AuditEventType.JOB_COMPLETED,
        tenant_id="tenant-b",
        job_id="job-2",
    )
    latest = service.record_event(
        AuditEventType.DUPLICATES_RESOLVED,
        tenant_id="tenant-a",
        job_id="job-3",
    )

    events = service.list_events(tenant_id="tenant-a", limit=1)

    assert len(events) == 1
    assert events[0].event_id == latest.event_id
    assert events[0].event_type == AuditEventType.DUPLICATES_RESOLVED
    assert events[0].tenant_id == "tenant-a"
    assert events[0].job_id == "job-3"
    assert events[0].event_id != first.event_id


def test_audit_service_can_filter_by_job_id():
    service = AuditService()
    service.record_event(
        AuditEventType.JOB_CREATED,
        tenant_id="tenant-a",
        job_id="job-1",
    )
    latest = service.record_event(
        AuditEventType.JOB_COMPLETED,
        tenant_id="tenant-a",
        job_id="job-2",
    )

    events = service.list_events(tenant_id="tenant-a", job_id="job-2")

    assert len(events) == 1
    assert events[0].event_id == latest.event_id
    assert events[0].job_id == "job-2"


def test_audit_service_filters_by_actor_target_type_period_and_excludes_admin_when_needed():
    service = AuditService()
    earlier = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)
    later = earlier + timedelta(minutes=10)

    admin_event = service.record_event(
        AuditEventType.OPERATOR_CREATED,
        tenant_id="tenant-a",
        details={
            "actor_operator_id": "operator-admin",
            "target_operator_id": "operator-target",
            "result": "success",
        },
    )
    admin_event.created_at = earlier

    operational_event = service.record_event(
        AuditEventType.JOB_COMPLETED,
        tenant_id="tenant-a",
        job_id="job-42",
    )
    operational_event.created_at = later

    filtered = service.list_events(
        tenant_id="tenant-a",
        actor_operator_id="operator-admin",
        target_operator_id="operator-target",
        event_types=[AuditEventType.OPERATOR_CREATED],
        created_from=earlier - timedelta(seconds=1),
        created_to=earlier + timedelta(seconds=1),
    )
    assert [event.event_id for event in filtered] == [admin_event.event_id]

    operational_only = service.list_events(
        tenant_id="tenant-a",
        include_administrative=False,
    )
    assert [event.event_id for event in operational_only] == [operational_event.event_id]


def test_audit_service_redacts_sensitive_details_before_persisting(tmp_path):
    storage_path = tmp_path / "audit.json"
    service = AuditService(storage_path=storage_path)

    service.record_event(
        AuditEventType.OPERATOR_CREATED,
        tenant_id="default",
        details={
            "password": "Senha@2026",
            "invite_token": "convite-bruto",
            "x_api_key": "vapi_secret",
            "nested": {
                "reset_token": "reset-bruto",
                "password_hash": "hash-sensivel",
            },
            "api_key_id": "issued-123",
        },
    )

    reloaded = AuditService(storage_path=storage_path)
    event = reloaded.list_events()[0]

    assert event.details["password"] == "[REDACTED]"
    assert event.details["invite_token"] == "[REDACTED]"
    assert event.details["x_api_key"] == "[REDACTED]"
    assert event.details["nested"]["reset_token"] == "[REDACTED]"
    assert event.details["nested"]["password_hash"] == "[REDACTED]"
    assert event.details["api_key_id"] == "issued-123"
    assert "Senha@2026" not in storage_path.read_text(encoding="utf-8")
    assert "convite-bruto" not in storage_path.read_text(encoding="utf-8")


def test_job_service_records_created_and_completed_audit_events():
    audit_service = AuditService()
    job_service = JobService(audit_service=audit_service)

    job = job_service.create_job(
        tenant_id="default",
        file_name="lote.csv",
        api_key_id="key-123",
        params={"validation_scope": "all_items"},
    )
    job_service.start_job(job.job_id)
    job_service.complete_job(
        job.job_id,
        result_path="/tmp/result.json",
        report_path="/tmp/report.pdf",
        total_rows=10,
        source_total_rows=12,
        rows_with_issues=3,
        total_issues=4,
    )

    events = audit_service.list_events(tenant_id="default")

    assert [event.event_type for event in events] == [
        AuditEventType.JOB_COMPLETED,
        AuditEventType.JOB_CREATED,
    ]
    assert events[0].api_key_id == "key-123"
    assert events[0].details == {
        "total_rows": 10,
        "source_total_rows": 12,
        "rows_with_issues": 3,
        "total_issues": 4,
        "validation_scope": "all_items",
    }
    assert events[1].details == {
        "file_name": "lote.csv",
        "validation_scope": "all_items",
    }


def test_audit_service_migrates_legacy_redesim_v2_events_on_reload(tmp_path):
    storage_path = tmp_path / "audit.json"
    service = AuditService(storage_path=storage_path)
    event = service.record_event(
        AuditEventType.JOB_CREATED,
        tenant_id="redesim",
        job_id="job-legacy",
        api_key_id="key-legacy",
    )

    payload = json.loads(storage_path.read_text(encoding="utf-8"))
    payload[0]["tenant_id"] = "redesim_v2"
    storage_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    reloaded = AuditService(storage_path=storage_path)
    events = reloaded.list_events(tenant_id="redesim")

    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].tenant_id == "redesim"
