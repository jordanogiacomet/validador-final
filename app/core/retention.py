from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

RETENTION_PRESERVE_ARTIFACTS_PARAM: Final[str] = "preserve_artifacts"

UPLOAD_RETENTION_DAYS_ENV: Final[str] = "VALIDATOR_RETENTION_UPLOAD_DAYS"
RESULT_RETENTION_DAYS_ENV: Final[str] = "VALIDATOR_RETENTION_RESULT_DAYS"
REPORT_RETENTION_DAYS_ENV: Final[str] = "VALIDATOR_RETENTION_REPORT_DAYS"
REVIEW_FLAGS_RETENTION_DAYS_ENV: Final[str] = "VALIDATOR_RETENTION_REVIEW_FLAGS_DAYS"
LLM_CACHE_RETENTION_DAYS_ENV: Final[str] = "VALIDATOR_RETENTION_LLM_CACHE_DAYS"

DEFAULT_JOB_ARTIFACT_RETENTION_DAYS: Final[int] = 30
DEFAULT_LLM_CACHE_RETENTION_DAYS: Final[int] = 30

_DISABLED_RETENTION_VALUES: Final[set[str]] = {
    "0",
    "disabled",
    "false",
    "never",
    "none",
    "off",
}


@dataclass(frozen=True)
class RetentionPolicy:
    upload_days: int | None = DEFAULT_JOB_ARTIFACT_RETENTION_DAYS
    result_days: int | None = DEFAULT_JOB_ARTIFACT_RETENTION_DAYS
    report_days: int | None = DEFAULT_JOB_ARTIFACT_RETENTION_DAYS
    review_flags_days: int | None = DEFAULT_JOB_ARTIFACT_RETENTION_DAYS
    llm_cache_days: int | None = DEFAULT_LLM_CACHE_RETENTION_DAYS

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> RetentionPolicy:
        source = environ if environ is not None else os.environ
        return cls(
            upload_days=_parse_retention_days(
                source.get(UPLOAD_RETENTION_DAYS_ENV),
                DEFAULT_JOB_ARTIFACT_RETENTION_DAYS,
            ),
            result_days=_parse_retention_days(
                source.get(RESULT_RETENTION_DAYS_ENV),
                DEFAULT_JOB_ARTIFACT_RETENTION_DAYS,
            ),
            report_days=_parse_retention_days(
                source.get(REPORT_RETENTION_DAYS_ENV),
                DEFAULT_JOB_ARTIFACT_RETENTION_DAYS,
            ),
            review_flags_days=_parse_retention_days(
                source.get(REVIEW_FLAGS_RETENTION_DAYS_ENV),
                DEFAULT_JOB_ARTIFACT_RETENTION_DAYS,
            ),
            llm_cache_days=_parse_retention_days(
                source.get(LLM_CACHE_RETENTION_DAYS_ENV),
                DEFAULT_LLM_CACHE_RETENTION_DAYS,
            ),
        )

    def as_dict(self) -> dict[str, int | None]:
        return {
            "upload_days": self.upload_days,
            "result_days": self.result_days,
            "report_days": self.report_days,
            "review_flags_days": self.review_flags_days,
            "llm_cache_days": self.llm_cache_days,
        }

    def cutoff_for(self, days: int | None, *, now: datetime) -> datetime | None:
        if days is None:
            return None
        return now - timedelta(days=days)

    def llm_cache_ttl_seconds(self) -> int | None:
        if self.llm_cache_days is None:
            return None
        return self.llm_cache_days * 24 * 60 * 60


def retention_now() -> datetime:
    return datetime.now(UTC)


def _parse_retention_days(value: str | None, default_days: int) -> int | None:
    if value is None or not value.strip():
        return default_days

    normalized_value = value.strip().casefold()
    if normalized_value in _DISABLED_RETENTION_VALUES:
        return None

    try:
        parsed_value = int(normalized_value)
    except ValueError as exc:
        raise ValueError(f"Invalid retention days value: {value}") from exc

    if parsed_value < 0:
        raise ValueError(f"Retention days must be non-negative: {value}")
    if parsed_value == 0:
        return None
    return parsed_value
