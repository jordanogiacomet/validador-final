from __future__ import annotations

import argparse
import os
import socket
from dataclasses import dataclass
from threading import Event

from app.core.logging import configure_logging, get_logger, log_event
from app.services.job_service import DEFAULT_EXECUTION_LEASE_SECONDS, JobService
from app.services.runtime import build_audit_service, build_job_service
from app.services.validation_service import run_validation_job

WORKER_ID_ENV = "VALIDATOR_JOB_WORKER_ID"
WORKER_POLL_INTERVAL_ENV = "VALIDATOR_JOB_WORKER_POLL_INTERVAL_SECONDS"
WORKER_LEASE_SECONDS_ENV = "VALIDATOR_JOB_WORKER_LEASE_SECONDS"

DEFAULT_WORKER_POLL_INTERVAL_SECONDS = 1.0

_logger = get_logger("validation_worker")


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class ValidationWorker:
    job_service: JobService
    worker_id: str
    poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS
    lease_seconds: int = DEFAULT_EXECUTION_LEASE_SECONDS

    def run_once(self) -> bool:
        job = self.job_service.claim_next_job(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return False

        log_event(
            _logger,
            "worker.job_claimed",
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            worker_id=self.worker_id,
        )
        run_validation_job(
            job.job_id,
            self.job_service,
            worker_id=self.worker_id,
            execution_lease_seconds=self.lease_seconds,
        )
        return True

    def run_forever(self, *, stop_event: Event | None = None) -> None:
        active_stop_event = stop_event or Event()
        while not active_stop_event.is_set():
            processed_job = self.run_once()
            if processed_job:
                continue
            active_stop_event.wait(self.poll_interval_seconds)


def build_validation_worker() -> ValidationWorker:
    audit_service = build_audit_service()
    job_service = build_job_service(audit_service=audit_service)
    if not job_service.supports_worker_claims:
        raise RuntimeError(
            "Dedicated worker mode requires SQLite-backed operational storage."
        )

    worker_id = (
        os.getenv(WORKER_ID_ENV, _default_worker_id()).strip()
        or _default_worker_id()
    )
    poll_interval_seconds = float(
        os.getenv(
            WORKER_POLL_INTERVAL_ENV,
            str(DEFAULT_WORKER_POLL_INTERVAL_SECONDS),
        )
    )
    lease_seconds = int(
        os.getenv(WORKER_LEASE_SECONDS_ENV, str(DEFAULT_EXECUTION_LEASE_SECONDS))
    )
    return ValidationWorker(
        job_service=job_service,
        worker_id=worker_id,
        poll_interval_seconds=max(0.1, poll_interval_seconds),
        lease_seconds=max(1, lease_seconds),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the validation job worker.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim at most one job and then exit.",
    )
    args = parser.parse_args()

    configure_logging()
    worker = build_validation_worker()
    if args.once:
        worker.run_once()
        return
    worker.run_forever()


if __name__ == "__main__":
    main()
