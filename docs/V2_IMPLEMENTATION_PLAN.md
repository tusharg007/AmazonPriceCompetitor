# V2 Implementation Plan: Amazon Competitor Intelligence

## 1. Implementation Principles

| Principle | What It Means in Practice |
|---|---|
| **MVP-first** | Every phase produces a working, demoable increment. No orphaned code. |
| **Evidence-first** | Every collected fact links to its source. Provenance is designed in from Phase 1, not retrofitted. |
| **Test-alongside** | Tests are written with each feature. Never accumulate untested code for a "test pass" later. |
| **Preserve what works** | `parsers.py`, `selectors.py`, `relevance.py`, and the LLM prompt are ported verbatim. Don't fix what isn't broken. |
| **No premature complexity** | Single FastAPI process, single PostgreSQL instance, single worker process. No Redis, Kafka, Kubernetes, or microservices. |
| **Realistic scope** | This is a portfolio project. It should be impressive and correct, not overengineered. |

---

## 2. Phase 0: Project Setup
**Estimate: 2–3 days**

### Tasks

**Monorepo structure**
```
amazon-competitor-v2/
├── backend/          # Python / FastAPI
├── frontend/         # React / TypeScript
├── docker-compose.yml
├── Makefile
└── .env.example
```

**Backend bootstrap** (`backend/`)
```
pyproject.toml         # Python ≥3.13, fastapi, uvicorn, asyncpg, playwright, pydantic-settings
app/main.py            # FastAPI app factory, health endpoint
app/core/config.py     # pydantic-settings Settings
tests/conftest.py      # pytest fixtures, test DB setup
```

**Frontend bootstrap** (`frontend/`)
```
vite.config.ts         # Vite + React + TypeScript
tailwind.config.js     # Tailwind CSS
src/App.tsx            # Router setup
src/api/client.ts      # Base fetch wrapper
```

**Infrastructure**
```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: aci_dev
      POSTGRES_USER: aci
      POSTGRES_PASSWORD: aci
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

**Makefile targets**
```makefile
dev:           # Starts PG + backend (uvicorn --reload) + frontend (vite) concurrently
test:          # Runs pytest + vitest
lint:          # ruff check + mypy + eslint
migrate:       # Runs Alembic upgrade head
```

**`.env.example`**
```
# Database
DATABASE_URL=postgresql+asyncpg://aci:aci@localhost/aci_dev
TEST_DATABASE_URL=postgresql+asyncpg://aci:aci@localhost/aci_test

# Groq
APP_GROQ_API_KEY=your_groq_api_key_here
APP_GROQ_MODEL=openai/gpt-oss-20b

# Browser
APP_BROWSER_HEADLESS=true
APP_BROWSER_NO_SANDBOX=false
APP_BROWSER_DISABLE_DEV_SHM_USAGE=false
APP_PAGE_TIMEOUT_SECONDS=30
APP_ELEMENT_TIMEOUT_SECONDS=10
APP_MIN_NAVIGATION_INTERVAL_SECONDS=2.0

# Collection limits
APP_MAX_SEARCH_PAGES=2
APP_MAX_COMPETITORS=20
APP_CHALLENGE_WAIT_SECONDS=300
APP_BLOCK_COOLDOWN_SECONDS=300

# Storage
APP_EVIDENCE_DIR=evidence

# Worker
APP_WORKER_POLL_INTERVAL=1.0
```

**Health check endpoint** — very first thing that must work:
```python
@app.get("/health")
async def health(pool: asyncpg.Pool = Depends(get_pool)):
    version = await pool.fetchval("SELECT version()")
    return {"status": "ok", "postgres": version}
```

**CI** (GitHub Actions, `.github/workflows/ci.yml`):
- Python: `ruff check` → `mypy` → `pytest` (unit only, no PG needed)
- Frontend: `eslint` → `vitest run`

**✅ Deliverable**: `make dev` starts Postgres + FastAPI at `localhost:8000` + Vite at `localhost:5173`. `GET /health` returns 200.

---

## 3. Phase 1: Database Foundation
**Estimate: 3–4 days**

### PostgreSQL Schema (Alembic migration)

Create the following tables in the first Alembic revision:

```sql
-- products: the entity being tracked (ASIN + domain + delivery location)
CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    asin        TEXT NOT NULL CHECK (length(asin) = 10),
    domain      TEXT NOT NULL CHECK (domain IN ('com','in','ca','co.uk','de','fr','it','ae')),
    geo_key     TEXT NOT NULL DEFAULT '__default__',
    requested_location TEXT,
    is_tracked  BOOLEAN NOT NULL DEFAULT TRUE,
    title       TEXT,           -- updated from latest observation
    brand       TEXT,           -- updated from latest observation
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (asin, domain, geo_key)
);

-- product_observations: append-only price history
CREATE TABLE product_observations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    job_id          UUID,       -- FK to collection_jobs added later
    price_amount    NUMERIC(12, 4),
    price_text      TEXT,
    currency        TEXT,
    availability    TEXT,
    rating          REAL CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
    rating_count    INTEGER CHECK (rating_count IS NULL OR rating_count >= 0),
    price_kind      TEXT,       -- 'current', 'deal', 'list'
    location_status TEXT NOT NULL DEFAULT 'default'
                    CHECK (location_status IN ('default','verified','unverified','unsupported')),
    observed_location TEXT,
    canonical_url   TEXT,
    variant         TEXT,
    condition       TEXT,
    categories      JSONB NOT NULL DEFAULT '[]',
    images          JSONB NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL DEFAULT 'playwright-v1',
    captured_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- evidence_snapshots: raw HTML / screenshot files
CREATE TABLE evidence_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    observation_id  UUID NOT NULL REFERENCES product_observations(id) ON DELETE CASCADE,
    evidence_type   TEXT NOT NULL CHECK (evidence_type IN ('html','screenshot','metadata')),
    storage_path    TEXT NOT NULL,       -- relative path under APP_EVIDENCE_DIR
    content_size_bytes INTEGER,
    content_hash    TEXT,                -- SHA-256
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- collection_jobs: PostgreSQL-based job queue
CREATE TABLE collection_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            TEXT NOT NULL CHECK (kind IN ('scrape_product','discover_competitors','analyze')),
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','running','succeeded','partial','failed','cancelled')),
    request_key     TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts    INTEGER NOT NULL DEFAULT 2,
    lease_token     UUID,
    lease_expires_at TIMESTAMPTZ,
    progress        INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    result          JSONB,
    error_code      TEXT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

-- competitor_matches: deterministic + LLM matching decisions
CREATE TABLE competitor_matches (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    baseline_product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    competitor_product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    match_score             REAL NOT NULL CHECK (match_score >= 0 AND match_score <= 1),
    match_method            TEXT NOT NULL CHECK (match_method IN ('deterministic','llm_assisted')),
    match_status            TEXT NOT NULL CHECK (match_status IN ('confirmed','rejected','ambiguous')),
    exclusion_reason        TEXT,
    search_rank             INTEGER,
    sponsored               BOOLEAN NOT NULL DEFAULT FALSE,
    search_query            TEXT,
    discovery_job_id        UUID REFERENCES collection_jobs(id),
    discovered_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_evaluated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (baseline_product_id, competitor_product_id)
);

-- match_evidence: audit trail for matching decisions
CREATE TABLE match_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id        UUID NOT NULL REFERENCES competitor_matches(id) ON DELETE CASCADE,
    evidence_type   TEXT NOT NULL CHECK (evidence_type IN ('attribute_comparison','llm_reasoning')),
    evidence_data   JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- analysis_runs: LLM analysis executions
CREATE TABLE analysis_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    job_id          UUID REFERENCES collection_jobs(id),
    input_hash      TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL DEFAULT 'v1',
    schema_version  TEXT NOT NULL DEFAULT 'v1',
    raw_output      JSONB,
    status          TEXT NOT NULL CHECK (status IN ('succeeded','failed')),
    error_message   TEXT,
    usage           JSONB,      -- token counts from Groq
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (product_id, input_hash, model, prompt_version, schema_version)
);

-- analysis_claims: structured claims from LLM output
CREATE TABLE analysis_claims (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    claim_type  TEXT NOT NULL CHECK (
                    claim_type IN ('price_comparison','rating_comparison',
                                   'positioning','recommendation','summary')
                ),
    claim_text  TEXT NOT NULL,
    claim_value JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- claim_evidence: junction linking claims to their source observations
CREATE TABLE claim_evidence (
    claim_id        UUID NOT NULL REFERENCES analysis_claims(id) ON DELETE CASCADE,
    observation_id  UUID NOT NULL REFERENCES product_observations(id) ON DELETE RESTRICT,
    role            TEXT NOT NULL CHECK (role IN ('baseline','competitor','supporting')),
    PRIMARY KEY (claim_id, observation_id)
);
```

### Key Indexes

```sql
CREATE INDEX idx_obs_product_time  ON product_observations(product_id, captured_at DESC);
CREATE INDEX idx_obs_job           ON product_observations(job_id);
CREATE UNIQUE INDEX idx_jobs_active_dedup
    ON collection_jobs(kind, product_id, request_key)
    WHERE status IN ('queued', 'running');
CREATE INDEX idx_jobs_queue        ON collection_jobs(status, created_at)
    WHERE status = 'queued';
CREATE INDEX idx_matches_baseline  ON competitor_matches(baseline_product_id, match_score DESC);
CREATE INDEX idx_claims_run        ON analysis_claims(run_id);
CREATE INDEX idx_evidence_obs      ON evidence_snapshots(observation_id);
CREATE INDEX idx_products_tracked  ON products(is_tracked, updated_at DESC);
```

### Repository Layer

Implement async repository modules. Each method takes an `asyncpg.Connection` (passed in by
dependency injection — no repository holds a connection):

```python
# backend/app/repository/products.py
async def get_or_create_product(
    conn: asyncpg.Connection,
    asin: str,
    domain: str,
    geo_key: str = "__default__",
    requested_location: str | None = None,
    tracked: bool = False,
) -> int:
    """Returns product.id. Creates if not exists."""
    await conn.execute(
        "INSERT INTO products(asin, domain, geo_key, requested_location, is_tracked) "
        "VALUES($1,$2,$3,$4,$5) ON CONFLICT(asin,domain,geo_key) "
        "DO UPDATE SET is_tracked = GREATEST(products.is_tracked, excluded.is_tracked),"
        "updated_at=NOW()",
        asin,
        domain,
        geo_key,
        requested_location,
        tracked,
    )
    return await conn.fetchval(
        "SELECT id FROM products WHERE asin=$1 AND domain=$2 AND geo_key=$3",
        asin,
        domain,
        geo_key,
    )
```

**✅ Deliverable**: All repository methods implemented. Integration tests against test PostgreSQL pass
for: product upsert, observation insert, job queue claim/heartbeat/finish.

---

## 4. Phase 2: Core API
**Estimate: 4–5 days**

### FastAPI Application Structure

```python
# backend/app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.core.database import create_pool, close_pool
from app.api import products, observations, jobs, competitors, analysis, evidence


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await create_pool()
    yield
    await close_pool(app.state.pool)


app = FastAPI(title="Amazon Competitor Intelligence V2", lifespan=lifespan)
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(observations.router, prefix="/api/products", tags=["observations"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(competitors.router, prefix="/api/products", tags=["competitors"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(evidence.router, prefix="/api/evidence", tags=["evidence"])
```

### Endpoint Implementation Details

**Products router** (`POST /api/products`):
- Input validation: ASIN regex, domain enum, postal code format rules (ported from V1's `validate_delivery_location`)
- Call `get_or_create_product()` — returns existing product if ASIN+domain+geo_key exists
- Return `ProductResponse` schema

**Job queue** (`POST /api/products/{id}/collect`):
- Check if cooldown active for this domain
- Insert into `collection_jobs` with `ON CONFLICT DO NOTHING` (deduplication via `idx_jobs_active_dedup`)
- Return job id and status

**WebSocket job progress** (`/ws/jobs/{id}`):
```python
@router.websocket("/ws/jobs/{job_id}")
async def job_progress(websocket: WebSocket, job_id: str, pool=Depends(get_pool)):
    await websocket.accept()
    async with pool.acquire() as conn:
        while True:
            row = await conn.fetchrow(
                "SELECT status, progress, error_code, error_message FROM collection_jobs WHERE id=$1",
                job_id,
            )
            if not row:
                await websocket.close(code=1008)
                return
            await websocket.send_json(
                {
                    "status": row["status"],
                    "progress": row["progress"],
                    "error_code": row["error_code"],
                    "error_message": row["error_message"],
                }
            )
            if row["status"] not in ("queued", "running"):
                await websocket.close()
                return
            await asyncio.sleep(1.5)
```

**Pydantic response schemas** — all in `app/models/schemas.py`:

```python
class ProductResponse(BaseModel):
    id: int
    asin: str
    domain: str
    geo_key: str
    requested_location: str | None
    title: str | None
    brand: str | None
    is_tracked: bool
    latest_observation: ObservationSummary | None
    competitor_count: int
    last_collected_at: datetime | None


class ObservationSummary(BaseModel):
    id: UUID
    price_amount: Decimal | None
    price_text: str | None
    currency: str | None
    rating: float | None
    availability: str | None
    captured_at: datetime


class AnalysisClaimResponse(BaseModel):
    id: UUID
    claim_type: str
    claim_text: str
    claim_value: dict | None
    evidence: list[ClaimEvidenceDetail]


class ClaimEvidenceDetail(BaseModel):
    observation_id: UUID
    product_asin: str
    price_text: str | None
    captured_at: datetime
    evidence_snapshot_id: UUID | None
    role: str  # "baseline" | "competitor"
```

**Error handling middleware**:
```python
@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(DatabaseError)
async def database_error(request, exc):
    return JSONResponse(status_code=400, content={"error": str(exc)})
```

**✅ Deliverable**: All endpoints in Swagger UI (`/docs`). FastAPI TestClient tests cover: product
creation, duplicate dedup, job enqueue, 422 on bad ASIN.

---

## 5. Phase 3: Playwright Collection Engine
**Estimate: 5–7 days**

### What to Port Directly (Day 13)

Copy these files verbatim from V1 into `backend/app/scraper/`:
- `parsers.py` — no changes
- `selectors.py` — no changes
- `errors.py` — no changes

Run V1's parser tests against the copies to confirm nothing broke.

### Browser Context Manager (Day 14)

```python
# backend/app/scraper/browser.py
from playwright.async_api import async_playwright, BrowserContext, Page
from pathlib import Path
from contextlib import asynccontextmanager
from app.core.config import Settings


@asynccontextmanager
async def browser_context(settings: Settings, domain: str):
    profile_dir = settings.evidence_dir.parent / "browser-profiles" / domain
    profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=settings.app_browser_headless,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            args=[
                "--no-sandbox" if settings.app_browser_no_sandbox else "",
                "--disable-dev-shm-usage" if settings.app_browser_disable_dev_shm_usage else "",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        # Apply stealth patches
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        try:
            yield ctx
        finally:
            await ctx.close()
```

### Product Page Scraper (Days 15–16)

The V1 `_text()` helper that tried multiple selectors with `WebDriverWait` becomes:

```python
async def _text(page: Page, selector_group: tuple[str, ...]) -> str | None:
    for selector in selector_group:
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0:
                text = await locator.text_content(timeout=2000)
                return clean_text(text)
        except Exception:
            continue
    return None
```

Evidence capture after extraction:
```python
async def capture_evidence(page: Page, obs_id: UUID, evidence_dir: Path) -> str:
    path = evidence_dir / f"{obs_id}.html"
    html = await page.content()
    path.write_text(html, encoding="utf-8")
    content_hash = hashlib.sha256(html.encode()).hexdigest()
    return content_hash
```

### CAPTCHA Detection (Day 16)

```python
async def check_page_state(page: Page) -> None:
    """Raises ScrapingError on bot detection. Same markers as V1 selectors.py."""
    for selector in selectors.BLOCK_MARKERS:
        elements = page.locator(selector)
        if await elements.count() > 0 and await elements.first.is_visible():
            raise ScrapingError(ScrapeErrorCode.BLOCKED, "Amazon bot check detected")
    title = await page.title()
    if "robot check" in title.lower():
        raise ScrapingError(ScrapeErrorCode.BLOCKED, "Bot detection page")
```

### Background Worker (Days 17–18)

```python
# backend/app/worker/runner.py
async def claim_next_job(conn: asyncpg.Connection) -> dict | None:
    return await conn.fetchrow(
        """
        UPDATE collection_jobs SET
            status = 'running',
            attempts = attempts + 1,
            lease_token = gen_random_uuid(),
            lease_expires_at = NOW() + INTERVAL '90 seconds',
            started_at = COALESCE(started_at, NOW())
        WHERE id = (
            SELECT id FROM collection_jobs
            WHERE status = 'queued'
              AND attempts < max_attempts
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
        """
    )


async def worker_loop(pool: asyncpg.Pool, settings: Settings) -> None:
    while True:
        async with pool.acquire() as conn:
            job = await claim_next_job(conn)
        if not job:
            await asyncio.sleep(settings.app_worker_poll_interval)
            continue
        await run_job(pool, job, settings)
```

**✅ Deliverable**: `POST /api/products/{id}/collect` triggers a real Playwright scrape of
amazon.com, stores a `product_observation` row, and saves an HTML evidence file.

---

## 6. Phase 4: Deterministic Matching
**Estimate: 3–4 days**

### Port V1's `relevance.py`

`select_comparable_competitors()` from V1 handles the **hard exclusion** rules (Phase 1 of
the matching algorithm). Call it during competitor discovery:

```python
from app.services.matching import select_comparable_competitors

included, excluded = select_comparable_competitors(parent_obs, candidate_obs_list)
# excluded = {"compatibility listing": 2, "currency mismatch": 1, ...}
```

### Scored Matching (Phase 2)

```python
def compute_match_score(baseline: dict, candidate: dict) -> float:
    title_sim = jaccard_similarity(tokenize(baseline["title"]), tokenize(candidate["title"]))
    brand_score = brand_match_score(baseline.get("brand"), candidate.get("brand"))
    cat_overlap = category_overlap(baseline.get("categories", []), candidate.get("categories", []))
    price_prox = price_proximity(baseline.get("price_amount"), candidate.get("price_amount"))
    rating_prox = rating_proximity(baseline.get("rating"), candidate.get("rating"))

    return (
        0.35 * title_sim
        + 0.25 * brand_score
        + 0.20 * cat_overlap
        + 0.15 * price_prox
        + 0.05 * rating_prox
    )


def classify_match(score: float) -> str:
    if score >= 0.7:
        return "confirmed"
    if score >= 0.3:
        return "ambiguous"
    return "rejected"
```

### Storing Match Decisions

Each candidate that passes hard exclusions gets a `competitor_matches` row:
```python
await conn.execute(
    "INSERT INTO competitor_matches("
    "  baseline_product_id, competitor_product_id, match_score,"
    "  match_method, match_status, exclusion_reason, search_rank,"
    "  sponsored, search_query, discovery_job_id"
    ") VALUES($1,$2,$3,'deterministic',$4,$5,$6,$7,$8,$9)"
    " ON CONFLICT(baseline_product_id,competitor_product_id)"
    " DO UPDATE SET match_score=$3, match_status=$4, last_evaluated_at=NOW()",
    baseline_id,
    competitor_id,
    score,
    classify_match(score),
    exclusion_reason,
    rank,
    sponsored,
    query,
    job_id,
)
```

And a `match_evidence` row storing the scoring breakdown:
```python
evidence_data = {
    "title_similarity": title_sim,
    "brand_score": brand_score,
    "category_overlap": cat_overlap,
    "price_proximity": price_prox,
    "rating_proximity": rating_prox,
    "exclusion_reasons": exclusion_reasons_dict,
}
```

**✅ Deliverable**: After competitor discovery, `GET /api/products/{id}/competitors` returns
scored matches with `confirmed`/`ambiguous`/`rejected` statuses and per-attribute evidence.

---

## 7. Phase 5: React Frontend — MVP
**Estimate: 5–7 days**

### API Client

```typescript
// frontend/src/api/client.ts
const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...init,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error ?? "Request failed");
    }
    return res.json();
}
```

### TanStack Query Hooks

```typescript
// frontend/src/hooks/useProducts.ts
export function useProducts() {
    return useQuery({
        queryKey: ["products"],
        queryFn: () => apiFetch<ProductResponse[]>("/api/products?tracked_only=true"),
        refetchInterval: 30_000,
    });
}

export function usePriceHistory(productId: number, windowDays = 30) {
    return useQuery({
        queryKey: ["observations", productId, windowDays],
        queryFn: () => apiFetch<Observation[]>(
            `/api/products/${productId}/observations?window_days=${windowDays}`
        ),
    });
}
```

### PriceHistoryChart Component

```tsx
// frontend/src/components/PriceHistoryChart.tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export function PriceHistoryChart({ data }: { data: Observation[] }) {
    const formatted = data.map(obs => ({
        date: new Date(obs.captured_at).toLocaleDateString(),
        price: Number(obs.price_amount),
    }));
    return (
        <ResponsiveContainer width="100%" height={280}>
            <LineChart data={formatted}>
                <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={v => `$${v}`} />
                <Tooltip formatter={(v: number) => [`$${v.toFixed(2)}`, "Price"]} />
                <Line type="monotone" dataKey="price" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
        </ResponsiveContainer>
    );
}
```

### WebSocket Job Progress

```typescript
// frontend/src/hooks/useJobProgress.ts
export function useJobProgress(jobId: string | null) {
    const [state, setState] = useState<JobProgressState | null>(null);
    useEffect(() => {
        if (!jobId) return;
        const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}`);
        ws.onmessage = e => setState(JSON.parse(e.data));
        return () => ws.close();
    }, [jobId]);
    return state;
}
```

### Pages

| Page | Route | Key Components |
|---|---|---|
| Dashboard | `/` | Product list, `ProductCard`, "Add Product" form |
| Product Detail | `/products/:id` | `PriceHistoryChart`, `CompetitorTable`, `JobStatusBadge` |
| Analysis View | `/analyses/:id` | Claim list with `EvidenceLink` citations |
| Jobs | `/jobs` | Active/recent jobs with progress bars |

**✅ Deliverable**: Dashboard shows tracked products. Clicking a product shows price history chart
and competitor table. Triggering a collection job shows real-time progress.

---

## 8. Phase 6: LLM Analysis with Evidence Tracking
**Estimate: 4–5 days**

### Port V1's `llm.py` (verbatim sections)

Copy these functions unchanged:
- `LLMAnalysis` and `LLMCompetitorInsight` Pydantic models
- `_normalize_analysis_payload()` — list/scalar drift repair
- `_schema_failure()` + `_failed_generation()` — Groq error recovery
- `_bounded_analysis()` — ASIN validation + text truncation
- The full prompt template string

### Adapt `build_analysis_input()` for PostgreSQL

Replace SQLiteRepository calls with async asyncpg queries. The evidence dict structure
stays identical — the LLM receives the same JSON it did in V1. Add `observation_id` to
each evidence record so the claim-linking step can map it back:

```python
def _analysis_record(row: dict) -> dict:
    return {
        "observation_id": str(row["id"]),  # NEW — enables claim linking
        "asin": row["asin"],
        "title": row["title"],
        "brand": row["brand"],
        "price_amount": row["price_amount"],
        "price_text": row["price_text"],
        "currency": row["currency"],
        "availability": row["availability"],
        "rating": row["rating"],
        "rating_count": row["rating_count"],
        "category_path": row["categories"],
        "captured_at": str(row["captured_at"]),
        "location_status": row["location_status"],
        "canonical_url": row["canonical_url"],
    }
```

### Claim-Evidence Linking (New in V2)

After the LLM returns valid output, create structured `analysis_claims` and `claim_evidence` rows:

```python
async def save_analysis_with_claims(
    conn: asyncpg.Connection,
    run_id: UUID,
    output: LLMAnalysis,
    evidence: dict,
    baseline_obs_id: UUID,
) -> None:
    obs_by_asin = {row["asin"]: UUID(row["observation_id"]) for row in evidence["competitors"]}

    # Summary and positioning as single claims
    for claim_type, text in [("summary", output.summary), ("positioning", output.positioning)]:
        claim_id = await conn.fetchval(
            "INSERT INTO analysis_claims(run_id, claim_type, claim_text) VALUES($1,$2,$3) RETURNING id",
            run_id,
            claim_type,
            text,
        )
        await conn.execute(
            "INSERT INTO claim_evidence(claim_id, observation_id, role) VALUES($1,$2,'baseline')",
            claim_id,
            baseline_obs_id,
        )

    # Competitor insights — link to their specific observation
    for insight in output.top_competitors:
        obs_id = obs_by_asin.get(insight.asin)
        if not obs_id:
            continue
        claim_id = await conn.fetchval(
            "INSERT INTO analysis_claims(run_id, claim_type, claim_text, claim_value)"
            " VALUES($1,'price_comparison',$2,$3) RETURNING id",
            run_id,
            "; ".join(insight.key_points),
            {"asin": insight.asin, "key_points": insight.key_points},
        )
        # Link to both baseline and competitor observations
        await conn.executemany(
            "INSERT INTO claim_evidence(claim_id, observation_id, role) VALUES($1,$2,$3)",
            [(claim_id, baseline_obs_id, "baseline"), (claim_id, obs_id, "competitor")],
        )
```

### Frontend — Evidence Citations

```tsx
// frontend/src/components/EvidenceLink.tsx
export function EvidenceLink({ observationId, capturedAt, role }: EvidenceLinkProps) {
    return (
        <a
            href={`/api/evidence?observation_id=${observationId}`}
            target="_blank"
            className="text-xs text-blue-500 underline ml-1"
            title={`${role} observation from ${new Date(capturedAt).toLocaleString()}`}
        >
            [source]
        </a>
    );
}
```

**✅ Deliverable**: LLM analysis runs produce `analysis_claims` rows each linked to specific
`product_observations`. Frontend renders claims with `[source]` links opening stored HTML.

---

## 9. Phase 7: Analytics & Polish
**Estimate: 3–4 days**

### Analytics API Queries

```sql
-- Price trend: compare last 7 days vs previous 7 days
SELECT
    AVG(CASE WHEN captured_at >= NOW() - INTERVAL '7 days' THEN price_amount END) AS recent_avg,
    AVG(CASE WHEN captured_at < NOW() - INTERVAL '7 days'
             AND captured_at >= NOW() - INTERVAL '14 days' THEN price_amount END) AS prev_avg
FROM product_observations WHERE product_id = $1;

-- Price rank among confirmed competitors (latest observation per product)
WITH latest AS (
    SELECT DISTINCT ON (product_id)
        product_id, price_amount
    FROM product_observations
    ORDER BY product_id, captured_at DESC
),
competitor_ids AS (
    SELECT competitor_product_id AS product_id
    FROM competitor_matches
    WHERE baseline_product_id = $1 AND match_status = 'confirmed'
    UNION SELECT $1
)
SELECT
    product_id,
    price_amount,
    RANK() OVER (ORDER BY price_amount) AS price_rank,
    PERCENT_RANK() OVER (ORDER BY price_amount) AS price_percentile,
    COUNT(*) OVER () AS total_in_set
FROM latest WHERE product_id IN (SELECT product_id FROM competitor_ids);
```

### Dashboard Enhancements
- Add "Price Trend" badge (↑ Rising / ↓ Falling / → Stable) to `ProductCard`.
- Add competitor price comparison bar chart to `ProductDetail`.
- Add CSV export: `GET /api/products/{id}/observations/export`.
- Add pagination to all list endpoints if not already present.

**✅ Deliverable**: Dashboard shows price trends. Product detail shows competitive position chart.

---

## 10. Phase 8: Hardening & Documentation
**Estimate: 2–3 days**

### Checklist

**Error handling**
- [ ] All repository methods have try/except wrapping asyncpg exceptions → `DatabaseError`
- [ ] Scraper catches all Playwright exceptions → `ScrapeErrorCode`
- [ ] Worker catches all exceptions → updates job status to `failed`
- [ ] FastAPI error handler middleware covers all `DatabaseError` and `ValidationError`

**Input validation**
- [ ] ASIN: `^[A-Z0-9]{10}$` regex, strip + uppercase
- [ ] Domain: enum check against `SUPPORTED_DOMAINS`
- [ ] Postal code: marketplace-specific format rules
- [ ] All UUIDs in path params: parse or 422

**API rate limiting**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
# Apply: @limiter.limit("5/minute") on /collect and /analyze endpoints
```

**CORS**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

**Docker Compose (full stack)**
```yaml
services:
  postgres:     # PostgreSQL 16
  backend:      # FastAPI + Uvicorn (depends_on: postgres)
  worker:       # Job worker process (depends_on: postgres)
  frontend:     # Vite preview build (depends_on: backend)
```

**README.md** minimum content:
- One-command start: `docker compose up`
- Environment variables documentation
- Architecture diagram
- Demo walkthrough (add product → collect → analyze → view)

**Test coverage targets**
- Backend unit: ≥80% (parsers, models, matching, LLM validation)
- Backend integration: all repository methods, job queue lifecycle
- Frontend: all pages render, API error states handled

**✅ Deliverable**: `docker compose up` starts the full stack. `README.md` enables a new
developer to run the project in under 5 minutes.

---

## 11. Effort Summary

| Phase | Est. Days | Key Deliverable | Depends On |
|---|---|---|---|
| 0 — Setup | 2–3 | `make dev` starts frontend + backend | — |
| 1 — Database | 3–4 | Schema + repo tests pass against PG | Phase 0 |
| 2 — Core API | 4–5 | All endpoints documented in Swagger UI | Phase 1 |
| 3 — Playwright | 5–7 | Real Amazon page scraped → observation stored | Phase 2 |
| 4 — Matching | 3–4 | Deterministic competitor scoring stored | Phase 3 |
| 5 — Frontend | 5–7 | Dashboard + price chart + competitor table | Phase 2 (mock), Phase 3 (real) |
| 6 — LLM Analysis | 4–5 | Evidence-linked claims in frontend | Phase 4 + 5 |
| 7 — Analytics | 3–4 | Price trend + position chart | Phase 5 + 6 |
| 8 — Hardening | 2–3 | Docker Compose, README, coverage ≥80% | Phase 7 |
| **Total** | **31–42 days** | Full V2 system | — |

### Critical Path
```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 6 → Phase 8
```

### Parallelizable After Phase 2
- Phase 3 (backend scraper) and Phase 5 (frontend) can proceed in parallel once API contracts
  are defined. The frontend uses mock data via MSW until the real scraper is ready.

---

## 12. MVP Definition

**MVP = Phases 0–5** (~20–27 days)

| MVP Includes | MVP Excludes |
|---|---|
| Product tracking (amazon.com) | Multi-marketplace |
| Playwright collection + evidence HTML | Screenshot evidence |
| Price history time series | Price trend analytics |
| Deterministic competitor matching (Phases 1–2) | LLM-assisted ambiguous matching |
| React dashboard: products, price chart, competitor table | Advanced analytics charts |
| Basic LLM analysis (text summary) | Structured claim-evidence linking |
| Job progress via WebSocket | — |

**Post-MVP** = Phases 6–8: evidence-linked claims, analytics, polish, Docker deployment.

---

## 13. Risk Mitigation

| Risk | Mitigation Strategy |
|---|---|
| **Amazon blocks Playwright during dev** | Use HTML fixtures for all scraper unit tests. Limit live scraping to CI `live` marker tests. |
| **Playwright stealth insufficient** | Test early against real Amazon pages. Accept occasional blocks as operational reality. Document headed recovery mode. |
| **PostgreSQL setup friction** | `docker compose up postgres` takes 15 seconds. Alembic runs on `make migrate`. Zero manual SQL setup. |
| **Frontend scope creep** | MVP page list is fixed: Dashboard, ProductDetail, AnalysisView, Jobs. No new pages until Phase 8. |
| **LLM API costs during development** | Mock `ChatGroq` in all unit/integration tests. Only call real Groq in `@pytest.mark.live` integration tests. |
| **asyncpg learning curve** | Fallback: use `SQLAlchemy[asyncio]` with the same repository interface. The repository pattern hides the driver. |
| **Evidence file storage** | HTML files average 100–300KB. 20 competitors × 30 days = ~180MB. Fine for portfolio. Add size cap if needed. |

---

## 14. Success Criteria

### Technical
- [ ] Backend: `pytest` coverage ≥80% for `app/` excluding `app/scraper/amazon.py`
- [ ] All API endpoints return correct status codes and response shapes for happy path and error cases
- [ ] Price history chart displays data from ≥3 separate collection runs
- [ ] LLM analysis completes without hallucinated ASINs in any test run
- [ ] Worker survives a CAPTCHA detection event: job marked `failed` with `error_code="blocked"`, cooldown set

### Portfolio
- [ ] `docker compose up` (or `make dev`) starts the full stack with zero manual steps after `.env` setup
- [ ] `README.md` explains the project in one page with architecture diagram and quickstart
- [ ] Swagger UI at `/docs` documents all endpoints
- [ ] At least one product tracked with ≥7 days of price observations visible in the chart
- [ ] At least one complete LLM analysis with evidence links demonstrable in the browser
