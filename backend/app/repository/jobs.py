"""Durable queue queries with atomic claims, recovery and lease ownership fencing."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import LeaseLostError
from app.models.entities import CollectionJob, Product

ACTIVE = ("queued", "running")


async def get_job(session: AsyncSession, job_id: UUID) -> CollectionJob | None:
    return await session.get(CollectionJob, job_id)


async def latest_collection(session: AsyncSession, product_id: int) -> CollectionJob | None:
    return await session.scalar(
        select(CollectionJob)
        .where(
            CollectionJob.product_id == product_id,
            CollectionJob.kind.in_(("scrape_product", "discover_competitors")),
        )
        .order_by(CollectionJob.created_at.desc(), CollectionJob.id.desc())
        .limit(1)
    )


async def list_jobs(
    session: AsyncSession, status: str | None, page: int, limit: int
) -> tuple[list[CollectionJob], int]:
    query = select(CollectionJob)
    if status is not None:
        query = query.where(CollectionJob.status == status)
    total = (await session.scalar(select(func.count()).select_from(query.subquery()))) or 0
    rows = await session.scalars(
        query.order_by(CollectionJob.created_at.desc(), CollectionJob.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(rows), total


async def last_blocked_at(session: AsyncSession, domain: str) -> datetime | None:
    return await session.scalar(
        select(func.max(func.coalesce(CollectionJob.finished_at, CollectionJob.created_at)))
        .join(Product)
        .where(
            Product.domain == domain,
            CollectionJob.error_code == "blocked",
            CollectionJob.status.in_(("failed", "partial")),
        )
    )


async def active_job(
    session: AsyncSession, kind: str, product_id: int, request_key: str
) -> CollectionJob | None:
    return await session.scalar(
        select(CollectionJob).where(
            CollectionJob.kind == kind,
            CollectionJob.product_id == product_id,
            CollectionJob.request_key == request_key,
            CollectionJob.status.in_(ACTIVE),
        )
    )


async def enqueue(
    session: AsyncSession, kind: str, product_id: int, request_key: str, options: dict[str, Any]
) -> CollectionJob:
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(CollectionJob)
        .values(
            kind=kind,
            product_id=product_id,
            request_key=request_key,
            status="queued",
            result={"request": options},
        )
        .on_conflict_do_nothing()
        .returning(CollectionJob.id)
    )
    job_id = (await session.execute(statement)).scalar_one_or_none()
    if job_id is not None:
        job = await get_job(session, job_id)
    else:
        job = await active_job(session, kind, product_id, request_key)
    if job is None:
        # A concurrently completing worker may remove a conflict from the active set.
        # Use a retryable error instead of creating an unbounded retry loop.
        from app.core.exceptions import ApplicationError

        raise ApplicationError("Job state changed concurrently; retry enqueue", "job_conflict", 409)
    return job


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    lease_token: str
    kind: str
    product_id: int
    asin: str
    domain: str
    geo_key: str
    requested_location: str | None
    attempts: int
    max_attempts: int
    result: dict[str, Any]


async def recover_expired(session: AsyncSession, now: datetime) -> None:
    exhausted = CollectionJob.attempts >= CollectionJob.max_attempts
    await session.execute(
        update(CollectionJob)
        .where(
            or_(
                and_(
                    CollectionJob.status == "running",
                    or_(
                        CollectionJob.lease_expires_at <= now,
                        CollectionJob.lease_expires_at.is_(None),
                    ),
                ),
                and_(CollectionJob.status == "queued", exhausted),
            )
        )
        .values(
            status=case((exhausted, "failed"), else_="queued"),
            progress=case((exhausted, 100), else_=0),
            lease_token=None,
            lease_expires_at=None,
            finished_at=case((exhausted, now), else_=None),
            error_code=case((exhausted, "attempts_exhausted"), else_="lease_expired"),
            error_message="Collection lease expired or retry budget exhausted",
        )
    )


async def claim_next_job(
    session: AsyncSession, lease_seconds: int, cooldown_seconds: int
) -> ClaimedJob | None:
    now = datetime.now(UTC)
    await recover_expired(session, now)
    blocked_job, blocked_product = aliased(CollectionJob), aliased(Product)
    blocked = (
        select(1)
        .select_from(blocked_job)
        .join(blocked_product, blocked_product.id == blocked_job.product_id)
        .where(
            blocked_product.domain == Product.domain,
            blocked_job.status.in_(("failed", "partial")),
            blocked_job.error_code == "blocked",
            func.coalesce(blocked_job.finished_at, blocked_job.created_at)
            > now - timedelta(seconds=cooldown_seconds),
        )
        .correlate(Product)
        .exists()
    )
    eligible = (
        select(CollectionJob.id)
        .join(Product)
        .where(
            CollectionJob.status == "queued",
            CollectionJob.attempts < CollectionJob.max_attempts,
            or_(CollectionJob.kind == "analyze", ~blocked),
        )
        .order_by(CollectionJob.created_at, CollectionJob.id)
        .limit(1)
        .with_for_update(skip_locked=True, of=CollectionJob)
        .scalar_subquery()
    )
    token = str(uuid4())
    row = (
        await session.scalars(
            update(CollectionJob)
            .where(CollectionJob.id == eligible, CollectionJob.status == "queued")
            .values(
                status="running",
                attempts=CollectionJob.attempts + 1,
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                started_at=func.coalesce(CollectionJob.started_at, now),
                finished_at=None,
                progress=0,
                error_code=None,
                error_message=None,
            )
            .returning(CollectionJob)
        )
    ).one_or_none()
    if row is None:
        return None
    product = await session.get(Product, row.product_id)
    if product is None:
        raise LeaseLostError("Claimed product no longer exists")
    return ClaimedJob(
        row.id,
        token,
        row.kind,
        row.product_id,
        product.asin,
        product.domain,
        product.geo_key,
        product.requested_location,
        row.attempts,
        row.max_attempts,
        dict(row.result),
    )


def ownership(job_id: UUID, token: str, now: datetime) -> Any:
    return and_(
        CollectionJob.id == job_id,
        CollectionJob.lease_token == token,
        CollectionJob.status == "running",
        CollectionJob.lease_expires_at > now,
    )


async def lock_owned_job(session: AsyncSession, job_id: UUID, token: str) -> CollectionJob:
    # Conditional UPDATE acquires a row/write lock on PostgreSQL AND SQLite.
    job = (
        await session.scalars(
            update(CollectionJob)
            .where(ownership(job_id, token, datetime.now(UTC)))
            .values(
                lease_expires_at=CollectionJob.lease_expires_at,
            )
            .returning(CollectionJob)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if job is None:
        raise LeaseLostError("Collection job lease is no longer owned")
    return job


async def heartbeat(
    session: AsyncSession, claim: ClaimedJob, lease_seconds: int, progress: int | None = None
) -> bool:
    now = datetime.now(UTC)
    values: dict[str, Any] = {"lease_expires_at": now + timedelta(seconds=lease_seconds)}
    if progress is not None:
        if not 0 <= progress <= 99:
            raise ValueError("Running progress must be between 0 and 99")
        values["progress"] = case(
            (CollectionJob.progress < progress, progress), else_=CollectionJob.progress
        )
    result = await session.scalar(
        update(CollectionJob)
        .where(ownership(claim.id, claim.lease_token, now))
        .values(**values)
        .returning(CollectionJob.id)
    )
    return result is not None


async def finish_job(
    session: AsyncSession,
    claim: ClaimedJob,
    status: str,
    result: dict[str, Any],
    error_code: str | None = None,
    error_message: str | None = None,
) -> bool:
    if status not in ("queued", "succeeded", "partial", "failed", "cancelled"):
        raise ValueError("Invalid collection completion status")
    now = datetime.now(UTC)
    identity = await session.scalar(
        update(CollectionJob)
        .where(ownership(claim.id, claim.lease_token, now))
        .values(
            status=status,
            progress=0 if status == "queued" else 100,
            result=result,
            error_code=error_code,
            error_message=error_message,
            finished_at=None if status == "queued" else now,
            lease_token=None,
            lease_expires_at=None,
        )
        .returning(CollectionJob.id)
    )
    return identity is not None
