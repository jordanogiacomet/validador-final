from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.audit import (
    AuditEvent,
    AuditEventType,
    is_administrative_audit_event,
    sanitize_audit_details,
)
from app.core.operational_sqlite import (
    OperationalSQLiteStore,
    resolve_operational_sqlite_path,
)
from app.core.tenant_loader import canonicalize_tenant_id


class AuditService:
    def __init__(
        self,
        storage_path: Path | str | None = None,
        *,
        sqlite_path: Path | str | None = None,
    ) -> None:
        self._events: list[AuditEvent] = []
        resolved_sqlite_path = resolve_operational_sqlite_path(sqlite_path, storage_path)
        self._sqlite_store = (
            OperationalSQLiteStore(resolved_sqlite_path)
            if resolved_sqlite_path is not None
            else None
        )
        self._storage_path = (
            resolved_sqlite_path
            if resolved_sqlite_path is not None
            else Path(storage_path)
            if storage_path is not None
            else None
        )
        self._load_events()

    @property
    def storage_path(self) -> Path | None:
        return self._storage_path

    def record_event(
        self,
        event_type: AuditEventType,
        *,
        tenant_id: str,
        job_id: str | None = None,
        api_key_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            tenant_id=canonicalize_tenant_id(tenant_id),
            job_id=job_id,
            api_key_id=api_key_id,
            details=sanitize_audit_details(details),
        )
        self._events.append(event)
        self._persist_events()
        return event

    def list_events(
        self,
        *,
        tenant_id: str | None = None,
        job_id: str | None = None,
        actor_operator_id: str | None = None,
        target_operator_id: str | None = None,
        event_types: list[AuditEventType | str] | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        include_administrative: bool = True,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        events = self._events
        if tenant_id is not None:
            resolved_tenant_id = canonicalize_tenant_id(tenant_id)
            events = [
                event for event in events if event.tenant_id == resolved_tenant_id
            ]

        if job_id is not None:
            events = [event for event in events if event.job_id == job_id]

        if not include_administrative:
            events = [
                event for event in events if not is_administrative_audit_event(event)
            ]

        if actor_operator_id is not None:
            events = [
                event
                for event in events
                if event.details.get("actor_operator_id") == actor_operator_id
            ]

        if target_operator_id is not None:
            events = [
                event
                for event in events
                if event.details.get("target_operator_id") == target_operator_id
            ]

        if event_types:
            normalized_event_types = {
                event_type.value
                if isinstance(event_type, AuditEventType)
                else str(event_type).strip()
                for event_type in event_types
                if str(event_type).strip()
            }
            events = [
                event
                for event in events
                if event.event_type.value in normalized_event_types
            ]

        if created_from is not None:
            events = [
                event for event in events if event.created_at >= created_from
            ]

        if created_to is not None:
            events = [event for event in events if event.created_at <= created_to]

        ordered_events = list(reversed(events))
        if limit is not None:
            ordered_events = ordered_events[:limit]
        return ordered_events

    def clear(self) -> None:
        self._events.clear()
        self._persist_events()

    def _load_events(self) -> None:
        if self._storage_path is None:
            return

        if self._sqlite_store is not None:
            payload = self._sqlite_store.load_audit_events()
        else:
            if not self._storage_path.exists():
                return
            import json

            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Audit storage payload must be a list")

        self._events = []
        updated = False
        for item in payload:
            event = AuditEvent.model_validate(item)
            resolved_tenant_id = canonicalize_tenant_id(event.tenant_id)
            if event.tenant_id != resolved_tenant_id:
                event.tenant_id = resolved_tenant_id
                updated = True
            self._events.append(event)

        if updated:
            self._persist_events()

    def _persist_events(self) -> None:
        if self._storage_path is None:
            return

        payload = [
            event.model_dump(mode="json")
            for event in sorted(self._events, key=lambda item: item.created_at)
        ]
        if self._sqlite_store is not None:
            self._sqlite_store.replace_audit_events(payload)
            return

        import json

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)
