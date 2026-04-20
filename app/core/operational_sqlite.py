from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

OPERATIONAL_SQLITE_PATH_ENV: Final[str] = "VALIDATOR_SQLITE_PATH"
SQLITE_SUFFIXES: Final[tuple[str, ...]] = (".db", ".sqlite", ".sqlite3")


def is_sqlite_path(path: Path | str | None) -> bool:
    if path is None:
        return False
    return Path(path).suffix.lower() in SQLITE_SUFFIXES


def resolve_operational_sqlite_path(
    sqlite_path: Path | str | None,
    *fallback_paths: Path | str | None,
) -> Path | None:
    if sqlite_path is not None:
        return Path(sqlite_path)

    candidates = [Path(path) for path in fallback_paths if is_sqlite_path(path)]
    if not candidates:
        return None

    first = candidates[0]
    if any(candidate != first for candidate in candidates[1:]):
        raise ValueError("SQLite-backed storage paths must point to the same database")
    return first


class OperationalSQLiteStore:
    """Centralized low-volume SQLite persistence for operational services."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def load_jobs(self) -> list[dict[str, Any]]:
        return self._load_payloads(
            "SELECT payload FROM jobs ORDER BY created_at ASC, job_id ASC"
        )

    def replace_jobs(self, payloads: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                str(payload["job_id"]),
                str(payload["tenant_id"]),
                str(payload["status"]),
                str(payload["created_at"]),
                str(payload["updated_at"]),
                _serialize_payload(payload),
            )
            for payload in payloads
        ]
        self._replace_rows(
            table_name="jobs",
            insert_sql=(
                "INSERT INTO jobs (job_id, tenant_id, status, created_at, updated_at, "
                "payload) VALUES (?, ?, ?, ?, ?, ?)"
            ),
            rows=rows,
        )

    def load_audit_events(self) -> list[dict[str, Any]]:
        return self._load_payloads(
            "SELECT payload FROM audit_events ORDER BY created_at ASC, event_id ASC"
        )

    def replace_audit_events(self, payloads: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                str(payload["event_id"]),
                str(payload["tenant_id"]),
                str(payload["event_type"]),
                str(payload["created_at"]),
                payload.get("job_id"),
                payload.get("api_key_id"),
                _serialize_payload(payload),
            )
            for payload in payloads
        ]
        self._replace_rows(
            table_name="audit_events",
            insert_sql=(
                "INSERT INTO audit_events (event_id, tenant_id, event_type, created_at, "
                "job_id, api_key_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?)"
            ),
            rows=rows,
        )

    def load_issued_api_keys(self) -> list[dict[str, Any]]:
        return self._load_payloads(
            "SELECT payload FROM issued_api_keys ORDER BY created_at ASC, key_id ASC"
        )

    def replace_issued_api_keys(self, payloads: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                str(payload["key_id"]),
                str(payload["tenant_id"]),
                str(payload["operator_id"]),
                str(payload["username"]),
                str(payload["key_hash"]),
                str(payload["created_at"]),
                payload.get("expires_at"),
                payload.get("revoked_at"),
                payload.get("expired_at"),
                _serialize_payload(payload),
            )
            for payload in payloads
        ]
        self._replace_rows(
            table_name="issued_api_keys",
            insert_sql=(
                "INSERT INTO issued_api_keys (key_id, tenant_id, operator_id, username, "
                "key_hash, created_at, expires_at, revoked_at, expired_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            ),
            rows=rows,
        )

    def load_operator_records(self) -> list[dict[str, Any]]:
        return self._load_payloads(
            "SELECT payload FROM operators ORDER BY tenant_id ASC, username_key ASC, "
            "operator_id ASC"
        )

    def replace_operator_records(self, payloads: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                str(payload["tenant_id"]),
                str(payload["operator_id"]),
                str(payload["username"]).casefold(),
                _serialize_payload(payload),
            )
            for payload in payloads
        ]
        self._replace_rows(
            table_name="operators",
            insert_sql=(
                "INSERT INTO operators (tenant_id, operator_id, username_key, payload) "
                "VALUES (?, ?, ?, ?)"
            ),
            rows=rows,
        )

    def load_runtime_tenants(self) -> list[dict[str, Any]]:
        return self._load_payloads(
            "SELECT payload FROM runtime_tenants ORDER BY tenant_id ASC"
        )

    def replace_runtime_tenants(self, payloads: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                str(payload["tenant_id"]),
                str(payload["display_name"]).casefold(),
                bool(payload.get("disabled", False)),
                str(payload["updated_at"]),
                _serialize_payload(payload),
            )
            for payload in payloads
        ]
        self._replace_rows(
            table_name="runtime_tenants",
            insert_sql=(
                "INSERT INTO runtime_tenants "
                "(tenant_id, display_name_key, disabled, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            rows=rows,
        )

    def try_insert_first_operator_record(self, payload: dict[str, Any]) -> bool:
        """Insert one operator only if no persisted operators exist yet."""
        row = (
            str(payload["tenant_id"]),
            str(payload["operator_id"]),
            str(payload["username"]).casefold(),
            _serialize_payload(payload),
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count_row = connection.execute("SELECT COUNT(*) FROM operators").fetchone()
            persisted_count = int(count_row[0]) if count_row is not None else 0
            if persisted_count > 0:
                return False

            connection.execute(
                "INSERT INTO operators (tenant_id, operator_id, username_key, payload) "
                "VALUES (?, ?, ?, ?)",
                row,
            )
            return True

    def probe(self) -> str:
        if not self.path.exists():
            return str(self.path)

        with self._connect() as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        result = row[0] if row is not None else None
        if result != "ok":
            raise ValueError("SQLite integrity check failed")
        return str(self.path)

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS jobs_tenant_created_idx
            ON jobs (tenant_id, created_at);

        CREATE TABLE IF NOT EXISTS audit_events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            job_id TEXT,
            api_key_id TEXT,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS audit_events_tenant_created_idx
            ON audit_events (tenant_id, created_at);

        CREATE TABLE IF NOT EXISTS issued_api_keys (
            key_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            username TEXT NOT NULL,
            key_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT,
            expired_at TEXT,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS issued_api_keys_tenant_created_idx
            ON issued_api_keys (tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS issued_api_keys_hash_idx
            ON issued_api_keys (key_hash);

        CREATE TABLE IF NOT EXISTS operators (
            tenant_id TEXT NOT NULL,
            operator_id TEXT NOT NULL,
            username_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (tenant_id, operator_id)
        );

        CREATE TABLE IF NOT EXISTS runtime_tenants (
            tenant_id TEXT PRIMARY KEY,
            display_name_key TEXT NOT NULL,
            disabled INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS runtime_tenants_display_name_idx
            ON runtime_tenants (display_name_key);
        CREATE INDEX IF NOT EXISTS runtime_tenants_disabled_idx
            ON runtime_tenants (disabled);
        """
        with self._connect() as connection:
            connection.executescript(schema)

    def _load_payloads(self, query: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [_deserialize_payload(str(row[0])) for row in rows]

    def _replace_rows(
        self,
        *,
        table_name: str,
        insert_sql: str,
        rows: Sequence[tuple[object, ...]],
    ) -> None:
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {table_name}")
            if rows:
                connection.executemany(insert_sql, rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _deserialize_payload(raw_payload: str) -> dict[str, Any]:
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("SQLite payload must be a JSON object")
    return payload
