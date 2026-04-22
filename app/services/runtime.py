import os
from pathlib import Path

from app.core.operational_sqlite import OPERATIONAL_SQLITE_PATH_ENV
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.services.retention_service import RetentionService


def build_audit_service() -> AuditService:
    sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV)
    storage_path = os.getenv("VALIDATOR_AUDIT_STORE_PATH")
    return AuditService(
        storage_path=Path(storage_path) if storage_path else None,
        sqlite_path=Path(sqlite_path) if sqlite_path else None,
    )


def build_job_service(*, audit_service: AuditService | None = None) -> JobService:
    sqlite_path = os.getenv(OPERATIONAL_SQLITE_PATH_ENV)
    storage_path = os.getenv("VALIDATOR_JOB_STORE_PATH")
    return JobService(
        storage_path=Path(storage_path) if storage_path else None,
        sqlite_path=Path(sqlite_path) if sqlite_path else None,
        audit_service=audit_service,
    )


def build_retention_service(
    *,
    job_service: JobService,
    audit_service: AuditService | None = None,
) -> RetentionService:
    return RetentionService(
        job_service=job_service,
        audit_service=audit_service,
    )
