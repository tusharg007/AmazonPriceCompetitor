"""Application use cases. UI and browser libraries stay outside this boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from src.config import Settings, get_settings
from src.db import SQLiteRepository
from src.models import (
    CollectionContext,
    CompetitorRunResult,
    ItemFailure,
    JobStatus,
    ProductKey,
    ScrapeErrorCode,
)
from src.scraping.amazon import AmazonSeleniumScraper
from src.scraping.parsers import normalized_query


def create_tracked_context(
    repo: SQLiteRepository, asin: str, domain: str, location: str | None
) -> CollectionContext:
    return repo.get_or_create_context(ProductKey(asin, domain), location, tracked=True)


def scrape_context(
    repo: SQLiteRepository,
    scraper: AmazonSeleniumScraper,
    context_id: int,
    *,
    capture_key: str | None = None,
) -> tuple[int | None, ItemFailure | None]:
    context = repo.get_context(context_id)
    if not context:
        return None, ItemFailure(
            None, ScrapeErrorCode.INVALID_INPUT, "Product context no longer exists"
        )
    outcome = scraper.scrape_product(context)
    if outcome.snapshot is None:
        return None, ItemFailure(
            context.key.asin,
            outcome.code or ScrapeErrorCode.PARSE_ERROR,
            outcome.message or "No product data",
        )
    snapshot = (
        replace(outcome.snapshot, capture_key=f"{capture_key}:{context.id}")
        if capture_key
        else outcome.snapshot
    )
    snapshot_id = repo.save_snapshot(snapshot)
    if outcome.code:
        return snapshot_id, ItemFailure(
            context.key.asin, outcome.code, outcome.message or outcome.code.value
        )
    return snapshot_id, None


def discover_competitors(
    repo: SQLiteRepository,
    scraper: AmazonSeleniumScraper,
    context_id: int,
    job_id: str,
    lease_token: str,
    progress: Callable[[int], bool],
    settings: Settings | None = None,
) -> CompetitorRunResult:
    settings = settings or get_settings()
    parent = repo.get_context(context_id)
    if not parent:
        return CompetitorRunResult(
            None,
            JobStatus.FAILED,
            failures=(
                ItemFailure(None, ScrapeErrorCode.INVALID_INPUT, "Product context does not exist"),
            ),
        )

    parent_snapshot_id, parent_failure = scrape_context(
        repo, scraper, context_id, capture_key=job_id
    )
    if parent_snapshot_id is None:
        return CompetitorRunResult(
            None, JobStatus.FAILED, failures=(parent_failure,) if parent_failure else ()
        )
    parent_snapshot = repo.get_snapshot(parent_snapshot_id)
    assert parent_snapshot is not None
    title = parent_snapshot.get("title")
    if not title:
        return CompetitorRunResult(
            None,
            JobStatus.FAILED,
            failures=(
                ItemFailure(
                    parent.key.asin, ScrapeErrorCode.PARSE_ERROR, "Parent title is missing"
                ),
            ),
        )

    run_id = repo.create_competitor_run(context_id, parent_snapshot_id, job_id)
    candidates, failures = scraper.discover(
        parent, normalized_query(title), settings.max_search_pages
    )
    candidates = [candidate for candidate in candidates if not candidate.sponsored][
        : settings.max_competitors
    ]
    stored: list[tuple[int, int, int, str, bool, float | None]] = []
    total = max(len(candidates), 1)
    for index, candidate in enumerate(candidates, start=1):
        if not progress(int((index - 1) / total * 90) + 5):
            failures.append(
                ItemFailure(candidate.asin, ScrapeErrorCode.CANCELLED, "Job lease was lost")
            )
            break
        competitor = repo.get_or_create_context(
            ProductKey(candidate.asin, parent.key.domain), parent.requested_location
        )
        snapshot_id, failure = scrape_context(repo, scraper, competitor.id, capture_key=job_id)
        if snapshot_id is not None:
            stored.append(
                (
                    competitor.id,
                    snapshot_id,
                    candidate.rank,
                    candidate.query,
                    candidate.sponsored,
                    None,
                )
            )
        if failure:
            failures.append(failure)
        progress(int(index / total * 90) + 5)
    status = JobStatus.SUCCEEDED if not failures else JobStatus.PARTIAL
    if not candidates and failures:
        status = JobStatus.FAILED
    published = repo.publish_competitor_run(
        run_id,
        status,
        stored,
        [{"asin": f.asin, "code": f.code.value, "message": f.message} for f in failures],
        job_id,
        lease_token,
    )
    if not published:
        return CompetitorRunResult(
            run_id,
            JobStatus.FAILED,
            tuple(context_id for context_id, *_ in stored),
            tuple(failures),
        )
    return CompetitorRunResult(
        run_id, status, tuple(context_id for context_id, *_ in stored), tuple(failures)
    )


def make_scraper(settings: Settings | None = None) -> AmazonSeleniumScraper:
    return AmazonSeleniumScraper(settings or get_settings())
