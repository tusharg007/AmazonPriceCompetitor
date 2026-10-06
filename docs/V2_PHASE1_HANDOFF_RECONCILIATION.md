# Phase 1 handoff reconciliation

Verified on 2026-10-06. Scope: stabilize the existing Phase 1 foundation and finish the
Critical/High review fixes already in progress. No Phase 2 application features were implemented.

## Incoming repository state

HEAD was `2447885` (`Fix pytest imports in GitHub Actions`). The recent history contained
V1 changes only. `.gitignore` and `pyproject.toml` were modified; `backend/` and the three
approved V2 documents were untracked. Consequently, Git cannot distinguish the original
Phase 1 implementation from the previous agent's later review changes. Classifications
below describe the inspected incoming files, not inferred commit authorship.

All incoming backend files and all three approved documents were read before editing.
The incoming V2 SQLite database contained no tables and no Alembic version. The initial
migration was untracked and unreleased, so its fixes remain in `001_initial`; no applied
revision was replaced. Runtime V1 files and the three approved architecture documents
were preserved. `.gitignore` changes belong to the incoming handoff and were not edited.

Baseline: Ruff lint passed; formatting failed on four files; mypy reported two errors
in `collector/base.py`; full pytest reported **68 passed, 1 failed** (`1.5K` became 15,000).
The dependency lock did not match the edited project manifest.

## Findings and resolution

| Incoming fix | Incoming classification | Final result |
| --- | --- | --- |
| Browser lifecycle | Incomplete; startup, context initialization and cancellation paths untested | Retain the Playwright manager before startup awaits; finish page/context/browser/driver cleanup on failure and cancellation, including repeated cancellation during teardown |
| Long-lived sessions | Working per-marketplace in-memory reuse; disk-state typing incorrect and saving incomplete | Preserve reuse, save state on teardown, reject invalid/cross-marketplace state, validate domains before profile creation, serialize context creation |
| App-owned engine | Incomplete | Lifespan uses factory-supplied settings, owns/disposes its engine in a protected finalizer, cleans app state after failure/cancellation, and preserves externally supplied test-engine ownership |
| Request DB dependency | Incorrect async-generator forwarding on exceptions | Use the app's session factory through an async context manager; commit successful requests, roll back failed/cancelled requests, close sessions |
| Health engine access | Engine access sound; settings/alias override incomplete | Preserve app-state engine access; settings and both health paths now honor app settings and dependency overrides |
| CORS | Safe default, incomplete configuration wiring | Support the documented `APP_ALLOWED_ORIGINS` and previous `_RAW` name; keep credentials disabled; test unlisted origins |
| Observation deduplication | Incorrect and conflicting with append-only history | Unique `(product_id, captured_at, collector, evidence_id)` rejects reprocessing a capture while allowing a later observation of unchanged HTML |
| Required provenance | Frozen Pydantic metadata sound; persistence incomplete | Require `source_url`, explicit `captured_at`, `collector`, `extraction_method`, and non-null/non-empty `evidence_id`; ORM and migration agree |
| Amazon selectors/location | Incomplete | Fix brand-value and modern search-link selectors; use search fallback chains; continue after unusable location inputs; verify the displayed location rather than treating an Apply click as proof |
| K/M parsing | Incorrect | Decimal suffixes retain their decimal point; `1.5K` is 1,500 and `1.5M` is 1,500,000 |
| Parser/timeout improvements | Partially complete | Preserve JSON-LD priority and structured DOM fallback; handle graph/type-list products, invalid/zero prices and invalid ratings; preserve correct price/currency pairing; separate navigation/element timeouts; pace each search page |
| Evidence capture | Untested cross-platform byte integrity | Store the exact UTF-8 bytes whose hash and size were recorded; test saved-file hash against provenance |
| Build/test configuration | Conflicting and unverified | Restore approved Python 3.13 targets, declare asyncio SQLAlchemy and HTTPX test dependencies, constrain SQLAlchemy to 2.0, update uv.lock, and extend CI with backend types, Chromium and PostgreSQL tests |

Rejected incoming choices: nullable evidence IDs; global settings inside an app factory's
lifespan/dependencies; forwarding request sessions through `async for`; content-only
deduplication across all capture times; unconditional Chromium sandbox disabling;
claiming a location was verified solely because Apply succeeded; stripping decimal
punctuation from K/M counts; and Python 3.11 targets conflicting with the approved runtime
and the locked dependency stubs. The collector abstraction, per-marketplace reuse,
SQLAlchemy persistence, frozen provenance model and structured extraction were retained.

## Verification

An isolated environment was synchronized from `uv.lock` using Python **3.13.14**.
PostgreSQL verification used a disposable local PostgreSQL **16.14** container and an
explicit test database; it did not use the application's runtime database.

| Check | Result |
| --- | --- |
| `pytest -q --basetemp .test-tmp` | **114 passed**, no skips; 10 deprecation warnings |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `mypy src main.py backend/app backend/alembic` | Passed, 35 source files |
| `uv lock --check` / locked environment sync | Passed |
| Alembic head | Single head: **001_initial** |
| SQLite migration | Fresh upgrade, duplicate/missing-provenance rejection, unchanged-content history, ORM drift check, downgrade and re-upgrade passed |
| PostgreSQL migration | Actual upgrade, ORM drift check, duplicate/missing-provenance rejection, unchanged-content history and downgrade passed; offline DDL also checked |
| Compile/import checks | Backend and Alembic compiled; 16 backend modules imported; no DB engine created on import |
| Secrets / generated state | No real API-key patterns found in reviewed source/docs; environment, browser profiles, evidence and test state remain ignored |

Browser tests include real Chromium disconnection after errors/cancellation and cookie
isolation between marketplaces, plus fault injection for partial startup and cleanup failures.
Collector workflow tests route requests to HTML fixtures; they do not test live Amazon access.

The 10 warnings are one Starlette 422-status-name deprecation and nine Alembic legacy
path-separator warnings. Those Low issues were left outside this Critical/High task.

## Exact files changed in this reconciliation

The following 24 code/configuration files differ from the incoming handoff; this report
is the 25th file authored during reconciliation:

- `.github/workflows/ci.yml`
- `pyproject.toml`
- `uv.lock`
- `backend/alembic/env.py`
- `backend/alembic/versions/001_initial_schema.py`
- `backend/app/api/deps.py`
- `backend/app/collector/amazon.py`
- `backend/app/collector/base.py`
- `backend/app/collector/parsers.py`
- `backend/app/collector/selectors.py`
- `backend/app/core/config.py`
- `backend/app/core/database.py`
- `backend/app/main.py`
- `backend/app/models/entities.py`
- `backend/app/models/schemas.py`
- `backend/tests/conftest.py`
- `backend/tests/test_collector.py`
- `backend/tests/test_config.py`
- `backend/tests/test_db.py`
- `backend/tests/test_extraction.py`
- `backend/tests/test_health.py`
- `backend/tests/test_lifecycle.py` (new)
- `backend/tests/test_migrations.py` (new)
- `backend/tests/test_parsers.py`
- `docs/V2_PHASE1_HANDOFF_RECONCILIATION.md` (this new report)

Current tracked Git diff: **4 files, 310 insertions, 3 deletions**. It includes the incoming
`.gitignore` changes. The 31 files under `backend/` and the four V2 documents remain untracked and therefore
are not represented in `git diff --stat`. Changes are intentionally left uncommitted.

## Remaining Medium/Low issues and Phase 2 readiness

- The approved documents use different phase numbering, direct asyncpg examples versus
  the permitted SQLAlchemy fallback, and different evidence/relationship table names.
  The explicit handoff scope takes precedence here; reconcile those API/schema contracts
  when planning Phase 2 without creating the deferred analysis tables now.
- Append-only writes are a convention beyond the new insertion constraint. ORM updates
  and cascading product deletes are still possible; choose history-retention semantics
  before adding product deletion/update flows.
- Evidence writes are synchronous and have no size/retention policy. Extraction reads the
  live DOM after HTML capture, so a rapidly changing page may differ from the saved snapshot.
- Health's Chromium check is directory-based; unavailable databases are not yet translated
  into a structured readiness response.
- Some JSON-LD availability values and malformed optional fields still need broader fixtures;
  fixtures do not prove current live marketplace compatibility.
- The reserved Groq configuration should be checked only when its later phase is authorized.
  No V2 AI, frontend, LangGraph or agent implementation was added.
- The deprecations listed above remain Low issues.

**Safe to continue Phase 2 foundation work: yes.** The Critical/High fixes in this handoff
are complete and tested. This task ends at the stabilized Phase 1 boundary.
