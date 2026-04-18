from pathlib import Path
from typing import Any

from app.core.audit import AuditEvent, AuditEventType
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
            details=details or {},
        )
        self._events.append(event)
        self._persist_events()
        return event

    def list_events(
        self,
        *,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        events = self._events
        if tenant_id is not None:
            resolved_tenant_id = canonicalize_tenant_id(tenant_id)
            events = [
                event for event in events if event.tenant_id == resolved_tenant_id
            ]

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
