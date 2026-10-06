# Phase 2 implementation: Core REST API

## Approved scope and acceptance criteria

The source of truth is **V2_IMPLEMENTATION_PLAN.md, section 4, Phase 2: Core API**.
The migration guide numbers its phases differently; its phase numbering was not substituted
for the implementation plan.

The plan's exact deliverable is:

> All endpoints in Swagger UI (`/docs`). FastAPI TestClient tests cover: product
> creation, duplicate dedup, job enqueue, 422 on bad ASIN.

The Phase 2 implementation details require:

- Validate ASIN, supported marketplace, and delivery/postal format.
- Return an existing product for the same ASIN/domain/geographic identity.
- Return product metadata, latest observation, competitor count and last capture time.
- Check marketplace cooldown before enqueueing a new collection job.
- Deduplicate active jobs through `idx_jobs_active_dedup` and return job identity/status.
- Stream job status, progress and errors over `/ws/jobs/{id}`, closing on terminal status.
- Use Pydantic contracts and centralized validation/database error handling.

The Phase 2 router skeleton names products, observations, jobs, competitors and evidence.
Their endpoint contracts come from the architecture's API Design section. Analysis router
imports and analysis-schema examples in the skeleton are not implemented: analysis execution
and claim storage explicitly belong to Phase 6. Analytics belong to Phase 7.

## Reused foundation

- Existing Product, ProductObservation, EvidenceArtifact, CollectionJob and
  CompetitorRelationship SQLAlchemy entities.
- Existing application lifespan, application-owned session factory, request transaction
  context manager and settings.
- Existing ProductRead, ProductObservationRead, EvidenceArtifactRead and CollectionJobRead
  contracts, extended where Phase 2 needs more fields.
- Existing Amazon ASIN URL parser; it is called only after an exact supported-host check.
- V1 geographic-normalization and location-validation behavior, adapted to backend validators
  and extended with marketplace format checks.

The collector is not rewritten or instantiated by an API request. No second browser manager,
database engine, worker, job broker, frontend or analysis implementation was added.

## Endpoints

All HTTP routes below use the configurable API prefix, default `/api`.

| Method | Default path | Contract / outcome |
|---|---|---|
| POST | `/api/products` | ProductCreate -> ProductResponse; 201 new, 200 existing/retracked |
| GET | `/api/products` | tracked_only, page, limit -> Page[ProductResponse] |
| GET | `/api/products/{product_id}` | positive integer -> ProductResponse; 404 absent |
| DELETE | `/api/products/{product_id}` | stop tracking; 204, no physical deletion |
| GET | `/api/products/{product_id}/observations` | from, to, limit -> ProductObservationRead[] |
| POST | `/api/products/{product_id}/collect` | optional CollectRequest -> CollectionJobRead; 202 |
| GET | `/api/jobs` | status, page, limit -> Page[CollectionJobRead] |
| GET | `/api/jobs/{job_id}` | UUID -> CollectionJobRead; 404 absent |
| GET | `/api/products/{product_id}/competitors` | status, min_score -> CompetitorRead[] |
| POST | `/api/products/{product_id}/competitors/scan` | enqueue discovery -> CollectionJobRead; 202 |
| GET | `/api/evidence/{evidence_id}` | UUID -> EvidenceArtifactRead |
| GET | `/api/evidence/{evidence_id}/content` | verified original HTML, PNG or JSON bytes |
| WS | `/ws/jobs/{job_id}` | JobProgress frames; independent of the HTTP prefix |

Swagger documents all HTTP endpoints and their response/error schemas. WebSockets are not
part of OpenAPI; their contract is documented here and tested with FastAPI TestClient.
Existing `/api/health` and `/health` remain available.

## Request and response contracts

### Product registration

```json
{"asin": "B09XS7JWHH", "domain": "com", "requested_location": "10001"}
```

Alternatively supply `url`, with optional matching `asin` and `domain`. Only HTTP(S) product
URLs at `amazon.<supported-domain>` or `www.amazon.<supported-domain>` are accepted. URL
credentials, nonstandard ports, foreign hosts, malformed product paths, and conflicting
identities are rejected. No user-supplied URL is fetched during registration.

ASINs are stripped and uppercased. Domains are normalized. Supported domains remain
com, in, ca, co.uk, de, fr, it, ae. Blank location becomes the existing `__default__` geographic
key. Postal-format checks cover US, India, Canada, UK, Germany, France and Italy; UAE accepts
a bounded delivery-locality string. Formatting validation does not verify deliverability.
Canadian and UK postal spacing is canonicalized for identity deduplication.

Unknown registration/collection body fields are rejected. ProductResponse includes the
existing ProductRead fields plus latest_observation (nullable), competitor_count (confirmed
relationships), and last_collected_at (nullable). Latest observations are selected in batch
with deterministic timestamp/UUID ordering rather than async lazy relationship loading.

### Lists and history

Page responses contain `items`, `total`, `page`, `limit`. Product/job pagination defaults to
page 1 and limit 20; page must be positive, limit is 1-100. Product lists default to tracked
products and sort by product ID. Job lists sort by creation time descending then UUID.

History defaults to 100 items, allows 1-1000, sorts chronologically with a UUID tie-breaker,
and uses inclusive `from`/`to` bounds. Supplied datetime bounds must include a timezone and
are normalized to UTC. Reversed bounds are rejected. Observation responses include decimal
prices serialized as strings and all five provenance fields: source_url, captured_at,
collector, extraction_method, evidence_id. SQLite persists UTC without timezone offsets;
its returned datetime representation retains the Phase 1 read-schema behavior.

Competitor reads filter stored relationships by pending/confirmed/ambiguous/rejected status
and minimum score in [0,1]. They include stored matching evidence_summary. These routes do
not perform discovery or scoring.

### Collection requests and progress

CollectRequest is optional and defaults to `include_competitors=false`; the field accepts
JSON booleans only. Collection requests persist `scrape_product` jobs; scan requests persist
`discover_competitors` jobs. Request options are stored under `result.request`, using the
existing JSON column, and hashed for the stable request_key. A later worker can consume
these options and publish results; Phase 2 does not implement that worker.

Equivalent queued/running requests return the same job. Terminal jobs do not block a new
request. Different collection options produce different request keys. Existing active jobs
can be retrieved during cooldown without creating another job.

Cooldown derives from the latest failed/partial job with error_code `blocked` in the same
marketplace and the existing configured block_cooldown_seconds. It applies across products
in that marketplace. This reuses durable job state rather than inventing a separate cooldown
store or process-local registry. Once execution exists, its block failures must populate
the existing status/error/finished_at fields.

CollectionJobRead returns ID, kind, product ID, status/progress, result, attempts/max_attempts,
diagnostic errors and lifecycle timestamps. Enqueue writes commit before HTTP success.
The API does not fabricate progress or completed collection data.

WebSocket frames contain `status`, `progress`, `error_code`, `error_message`. Polling uses
short-lived sessions released before socket waits. Terminal status closes with code 1000,
invalid/missing identity with 1008, and database failure with 1011. Client disconnection
stops polling; client messages cannot modify job state or speed up polling.

### Evidence and errors

Evidence metadata preserves ID, type, storage_path, content_size_bytes, content_hash,
source_url, collector and captured_at. Content is read off the event loop, confined to
the configured evidence root, and verified against its stored SHA-256 and byte count.
HTML downloads use attachment, sandbox, nosniff and no-store headers; captured scripts
are not intentionally rendered into the application origin.

Application errors use ErrorResponse: `error`, `detail`, optional typed `issues`.
Malformed inputs return 422; absent records/files 404; conflicts or corrupted evidence 409;
cooldown 429 with Retry-After; database/storage unavailability 503. SQL statements,
connection details and submitted secret values are not included in database error responses.

## Persistence and migration

Revision `002_active_job_dedup` adds only the approved unique partial index on
collection_jobs(kind, product_id, request_key) where status is queued/running. The ORM
declares the same PostgreSQL and SQLite predicates. Revision `001_initial` is unchanged.
Upgrade/downgrade preserves products, jobs, observations and evidence. An existing database
with duplicate active identities must resolve those jobs deliberately before upgrading;
the migration does not silently delete history.

DELETE updates only Product.is_tracked. There are no observation/evidence update or delete
endpoints, and their provenance constraints are unchanged.

Before starting the API against an existing database:

```powershell
uv sync --locked --group dev
uv run alembic -c backend/alembic.ini upgrade head
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Use the existing APP_DATABASE_URL/DATABASE_URL and APP_EVIDENCE_DIR settings. Production
still requires PostgreSQL migrations; the test/development create_all shortcut does not
migrate existing tables. Swagger: `http://127.0.0.1:8000/docs`. The local API has the existing
MVP authentication scope; this task does not add a public deployment.

## Verification

Verified with the locked Python 3.13 environment and an isolated PostgreSQL 16.14 container:

- Full pytest: **192 passed, no skips**, 14 inherited Alembic path-separator warnings.
- Ruff lint: passed.
- Ruff formatting: passed.
- mypy for V1, backend application and Alembic: passed, **49 source files**.
- Compile checks: passed for backend application and Alembic.
- Imports: 24 backend modules imported; importing the API creates no database engine.
- Alembic: single head **002_active_job_dedup**; fresh upgrades, ORM drift checks,
  downgrades and Phase 1-data-preserving upgrades passed.
- SQLite/PostgreSQL: concurrent identity upserts, active-job uniqueness, later/terminal jobs,
  history queries, competitor filters, evidence links and marketplace cooldown passed.
- Lockfile check and locked dependency installation: passed.
- Git diff whitespace check: passed.

HTTP tests cover success, invalid input, not-found cases and sanitized database failures for
every applicable endpoint. Additional tests cover failed-commit rollback, evidence integrity,
path escapes, file failures, retracking, concurrent writes, WebSocket terminal/error closure,
disconnect and connection release. V1 and all Phase 1 tests remain passing.

The disposable PostgreSQL container is removed after verification. Application runtime data
was not migrated, deleted or populated by verification.

## Exact files changed in this phase

1. backend/app/api/deps.py
2. backend/app/api/products.py
3. backend/app/api/observations.py
4. backend/app/api/competitors.py
5. backend/app/api/evidence.py
6. backend/app/api/jobs.py
7. backend/app/core/exceptions.py
8. backend/app/core/validation.py
9. backend/app/main.py
10. backend/app/models/entities.py
11. backend/app/models/schemas.py
12. backend/app/repository/__init__.py
13. backend/app/repository/catalog.py
14. backend/app/repository/jobs.py
15. backend/app/services/__init__.py
16. backend/app/services/catalog.py
17. backend/app/services/jobs.py
18. backend/alembic/versions/002_active_job_dedup.py
19. backend/tests/test_api.py
20. backend/tests/test_api_postgres.py
21. backend/tests/test_job_progress.py
22. backend/tests/test_migrations.py
23. pyproject.toml
24. uv.lock
25. docs/V2_PHASE2_IMPLEMENTATION.md

## Plan adaptations and remaining work

- Retained the approved SQLAlchemy fallback and current entity/table names instead of
  rewriting the stabilized foundation into the plan's raw-asyncpg examples.
- Added the missing active-job index in a new migration, not by modifying published Phase 1.
- Database availability errors return 503 and integrity conflicts 409 rather than treating
  all database failures as the example's generic 400.
- Omitted later-phase analysis/claim schemas and endpoints, matching execution, analytics,
  React, worker leasing/execution and AI/agents. No placeholder success responses were added.
- Grouped related persistence/read operations in two repository and two service modules;
  transport handlers contain no database queries or browser operations.

No Phase 2 acceptance requirement remains unfinished. Actual job execution is intentionally
future work: queued jobs stay queued until the later worker/collector integration is built.
Schema upgrades are not run automatically against user data. Remaining foundation items
(retention policies, evidence size caps, broader live-marketplace checks, readiness diagnostics,
and documentation naming consistency) remain outside this phase, as recorded in the Phase 1
reconciliation. Stop here before Phase 3.
