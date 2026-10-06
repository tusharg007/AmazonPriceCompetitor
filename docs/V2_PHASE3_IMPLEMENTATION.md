# Phase 3: Playwright Collection Engine

Implemented against Phase 3 of `V2_IMPLEMENTATION_PLAN.md`. Phase 2 was already complete
in the incoming working tree. Its routes, schemas, database constraints, migration and
tests were retained. No Phase 4 matching, analytics, frontend or AI work was implemented.

## Acceptance criteria and status

The plan's explicit deliverable is:

> `POST /api/products/{id}/collect` triggers a real Playwright scrape of
> amazon.com, stores a `product_observation` row, and saves an HTML evidence file.

| Phase 3 requirement | Status and verification |
|---|---|
| Reuse parser, selector and error behavior from V1 | Passed. Reused Phase 1's adapted Playwright collector/parser/selector modules without another scraper abstraction. V1 parser tests still pass; a compatibility test checks the collection error vocabulary. |
| Browser/context lifecycle and marketplace session reuse | Passed. Standalone worker lazily opens one long-lived collector. Existing per-marketplace contexts and cancellation-safe teardown are reused. Real Chromium tests verify page closure and browser disconnection. |
| Structured product extraction and HTML evidence | Passed. JSON-LD remains primary with DOM fallback. Hash, file length, source, identity and capture provenance are verified before observations are published. |
| CAPTCHA detection with stable failure codes | Passed. Challenges stop collection, return `blocked`, preserve prior evidence and activate existing marketplace cooldown checks. |
| Background polling worker with safe SQL claims | Passed. PostgreSQL uses atomic UPDATE/RETURNING with `FOR UPDATE SKIP LOCKED`; SQLite uses its supported atomic write behavior. Attempts, unique lease tokens, expiry, heartbeats, recovery and fenced completion are covered on both databases. |
| Collection endpoint executes a real amazon.com scrape | Passed in a live smoke check on 2026-10-06. ASIN `B09XS7JWHH`, domain `com`: succeeded, one observation, `playwright_amazon`, `structured_dom`, verified HTML returned by the evidence API (2,322,296 bytes). Used disposable SQLite and evidence storage. |

## Implementation boundaries

The API still enqueues work and returns HTTP 202. It performs no browser navigation.
`CollectionWorker` claims and commits a job before invoking `CollectionService`.
The service coordinates extraction, evidence verification and repository writes.
Each checkpoint/observation uses a short transaction and proves current lease ownership
before writing. Browser startup/navigation never holds a database transaction.

The worker renews leases independently, stops stale operations, recovers expired jobs,
limits transient retries to the existing attempt budget and records sanitized outcomes.
Cancellation preserves committed observations, cancels the collection task and finishes
resource cleanup. A crashed process relies on lease expiry for subsequent recovery.

Observations are appended, never edited or removed. The existing unique capture constraint
remains authoritative; saving the exact same capture twice reuses its observation.
EvidenceArtifact rows retain their individual capture metadata even when HTML hashes match.
HTML files use content-addressed names and atomic replacement, preserving already linked
content if a repeated write fails. The existing evidence API and new collection service
share the same file confinement, SHA-256 and length checks.

The existing `include_competitors` and competitor scan requests collect search pages and
candidate product observations. Every saved candidate references its specific search page
capture. Self, duplicate and sponsored ASINs are excluded; raw candidate results are bounded
by configuration. New candidate products remain untracked. **No relevance scoring or
CompetitorRelationship publication occurs:** those belong to Phase 4. Accordingly, the
competitor read endpoint can remain empty until matching is implemented.

## Local execution

Run from the repository root, with the same database URL and evidence directory configured
for the API and worker. Install dependencies/browsers and apply the existing migrations:

```powershell
uv sync --locked --group dev
uv run playwright install chromium
$env:PYTHONPATH = "backend"
uv run alembic -c backend/alembic.ini upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal at the same repository root:

```powershell
$env:PYTHONPATH = "backend"
uv run python -m app.worker.runner
```

On Linux/macOS use `export PYTHONPATH=backend`; Playwright's Linux browser installation may
need `uv run playwright install --with-deps chromium`. SQLite remains the local default;
`APP_DATABASE_URL` / `DATABASE_URL` can select `postgresql+asyncpg://...` as before.
The standalone worker does not create or migrate the schema.

Register a real ASIN via `POST /api/products`, then send
`POST /api/products/{id}/collect` with `{"include_competitors": false}`. Follow
`GET /api/jobs/{job_id}` or the existing progress WebSocket, read
`GET /api/products/{id}/observations`, and retrieve linked evidence through
`GET /api/evidence/{evidence_artifact_id}/content`.

| Environment setting | Default |
|---|---|
| `APP_WORKER_POLL_INTERVAL` | 1 second |
| `APP_WORKER_LEASE_SECONDS` | 90 seconds |
| `APP_WORKER_HEARTBEAT_SECONDS` | 15 seconds; must be shorter than lease |
| `APP_MAX_SEARCH_PAGES` | 2; accepted range 1–10 |
| `APP_MAX_COMPETITORS` | 20; accepted range 1–100 |
| `APP_BLOCK_COOLDOWN_SECONDS` | 300 seconds |
| `APP_MIN_NAVIGATION_INTERVAL_SECONDS` | 2 seconds |

Existing page/element timeouts, browser path/headless settings and evidence path remain
supported. Run one worker process with its owned browser storage, matching the approved
single-worker architecture. SQL claim concurrency is tested but sharing cookie state files
across multiple worker processes is not an advertised capability.

## Verification

Completed using the existing locked Python 3.13 verification environment and Chromium.
PostgreSQL 16.14 ran in a disposable local test container; application data was untouched.

- Full pytest: **236 passed, no skips**, 109.94 seconds. Includes all V1, Phase 1 and Phase 2
  tests, real Chromium routed-page tests, and SQLite/PostgreSQL worker integration.
- Ruff check: passed.
- Ruff format check: passed.
- mypy (`src main.py backend/app backend/alembic`): passed, 56 source files.
- Compile checks (`backend/app backend/alembic`): passed.
- Application, worker, service and collector module imports: passed.
- Alembic: single head **`002_active_job_dedup`**, unchanged by this phase.
- Existing migration import, SQLite/PostgreSQL upgrade/downgrade, constraint enforcement,
  ORM drift checks and Phase 1-data-preserving upgrades: passed in full pytest.
- Live Amazon API → worker → HTML evidence smoke check: passed as recorded above.
- Git whitespace check: passed.

Deterministic tests cover claim races, PostgreSQL locked-row skipping, stale lease writes,
expiry recovery, attempt exhaustion, cancellation, browser startup failure, heartbeat
connection release, cooldown, append-only history, repeat capture idempotency, transactional
rollback, partial collection, page-specific search provenance, missing/invalid evidence,
configuration validation and atomic file-write failure. Synthetic responses exist only in
tests; production collection uses real Playwright navigation.

## Exact files changed in Phase 3

This list was checked against file hashes saved before Phase 3 edits. Other incoming
uncommitted Phase 2 files remain in the working tree but are not changes made in this phase.

1. `backend/app/api/products.py`
2. `backend/app/collector/amazon.py`
3. `backend/app/collector/base.py`
4. `backend/app/collector/errors.py`
5. `backend/app/core/config.py`
6. `backend/app/core/exceptions.py`
7. `backend/app/models/enums.py`
8. `backend/app/repository/catalog.py`
9. `backend/app/repository/jobs.py`
10. `backend/app/repository/observations.py`
11. `backend/app/services/catalog.py`
12. `backend/app/services/collection.py`
13. `backend/app/services/evidence.py`
14. `backend/app/worker/__init__.py`
15. `backend/app/worker/runner.py`
16. `backend/tests/test_worker.py`
17. `backend/tests/test_worker_browser.py`
18. `backend/tests/test_worker_config.py`
19. `backend/tests/test_worker_persistence.py`
20. `backend/tests/worker_fixtures.py`
21. `docs/V2_PHASE3_IMPLEMENTATION.md`

## Plan adaptations and known limitations

- Retained the stabilized async SQLAlchemy and `collector/` layout instead of recreating
  the plan's illustrative raw-asyncpg and `scraper/` examples. No new schema migration,
  external queue, API endpoint or browser abstraction was needed.
- Preserved existing content-addressed EvidenceArtifact naming and cookie-state context
  reuse rather than replacing completed Phase 1 lifecycle/provenance implementations.
- Live success is one bounded smoke check, not a guarantee of Amazon availability.
  Challenges fail closed and do not invoke automatic CAPTCHA solving. Headed manual
  challenge recovery (`challenge_waiting`) is not implemented in this phase; the Phase 3
  plan requires detection, while the broader architecture describes this additional flow.
- Delivery-location verification remains best effort. Existing provenance reports
  `default`, `verified` or `unverified`; collection does not promise a regional price when
  Amazon will not confirm the requested postal code.
- Candidate selection is raw collection only. Matching thresholds, product relevance,
  classification, relationships and analytical interpretation remain future work.
- HTML retention, size caps and orphan cleanup remain deferred. A crash/storage failure
  can leave a captured file without a database link; it cannot publish an unverified link.
- The suite emits 14 existing Alembic `path_separator` deprecation warnings. They do not
  affect migration correctness and were not changed as part of collection work.

No Phase 3 acceptance requirement remains incomplete. Stop here before Phase 4.
