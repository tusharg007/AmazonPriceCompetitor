# Phase 4 — Deterministic Matching

## Acceptance and implemented architecture

All Phase 4 requirements are complete: V1 hard exclusions are preserved verbatim;
normalized title, brand, category, price and rating factors use the approved weights
0.35/0.25/0.20/0.15/0.05. Scores >=0.7 are confirmed, >=0.3 ambiguous, and lower scores
rejected. Known structured type, capacity, dimensions, quantity and variant conflicts
also reject candidates. Missing specifications are recorded, not fabricated.

The existing collection service calls a separate matching service inside its short,
lease-fenced candidate transaction. Pure normalization/scoring lives in `app/matching`;
relationship upserts and audit insertion live in the repository. The existing competitor
REST endpoint exposes scores/statuses and per-attribute `evidence_summary`.

`MatchEvidence` stores the exact baseline/candidate observation IDs, job ID, policy version,
scoring inputs and source provenance. It is append-only and unique per capture pair/policy.
Relationship identity remains unique per product pair. Replayed decisions do not overwrite
their existing audit or relationship summary. Fresh captures keep earlier audits.
Captured title/brand are now frozen in each new observation's raw metadata, keeping later
comparison input independent from mutable Product labels. Historical observations are untouched.

Migration `003_match_evidence` adds only the missing audit table and index. It retains
completed entity/table names and supports SQLite and PostgreSQL. Upgrade/downgrade and
ORM drift tests pass; earlier products, observations and relationships survive.

## Verification

- Full pytest with actual PostgreSQL 16.14: **258 passed**, no skips, 133.51 seconds.
- Focused matching/worker/migration tests: passed before the full suite.
- Ruff and formatting: passed.
- mypy: passed, 63 source files.
- Compile/import and Git whitespace checks: passed.
- Single Alembic head: **003_match_evidence**.

Tests cover strong/non/ambiguous matches, regional/currency/location exclusions, variants,
pack/capacity/type conflicts, missing inputs, normalized equivalent units, deterministic
repeatability, score thresholds, V1 parity, duplicate relationship/audit handling, API
filters and invalid/not-found responses, both database engines and transaction rollback.

## Exact files changed

- `backend/alembic/versions/003_match_evidence.py`
- `backend/app/api/competitors.py`
- `backend/app/matching/__init__.py`
- `backend/app/matching/exclusions.py`
- `backend/app/matching/scoring.py`
- `backend/app/models/entities.py`
- `backend/app/repository/matching.py`
- `backend/app/repository/observations.py`
- `backend/app/services/collection.py`
- `backend/app/services/matching.py`
- `backend/app/services/records.py`
- `backend/tests/test_matching.py`
- `backend/tests/test_match_migration.py`
- `backend/tests/test_migrations.py`
- `backend/tests/test_worker.py`
- `docs/V2_PHASE4_IMPLEMENTATION.md`

## Adaptations, limitations and later phases

Retained SQLAlchemy, current relationship naming and thin existing REST routes. Rejected
collected candidates also receive auditable decisions, making exclusion reasons visible.
The Phase 3 test forbidding relationships was updated to require a traced ambiguous match:
that deliberately deferred behavior is now implemented. Migration-head assertions advance
to the new revision; previous constraints and data-preservation assertions remain intact.

Matching is conservative lexical/structured comparison, not proof of commercial equivalence.
Specifications are compared only when explicitly extracted; unobserved pack counts, product
dimensions or capacities are not guessed. Legacy observations lacking captured title/brand
use existing known Product metadata, recorded in the audit. Production deployment scale
and multi-worker cookie sharing are not claimed. Ambiguous cases stay ambiguous; no LLM,
frontend or analytics was introduced. These remain subsequent approved phases.

The 19 existing Alembic path-separator warnings remain non-blocking. No push was performed.
