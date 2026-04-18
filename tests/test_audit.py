import json

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
