# Phase 8 — Hardening & Documentation

Completed implementation and local verification on 2026-10-07 (Asia/Calcutta).
This phase reuses the established async SQLAlchemy repositories, application-owned
database lifecycle, Playwright collector, durable worker, typed API and React UI.
No new product surfaces, agent framework or public deployment were introduced.

## Acceptance criteria and status

| Approved criterion | Status and evidence |
| --- | --- |
| Stable database, validation, browser and worker errors | Met. Existing transaction/service exception boundaries retained; sanitized unexpected HTTP failures and typed 413/500 contracts added. Worker regressions verify terminal failures, partial results, retries and ownership fencing. |
| ASIN, supported domain, marketplace postcode and UUID validation | Met by existing schemas/normalization and invalid-input HTTP tests; not duplicated in routes. |
| Five collection/analysis requests per minute | Met. App-owned bounded sliding windows; collect/scan share a budget, analyze has a separate budget. 429 includes Retry-After; reads remain available. |
| Configurable CORS with GET/POST/DELETE | Met, with credentials disabled and pagination header exposed. |
| PostgreSQL, backend, worker and frontend through Compose | Met. Fresh named verification project applied migrations and started all services. API health, REST proxy, WebSocket proxy, real queue execution and non-root Chromium verified. |
| README architecture, environment, quickstart and walkthrough | Met. README links the detailed configuration/native workflow and demo guide. Cold image/browser downloads can exceed five minutes; cached startup is straightforward, not a timing guarantee. |
| Backend coverage at least 80% | Met. Final full-suite coverage exceeds 92% with only the approved Amazon adapter excluded. The adapter still has fixture, browser and worker tests. |
| Frontend pages and API error handling | Met. 16 component/contract/progress tests; desktop/mobile real Chromium checks across all four routes. |

## Findings fixed

| Severity | Finding | Resolution |
| --- | --- | --- |
| High | `APP_ENV=production` was ignored by the automatic prefix (`APP_APP_ENV`) | Explicit alias choices accept the documented APP_ENV first, retaining the previous alias. Regression test verifies precedence. Rebuilt container logs confirm production mode without create_all. |
| High | Default container SIGTERM would bypass the standalone worker's asyncio teardown | Worker Compose stop signal is SIGINT, which uses asyncio.run cancellation and existing shielded browser/engine cleanup. Actual container stop is verified. |
| High | Unexpected conversion/runtime errors could leak internal exception strings | Centralized safe 422/500 payloads; logs record exception types rather than raw potentially sensitive messages. |
| High | Evidence reads and captures lacked configured size bounds | Metadata and actual bounded-read checks, capture cap before file publication, stable 413 and integrity/path tests. |
| High | Analysis artifact verification checked hash but not capture metadata consistency | Require matching source URL, collector and normalized capture timestamp as well as content integrity. |
| High | Mutating collection/analysis API calls had no request budget | Sliding 60-second limiter with a maximum number of tracked windows and fail-closed capacity handling. |
| High | Dependency audit identified frontend runtime and development vulnerabilities | Updated React Router, Tailwind/PostCSS and Vitest through the lockfile; complete npm audit now reports zero vulnerabilities. React remains 18. |
| Medium | Frozen analysis payloads were unbounded | Configurable serialized-input cap checked before queue/provider work; inputs are not silently truncated. |
| Medium | Malformed model competitor identities could expose arbitrary provider text | Validate ASIN shape before existing known-identity output validation; safe rejection tests. |
| Medium | Browser WebSocket creation could throw and disrupt progress rendering | Preserve polling fallback on construction failure; reject malformed/out-of-range progress; cleanup tests. |
| Low | SQLite test transaction managers did not close connections | Explicit closing around transaction context managers in migration/repository/socket test helpers. Assertions and transaction behavior preserved. |
| Low | Alembic configuration emitted path-separator deprecations | Explicit OS path separator. |
| Low | Large eagerly loaded route bundle | Lazy route chunks with loading feedback; production build no longer emits the large-chunk warning. |

## Architecture and contracts

Routes remain thin. Settings own request/evidence/input budgets; application
exceptions and existing database boundaries own error translation. OpenAPI and
generated TypeScript contracts include the new 413/500 response variants.

Compose runs PostgreSQL 16, an Alembic migration task, the API, a separate worker,
and an unprivileged nginx frontend. API/worker share evidence storage and use the
same locked backend image. The worker has an init process, shared-memory budget
and SIGINT graceful-stop interval. Browser binaries are readable by UID 10001; runtime
storage is writable by that user. Published API/UI ports bind to localhost.

Docker context excludes secrets, local databases, captured evidence, browsers,
node_modules and temporary output. The previous V1 container configurations are
preserved as Dockerfile.v1/compose.v1.yaml with separate volumes.

## Verification

- Final pytest: **311 passed, no skips or warnings** with real PostgreSQL 16 and real local
  Chromium available. Coverage above 92%; exact final percentage is recorded in
  the final engineering report. No assertions were weakened for this gate.
- Ruff check and formatting pass; mypy passes for **79 source files**, using the
  CI command covering V1, V2 and Alembic.
- Compile/import checks pass; Alembic has one head: **004_analysis_evidence**.
  Fresh SQLite/PostgreSQL upgrade, downgrade, schema alignment and preservation
  checks are included in pytest. The actual Compose database is also at this head.
- Frontend: **16 tests passed**; Prettier, ESLint, TypeScript and build pass.
- Python pip-audit: no known vulnerabilities. Full npm audit: zero vulnerabilities.
- Docker images build; migration exits 0; PostgreSQL/API become healthy; worker
  and frontend run. A real Amazon collection succeeds through the complete stack.
- Native React browser verification uses six genuine baseline observations at
  1440px and 390px; no page exceptions or document horizontal overflow. Verified
  evidence attachment download hashes match the inspector metadata.
- Whitespace/secret-path checks pass. No real credentials or runtime data committed.
  GitHub Actions was updated but not remotely executed because nothing was pushed.

## Adaptations and remaining limits

The approved plan's raw asyncpg exception examples are implemented at existing
SQLAlchemy transaction/service and HTTP boundaries, preserving the approved Phase 1
architecture rather than adding redundant wrappers around every query. A small
app-owned limiter provides the requested behavior without a new framework. It is
per process/client address; nginx can share a client budget. It is not a distributed
quota. nginx serves the built SPA instead of using Vite's development preview server.
Coverage excludes collector/amazon.py, the actual equivalent of the plan's illustrative
scraper/amazon.py. No schema migration was necessary in this phase.

Authentication, distributed workers/profile coordination, scheduled collection,
automatic evidence retention and a V1 historical-data import remain outside this
implementation. Evidence/input caps limit individual operations, not total disk use.
No CAPTCHA bypass or V2 headed recovery interface is claimed.

All implementation phases are complete. Two live-demo criteria remain unverified:
seven actual days of observations, and a real Groq analysis with a configured key
and suitable confirmed competitors. Neither timestamps nor provider results are
fabricated to mark them complete. See the final report and demo guide.

## Exact files changed in this phase

```text
.dockerignore
.env.example
.github/workflows/ci.yml
.gitignore
Dockerfile
Dockerfile.v1
Makefile
README.md
backend/alembic.ini
backend/app/analysis/claims.py
backend/app/api/analysis.py
backend/app/api/competitors.py
backend/app/api/deps.py
backend/app/api/products.py
backend/app/collector/base.py
backend/app/core/config.py
backend/app/core/exceptions.py
backend/app/core/rate_limit.py
backend/app/main.py
backend/app/services/analysis.py
backend/app/services/evidence.py
backend/tests/conftest.py
backend/tests/test_api.py
backend/tests/test_api_postgres.py
backend/tests/test_hardening.py
backend/tests/test_job_progress.py
backend/tests/test_match_migration.py
backend/tests/test_migrations.py
compose.v1.yaml
compose.yaml
docs/V2_DEMO_GUIDE.md
docs/V2_FINAL_ENGINEERING_REPORT.md
docs/V2_PHASE8_IMPLEMENTATION.md
frontend/Dockerfile
frontend/nginx.conf
frontend/openapi.json
frontend/package-lock.json
frontend/package.json
frontend/postcss.config.js
frontend/src/App.tsx
frontend/src/api/schema.d.ts
frontend/src/hooks/useJobProgress.ts
frontend/src/styles.css
frontend/src/test/progress.test.tsx
frontend/src/test/setup.ts
frontend/vite.config.ts
pyproject.toml
tests/integration/test_sqlite_repository.py
```
