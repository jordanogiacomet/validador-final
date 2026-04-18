from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Final, Protocol

LLM_CACHE_PATH_ENV: Final[str] = "VALIDATOR_LLM_CACHE_PATH"
LLM_FORCE_REFRESH_PARAM: Final[str] = "force_refresh"
DEFAULT_LLM_CACHE_PATH: Final[Path] = Path("results") / "llm_cache.json"
LLM_CACHE_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "descricao",
    "marca",
    "modelo",
    "ns",
    "complemento",
    "observacao",
)


class LLMResponseCache(Protocol):
    def get(self, cache_key: str, *, ttl_seconds: int) -> str | None: ...

    def set(self, cache_key: str, response_text: str) -> None: ...


class FileLLMResponseCache:
    def __init__(self, path: Path | str, *, clock: Any | None = None) -> None:
        self.path = Path(path)
        self._clock = clock or time.time

    @classmethod
    def from_env(cls) -> FileLLMResponseCache:
        return cls(os.getenv(LLM_CACHE_PATH_ENV) or DEFAULT_LLM_CACHE_PATH)

    def get(self, cache_key: str, *, ttl_seconds: int) -> str | None:
        if ttl_seconds <= 0:
            return None

        entry = self._read_entries().get(cache_key)
        if not isinstance(entry, dict):
            return None

        created_at = entry.get("created_at")
        response_text = entry.get("response_text")
        if not isinstance(created_at, (int, float)) or not isinstance(
            response_text,
            str,
        ):
            return None

        if self._clock() - float(created_at) > ttl_seconds:
            return None

        return response_text

    def set(self, cache_key: str, response_text: str) -> None:
        entries = self._read_entries()
        entries[cache_key] = {
            "created_at": self._clock(),
            "response_text": response_text,
        }
        self._write_entries(entries)

    def _read_entries(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            return {}

        return {
            str(key): value
            for key, value in entries.items()
            if isinstance(value, dict)
        }

    def _write_entries(self, entries: dict[str, dict[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": entries,
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)


def resolve_force_refresh(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_llm_cache_payload(row: dict[str, Any]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for field_name in LLM_CACHE_PAYLOAD_FIELDS:
        value = row.get(field_name)
        payload[field_name] = "" if value is None else " ".join(str(value).split())
    return payload


def build_llm_cache_key(
    *,
    tenant_id: str,
    prompt_version: str,
    model: str,
    payload: dict[str, str],
) -> str:
    key_payload = {
        "tenant_id": tenant_id,
        "prompt_version": prompt_version,
        "model": model,
        "payload": payload,
    }
    serialized = json.dumps(
        key_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
