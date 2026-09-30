"""Single-worker durable job runner. Run with ``python -m src.worker``."""

from __future__ import annotations

import logging
import os
import socket
import time

from src.config import get_settings
from src.db import DatabaseError, SQLiteRepository
from src.llm import run_analysis
from src.logging_config import configure_logging
from src.models import Job, JobKind, JobStatus
from src.services import discover_competitors, make_scraper, scrape_context

LOGGER = logging.getLogger(__name__)


def run_job(repo: SQLiteRepository, job: Job) -> None:
    if not job.lease_token:
        raise DatabaseError("Claimed job is missing a lease token")
    settings = get_settings()
    scraper = make_scraper(settings)
    try:
        if job.kind == JobKind.SCRAPE_PRODUCT:
            snapshot_id, failure = scrape_context(repo, scraper, job.context_id, capture_key=job.id)
            status = (
                JobStatus.SUCCEEDED
                if not failure
                else (JobStatus.PARTIAL if snapshot_id else JobStatus.FAILED)
            )
            repo.finish_job(
                job.id,
                job.lease_token,
                status,
                result={"snapshot_id": snapshot_id},
                error_code=failure.code.value if failure else None,
                error_message=failure.message if failure else None,
            )
        elif job.kind == JobKind.DISCOVER_COMPETITORS:
            result = discover_competitors(
                repo,
                scraper,
                job.context_id,
                job.id,
                job.lease_token,
                lambda progress: repo.heartbeat(job.id, job.lease_token or "", progress),
                settings,
            )
            repo.finish_job(
                job.id,
                job.lease_token,
                result.status,
                result={"run_id": result.run_id, "stored_context_ids": result.stored_context_ids},
                error_code=result.failures[0].code.value if result.failures else None,
                error_message=result.failures[0].message if result.failures else None,
            )
        elif job.kind == JobKind.ANALYZE:
            repo.heartbeat(job.id, job.lease_token, 15)
            output = run_analysis(repo, job.context_id, settings)
            repo.finish_job(
                job.id, job.lease_token, JobStatus.SUCCEEDED, result={"analysis": output}
            )
        else:
            repo.finish_job(
                job.id,
                job.lease_token,
                JobStatus.FAILED,
                error_code="unknown_job",
                error_message="Unknown job kind",
            )
    except (
        Exception
    ) as exc:  # Worker boundary: persist safe diagnostic, never leave an owned job running.
        LOGGER.exception("Job failed: %s", job.id)
        repo.finish_job(
            job.id,
            job.lease_token,
            JobStatus.FAILED,
            error_code="worker_error",
            error_message=str(exc),
        )


def run_once(repo: SQLiteRepository, worker_id: str) -> bool:
    job = repo.claim_next_job(worker_id)
    if not job:
        return False
    run_job(repo, job)
    return True


def main() -> None:
    configure_logging(os.getenv("APP_LOG_LEVEL", "INFO"))
    repo = SQLiteRepository()
    repo.migrate()
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    LOGGER.info("Worker %s started", worker_id)
    try:
        while True:
            if not run_once(repo, worker_id):
                time.sleep(1)
    except KeyboardInterrupt:
        LOGGER.info("Worker stopped")


if __name__ == "__main__":
    main()
