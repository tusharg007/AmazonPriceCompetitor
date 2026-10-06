# Phase 7 — Analytics & Polish

## Acceptance criteria

Met: dashboard cards show price-trend badges; product detail shows computed price
statistics and a confirmed-cohort price comparison chart; observation CSV export
is available. Product/job lists retain page/limit pagination; observation and
competitor arrays now support offset/limit pagination without breaking existing
response contracts. Competitor totals are returned in `X-Total-Count` and rendered
with table pagination. Claims remain explicitly bounded by analysis output limits.

## Architecture and contracts

- `GET /api/products/{id}/analytics?window_days=30&currency=USD`: counts, Decimal
  min/max/average/current/previous/change/percentage, UTC daily averages with source
  observation UUIDs, and seven-day vs previous-seven-day trends. Window range 1–3650
  days; currency optional, defaults to the latest capture's known currency.
- `GET /api/products/{id}/position`: confirmed-cohort current prices, source capture
  UUIDs/times/artifacts, competition rank, percent-rank, median and exclusions.
  Missing baseline price or fewer than two compatible priced listings returns an
  explicit insufficient-data reason and nullable comparative statistics.
- `GET /api/products/{id}/observations/export?from=…&to=…`: CSV attachment with
  exact Decimal strings, UTC timestamps, ASIN/marketplace/delivery context and full
  capture provenance. Maximum 10,000 captures/export; narrow the range on 413.
  Spreadsheet formula prefixes are neutralized. No HTML or arbitrary instructions
  execute in the SPA.
- Observation/competitor lists accept non-negative `offset` and bounded `limit`.
  Existing array responses, routes, async sessions and service boundaries are retained.

Monetary arithmetic uses Decimal in Python. Missing prices are not zero. Known
currencies remain separate; unverified delivery prices and future captures are
excluded from computed comparisons. Trend thresholds are >5% rising, <-5% falling,
otherwise stable; absent periods/zero denominators return insufficient data.
Dashboard trends use one batch history query, not per-product browser/provider work.
Recharts converts values only for plotting; authoritative values remain API strings.

## Verification

- Full pytest: **299 passed, no skips**, including existing PostgreSQL migrations,
  queue, browser lifecycle, matching, and analysis tests.
- Ruff and formatting passed; mypy passed, 78 source files; compile checks passed.
- Alembic single head remains `004_analysis_evidence`; no schema change was needed.
- Frontend: **14 tests passed**; TypeScript, ESLint, Prettier, production build passed.
- Real Chromium rendered statistics and a two-listing cohort chart from test-only
  fixtures at 390px, with no page exceptions or horizontal overflow.
- API tests cover windows, precision, currencies, location exclusions, tied ranks,
  no history, missing prices, zero denominators, trend thresholds, CSV provenance,
  formula safety, pagination, bad inputs, not-found and database error paths.

## Exact changed files

```text
backend/app/analytics/__init__.py
backend/app/analytics/prices.py
backend/app/api/analytics.py
backend/app/api/competitors.py
backend/app/api/observations.py
backend/app/main.py
backend/app/models/schemas.py
backend/app/repository/analytics.py
backend/app/repository/catalog.py
backend/app/services/analytics.py
backend/app/services/catalog.py
backend/app/services/export.py
backend/tests/test_analytics.py
backend/tests/test_api.py
frontend/openapi.json
frontend/src/api/client.ts
frontend/src/api/queries.ts
frontend/src/api/schema.d.ts
frontend/src/api/types.ts
frontend/src/components/AnalyticsPanel.tsx
frontend/src/pages/Dashboard.tsx
frontend/src/pages/ProductDetail.tsx
frontend/src/styles.css
frontend/src/test/analytics.test.tsx
frontend/src/test/setup.ts
docs/V2_PHASE7_IMPLEMENTATION.md
```

## Adaptations and limitations

Python Decimal aggregation replaces illustrative PostgreSQL-specific AVG/window SQL,
so SQLite development and PostgreSQL share behavior. Array pagination is additive;
already bounded claims need no arbitrary unbounded list reads. Averages are capture
averages, not a continuous or time-weighted market history. Captures in a cohort may
have different times; the chart states this and does not claim a simultaneous market
survey. Percent-rank is nullable for an insufficient cohort. Historical charts remain
bounded at 1,000 captures/window with an explicit note and API offsets available.

No fabricated seven-day production history was added. Long-running history requires
future legitimate captures. Full-stack packaging, rate limiting, coverage verification
and final documentation remain Phase 8 work. Existing build/router/Alembic warnings
are still non-blocking and recorded for the hardening review.
