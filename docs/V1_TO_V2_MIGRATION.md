# V1 → V2 Migration Guide: Amazon Competitor Intelligence

This document maps every V1 component to its V2 fate, explains what changes and why, and
provides a concrete data-migration path and risk register for the transition.

---

## 1. Migration Overview

### V1 → V2 Component Fate

| V1 File | V1 Role | V2 Fate | Action |
|---|---|---|---|
| `main.py` | Streamlit UI + job dispatch | React/TypeScript SPA | **Rewrite** |
| `src/config.py` | Env-var dataclass | `pydantic-settings` BaseSettings | **Adapt** |
| `src/db.py` | SQLite repository (754 lines) | Async PostgreSQL repositories | **Rewrite** |
| `src/jobs.py` | Job dispatch helpers (26 lines) | FastAPI endpoints + PG queue | **Rewrite** |
| `src/llm.py` | LangChain/Groq analysis pipeline | Same pipeline + evidence linking | **Adapt** |
| `src/logging_config.py` | JSON structured logging | `structlog` (or direct port) | **Reuse** |
| `src/models.py` | Frozen dataclasses | Pydantic BaseModel | **Adapt** |
| `src/relevance.py` | Deterministic competitor filter | Direct copy as-is | **Reuse** |
| `src/services.py` | Orchestration layer | FastAPI async service layer | **Adapt** |
| `src/worker.py` | Single-worker polling daemon | Async PostgreSQL job worker | **Adapt** |
| `src/scraping/amazon.py` | Selenium scraper (517 lines) | Playwright scraper | **Rewrite** |
| `src/scraping/browser.py` | Chrome session + profile lock | Playwright context manager | **Rewrite** |
| `src/scraping/errors.py` | Scraping error codes/exceptions | Direct copy as-is | **Reuse** |
| `src/scraping/parsers.py` | Pure text parsing functions | Direct copy as-is | **Reuse** |
| `src/scraping/selectors.py` | CSS selector chains | Direct copy as-is | **Reuse** |
| `migrations/*.sql` | SQLite schema via custom runner | Alembic + PostgreSQL | **Rewrite** |
| `scripts/db_admin.py` | SQLite admin CLI | PostgreSQL admin utilities | **Rewrite** |
| `scripts/migrate_tinydb.py` | TinyDB → SQLite migration | Not needed (TinyDB dropped) | **Drop** |

---

## 2. What to Reuse Directly

These modules are pure logic with zero framework dependencies. Copy them verbatim into
`backend/app/scraper/` and run the existing V1 tests against the V2 copies to confirm nothing broke.

### `src/scraping/parsers.py` → `backend/app/scraper/parsers.py`

All 6 functions are pure Python with no imports beyond stdlib `re` and `decimal`:

| Function | Purpose | Tests to Port |
|---|---|---|
| `clean_text(value)` | Normalizes whitespace, `\xa0` | V1 `test_models.py` has indirect coverage |
| `parse_decimal_price(text, domain)` | Multi-locale price + currency | V1 `test_models.py` parametrized cases |
| `parse_rating(text)` | Star rating from "4.7 out of 5 stars" | V1 `test_models.py` comma-decimal case |
| `parse_count(text)` | Review count from "12,450 ratings" | Covered in V1 unit tests |
| `product_asin_from_url(url)` | ASIN from `/dp/` or `/gp/product/` URL | Trivial regex — add V2 unit test |
| `normalized_query(title)` | Title → search query (truncate to 180 chars) | Port from V1 |

> **Note**: The `CURRENCY_BY_DOMAIN` and `SYMBOL_TO_CURRENCY` constants at the top of `parsers.py`
> need one addition for V2: check that any new marketplace domains added to V2 config have entries.

### `src/scraping/selectors.py` → `backend/app/scraper/selectors.py`

The CSS selector tuples work identically in Playwright. No changes needed. The V2 scraper iterates them with:

```python
for selector in selectors.TITLE:
    locator = page.locator(selector)
    if await locator.count() > 0:
        text = await locator.first.text_content()
        if text:
            return clean_text(text)
```

### `src/scraping/errors.py` → `backend/app/scraper/errors.py`

`ScrapeErrorCode` (StrEnum) and `ScrapingError(RuntimeError)` are fully reusable. The
`TRANSIENT_CODES` set also carries forward unchanged.

### `src/relevance.py` → `backend/app/services/matching.py` (or its own module)

`select_comparable_competitors()` and `_brand()` are pure functions operating on plain dicts.
They don't touch Selenium, SQLite, or Streamlit. Port them verbatim — V1's test suite
(`test_relevance.py`) transfers completely.

The V2 matching service calls these functions as Phase 1 of the matching pipeline, then adds
scored matching on top. The exclusion audit dict (`{"compatibility listing": 2, ...}`) feeds
directly into the `match_evidence` table.

### `src/logging_config.py` → Direct port or replace with `structlog`

V1's `JsonFormatter` is 20 lines and produces clean JSON log lines. Either copy it directly or
replace with `structlog` configured to emit JSON — both work. No business logic lives here.

---

## 3. What to Adapt

These components have the right design intent but need modifications for the V2 stack.

### `src/config.py` → `backend/app/core/config.py`

**What changes**: Switch from a hand-rolled `dataclass` with manual `os.getenv()` calls to
`pydantic-settings BaseSettings`.

**What stays**: All existing config field names and defaults. Add new fields:

```python
class Settings(BaseSettings):
    # Preserved from V1 (renamed where appropriate)
    app_groq_api_key: str
    app_groq_model: str = "openai/gpt-oss-20b"
    app_browser_headless: bool = True
    app_browser_no_sandbox: bool = False
    app_browser_disable_dev_shm_usage: bool = False
    app_page_timeout_seconds: int = 30
    app_element_timeout_seconds: int = 10
    app_min_navigation_interval_seconds: float = 2.0
    app_max_search_pages: int = 2
    app_max_competitors: int = 20
    app_challenge_wait_seconds: int = 300
    app_block_cooldown_seconds: int = 300

    # New in V2
    database_url: str  # postgresql+asyncpg://...
    evidence_dir: Path = Path("evidence")
    app_worker_poll_interval: float = 1.0
    app_max_concurrent_jobs: int = 1  # single worker for portfolio

    model_config = SettingsConfigDict(env_file=".env")
```

### `src/models.py` → `backend/app/models/domain.py` + `schemas.py`

**What changes**: Convert frozen `dataclasses` to Pydantic `BaseModel` for FastAPI integration.
The validation logic (ASIN regex, domain normalization, geo normalization, delivery location
rules) all carry forward as `@field_validator` methods.

**Migration of key types**:

| V1 Dataclass | V2 Pydantic Model | Changes |
|---|---|---|
| `ProductKey` | Internal helper / validator | Keep as frozen `dataclass` or `@model_validator` |
| `CollectionContext` | `Product` DB model | Fields split: product + context merged |
| `ProductSnapshot` | `ProductObservation` | Renamed; `capture_key` removed (append-only) |
| `SearchCandidate` | `SearchCandidate` | Unchanged |
| `Job` | `CollectionJob` | Renamed; `lease_token` etc. preserved |
| `ScrapeOutcome` | `ScrapeOutcome` | Unchanged |
| `AnalysisOutput` | `AnalysisResult` | Expanded with `claims: list[AnalysisClaim]` |

**What stays**: All enum values (`JobKind`, `JobStatus`, `ScrapeErrorCode`, `LocationStatus`) are
StrEnums — copy them verbatim. All normalization functions (`normalize_asin`, `normalize_domain`,
`normalize_geo`, `validate_delivery_location`) transfer without changes.

### `src/llm.py` → `backend/app/llm/engine.py`

**What changes**:
1. `build_analysis_input()` now reads from PostgreSQL async repository instead of `SQLiteRepository`.
2. The `_analysis_record()` function gets an `observation_id` field added — this ID is included in the evidence payload so the LLM response can be linked back to specific observations.
3. After `run_analysis()` saves the LLM output, a new step creates `analysis_claims` rows and `claim_evidence` rows linking numerical claims to their source observations.

**What stays** (verbatim):
- The full prompt template (evidence-as-untrusted-data instruction)
- `LLMAnalysis` and `LLMCompetitorInsight` Pydantic models
- `_normalize_analysis_payload()` list/scalar drift repair
- `_schema_failure()` + `_failed_generation()` Groq error recovery
- `_bounded_analysis()` with ASIN hallucination check and text truncation
- `input_hash` SHA-256 deduplication
- Three-tier schema resilience: strict → `failed_generation` → `json_mode`

**Evidence-linking addition** (new in V2):

```python
def _build_claim_evidence(
    output: LLMAnalysis,
    evidence: dict,
) -> list[ClaimEvidence]:
    """Map each LLM competitor insight to its source observation_id."""
    obs_by_asin = {row["asin"]: row["observation_id"] for row in evidence["competitors"]}
    claims = []
    for insight in output.top_competitors:
        obs_id = obs_by_asin.get(insight.asin)
        if obs_id:
            claims.append(
                ClaimEvidence(
                    observation_id=obs_id,
                    role="competitor",
                    asin=insight.asin,
                )
            )
    return claims
```

### `src/services.py` → `backend/app/services/collection.py`

**What changes**: Refactor the synchronous orchestration functions into `async def` coroutines
that accept an asyncpg connection/pool rather than `SQLiteRepository`. The structure maps 1:1:

| V1 Function | V2 Function | Change |
|---|---|---|
| `create_tracked_context()` | `create_tracked_product()` | Async, PostgreSQL |
| `scrape_context()` | `scrape_and_store()` | Async; saves to `product_observations` |
| `discover_competitors()` | `discover_competitors()` | Async; uses Playwright instead of Selenium |
| `make_scraper()` | `make_playwright_scraper()` | Returns Playwright-based scraper |

**What stays**: The orchestration sequence is identical:
1. Scrape parent product → save observation
2. Run search → collect candidates
3. Filter sponsored ads
4. Scrape each candidate → save observations
5. Publish results with progress heartbeats
6. Handle BLOCKED → cooldown, CANCELLED → stop

### `src/worker.py` → `backend/app/worker/runner.py`

**What changes**:
- Replace SQLite job claiming with PostgreSQL `FOR UPDATE SKIP LOCKED`.
- Replace `time.sleep(1)` poll loop with async `asyncio.sleep()`.
- Replace `ExitStack` browser cleanup with `async with playwright.chromium.launch_persistent_context()`.
- Worker runs as a separate `asyncio` task or a separate process, not a threading-based Streamlit workaround.

**What stays**: The job dispatch logic, lease/heartbeat pattern, `challenge_notice` callback,
`run_job()` structure, error boundary with `finish_job()` on exception.

---

## 4. What to Rewrite

### `main.py` → React/TypeScript SPA (`frontend/`)

V1's Streamlit UI is a single 244-line Python file managing session state (`st.session_state`),
polling via `@st.fragment`, and rendering markdown analysis. This is replaced entirely by a
proper React application:

- **Dashboard page**: TanStack Query fetches `/api/products` — no manual polling.
- **Job progress**: WebSocket connection to `/ws/jobs/{id}` — no Streamlit fragment tricks.
- **Price charts**: Recharts `LineChart` with `product_observations` time-series data.
- **Evidence links**: Click on any claim number to see the source HTML snapshot.

There is no code reuse between Streamlit Python and React TypeScript.

### `src/db.py` → `backend/app/repository/` (multiple modules)

V1's `db.py` is a 754-line monolith mixing schema migration, product storage, job queue,
competitor runs, and analyses. In V2 this splits into focused repository modules:

| V1 `db.py` method group | V2 Repository module |
|---|---|
| `migrate()`, `health()`, schema_migrations | Alembic + `core/database.py` |
| `get_or_create_context()`, `get_context()`, `list_tracked_contexts()` | `repository/products.py` |
| `save_snapshot()`, `get_snapshot()`, `get_latest_snapshot()` | `repository/observations.py` |
| `enqueue_job()`, `claim_next_job()`, `heartbeat()`, `finish_job()` | `repository/jobs.py` |
| `create_competitor_run()`, `publish_competitor_run()`, `get_competitor_rows()` | `repository/competitors.py` |
| `save_analysis()`, `latest_analysis()` | `repository/analysis.py` |

The design principles carry over: short transactions, no shared connections, explicit repository
methods, no raw SQL leaking outside the repository layer.

### `src/scraping/amazon.py` → `backend/app/scraper/amazon.py`

The biggest single rewrite. The 517-line Selenium scraper becomes a Playwright scraper with
the same logical structure but a completely different API:

| V1 (Selenium) | V2 (Playwright) |
|---|---|
| `WebDriverWait(driver, timeout).until(fn)` | `page.locator(selector).wait_for(timeout=ms)` |
| `driver.find_element(By.CSS_SELECTOR, sel)` | `page.locator(selector)` |
| `element.get_attribute("src")` | `await locator.get_attribute("src")` |
| `driver.get(url)` | `await page.goto(url)` |
| `_text(driver, selectors.TITLE, 10)` | `await _text(page, selectors.TITLE)` |
| `AmazonSeleniumScraper` | `AmazonPlaywrightScraper` |
| `chrome_session()` context manager | `async with browser_context() as ctx` |
| `StaleElementReferenceException` handling | Auto-waiting eliminates most cases |
| `time.sleep(delay)` | `await asyncio.sleep(delay)` |

The `_capture_key` logic is dropped — V2 uses a pure append-only model so no deduplication
hash is needed per scrape.

### `src/scraping/browser.py` → `backend/app/scraper/browser.py`

V1's browser.py handles Chrome option building, OS profile locks, and `webdriver.Chrome`
or `webdriver.Remote` startup. V2 replaces this:

```python
from playwright.async_api import async_playwright, BrowserContext


async def browser_context(settings: Settings, domain: str) -> AsyncIterator[BrowserContext]:
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=settings.browser_profile_dir / domain,
            headless=settings.app_browser_headless,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            args=["--no-sandbox"] if settings.app_browser_no_sandbox else [],
        )
        try:
            yield ctx
        finally:
            await ctx.close()
```

The OS-level profile lock (`msvcrt`/`fcntl`) is not needed in V2 because the single-worker
model means only one process touches a given browser context at a time.

---

## 5. What to Drop

| V1 Pattern | Why Dropped |
|---|---|
| `st.session_state`, `st.fragment`, `st.rerun` | Streamlit removed — React handles state |
| `@st.fragment(run_every=...)` | Replaced by WebSocket job progress |
| `PRAGMA journal_mode = WAL`, `PRAGMA foreign_keys = ON` | SQLite-specific — Postgres handles this |
| `BEGIN IMMEDIATE` | PostgreSQL uses `BEGIN`; `SKIP LOCKED` for queuing |
| `undetected-chromedriver` | Playwright stealth replaces this |
| `selenium.webdriver`, `By`, `WebDriverWait` | Entire Selenium stack removed |
| `StaleElementReferenceException` handling | Playwright auto-wait eliminates most occurrences |
| `tinydb` / `scripts/migrate_tinydb.py` | TinyDB is gone; legacy import table not needed |
| `legacy_imports` table | No TinyDB data to migrate in V2 |
| `SQLITE_MINIMUM_VERSION` check | SQLite not used in V2 |
| In-memory job dict (`JobManager` from earlier V1 iterations) | Not present in current V1, confirmed dropped |

---

## 6. Data Migration (SQLite → PostgreSQL)

If you have real product data in the V1 SQLite database that you want to preserve in V2,
use this migration path.

### Schema Mapping

| V1 SQLite Table | V2 PostgreSQL Table | Column Changes |
|---|---|---|
| `products` | `products` | `id` stays INTEGER PK; add `updated_at`; expand domain CHECK |
| `product_contexts` | `products` (merged) | `geo_key`, `requested_location`, `is_tracked` become columns on `products` |
| `product_snapshots` | `product_observations` | Rename; drop `capture_key` (not needed append-only); add `job_id UUID FK`; `price_amount` stays TEXT/NUMERIC |
| `jobs` | `collection_jobs` | UUID PK stays TEXT in V1, becomes UUID in V2; add `max_attempts` |
| `competitor_runs` | Dissolved into `collection_jobs` + `competitor_matches` | `competitor_run_items` becomes `competitor_matches` rows |
| `competitor_run_items` | `competitor_matches` | `snapshot_id` → `competitor_observation_id`; add `match_score`, `match_method` |
| `analyses` | `analysis_runs` | `output_json` → separate `analysis_claims` rows; keep `input_hash`, `model` |
| `marketplace_cooldowns` | `collection_jobs` metadata / settings table | Small table; can be application-level config |
| `schema_migrations` | Alembic `alembic_version` | Replace custom runner with Alembic |
| `legacy_imports` | Not migrated | V2 does not support TinyDB import |

### Migration Script Outline

```python
"""
scripts/migrate_v1_to_v2.py
Reads V1 SQLite database, inserts records into V2 PostgreSQL.
Safe to run multiple times (idempotent via ON CONFLICT DO NOTHING).
"""

import sqlite3
import asyncpg
import asyncio
from decimal import Decimal
from pathlib import Path

SQLITE_PATH = "data/amazon_competitor.sqlite3"
PG_DSN = "postgresql://user:pass@localhost/aci_v2"


async def migrate_products(sqlite: sqlite3.Connection, pg: asyncpg.Connection) -> dict[int, int]:
    """Returns mapping of old product_context.id → new product.id."""
    rows = sqlite.execute(
        "SELECT c.id, p.asin, p.amazon_domain, c.geo_key, "
        "c.requested_location, c.is_tracked, c.created_at "
        "FROM product_contexts c JOIN products p ON p.id = c.product_id"
    ).fetchall()
    mapping = {}
    for row in rows:
        new_id = await pg.fetchval(
            "INSERT INTO products(asin, domain, geo_key, requested_location, "
            "is_tracked, created_at, updated_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$6) "
            "ON CONFLICT(asin, domain, geo_key) DO UPDATE SET updated_at=NOW() "
            "RETURNING id",
            row["asin"],
            row["amazon_domain"],
            row["geo_key"],
            row["requested_location"],
            bool(row["is_tracked"]),
            row["created_at"],
        )
        mapping[row["id"]] = new_id
    return mapping


async def migrate_observations(
    sqlite: sqlite3.Connection, pg: asyncpg.Connection, product_map: dict[int, int]
) -> dict[int, str]:
    """Returns mapping of old snapshot.id → new observation.id (UUID)."""
    rows = sqlite.execute("SELECT * FROM product_snapshots ORDER BY captured_at").fetchall()
    mapping = {}
    for row in rows:
        new_product_id = product_map.get(row["context_id"])
        if not new_product_id:
            continue
        new_id = await pg.fetchval(
            "INSERT INTO product_observations("
            "  product_id, price_amount, price_text, currency, availability, "
            "  rating, rating_count, location_status, canonical_url, "
            "  source, captured_at, created_at"
            ") VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'selenium-v1',$10,$10) "
            "RETURNING id",
            new_product_id,
            Decimal(row["price_amount"]) if row["price_amount"] else None,
            row["price_text"],
            row["currency"],
            row["availability"],
            row["rating"],
            row["rating_count"],
            row["location_status"],
            row["canonical_url"],
            row["captured_at"],
        )
        mapping[row["id"]] = str(new_id)
    return mapping


async def main():
    sqlite = sqlite3.connect(SQLITE_PATH)
    sqlite.row_factory = sqlite3.Row
    pg = await asyncpg.connect(PG_DSN)
    product_map = await migrate_products(sqlite, pg)
    obs_map = await migrate_observations(sqlite, pg, product_map)
    print(f"Migrated {len(product_map)} products, {len(obs_map)} observations")
    await pg.close()
    sqlite.close()


asyncio.run(main())
```

> **Preserving history**: V1's snapshot history is fully preserved — each `product_snapshot`
> row becomes a separate `product_observation`. The `capture_key` column is dropped since V2
> is append-only, but all price/rating/availability data survives.

---

## 7. Dependency Changes

### Backend (Python)

| V1 Dependency | Version | V2 Replacement | Version | Reason |
|---|---|---|---|---|
| `selenium` | ≥4.27 | `playwright` | ≥1.44 | Async, auto-wait, less flaky |
| `streamlit` | ≥1.54 | *(removed)* | — | Replaced by React frontend |
| `langchain` | ≥1.3.9 | `langchain` | ≥1.3.9 | **Preserved** — keep exact version |
| `langchain-groq` | ≥1.1.0 | `langchain-groq` | ≥1.1.0 | **Preserved** |
| `pydantic` | ≥2.11 | `pydantic` | ≥2.11 | **Preserved** + expand for FastAPI |
| `python-dotenv` | ≥1.2 | `pydantic-settings` | ≥2.3 | Type-safe env parsing |
| *(not present)* | — | `fastapi` | ≥0.111 | REST API framework |
| *(not present)* | — | `uvicorn` | ≥0.30 | ASGI server |
| *(not present)* | — | `asyncpg` | ≥0.29 | Async PostgreSQL driver |
| *(not present)* | — | `alembic` | ≥1.13 | Schema migrations |
| *(not present)* | — | `structlog` | ≥24.1 | Structured logging |
| *(not present)* | — | `httpx` | ≥0.27 | Async HTTP for testing |

### Frontend (Node/TypeScript)

| New Dependency | Purpose |
|---|---|
| `react` + `react-dom` (18) | UI framework |
| `vite` | Build tool + dev server |
| `typescript` | Type safety |
| `tailwindcss` | Utility-first styling |
| `recharts` | Price history line charts |
| `@tanstack/react-query` | API data fetching/caching |
| `react-router-dom` | Client-side routing |
| `vitest` | Component testing |
| `@testing-library/react` | React Testing Library |
| `msw` (Mock Service Worker) | API mocking for tests |
| `eslint` + `prettier` | Linting and formatting |

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Playwright detected as bot** | Medium | High — scraping blocked | Use `playwright-stealth`; test early against live Amazon; have headed recovery path; accept rate limits as feature not bug |
| **Amazon DOM changes during development** | High | Medium — broken selectors | Keep `selectors.py` as single-file authority; add fixture-based tests for each selector group; monitor V1 while building V2 |
| **PostgreSQL complexity vs SQLite zero-config** | Low | Medium — setup friction | Docker Compose hides all PG complexity; `make dev` starts everything; Alembic auto-applies migrations on startup |
| **Frontend rewrite scope** | High | Medium — schedule overrun | Hard MVP boundary: Dashboard + PriceChart + CompetitorTable only; no auth, no settings page in MVP |
| **LLM provider API changes (Groq)** | Low | Medium — analysis breaks | V1's three-tier fallback already handles Groq quirks; isolate provider behind `engine.py`; Groq API is stable |
| **asyncpg learning curve** | Low | Low | asyncpg is well-documented; SQLAlchemy Core (async) is an alternative if raw asyncpg is uncomfortable |
| **Evidence file storage at scale** | Low | Low | HTML snapshots are ~50–200KB each; at 20 competitors × daily scrapes = manageable on a local disk for a portfolio project |
| **Playwright persistent context profile corruption** | Low | Medium | V2 uses per-domain profiles same as V1; single worker owns profile; file locking not needed with single worker |
| **Groq model name changes** | Medium | Low | Model name is a config value (`app_groq_model`); updating takes 30 seconds |

---

## 9. Migration Order (Recommended Sequence)

This sequence minimizes blocked work and ensures every phase is independently testable.

### Phase 1: Repository Skeleton (Days 1–3)
- Initialize monorepo: `backend/` (Python) and `frontend/` (TypeScript) directories.
- Set up `pyproject.toml`, `package.json`, `docker-compose.yml` (PostgreSQL service).
- Copy V1's `parsers.py`, `selectors.py`, `errors.py`, `relevance.py` verbatim into `backend/app/scraper/` and `backend/app/services/`.
- Port V1's test suite for these files — all tests must pass with zero changes.
- **Deliverable**: `pytest tests/unit/` passes for all ported pure-function modules.

### Phase 2: Database & Repository (Days 4–7)
- Write Alembic migration creating all V2 PostgreSQL tables.
- Implement async repository modules (`products.py`, `observations.py`, `jobs.py`, etc.).
- Port V1's `test_sqlite_repository.py` integration tests to PostgreSQL — same test scenarios, different backend.
- **Deliverable**: `pytest tests/integration/` passes against a real test PostgreSQL instance.

### Phase 3: FastAPI Application (Days 8–12)
- Implement `app/main.py`, all API routers, Pydantic schemas, dependency injection.
- Wire up repository modules into service layer.
- Implement job queue endpoints and WebSocket job progress.
- **Deliverable**: All API endpoints documented in Swagger UI; TestClient tests pass.

### Phase 4: Playwright Scraper (Days 13–19)
- Implement `browser.py` (Playwright context management).
- Implement `amazon.py` (product scraping + search discovery) using same selector chains.
- Test against saved HTML fixtures — no live browser needed.
- Integrate with job worker and repository.
- **Deliverable**: Running `POST /api/products/{id}/collect` scrapes a real Amazon page and stores an observation with evidence.

### Phase 5: React Frontend (Days 20–26)
- Scaffold Vite + TypeScript + Tailwind.
- Implement API client with TanStack Query.
- Build Dashboard, ProductDetail with PriceHistoryChart, JobsPage.
- **Deliverable**: Working dashboard that displays collected data with price history chart.

### Phase 6: LLM Analysis with Evidence Linking (Days 27–31)
- Port `llm.py` to async; adapt for PostgreSQL evidence retrieval.
- Add evidence-linking step: `analysis_claims` + `claim_evidence` rows.
- Build AnalysisView in React with clickable evidence citations.
- **Deliverable**: LLM analysis output with each claim linkable to source observations.

### Phase 7: Analytics & Polish (Days 32–35)
- Implement price analytics API endpoints (trend, rank, percentile).
- Add comparison charts to frontend.
- Docker Compose for full-stack local deployment.
- Final documentation pass.
- **Deliverable**: Complete, deployable V2 with README and one-command start.
