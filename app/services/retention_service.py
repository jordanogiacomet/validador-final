from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.audit import AuditEventType
from app.core.job import JobRecord, JobStatus
from app.core.llm_cache import FileLLMResponseCache
from app.core.logging import get_logger, log_event
from app.core.retention import (
    RETENTION_PRESERVE_ARTIFACTS_PARAM,
    RetentionPolicy,
    retention_now,
)
from app.core.tenant_loader import canonicalize_tenant_id
from app.services import validation_service
from app.services.audit_service import AuditService
from app.services.job_service import JobService

_logger = get_logger("retention_service")


@dataclass(frozen=True)
class RetentionArtifact:
    kind: str
    path: str
    tenant_id: str | None = None
    job_id: str | None = None
    size_bytes: int = 0
    reference_time: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "size_bytes": self.size_bytes,
            "reference_time": self.reference_time.isoformat()
            if self.reference_time is not None
            else None,
        }


@dataclass(frozen=True)
class RetentionRunResult:
    tenant_id: str
    dry_run: bool
    policy: RetentionPolicy
    scanned_jobs: int
    protected_artifacts: int
    retained_artifacts: int
    artifacts: list[RetentionArtifact] = field(default_factory=list)
    llm_cache_entries_removed: int = 0
    llm_cache_entries_remaining: int = 0
    started_at: datetime = field(default_factory=retention_now)
    finished_at: datetime = field(default_factory=retention_now)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)


@dataclass(frozen=True)
class _ArtifactConfig:
    kind: str
    policy_field: str
    resolve_path: Callable[[JobRecord], Path]
    prune_empty_parent: bool = False


_JOB_ARTIFACT_CONFIGS = (
    _ArtifactConfig(
        kind="upload",
        policy_field="upload_days",
        resolve_path=validation_service.resolve_job_upload_path,
    ),
    _ArtifactConfig(
        kind="result",
        policy_field="result_days",
        resolve_path=validation_service.resolve_job_result_path,
    ),
    _ArtifactConfig(
        kind="report",
        policy_field="report_days",
        resolve_path=validation_service.resolve_job_report_path,
    ),
    _ArtifactConfig(
        kind="review_flags",
        policy_field="review_flags_days",
        resolve_path=validation_service.resolve_job_review_flags_path,
        prune_empty_parent=True,
    ),
)
_PRUNE_EMPTY_PARENT_KINDS = frozenset(
    config.kind for config in _JOB_ARTIFACT_CONFIGS if config.prune_empty_parent
)


class RetentionService:
    def __init__(
        self,
        *,
        job_service: JobService,
        audit_service: AuditService | None = None,
    ) -> None:
        self._job_service = job_service
        self._audit_service = audit_service

    def inspect(
        self,
        *,
        tenant_id: str,
        policy: RetentionPolicy | None = None,
    ) -> RetentionRunResult:
        return self._run(
            tenant_id=tenant_id,
            policy=policy or RetentionPolicy.from_env(),
            dry_run=True,
            api_key_id=None,
            record_audit=False,
        )

    def cleanup(
        self,
        *,
        tenant_id: str,
        policy: RetentionPolicy | None = None,
        api_key_id: str | None = None,
    ) -> RetentionRunResult:
        return self._run(
            tenant_id=tenant_id,
            policy=policy or RetentionPolicy.from_env(),
            dry_run=False,
            api_key_id=api_key_id,
            record_audit=True,
        )

    def _run(
        self,
        *,
        tenant_id: str,
        policy: RetentionPolicy,
        dry_run: bool,
        api_key_id: str | None,
        record_audit: bool,
    ) -> RetentionRunResult:
        started_at = retention_now()
        started_timer = perf_counter()
        resolved_tenant_id = canonicalize_tenant_id(tenant_id)
        jobs = self._job_service.list_jobs(tenant_id=resolved_tenant_id)
        protected_paths = self._collect_protected_artifact_paths(
            jobs=jobs,
            policy=policy,
            now=started_at,
        )
        artifacts, retained_artifacts = self._collect_expired_artifacts(
            jobs=jobs,
            policy=policy,
            now=started_at,
            protected_paths=protected_paths,
        )

        if not dry_run:
            self._delete_artifacts(artifacts)

        llm_cache_removed = 0
        llm_cache_remaining = 0
        llm_cache_ttl_seconds = policy.llm_cache_ttl_seconds()
        if llm_cache_ttl_seconds is not None:
            llm_cache = FileLLMResponseCache.from_env()
            cache_prune = llm_cache.prune_expired(
                ttl_seconds=llm_cache_ttl_seconds,
                dry_run=dry_run,
            )
            llm_cache_removed = cache_prune.removed_entries
            llm_cache_remaining = cache_prune.remaining_entries

        finished_at = retention_now()
        result = RetentionRunResult(
            tenant_id=resolved_tenant_id,
            dry_run=dry_run,
            policy=policy,
            scanned_jobs=len(jobs),
            protected_artifacts=sum(len(paths) for paths in protected_paths.values()),
            retained_artifacts=retained_artifacts,
            artifacts=artifacts,
            llm_cache_entries_removed=llm_cache_removed,
            llm_cache_entries_remaining=llm_cache_remaining,
            started_at=started_at,
            finished_at=finished_at,
        )
        duration_ms = (perf_counter() - started_timer) * 1000.0
        self._emit_log(result, duration_ms=duration_ms)
        if record_audit:
            self._record_audit_event(
                result,
                api_key_id=api_key_id,
                duration_ms=duration_ms,
            )
        return result

    def _collect_protected_artifact_paths(
        self,
        *,
        jobs: list[JobRecord],
        policy: RetentionPolicy,
        now: datetime,
    ) -> dict[str, set[str]]:
        protected_paths: dict[str, set[str]] = {
            config.kind: set() for config in _JOB_ARTIFACT_CONFIGS
        }
        for job in jobs:
            for config in _JOB_ARTIFACT_CONFIGS:
                retention_days = getattr(policy, config.policy_field)
                if retention_days is None:
                    continue

                path = config.resolve_path(job)
                if not path.is_file():
                    continue

                cutoff = policy.cutoff_for(retention_days, now=now)
                if (
                    self._is_active(job)
                    or self._is_explicitly_preserved(job)
                    or (
                        cutoff is not None
                        and self._reference_time(job, path) > cutoff
                    )
                ):
                    protected_paths[config.kind].add(_path_key(path))
        return protected_paths

    def _collect_expired_artifacts(
        self,
        *,
        jobs: list[JobRecord],
        policy: RetentionPolicy,
        now: datetime,
        protected_paths: dict[str, set[str]],
    ) -> tuple[list[RetentionArtifact], int]:
        artifacts: list[RetentionArtifact] = []
        retained_artifacts = 0
        candidate_path_keys: set[tuple[str, str]] = set()

        for job in jobs:
            for config in _JOB_ARTIFACT_CONFIGS:
                retention_days = getattr(policy, config.policy_field)
                if retention_days is None:
                    continue

                path = config.resolve_path(job)
                if not path.is_file():
                    continue

                path_key = _path_key(path)
                if path_key in protected_paths.get(config.kind, set()):
                    retained_artifacts += 1
                    continue

                cutoff = policy.cutoff_for(retention_days, now=now)
                if cutoff is None:
                    continue

                reference_time = self._reference_time(job, path)
                if reference_time > cutoff:
                    retained_artifacts += 1
                    continue

                candidate_key = (config.kind, path_key)
                if candidate_key in candidate_path_keys:
                    continue

                candidate_path_keys.add(candidate_key)
                artifacts.append(
                    RetentionArtifact(
                        kind=config.kind,
                        path=str(path),
                        tenant_id=job.tenant_id,
                        job_id=job.job_id,
                        size_bytes=path.stat().st_size,
                        reference_time=reference_time,
                    )
                )

        return artifacts, retained_artifacts

    def _delete_artifacts(self, artifacts: list[RetentionArtifact]) -> None:
        for artifact in artifacts:
            path = Path(artifact.path)
            path.unlink(missing_ok=True)
            if artifact.kind in _PRUNE_EMPTY_PARENT_KINDS:
                _remove_empty_parent(path)

    def _emit_log(
        self,
        result: RetentionRunResult,
        *,
        duration_ms: float,
    ) -> None:
        log_event(
            _logger,
            "retention.cleanup.completed",
            tenant_id=result.tenant_id,
            duration_ms=duration_ms,
            dry_run=result.dry_run,
            artifact_count=result.artifact_count,
            llm_cache_entries_removed=result.llm_cache_entries_removed,
            retained_artifacts=result.retained_artifacts,
            protected_artifacts=result.protected_artifacts,
        )

    def _record_audit_event(
        self,
        result: RetentionRunResult,
        *,
        api_key_id: str | None,
        duration_ms: float,
    ) -> None:
        if self._audit_service is None:
            return

        self._audit_service.record_event(
            AuditEventType.ARTIFACT_RETENTION_RUN,
            tenant_id=result.tenant_id,
            api_key_id=api_key_id,
            details={
                "dry_run": result.dry_run,
                "duration_ms": duration_ms,
                "policy": result.policy.as_dict(),
                "scanned_jobs": result.scanned_jobs,
                "artifact_count": result.artifact_count,
                "artifacts": [artifact.as_dict() for artifact in result.artifacts],
                "llm_cache_entries_removed": result.llm_cache_entries_removed,
                "llm_cache_entries_remaining": result.llm_cache_entries_remaining,
            },
        )

    def _is_active(self, job: JobRecord) -> bool:
        return job.status in {JobStatus.QUEUED, JobStatus.RUNNING} or job.cancel_requested

    def _is_explicitly_preserved(self, job: JobRecord) -> bool:
        return _truthy(job.params.get(RETENTION_PRESERVE_ARTIFACTS_PARAM))

    def _reference_time(self, job: JobRecord, path: Path) -> datetime:
        job_updated_at = _ensure_utc(job.updated_at)
        path_updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return max(job_updated_at, path_updated_at)


def _path_key(path: Path) -> str:
    return str(path.resolve())


def _remove_empty_parent(path: Path) -> None:
    try:
        path.parent.rmdir()
    except OSError:
        return


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}
