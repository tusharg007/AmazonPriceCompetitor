"""Small durable job API used by Streamlit and the worker."""

from __future__ import annotations

from src.db import DatabaseError, SQLiteRepository
from src.models import Job, JobKind


def enqueue_scrape(repo: SQLiteRepository, context_id: int) -> Job:
    return repo.enqueue_job(JobKind.SCRAPE_PRODUCT, context_id, "scrape-product")


def enqueue_competitors(repo: SQLiteRepository, context_id: int) -> Job:
    if repo.get_latest_snapshot(context_id) is None:
        raise DatabaseError("Scrape the product successfully before refreshing competitors")
    return repo.enqueue_job(JobKind.DISCOVER_COMPETITORS, context_id, "discover-competitors")


def enqueue_analysis(repo: SQLiteRepository, context_id: int) -> Job:
    if repo.get_analysis_run(context_id) is None:
        raise DatabaseError("Collect at least one competitor before running analysis")
    return repo.enqueue_job(JobKind.ANALYZE, context_id, "analyze-current-run")
