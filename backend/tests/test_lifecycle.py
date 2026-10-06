"""Regression tests for browser and database failure/cancellation cleanup."""

import asyncio
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.deps import get_db, get_settings_dep
from app.collector.amazon import AmazonCollector
from app.core.database import create_engine_and_session_factory
from app.main import create_app
from app.models.entities import Product
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


def fake_browser(monkeypatch):
    page = AsyncMock()
    page.set_default_timeout = MagicMock()
    page.set_default_navigation_timeout = MagicMock()
    context = AsyncMock()
    context.new_page.return_value = page
    browser = AsyncMock()
    browser.new_context.return_value = context
    playwright = AsyncMock()
    playwright.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)

    async def stop_manager(*_):
        await playwright.stop()

    manager.__aexit__ = AsyncMock(side_effect=stop_manager)
    monkeypatch.setattr("app.collector.base.async_playwright", lambda: manager)
    return playwright, browser, context, page


@pytest.mark.asyncio
async def test_launch_failure_stops_playwright(monkeypatch, test_settings) -> None:
    playwright, browser, _, _ = fake_browser(monkeypatch)
    playwright.chromium.launch.side_effect = RuntimeError("launch failed")
    collector = AmazonCollector(test_settings)
    with pytest.raises(RuntimeError, match="launch failed"):
        async with collector:
            pytest.fail("Failed startup must not yield the collector")
    playwright.stop.assert_awaited_once()
    browser.close.assert_not_awaited()
    assert collector._playwright is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("driver start failed"), asyncio.CancelledError()])
async def test_partial_playwright_startup_still_closes_manager(
    monkeypatch, test_settings, failure
) -> None:
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(side_effect=failure)
    manager.__aexit__ = AsyncMock()
    monkeypatch.setattr("app.collector.base.async_playwright", lambda: manager)
    collector = AmazonCollector(test_settings)
    with pytest.raises(type(failure)):
        async with collector:
            pytest.fail("Failed driver startup must not yield a collector")
    manager.__aexit__.assert_awaited_once()
    assert collector._playwright_manager is None and collector._playwright is None


@pytest.mark.asyncio
async def test_context_initialization_failure_closes_every_resource(
    monkeypatch, test_settings
) -> None:
    playwright, browser, context, _ = fake_browser(monkeypatch)
    context.add_init_script.side_effect = RuntimeError("script failed")
    collector = AmazonCollector(test_settings)
    with pytest.raises(RuntimeError, match="script failed"):
        async with collector, collector.session("com"):
            pytest.fail("Failed context initialization must not yield a page")
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert not collector._contexts


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("parse failed"), asyncio.CancelledError()])
async def test_page_failure_and_cancellation_close_resources(
    monkeypatch, test_settings, failure
) -> None:
    playwright, browser, context, page = fake_browser(monkeypatch)
    collector = AmazonCollector(test_settings)
    with pytest.raises(type(failure)):
        async with collector, collector.session("com"):
            raise failure
    page.close.assert_awaited_once()
    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    page.set_default_timeout.assert_called_once_with(test_settings.element_timeout_seconds * 1000)
    page.set_default_navigation_timeout.assert_called_once_with(
        test_settings.page_timeout_seconds * 1000
    )


@pytest.mark.asyncio
async def test_cancellation_during_teardown_does_not_stop_cleanup(
    monkeypatch, test_settings
) -> None:
    playwright, browser, context, _ = fake_browser(monkeypatch)
    closing, release = asyncio.Event(), asyncio.Event()

    async def close_context():
        closing.set()
        await release.wait()

    context.close.side_effect = close_context

    async def run():
        async with AmazonCollector(test_settings) as collector, collector.session("com"):
            pass

    task = asyncio.create_task(run())
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_failure_still_stops_browser_and_playwright(monkeypatch, test_settings) -> None:
    playwright, browser, context, _ = fake_browser(monkeypatch)
    context.close.side_effect = RuntimeError("context already gone")
    browser.close.side_effect = RuntimeError("browser already gone")
    async with AmazonCollector(test_settings) as collector, collector.session("com"):
        pass
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_uses_supplied_settings_and_disposes_owned_engine(
    monkeypatch, test_settings
) -> None:
    engine, factory = create_engine_and_session_factory(test_settings)
    disposed = AsyncMock(wraps=engine.dispose)
    monkeypatch.setattr(type(engine), "dispose", disposed)
    created = MagicMock(return_value=(engine, factory))
    monkeypatch.setattr("app.main.create_engine_and_session_factory", created)
    app = create_app(test_settings)
    async with app.router.lifespan_context(app):
        created.assert_called_once_with(test_settings)
        assert app.state.engine is engine
        assert app.state.session_factory is factory
        assert app.state.settings is test_settings
    disposed.assert_awaited_once()
    assert not hasattr(app.state, "engine")


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", [True, False])
async def test_lifespan_disposes_engine_on_startup_or_body_error(
    monkeypatch, test_settings, startup
) -> None:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    engine.begin.side_effect = RuntimeError("startup failed")
    factory = MagicMock()
    monkeypatch.setattr("app.main.create_engine_and_session_factory", lambda _: (engine, factory))
    if not startup:
        test_settings.app_env = "production"
    app = create_app(test_settings)
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            raise RuntimeError("body failed")
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_override_and_request_transaction_boundaries(
    test_settings, test_engine
) -> None:
    app = create_app(test_settings)
    app.state.engine = test_engine

    @app.post("/test-write/{fail}")
    async def write(fail: bool, db: Annotated[AsyncSession, Depends(get_db)]):
        db.add(Product(asin="B000000001" if fail else "B000000002", domain="com"))
        await db.flush()
        if fail:
            raise ValueError("reject write")
        return {"written": True}

    override_settings = test_settings.model_copy(update={"app_name": "Isolated override"})
    app.dependency_overrides[get_settings_dep] = lambda: override_settings
    async with app.router.lifespan_context(app):
        assert app.state.engine is test_engine
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/test-write/true")).status_code == 422
            assert (await client.post("/test-write/false")).status_code == 200
            for url in ("/api/health", "/health"):
                assert (await client.get(url)).json()["app_name"] == "Isolated override"
        async with app.state.session_factory() as db:
            products = (await db.execute(select(Product))).scalars().all()
            assert [p.asin for p in products] == ["B000000002"]
    # An externally supplied engine is still usable after app teardown.
    async with test_engine.connect() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1


@pytest.mark.asyncio
async def test_lifespan_cancellation_finishes_disposal_and_clears_state(
    monkeypatch, test_settings
) -> None:
    closing, release, disposed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    engine = MagicMock()

    async def dispose():
        closing.set()
        await release.wait()
        disposed.set()

    engine.dispose = dispose
    monkeypatch.setattr(
        "app.main.create_engine_and_session_factory", lambda _: (engine, MagicMock())
    )
    test_settings.app_env = "production"
    app = create_app(test_settings)

    async def run():
        async with app.router.lifespan_context(app):
            pass

    task = asyncio.create_task(run())
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert disposed.is_set()
    assert not hasattr(app.state, "engine") and not hasattr(app.state, "session_factory")


@pytest.mark.asyncio
async def test_request_session_rolls_back_on_cancellation(test_settings, test_engine) -> None:
    from app.core.database import get_db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    with pytest.raises(asyncio.CancelledError):
        async with get_db_session(factory) as db:
            db.add(Product(asin="B000000003", domain="com"))
            await db.flush()
            raise asyncio.CancelledError()
    async with factory() as db:
        assert (await db.execute(select(Product))).scalars().all() == []
