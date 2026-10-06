# Phase 6 — LLM Analysis with Evidence Tracking

## Acceptance criteria

Met: bounded Groq analysis creates persisted `analysis_runs`, `analysis_claims`
and `claim_evidence`. Every published claim references exact stored observations;
the frontend renders capture citations and an evidence inspector with verified
HTML attachment downloads. No agents, browser-driven reasoning or fabricated
production evidence were introduced.

## Implemented architecture and contracts

- `POST /api/products/{id}/analyze` returns 202 with the existing Job contract.
  Baseline and confirmed matches must refer to the same baseline capture. Input
  observations and artifact hashes are verified and frozen into the job before
  any provider call. Missing evidence/matches return 409, missing configuration
  503, bad identifiers 422 and absent products 404.
- `GET /api/analyses/{id}` returns run identity, policy versions, status and claims.
  `GET /api/analyses/{id}/claims` returns each claim and observation citations.
  Sources include ASIN, observation UUID, price text, URL, capture time, collector,
  extraction method, content hash and artifact UUID.
- The existing durable worker dispatches analysis without creating a browser.
  Provider waits hold no database session. Publication is lease-fenced and atomic.
  Input SHA-256/model/prompt/schema identity deduplicates calls; successful runs
  are reused, while failed identities may be explicitly retried.
- V1 models, drift repair, schema failure/generation recovery, output bounding and
  the full original prompt are preserved. AST/prompt parity is tested. An extra
  V2 instruction reserves quantitative prose for Python calculations.
- Unknown competitor ASINs fail validation. Numeric/URL prose is withheld; prices
  and rating comparisons are generated from captured values with Decimal arithmetic
  and currency/location checks. Claim origins identify computed facts vs generated
  interpretations. Summary/positioning/recommendations cite the supplied cohort;
  candidate insights cite baseline plus that candidate.

## Verification

- Full pytest: **276 passed, no skips**. Final expanded API DB-error tests: **15 passed**.
- PostgreSQL and SQLite fresh migration/ORM drift checks passed. PostgreSQL run
  uniqueness and claim-observation foreign keys were exercised against PostgreSQL 16.
- Worker tests cover no-browser analysis, active enqueue dedup, cached execution,
  failed-run retry, input tampering, replaced leases and full rollback on invalid links.
- Ruff, formatting and mypy passed (72 source files); compile/import passed.
- Single Alembic head: **004_analysis_evidence**.
- Frontend: **12 tests passed**, ESLint, TypeScript, Prettier and production build passed.
- Real Chromium Analysis View fixture check passed at mobile width with no page
  exceptions or horizontal overflow. Test data exists only in tests/checks.
- No Groq API key is configured in this environment. Provider schema tiers and safe
  failures were verified with mocks; no live Groq success is claimed.

## Exact changed files

```text
backend/alembic/versions/004_analysis_evidence.py
backend/app/analysis/__init__.py
backend/app/analysis/claims.py
backend/app/analysis/errors.py
backend/app/analysis/ported.py
backend/app/analysis/provider.py
backend/app/api/analysis.py
backend/app/core/config.py
backend/app/main.py
backend/app/models/entities.py
backend/app/models/schemas.py
backend/app/repository/analysis.py
backend/app/repository/jobs.py
backend/app/services/analysis.py
backend/app/worker/runner.py
backend/tests/test_analysis.py
backend/tests/test_analysis_provider.py
backend/tests/test_api.py
backend/tests/test_match_migration.py
backend/tests/test_migrations.py
frontend/openapi.json
frontend/src/App.tsx
frontend/src/api/queries.ts
frontend/src/api/schema.d.ts
frontend/src/api/types.ts
frontend/src/components/JobProgress.tsx
frontend/src/pages/AnalysisView.tsx
frontend/src/pages/ProductDetail.tsx
frontend/src/test/analysis.test.tsx
frontend/src/test/pages.test.tsx
docs/V2_PHASE6_IMPLEMENTATION.md
```

## Adaptations, limitations and later work

The established SQLAlchemy/EvidenceArtifact/queue abstractions replace illustrative
raw-asyncpg SQL. Frozen input JSON is additionally stored for reproducibility. Failed
run identities are reused on manual retry; successful results are never overwritten.
Safe downloaded HTML replaces executing raw Amazon HTML inside the SPA.

Matching remains deterministic: ambiguous candidates are not silently promoted by
AI. Only current confirmed matches are analyzed. Qualitative claims remain model
interpretations; citations prove input provenance, not semantic truth. The conservative
number filter can withhold valid feature numbers as well as invalid calculations.
Provider token usage is nullable and is not invented. Live provider availability,
quotas and model support require a configured key. Analytics and full-stack packaging
remain Phase 7/8 work. Existing build-size/router/Alembic warnings are non-blocking.
