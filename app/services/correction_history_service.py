from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.audit import (
    AuditEvent,
    AuditEventType,
    AuditPrincipal,
    build_audit_principal_details,
)
from app.core.job import JobStatus
from app.services import validation_service
from app.services.audit_service import AuditService
from app.services.job_service import JobService


class CorrectionAction(StrEnum):
    ROW_UPDATE = "row_update"
    REVIEW_FLAG = "review_flag"
    DUPLICATE_RESOLUTION = "duplicate_resolution"


@dataclass(frozen=True)
class CorrectionFieldDiff:
    field: str
    source_column: str | None
    before: str
    after: str


@dataclass(frozen=True)
class CorrectionRowSnapshot:
    row_index: int
    row: dict[str, str]


@dataclass(frozen=True)
class CorrectionHistoryEntry:
    event_id: str
    event_type: AuditEventType
    action: CorrectionAction
    tenant_id: str
    job_id: str
    api_key_id: str | None
    created_at: datetime
    actor_operator_id: str | None = None
    actor_username: str | None = None
    actor_role: str | None = None
    row_index: int | None = None
    row_indices: list[int] = field(default_factory=list)
    kept_row_index: int | None = None
    current_kept_row_index: int | None = None
    deleted_row_indices: list[int] = field(default_factory=list)
    merged_columns: list[str] = field(default_factory=list)
    field_diffs: list[CorrectionFieldDiff] = field(default_factory=list)
    before_status: str | None = None
    after_status: str | None = None
    before_rows: list[CorrectionRowSnapshot] = field(default_factory=list)
    after_rows: list[CorrectionRowSnapshot] = field(default_factory=list)
    is_reverted: bool = False
    reverted_at: datetime | None = None
    reverted_by_event_id: str | None = None
    can_revert: bool = False
    revert_blocked_reason: str | None = None


@dataclass(frozen=True)
class CorrectionRevertResult:
    job_id: str
    reverted_event_id: str
    revert_event_id: str
    action: CorrectionAction


class CorrectionHistoryConflictError(RuntimeError):
    pass


CORRECTION_EVENT_TYPES = frozenset(
    {
        AuditEventType.JOB_ROW_UPDATED,
        AuditEventType.JOB_REVIEW_FLAG_UPDATED,
        AuditEventType.DUPLICATES_RESOLVED,
    }
)


def update_job_row_with_history(
    job_id: str,
    job_service: JobService,
    audit_service: AuditService,
    *,
    row_index: int,
    updates: dict[str, str],
    api_key_id: str | None,
    actor: AuditPrincipal | None,
) -> dict[str, str]:
    before_row, resolved_columns = validation_service.read_job_csv_row(
        job_id,
        job_service,
        row_index=row_index,
    )
    updated_row = validation_service.update_job_csv_row(
        job_id,
        job_service,
        row_index=row_index,
        updates=updates,
    )

    field_diffs: list[CorrectionFieldDiff] = []
    for field_name, requested_value in updates.items():
        source_column = resolved_columns.get(field_name, field_name)
        before_value = str(before_row.get(source_column, "") or "")
        after_value = str(updated_row.get(source_column, "") or "")
        if before_value == after_value and before_value == str(requested_value):
            continue
        field_diffs.append(
            CorrectionFieldDiff(
                field=field_name,
                source_column=source_column,
                before=before_value,
                after=after_value,
            )
        )

    if field_diffs:
        job = _get_job_or_raise(job_id, job_service)
        audit_service.record_event(
            AuditEventType.JOB_ROW_UPDATED,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            api_key_id=api_key_id,
            details=build_audit_principal_details(
                actor=actor,
                extra={
                    "action": CorrectionAction.ROW_UPDATE.value,
                    "row_index": row_index,
                    "field_diffs": [
                        {
                            "field": diff.field,
                            "source_column": diff.source_column,
                            "before": diff.before,
                            "after": diff.after,
                        }
                        for diff in field_diffs
                    ],
                },
            ),
        )

    return {key: "" if value is None else str(value) for key, value in updated_row.items()}


def set_job_row_review_flag_with_history(
    job_id: str,
    job_service: JobService,
    audit_service: AuditService,
    *,
    row_index: int,
    status: str,
    api_key_id: str | None,
    actor: AuditPrincipal | None,
) -> validation_service.ReviewFlagUpdate:
    update = validation_service.set_job_row_review_flag(
        job_id,
        job_service,
        row_index=row_index,
        status=status,
    )
    if update.previous_status != update.status:
        job = _get_job_or_raise(job_id, job_service)
        audit_service.record_event(
            AuditEventType.JOB_REVIEW_FLAG_UPDATED,
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            api_key_id=api_key_id,
            details=build_audit_principal_details(
                actor=actor,
                extra={
                    "action": CorrectionAction.REVIEW_FLAG.value,
                    "row_index": row_index,
                    "before_status": update.previous_status,
                    "after_status": update.status,
                },
            ),
        )
    return update


def resolve_duplicate_rows_with_history(
    job_id: str,
    job_service: JobService,
    audit_service: AuditService,
    *,
    row_indices: list[int],
    api_key_id: str | None,
    actor: AuditPrincipal | None,
) -> validation_service.DuplicateCsvResolution:
    normalized_indices = sorted(set(row_indices))
    before_rows = [
        CorrectionRowSnapshot(
            row_index=row_index,
            row=validation_service.read_job_csv_row(
                job_id,
                job_service,
                row_index=row_index,
            )[0],
        )
        for row_index in normalized_indices
    ]
    resolution = validation_service.resolve_duplicate_csv_rows_and_refresh(
        job_id,
        job_service,
        row_indices=normalized_indices,
    )
    after_row, _ = validation_service.read_job_csv_row(
        job_id,
        job_service,
        row_index=resolution.current_kept_row_index,
    )
    job = _get_job_or_raise(job_id, job_service)
    audit_service.record_event(
        AuditEventType.DUPLICATES_RESOLVED,
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        api_key_id=api_key_id,
        details=build_audit_principal_details(
            actor=actor,
            extra={
                "action": CorrectionAction.DUPLICATE_RESOLUTION.value,
                "row_indices": normalized_indices,
                "kept_row_index": resolution.kept_row_index,
                "current_kept_row_index": resolution.current_kept_row_index,
                "deleted_row_indices": resolution.deleted_row_indices,
                "remaining_rows": resolution.remaining_rows,
                "merged_columns": resolution.merged_columns,
                "before_rows": [
                    {"row_index": snapshot.row_index, "row": snapshot.row}
                    for snapshot in before_rows
                ],
                "after_rows": [
                    {
                        "row_index": resolution.current_kept_row_index,
                        "row": after_row,
                    }
                ],
            },
        ),
    )
    return resolution


def get_job_result_payload_with_history(
    job_id: str,
    job_service: JobService,
    audit_service: AuditService,
) -> dict[str, Any]:
    payload = validation_service.get_job_result_payload(job_id, job_service)
    payload["correction_history"] = [
        serialize_correction_history_entry(entry)
        for entry in list_job_correction_history(
            job_id,
            job_service,
            audit_service,
        )
    ]
    return payload


def list_job_correction_history(
    job_id: str,
    job_service: JobService,
    audit_service: AuditService,
) -> list[CorrectionHistoryEntry]:
    job = _get_job_or_raise(job_id, job_service)
    raw_events = audit_service.list_events(
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        event_types=[
            *(event_type.value for event_type in CORRECTION_EVENT_TYPES),
            AuditEventType.JOB_CORRECTION_REVERTED.value,
        ],
        limit=None,
    )
    chronological_events = list(reversed(raw_events))

    correction_entries: list[CorrectionHistoryEntry] = []
    reverted_by_event_id: dict[str, AuditEvent] = {}
    active_event_ids: list[str] = []

    for event in chronological_events:
        if event.event_type in CORRECTION_EVENT_TYPES:
            entry = _parse_correction_event(event)
            if entry is None:
                continue
            correction_entries.append(entry)
            active_event_ids.append(entry.event_id)
            continue

        if event.event_type != AuditEventType.JOB_CORRECTION_REVERTED:
            continue

        reverted_event_id = _read_string(event.details, "reverted_event_id")
        if not reverted_event_id:
            continue
        reverted_by_event_id[reverted_event_id] = event
        if active_event_ids and active_event_ids[-1] == reverted_event_id:
            active_event_ids.pop()

    latest_active_event_id = active_event_ids[-1] if active_event_ids else None
    entries_desc = list(reversed(correction_entries))
    return [
        _decorate_correction_entry(
            entry,
            job=job,
            latest_active_event_id=latest_active_event_id,
            reverted_event=reverted_by_event_id.get(entry.event_id),
        )
        for entry in entries_desc
    ]


def revert_job_correction(
    job_id: str,
    *,
    event_id: str,
    job_service: JobService,
    audit_service: AuditService,
    api_key_id: str | None,
    actor: AuditPrincipal | None,
) -> CorrectionRevertResult:
    job = _get_job_or_raise(job_id, job_service)
    if job.status != JobStatus.COMPLETED:
        raise CorrectionHistoryConflictError(
            "Only completed jobs can revert corrections"
        )

    history_entries = list_job_correction_history(
        job_id,
        job_service,
        audit_service,
    )
    target_entry = next(
        (entry for entry in history_entries if entry.event_id == event_id),
        None,
    )
    if target_entry is None:
        raise KeyError(f"Correction not found: {event_id}")
    if not target_entry.can_revert:
        raise CorrectionHistoryConflictError(
            target_entry.revert_blocked_reason or "Correction cannot be reverted"
        )

    if target_entry.action == CorrectionAction.ROW_UPDATE:
        _revert_row_update(target_entry, job_service)
    elif target_entry.action == CorrectionAction.REVIEW_FLAG:
        _revert_review_flag(target_entry, job_service)
    else:
        _revert_duplicate_resolution(target_entry, job_service)
        validation_service.rerun_job_validation(job_id, job_service)

    revert_event = audit_service.record_event(
        AuditEventType.JOB_CORRECTION_REVERTED,
        tenant_id=job.tenant_id,
        job_id=job.job_id,
        api_key_id=api_key_id,
        details=build_audit_principal_details(
            actor=actor,
            extra={
                "reverted_event_id": target_entry.event_id,
                "reverted_action": target_entry.action.value,
                "row_index": target_entry.row_index,
                "row_indices": target_entry.row_indices,
            },
        ),
    )
    return CorrectionRevertResult(
        job_id=job.job_id,
        reverted_event_id=target_entry.event_id,
        revert_event_id=revert_event.event_id,
        action=target_entry.action,
    )


def serialize_correction_history_entry(
    entry: CorrectionHistoryEntry,
) -> dict[str, Any]:
    return {
        "event_id": entry.event_id,
        "event_type": entry.event_type.value,
        "action": entry.action.value,
        "tenant_id": entry.tenant_id,
        "job_id": entry.job_id,
        "api_key_id": entry.api_key_id,
        "created_at": entry.created_at.isoformat(),
        "actor_operator_id": entry.actor_operator_id,
        "actor_username": entry.actor_username,
        "actor_role": entry.actor_role,
        "row_index": entry.row_index,
        "row_indices": entry.row_indices,
        "kept_row_index": entry.kept_row_index,
        "current_kept_row_index": entry.current_kept_row_index,
        "deleted_row_indices": entry.deleted_row_indices,
        "merged_columns": entry.merged_columns,
        "field_diffs": [
            {
                "field": diff.field,
                "source_column": diff.source_column,
                "before": diff.before,
                "after": diff.after,
            }
            for diff in entry.field_diffs
        ],
        "before_status": entry.before_status,
        "after_status": entry.after_status,
        "before_rows": [
            {"row_index": snapshot.row_index, "row": snapshot.row}
            for snapshot in entry.before_rows
        ],
        "after_rows": [
            {"row_index": snapshot.row_index, "row": snapshot.row}
            for snapshot in entry.after_rows
        ],
        "is_reverted": entry.is_reverted,
        "reverted_at": entry.reverted_at.isoformat()
        if entry.reverted_at is not None
        else None,
        "reverted_by_event_id": entry.reverted_by_event_id,
        "can_revert": entry.can_revert,
        "revert_blocked_reason": entry.revert_blocked_reason,
    }


def has_active_reprocess_corrections(entries: list[dict[str, Any]]) -> bool:
    return any(
        not bool(entry.get("is_reverted"))
        and entry.get("action") == CorrectionAction.ROW_UPDATE.value
        for entry in entries
    )


def _get_job_or_raise(job_id: str, job_service: JobService):
    job = job_service.get_job(job_id)
    if job is None:
        raise KeyError(f"Job not found: {job_id}")
    return job


def _decorate_correction_entry(
    entry: CorrectionHistoryEntry,
    *,
    job,
    latest_active_event_id: str | None,
    reverted_event: AuditEvent | None,
) -> CorrectionHistoryEntry:
    if reverted_event is not None:
        return replace(
            entry,
            is_reverted=True,
            reverted_at=reverted_event.created_at,
            reverted_by_event_id=reverted_event.event_id,
            can_revert=False,
            revert_blocked_reason="Esta correção já foi desfeita.",
        )

    if not _entry_supports_revert(entry):
        return replace(
            entry,
            can_revert=False,
            revert_blocked_reason=(
                "Este histórico não possui snapshot suficiente para reversão segura."
            ),
        )

    if job.latest_retry_job_id is not None:
        return replace(
            entry,
            can_revert=False,
            revert_blocked_reason=(
                "Este lote já gerou um reprocessamento. Abra o lote mais recente "
                "para continuar."
            ),
        )

    if entry.event_id != latest_active_event_id:
        return replace(
            entry,
            can_revert=False,
            revert_blocked_reason=(
                "Desfaça primeiro a correção mais recente para manter o CSV consistente."
            ),
        )

    return replace(entry, can_revert=True, revert_blocked_reason=None)


def _entry_supports_revert(entry: CorrectionHistoryEntry) -> bool:
    if entry.action == CorrectionAction.ROW_UPDATE:
        return bool(entry.field_diffs and entry.row_index is not None)
    if entry.action == CorrectionAction.REVIEW_FLAG:
        return (
            entry.row_index is not None
            and entry.before_status in {"clear", "review"}
            and entry.after_status in {"clear", "review"}
        )
    return bool(
        entry.before_rows
        and entry.after_rows
        and entry.current_kept_row_index is not None
    )


def _parse_correction_event(event: AuditEvent) -> CorrectionHistoryEntry | None:
    if event.job_id is None:
        return None

    action_value = _read_string(event.details, "action")
    if not action_value and event.event_type == AuditEventType.DUPLICATES_RESOLVED:
        action_value = CorrectionAction.DUPLICATE_RESOLUTION.value

    try:
        action = CorrectionAction(action_value)
    except ValueError:
        return None

    return CorrectionHistoryEntry(
        event_id=event.event_id,
        event_type=event.event_type,
        action=action,
        tenant_id=event.tenant_id,
        job_id=event.job_id,
        api_key_id=event.api_key_id,
        created_at=event.created_at,
        actor_operator_id=_read_string(event.details, "actor_operator_id"),
        actor_username=_read_string(event.details, "actor_username"),
        actor_role=_read_string(event.details, "actor_role"),
        row_index=_read_int(event.details, "row_index"),
        row_indices=_read_int_list(event.details, "row_indices"),
        kept_row_index=_read_int(event.details, "kept_row_index"),
        current_kept_row_index=_read_int(event.details, "current_kept_row_index"),
        deleted_row_indices=_read_int_list(event.details, "deleted_row_indices"),
        merged_columns=_read_string_list(event.details, "merged_columns"),
        field_diffs=_read_field_diffs(event.details),
        before_status=_read_string(event.details, "before_status"),
        after_status=_read_string(event.details, "after_status"),
        before_rows=_read_row_snapshots(event.details, "before_rows"),
        after_rows=_read_row_snapshots(event.details, "after_rows"),
    )


def _read_field_diffs(details: dict[str, Any]) -> list[CorrectionFieldDiff]:
    payload = details.get("field_diffs")
    if not isinstance(payload, list):
        return []

    diffs: list[CorrectionFieldDiff] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        field_name = _read_string(item, "field")
        if not field_name:
            continue
        diffs.append(
            CorrectionFieldDiff(
                field=field_name,
                source_column=_read_string(item, "source_column"),
                before=_read_string(item, "before") or "",
                after=_read_string(item, "after") or "",
            )
        )
    return diffs


def _read_row_snapshots(
    details: dict[str, Any],
    key: str,
) -> list[CorrectionRowSnapshot]:
    payload = details.get(key)
    if not isinstance(payload, list):
        return []

    snapshots: list[CorrectionRowSnapshot] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        row_index = _read_int(item, "row_index")
        row = item.get("row")
        if row_index is None or not isinstance(row, dict):
            continue
        snapshots.append(
            CorrectionRowSnapshot(
                row_index=row_index,
                row={
                    str(column): "" if value is None else str(value)
                    for column, value in row.items()
                },
            )
        )
    return snapshots


def _revert_row_update(
    entry: CorrectionHistoryEntry,
    job_service: JobService,
) -> None:
    assert entry.row_index is not None
    _, resolved_columns = validation_service.read_job_csv_row(
        entry.job_id,
        job_service,
        row_index=entry.row_index,
    )
    updates: dict[str, str] = {}
    current_row, _ = validation_service.read_job_csv_row(
        entry.job_id,
        job_service,
        row_index=entry.row_index,
    )
    for diff in entry.field_diffs:
        source_column = diff.source_column or resolved_columns.get(diff.field, diff.field)
        current_value = str(current_row.get(source_column, "") or "")
        if current_value != diff.after:
            raise CorrectionHistoryConflictError(
                "A linha já mudou depois desta correção e não pode ser desfeita com segurança."
            )
        updates[diff.field] = diff.before

    validation_service.update_job_csv_row(
        entry.job_id,
        job_service,
        row_index=entry.row_index,
        updates=updates,
    )


def _revert_review_flag(
    entry: CorrectionHistoryEntry,
    job_service: JobService,
) -> None:
    assert entry.row_index is not None
    assert entry.before_status is not None
    current_payload = validation_service.get_job_result_payload(entry.job_id, job_service)
    current_review_rows = {
        int(flag.get("row_index"))
        for flag in current_payload.get("review_flags") or []
        if isinstance(flag, dict)
        and flag.get("status") == "review"
        and isinstance(flag.get("row_index"), int)
    }
    current_status = "review" if entry.row_index in current_review_rows else "clear"
    if current_status != entry.after_status:
        raise CorrectionHistoryConflictError(
            "A marcação de revisão já mudou depois desta ação e não pode ser "
            "desfeita com segurança."
        )

    validation_service.set_job_row_review_flag(
        entry.job_id,
        job_service,
        row_index=entry.row_index,
        status=entry.before_status,
    )


def _revert_duplicate_resolution(
    entry: CorrectionHistoryEntry,
    job_service: JobService,
) -> None:
    assert entry.current_kept_row_index is not None
    current_survivor_snapshot = entry.after_rows[0]
    current_rows = _read_all_job_rows(entry.job_id, job_service)
    if entry.current_kept_row_index >= len(current_rows):
        raise CorrectionHistoryConflictError(
            "O CSV corrigido não possui mais a linha-base esperada para desfazer esta consolidação."
        )

    current_survivor_row = current_rows[entry.current_kept_row_index]
    if not _rows_match(current_survivor_row, current_survivor_snapshot.row):
        raise CorrectionHistoryConflictError(
            "O CSV corrigido já mudou depois desta consolidação e não pode ser "
            "desfeito com segurança."
        )

    restored_rows = list(current_rows)
    restored_rows.pop(entry.current_kept_row_index)
    for snapshot in sorted(entry.before_rows, key=lambda item: item.row_index):
        restored_rows.insert(snapshot.row_index, snapshot.row)

    validation_service.replace_job_csv_rows(
        entry.job_id,
        job_service,
        rows=restored_rows,
    )


def _read_all_job_rows(
    job_id: str,
    job_service: JobService,
) -> list[dict[str, str]]:
    return validation_service.read_all_job_csv_rows(job_id, job_service)


def _rows_match(left: dict[str, str], right: dict[str, str]) -> bool:
    all_keys = set(left) | set(right)
    return all(str(left.get(key, "") or "") == str(right.get(key, "") or "") for key in all_keys)


def _read_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _read_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _read_int_list(payload: dict[str, Any], key: str) -> list[int]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    result: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            result.append(parsed)
    return result


def _read_string_list(payload: dict[str, Any], key: str) -> list[str]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            result.append(text)
    return result
