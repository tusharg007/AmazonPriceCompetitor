# V2 local demo and development guide

## Docker setup

Use Docker Desktop with Linux containers (or Docker Engine with Compose). Keep
published ports on localhost. No cloud deployment or public hosting is configured.

From a fresh checkout, PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Do not replace an existing `.env`. Edit it locally instead. Initial dependency and
Chromium image downloads can take several minutes; cached starts are much faster.
Compose waits for PostgreSQL, runs Alembic once, then starts API and worker. The
frontend serves a static build with REST/WebSocket proxying to the API.

- UI: http://localhost:5173
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Logs: `docker compose logs -f backend worker`
- Status: `docker compose ps -a`
- Stop: `docker compose down` (retains volumes)
- Recreate after configuration changes: `docker compose up -d --force-recreate backend worker`

The volumes contain PostgreSQL data and runtime evidence/browser profiles. Keep
both when backing up the workspace. Deleting volumes deletes those records; it is
not an error-recovery step. There is no automated evidence garbage collector or
scheduled collection service.

## Native development

Requires Python 3.13+, uv, Node 22.12+ and npm. From the root:

```powershell
uv sync --locked --group dev
Copy-Item .env.example .env  # Fresh checkout only
uv run playwright install chromium
uv run alembic -c backend/alembic.ini upgrade head
```

On Linux, use `uv run playwright install --with-deps chromium`. If desired, install
browsers under `.browsers` using `PLAYWRIGHT_BROWSERS_PATH`; the application detects
that directory. Do not commit browsers or runtime data.

Run each process in a separate terminal, keeping the root as the backend/worker
working directory so configuration paths agree:

```powershell
# Terminal 1 — API
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2 — worker
$env:PYTHONPATH = "backend"
uv run python -m app.worker.runner
```

```powershell
# Terminal 3 — frontend
cd frontend
npm ci
npm run dev
```

The default native database is SQLite. To use PostgreSQL, set
`APP_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE`, create the
database, and apply Alembic before starting the processes. V2 does not upgrade V1's
schema or import its historical records automatically. Development uses `create_all`
for convenience but it does not migrate an older schema: still run Alembic.

## Configuration

Settings load the root `.env` and `APP_*` environment variables. Never put keys in
frontend configuration. Compose selects its internal database URL; native settings
use the URL in `.env`. The checked-in example has blank Groq keys.

| Variable | Default/example | Purpose |
| --- | --- | --- |
| `APP_DATABASE_URL` | `sqlite+aiosqlite:///data/amazon_competitor_v2.db` in example | Native async database URL |
| `POSTGRES_PASSWORD` | `aci_local` | Local Compose database password; use URL-safe characters |
| `APP_ENV` | `development`; Compose forces `production` | Production startup requires applied migrations |
| `APP_EVIDENCE_DIR` | `evidence`; Compose `/app/runtime/evidence` | Captured files; keep this with the database |
| `APP_ALLOWED_ORIGINS` | localhost and 127.0.0.1 on 5173 | Allowed REST CORS origins |
| `APP_PLAYWRIGHT_HEADLESS` | `true` | Native browser visibility; Compose remains headless |
| `APP_PLAYWRIGHT_BROWSERS_PATH` | auto-detected/Playwright default | Optional browser installation directory |
| `APP_PAGE_TIMEOUT_SECONDS` / `APP_ELEMENT_TIMEOUT_SECONDS` | `30` / `10` | Browser navigation and element timeouts |
| `APP_MIN_NAVIGATION_INTERVAL_SECONDS` | `5` in example | Minimum spacing between navigations |
| `APP_MAX_SEARCH_PAGES` / `APP_MAX_COMPETITORS` | `2` / `20` | Bounded discovery effort |
| `APP_BLOCK_COOLDOWN_SECONDS` | `300` | Marketplace pause after a detected access block |
| `APP_API_RATE_LIMIT_PER_MINUTE` | `5` | Collection and analysis request budgets |
| `APP_MAX_EVIDENCE_BYTES` | `5242880` | Capture/download evidence size cap |
| `APP_MAX_ANALYSIS_INPUT_BYTES` | `131072` | Frozen provider input size cap |
| `APP_WORKER_POLL_INTERVAL` | `1` | Idle queue polling interval in seconds |
| `APP_WORKER_LEASE_SECONDS` / `APP_WORKER_HEARTBEAT_SECONDS` | `90` / `15` | Ownership lease and renewal interval |
| `APP_GROQ_API_KEY` | blank | Optional analysis credential; `GROQ_API_KEY` is an alias |
| `APP_GROQ_MODEL` | `openai/gpt-oss-20b` | Configured Groq model; availability depends on the service |
| `VITE_API_URL` | unset | Optional native frontend API origin; public build setting, never a secret |
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite development REST/WebSocket proxy target |

Compose exposes the documented collection limits and Groq settings. Advanced
native settings are declared in `backend/app/core/config.py`; explicit changes to
other Compose settings require editing its environment mapping. The API limiter
is bounded, in-memory and per process/client address. Collect and scan share a
budget; analyze has another. The local nginx proxy may share a single address
budget. It is not a distributed public-service quota system.

## Demo walkthrough

1. **Register:** on Products, enter an actual ASIN or Amazon `/dp/` product URL.
   Choose its marketplace; omit the postal code for default context, or supply a
   valid marketplace-specific code. The same identity/location is reused.
2. **Collect:** open the product and request a collection. The API returns a job
   ID immediately. Watch Jobs or the product's job progress. A successful job
   publishes an immutable observation and its raw HTML evidence.
3. **History:** collect again on later visits. The product's window/currency
   selectors show actual capture history and minimum/maximum/average/change.
   Three separate successful collection jobs produce three capture points, even
   if prices are unchanged. Seven days require collecting across seven real days;
   never alter timestamps or seed imaginary historical prices for a demo.
4. **Competitors:** discover competitors (or include discovery with collection).
   Inspect confirmed/ambiguous/rejected relationships and reasons. Missing or
   blocked candidates are not fabricated. A partial run uses only saved evidence.
5. **Evidence:** open an observation's evidence inspector. Check URL, capture time,
   collector, extraction method and hash. The download is verified against its
   hash and size, delivered as an attachment, and never injected into the UI.
6. **Position:** view the saved confirmed cohort, captured prices, rank/percentile
   and capture times. This is not a full-market or simultaneous price survey.
7. **AI insight (optional):** configure a valid Groq key, restart API and worker,
   and collect/discover confirmed competitors for the current baseline. Request
   analysis. The completed job links to AnalysisView. Distinguish Python-computed
   facts from labelled model interpretations and follow each observation citation.
   Frozen inputs are hashed; completed equivalent analyses are reused. Unsupported
   ASINs are rejected and model-supplied quantitative prose is withheld.
8. **Export:** download the CSV for the selected time window. It includes exact
   Decimal values and provenance; spreadsheet formula prefixes are escaped.

API alternative (PowerShell):

```powershell
$product = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/products `
  -ContentType application/json -Body '{"asin":"B09XS7JWHH","domain":"com"}'
$job = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/products/$($product.id)/collect"
Invoke-RestMethod -Uri "http://localhost:8000/api/jobs/$($job.id)"
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/products/$($product.id)/competitors/scan"
Invoke-RestMethod -Uri "http://localhost:8000/api/products/$($product.id)/observations"
```

Use an ASIN that exists in the selected marketplace; the example is not a guarantee
of current availability. Swagger describes the request/response and error shapes.

## Failure and recovery

- `blocked`: stop collection attempts during the reported cooldown. V2 does not
  solve CAPTCHA or expose a headed challenge-recovery UI. Do not repeatedly retry
  or overwrite saved evidence. An unavailable marketplace is a real operational
  limitation; the worker remains available for other permitted work.
- `location_unverified`: observations can be retained with that status, but numeric
  comparisons exclude an unverified context. Check the chosen marketplace/postcode.
- `429 rate_limited`: honor `Retry-After`. Reads remain available.
- `413`: evidence or analysis input exceeds configured bounds. Review the limit
  and input rather than silently truncating provenance.
- `analysis_not_configured`: collection does not need a Groq key; analysis does.
- Failed model validation/provider error: no unsupported claims are published.
  Review configuration and retry deliberately. Model text is interpretation,
  even when schema validation succeeds.
- Database unavailable: inspect PostgreSQL health and logs. Leases permit recovery
  after interrupted jobs. Never reset a persistent volume to work around an error.

## Verification commands

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src main.py backend/app backend/alembic
uv run pytest -q --cov=backend/app --cov-report=term-missing
uv run python -m compileall -q backend/app backend/alembic scripts
uv run alembic -c backend/alembic.ini heads
cd frontend
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm audit
```

The backend coverage gate is 80% excluding `collector/amazon.py`, matching the
approved plan's Amazon adapter exclusion. The adapter still has extraction,
real-browser fixture and worker regression tests. PostgreSQL integration tests
require an isolated database whose name ends `_test`:

```powershell
$env:ACI_TEST_POSTGRES_URL = "postgresql+asyncpg://aci:aci_test@localhost:55434/aci_completion_test"
uv run pytest -q --cov=backend/app
```

Tests create/drop that dedicated schema. Never point this variable at application
data. Without it, PostgreSQL-specific cases are skipped; CI supplies PostgreSQL 16.
Unit/browser fixtures and mocked provider responses are test-only, clearly separate
from live Amazon/Groq verification.

After API schema changes: `uv run python scripts/export_openapi.py`, then in
`frontend`, `npm run contracts`. Commit both generated contract files. The optional
Makefile mirrors the common commands; PowerShell commands above require no Make.

## Legacy V1

V1 remains separate:

```powershell
docker compose -p aci-v1 -f compose.v1.yaml up --build
```

It uses Streamlit on localhost:8501, Selenium/noVNC on localhost:7900 and separate
SQLite/browser volumes. V1 reads `GROQ_API_KEY`, while V2 prefers
`APP_GROQ_API_KEY`. Legacy settings in `.env.example` apply only to V1. Its browser
recovery UI is not a V2 capability. The original V1 regression suite remains in CI.
