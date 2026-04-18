import json
from pathlib import Path
from typing import Any

from app.core.audit import AuditEvent, AuditEventType


class AuditService:
    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._storage_path = Path(storage_path) if storage_path is not None else None
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
            tenant_id=tenant_id,
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
            events = [event for event in events if event.tenant_id == tenant_id]

        ordered_events = list(reversed(events))
        if limit is not None:
            ordered_events = ordered_events[:limit]
        return ordered_events

    def clear(self) -> None:
        self._events.clear()
        self._persist_events()

    def _load_events(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return

        payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Audit storage payload must be a list")

        self._events = [AuditEvent.model_validate(item) for item in payload]

    def _persist_events(self) -> None:
        if self._storage_path is None:
            return

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            event.model_dump(mode="json")
            for event in sorted(self._events, key=lambda item: item.created_at)
        ]
        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._storage_path)
