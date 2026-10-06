"""Single async worker using the existing durable queue and long-lived collector."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Self

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.errors import AnalysisError
from app.analysis.provider import AnalysisProvider
from app.collector.amazon import AmazonCollector
from app.collector.base import finish_cleanup
from app.collector.errors import TRANSIENT_CODES, ScrapingError
from app.core.config import Settings, get_settings
from app.core.database import create_engine_and_session_factory, get_db_session
from app.core.exceptions import LeaseLostError
from app.models.enums import ScrapeErrorCode
from app.repository import jobs
from app.services.analysis import AnalysisWorkerService
from app.services.collection import CollectionService, collection_error

logger = logging.getLogger(__name__)


class CollectionWorker:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        collector_factory: Callable[[Settings], AmazonCollector] = AmazonCollector,
        analysis_provider: AnalysisProvider | None = None,
    ) -> None:
        self.factory, self.settings, self.collector_factory = factory, settings, collector_factory
        self.collector: AmazonCollector | None = None
        self.analysis_provider = analysis_provider

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.collector is not None:
            collector, self.collector = self.collector, None
            await collector.__aexit__()

    async def browser(self) -> AmazonCollector:
        if self.collector is None:
            collector = self.collector_factory(self.settings)
            try:
                await collector.__aenter__()
            except Exception as exc:
                raise ScrapingError(
                    ScrapeErrorCode.BROWSER_ERROR, "Unable to start collection browser"
                ) from exc
            self.collector = collector
        return self.collector

    async def heartbeat_loop(self, claim: jobs.ClaimedJob) -> None:
        while True:
            await asyncio.sleep(self.settings.worker_heartbeat_seconds)
            async with get_db_session(self.factory) as session:
                if not await jobs.heartbeat(session, claim, self.settings.worker_lease_seconds):
                    raise LeaseLostError("Collection lease expired or was replaced")

    async def finish(
        self,
        claim: jobs.ClaimedJob,
        result: dict[str, Any],
        status: str,
        error: ScrapingError | None = None,
    ) -> None:
        async with get_db_session(self.factory) as session:
            await jobs.finish_job(
                session,
                claim,
                status,
                result,
                error.code.value if error else None,
                str(error) if error else None,
            )

    async def execute(self, claim: jobs.ClaimedJob) -> None:
        service: CollectionService | AnalysisWorkerService | None = None
        heartbeat: asyncio.Task[None] | None = None
        operation: asyncio.Task[None] | None = None
        result = dict(claim.result)
        try:
            # Keep the lease alive while browser startup, navigation or storage is awaiting.
            heartbeat = asyncio.create_task(self.heartbeat_loop(claim))

            async def collect() -> None:
                nonlocal service
                if claim.kind == "analyze":
                    service = AnalysisWorkerService(
                        self.factory, self.settings, claim, self.analysis_provider
                    )
                    await service.run()
                    return
                if claim.kind not in ("scrape_product", "discover_competitors"):
                    raise ScrapingError(
                        ScrapeErrorCode.INVALID_INPUT, "Unsupported collection job kind"
                    )
                collector = await self.browser()
                service = CollectionService(self.factory, self.settings, collector, claim)
                await service.run()

            operation = asyncio.create_task(collect())
            done, _ = await asyncio.wait(
                (heartbeat, operation), return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                await heartbeat
            await operation
            assert service is not None
            result = service.result
            failures = result.get("failures", [])
            error = (
                ScrapingError(ScrapeErrorCode(failures[0]["code"]), failures[0]["message"])
                if failures
                else None
            )
            await self.finish(claim, result, "partial" if failures else "succeeded", error)
        except asyncio.CancelledError:

            async def cancel_collection() -> None:
                if operation is not None:
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                await self.finish(
                    claim,
                    service.result if service else result,
                    "cancelled",
                    ScrapingError(ScrapeErrorCode.CANCELLED, "Collection worker was stopped"),
                )

            await finish_cleanup(cancel_collection())
            raise
        except LeaseLostError:
            logger.warning("Stopped stale collection job %s", claim.id)
        except AnalysisError as exc:
            async with get_db_session(self.factory) as session:
                await jobs.finish_job(
                    session,
                    claim,
                    "failed",
                    service.result if service else result,
                    "analysis_failed",
                    str(exc),
                )
        except Exception as exc:  # noqa: BLE001 -- Persist a safe terminal outcome at the worker boundary.
            logger.error("Collection job %s failed: %s", claim.id, type(exc).__name__)
            result = service.result if service else result
            error = collection_error(exc)
            result.setdefault("failures", []).append(
                {"asin": claim.asin, "code": error.code.value, "message": str(error)}
            )
            has_observations = bool(result.get("observation_ids"))
            retry = (
                not has_observations
                and error.code in TRANSIENT_CODES
                and claim.attempts < claim.max_attempts
            )
            await self.finish(
                claim,
                result,
                "queued" if retry else "partial" if has_observations else "failed",
                error,
            )
            if error.code == ScrapeErrorCode.BROWSER_ERROR and self.collector is not None:
                collector, self.collector = self.collector, None
                await collector.__aexit__()
        finally:

            async def stop_tasks() -> None:
                running = [task for task in (operation, heartbeat) if task is not None]
                for task in running:
                    task.cancel()
                await asyncio.gather(*running, return_exceptions=True)

            await finish_cleanup(stop_tasks())

    async def run_once(self) -> bool:
        async with get_db_session(self.factory) as session:
            claim = await jobs.claim_next_job(
                session, self.settings.worker_lease_seconds, self.settings.block_cooldown_seconds
            )
        if claim is None:
            return False
        await self.execute(claim)
        return True

    async def run(self) -> None:
        while True:
            try:
                if await self.run_once():
                    continue
            except SQLAlchemyError as exc:
                # Durable leases permit recovery after temporary DB unavailability.
                logger.error("Worker database unavailable: %s", type(exc).__name__)
            await asyncio.sleep(self.settings.worker_poll_interval)


async def worker_main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    engine, factory = create_engine_and_session_factory(settings)
    try:
        async with CollectionWorker(factory, settings) as worker:
            await worker.run()
    finally:
        await finish_cleanup(engine.dispose())


def main() -> None:
    try:
        asyncio.run(worker_main())
    except KeyboardInterrupt:
        logger.info("Collection worker stopped")


if __name__ == "__main__":
    main()
