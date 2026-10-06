"""Pytest configuration and shared async fixtures for backend tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

# Ensure Playwright finds project-installed browsers
_browsers = Path(__file__).resolve().parents[2] / ".browsers"
if _browsers.exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_browsers)

import pytest
import pytest_asyncio
from app.core.config import Settings
from app.core.database import create_engine_and_session_factory
from app.main import create_app
from app.models.base import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

# Sample Amazon HTML with structured Schema.org JSON-LD
SAMPLE_JSONLD_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Sony WH-1000XM5 Wireless Headphones : Electronics</title>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Sony WH-1000XM5 Noise Canceling Headphones",
        "brand": {
            "@type": "Brand",
            "name": "Sony"
        },
        "image": "https://m.media-amazon.com/images/I/61+ElP4f5yL._AC_SL1500_.jpg",
        "offers": {
            "@type": "Offer",
            "price": "398.00",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
            "url": "https://www.amazon.com/dp/B09XS7JWHH"
        },
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": "4.6",
            "reviewCount": "12845"
        }
    }
    </script>
</head>
<body>
    <div id="dp">
        <h1 id="title"><span id="productTitle">Sony WH-1000XM5 Noise Canceling Headphones</span></h1>
        <div id="wayfinding-breadcrumbs_feature_div">
            <ul>
                <li><a href="#">Electronics</a></li>
                <li><a href="#">Headphones</a></li>
                <li><a href="#">Over-Ear</a></li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

# Sample Amazon HTML without JSON-LD (structured DOM only)
SAMPLE_DOM_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Bose QuietComfort 45 Bluetooth Headphones</title>
</head>
<body>
    <div id="dp">
        <span id="productTitle">  Bose QuietComfort 45 Bluetooth Wireless Headphones  </span>
        <a id="bylineInfo" href="#">Visit the Bose Store</a>
        <div id="corePriceDisplay_desktop_feature_div">
            <span class="a-priceToPay"><span class="a-offscreen">$279.00</span></span>
        </div>
        <div id="acrPopover">
            <span class="a-icon-alt">4.5 out of 5 stars</span>
        </div>
        <span id="acrCustomerReviewText">8,320 ratings</span>
        <div id="availability"><span class="a-color-success">In Stock</span></div>
        <img id="landingImage" src="https://m.media-amazon.com/images/I/bose_qc45.jpg" />
        <div id="wayfinding-breadcrumbs_feature_div">
            <ul>
                <li><a href="#">Electronics</a></li>
                <li><a href="#">Audio</a></li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

# Sample Amazon Search Results HTML
SAMPLE_SEARCH_HTML = """<!DOCTYPE html>
<html>
<head><title>Amazon.com : wireless headphones</title></head>
<body>
    <div data-component-type="s-search-result" data-asin="B09XS7JWHH">
        <h2><a href="/dp/B09XS7JWHH"><span>Sony WH-1000XM5 Headphones</span></a></h2>
        <span class="a-price"><span class="a-offscreen">$398.00</span></span>
        <i class="a-icon-star-small"><span class="a-icon-alt">4.6 out of 5 stars</span></i>
        <span aria-label="12,845 ratings">12,845</span>
    </div>
    <div data-component-type="s-search-result" data-asin="B098FKXT8L">
        <div class="puis-sponsored-label-text">Sponsored</div>
        <h2><a href="/dp/B098FKXT8L"><span>Anker Soundcore Space Q45</span></a></h2>
        <span class="a-price"><span class="a-offscreen">$149.99</span></span>
        <i class="a-icon-star-small"><span class="a-icon-alt">4.4 out of 5 stars</span></i>
        <span aria-label="5,200 ratings">5,200</span>
    </div>
</body>
</html>
"""

# Sample Amazon CAPTCHA Block HTML
SAMPLE_BLOCK_HTML = """<!DOCTYPE html>
<html>
<head><title>Robot Check</title></head>
<body>
    <form action="/errors/validateCaptcha" method="get">
        <input id="captchacharacters" name="field-keywords" />
    </form>
</body>
</html>
"""


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Create isolated test settings with temporary storage and database."""
    db_file = tmp_path / "test.db"
    evidence_path = tmp_path / "evidence"
    evidence_path.mkdir(parents=True, exist_ok=True)

    return Settings(
        app_env="testing",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        evidence_dir=evidence_path,
        min_navigation_interval_seconds=0.0,
        page_timeout_seconds=5,
        element_timeout_seconds=2,
    )


@pytest_asyncio.fixture
async def test_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Create async SQLite engine and initialize tables."""
    engine, _ = create_engine_and_session_factory(test_settings)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide an isolated database session for testing."""
    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(
    test_settings: Settings, test_engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    """Provide an HTTPX AsyncClient bound to the FastAPI test application.

    C-3: The test engine is stored in app.state.engine so the health endpoint
    and all DB dependencies use the isolated test database, not the default SQLite path.
    """
    app = create_app(test_settings)
    # The fixture owns this engine. Lifespan must reuse it and must not dispose it.
    app.state.engine = test_engine
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
