# Phase 5 — React Frontend MVP

## Acceptance criteria and status

All Phase 5 deliverables are met: the dashboard lists tracked products and accepts
ASINs/Amazon URLs; product detail shows actual price history and saved deterministic
competitor decisions; collection queues durable jobs and displays WebSocket progress
with HTTP polling fallback. Jobs and evidence inspection are available. Loading,
empty, error and not-found states are visible and accessible.

## Architecture

React 18, TypeScript, Vite, Tailwind, React Router, TanStack Query and Recharts use
the existing FastAPI services. TypeScript response contracts are generated from
FastAPI OpenAPI via `scripts/export_openapi.py` and `npm run contracts`.
Routes remain thin. Competitor responses add bulk-loaded product details; UTC
timestamps and Decimal strings preserve capture identity and monetary precision.
Charts convert Decimal strings only for plotting; the table retains exact API values.
Unknown price/currency is explicit; different currencies are never merged.
Evidence inspection displays source URL/time/collector/hash and downloads verified
attachments. Captured HTML is never injected into the application document.

## Verification

- Full pytest: **259 passed, no skips**, including PostgreSQL and Chromium lifecycle checks.
- Final targeted API/contract regression rerun: **68 passed**.
- Ruff and Ruff format: passed; mypy: passed, 63 source files.
- Compile/import and Alembic: passed; single head `003_match_evidence` unchanged.
- Vitest/MSW: **9 passed**; TypeScript, ESLint, Prettier and production build passed.
- Real Chromium rendered dashboard, product detail and jobs using test-only HTTP
  fixtures. Desktop 1440px/mobile 390px checks found no horizontal overflow or page
  exceptions. Dashboard screenshot visually inspected.
- Git whitespace check passed. Runtime captures, databases, dependencies and screenshots
  remain ignored. No secrets were added.

## Exact changed files

`.gitignore`; `backend/app/models/schemas.py`; `backend/app/repository/catalog.py`;
`backend/app/services/catalog.py`; `backend/tests/test_api.py`;
`backend/tests/test_frontend_contracts.py`; `scripts/export_openapi.py`; this report;
and these frontend files:

```text
.env.example
.prettierignore
eslint.config.js
index.html
openapi.json
package-lock.json
package.json
postcss.config.js
tailwind.config.js
tsconfig.json
vite.config.ts
src/App.tsx
src/main.tsx
src/styles.css
src/format.ts
src/api/client.ts
src/api/queries.ts
src/api/schema.d.ts
src/api/types.ts
src/hooks/useJobProgress.ts
src/components/EvidenceInspector.tsx
src/components/Feedback.tsx
src/components/JobProgress.tsx
src/components/PriceHistoryChart.tsx
src/pages/Dashboard.tsx
src/pages/JobsPage.tsx
src/pages/ProductDetail.tsx
src/test/pages.test.tsx
src/test/setup.ts
```

## Adaptations and limitations

Analysis View is deferred to Phase 6 because its endpoints/claims do not yet exist.
No fake production data or placeholder analysis page was introduced. Existing
SQLAlchemy abstractions and additive API fields replace illustrative raw queries.
History is bounded at 1,000 captures/window and explicitly says so. WebSockets use
same-origin ws/wss or the configurable API origin, not a hard-coded localhost URL.
Evidence opens as a safe attachment rather than active untrusted HTML. Build emits
a 622KB chunk-size warning; code splitting remains a non-blocking polish item.
React Router emits v7 future warnings in tests. Alembic retains its existing
path_separator deprecation warnings. No analytics or AI functionality was added.

Continue with Phase 6; no Phase 5 acceptance requirement remains incomplete.
