"""Collection requests and read-only progress; intentionally no worker execution."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import get_db_session
from app.core.exceptions import CooldownError, NotFoundError, database_error
from app.models.schemas import CollectionJobRead, JobProgress, Page
from app.repository import jobs
from app.services.catalog import CatalogService


class JobService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def enqueue(
        self, product_id: int, kind: str, include_competitors: bool = False
    ) -> CollectionJobRead:
        product = await CatalogService(self.session, self.settings).require_product(product_id)
        options = {"include_competitors": include_competitors}
        key = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
        job = await jobs.active_job(self.session, kind, product_id, key)
        if job is None:
            blocked = await jobs.last_blocked_at(self.session, product.domain)
            if blocked is not None:
                if blocked.tzinfo is None:  # SQLite stores naive UTC.
                    blocked = blocked.replace(tzinfo=UTC)
                remaining = (
                    blocked
                    + timedelta(seconds=self.settings.block_cooldown_seconds)
                    - datetime.now(UTC)
                ).total_seconds()
                if remaining > 0:
                    raise CooldownError(math.ceil(remaining))
            job = await jobs.enqueue(self.session, kind, product_id, key, options)
        await self.session.commit()
        return CollectionJobRead.model_validate(job)

    async def detail(self, job_id: UUID) -> CollectionJobRead:
        row = await jobs.get_job(self.session, job_id)
        if row is None:
            raise NotFoundError("Collection job")
        return CollectionJobRead.model_validate(row)

    async def list(self, status: str | None, page: int, limit: int) -> Page[CollectionJobRead]:
        rows, total = await jobs.list_jobs(self.session, status, page, limit)
        return Page(
            items=[CollectionJobRead.model_validate(row) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )


class JobProgressService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def read(self, job_id: UUID) -> JobProgress:
        # Release the DB connection on every poll, never hold it across socket waits.
        try:
            async with get_db_session(self.factory) as session:
                job = await jobs.get_job(session, job_id)
                if job is None:
                    raise NotFoundError("Collection job")
                return JobProgress.model_validate(job)
        except SQLAlchemyError as exc:
            raise database_error(exc) from exc
