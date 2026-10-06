# Collection and analysis failure investigation

Verified locally on 2026-10-07, Asia/Calcutta. Existing V2 architecture is retained.

## Cause and resolution

The original registration tracked `B098LMDXS6` on `amazon.com`. Job
`070f138e-cf96-43cb-a2d1-e0c224e6b227` encountered an Amazon CAPTCHA/access block
before any observation was saved. Registering a product stores its identity,
not its price or listing details. Without a successful baseline capture, history,
matching, analytics and Groq inputs were correctly absent. This was not a database
failure or a missing Groq credential.

The user confirmed that the intended marketplace is `amazon.in`. Product 2 now
tracks that identity. The mistaken registration was untracked through the existing
API; its identity and failed-job audit remain intact. No schema reset, synthetic
capture, timestamp alteration or CAPTCHA bypass was used.

A separate live analysis failure returned Groq HTTP 413. Full capture provenance
was being repeated inside the model request. The provider now sends compact listing
facts for every selected competitor, while retaining the complete frozen input,
hashes and observation/artifact identifiers locally for exact claim linking.
It bounds output to 2,048 tokens and uses the installed integration's explicit
`reasoning_effort="low"` setting for GPT-OSS. Its system instruction distinguishes
qualitative prose from Python-computed numbers and avoids repeating product codes.
Numerical and ASIN safeguards remain enforced. Prompt identity was versioned to
prevent reusing an analysis generated with the earlier prompt.

Provider size, rate-limit, authentication and model-configuration errors now have
safe, actionable messages. No provider body or credential is returned to the UI.
Account limits can still vary: see [Groq rate limits](https://console.groq.com/docs/rate-limits)
and [the API reference](https://console.groq.com/docs/api-reference).

## Interface corrections

- Product detail reads the latest persisted collection job after reload. Later
  analysis jobs cannot conceal a previous collection failure.
- A first failed capture displays “No product data collected” and explains why
  history, competitors and analysis are unavailable. Previous successful captures
  remain available after a failed refresh.
- Marketplace cooldown is returned by the API and shown beside disabled collection
  controls. Active collection and cooldown states refresh automatically.
- Failed progress indicators use failure styling; the jobs table labels its
  percentage as work processed, rather than implying successful data capture.
- The collector distinguishes visible sign-in restrictions from CAPTCHA markers;
  hidden markers on an otherwise normal page do not cause a false positive.

## Actual verification

| Check | Result |
| --- | --- |
| Corrected collection | Job `249e193c-6e97-4804-8a02-63fdb2b9c5bc` succeeded: baseline plus 20 candidate observations, zero collection failures |
| Baseline | Campus Men Sl-Spr001 Sliders; captured price `649.0000 INR`, in stock, default delivery context |
| Matching | 20 confirmed saved candidates; no manual relationship promotion |
| Analytics | One genuine baseline capture; minimum/maximum/average `649.0000 INR`; price rank 16 of 21 in the saved cohort |
| Live Groq | Job `56ade632-7d40-40bf-87b9-091f9d6806a1` succeeded with `openai/gpt-oss-20b` |
| Saved analysis | `2d194001-53a3-4dbe-9713-3fbdb23ac46a`: 47 claims, including 7 generated interpretations and 40 deterministic comparisons; all cite saved observations |
| Evidence | Baseline attachment SHA-256 verified: `c87775e07e0c85cf8c49021608de107fdba9f32c41b5649b163019ce1bf77099` |
| Browser | Actual built dashboard, product pages, jobs and live analysis at 1440px and 390px; persisted failure after reload, populated charts, source inspector, no page errors or document overflow |
| Full pytest | 319 passed, no skips or warnings; dedicated PostgreSQL 16 and Chromium enabled; backend coverage 92.21% with approved Amazon adapter exclusion |
| Frontend | 17 tests passed; TypeScript, ESLint, Prettier and production build passed |
| Static/backend | Ruff check and formatting, mypy across 79 source files, compile checks passed |
| Migration | Head remains `004_analysis_evidence`; Compose migration container exits successfully; no schema change required |

Local runtime evidence, database records, browser verification scripts and screenshots
remain ignored. Updated Compose services are running with their existing volumes.
No remote push or public deployment was performed.

## Changed files

- Backend: `app/analysis/provider.py`, `app/analysis/claims.py`,
  `app/collector/base.py`, `app/models/schemas.py`, `app/repository/jobs.py`,
  `app/services/catalog.py` beneath `backend/`.
- Tests: `backend/tests/test_analysis_provider.py`, `backend/tests/test_api.py`,
  `backend/tests/test_collector.py`, `frontend/src/test/pages.test.tsx`.
- Frontend: `frontend/src/api/queries.ts`, `frontend/src/components/JobProgress.tsx`,
  `frontend/src/pages/JobsPage.tsx`, `frontend/src/pages/ProductDetail.tsx`,
  `frontend/src/styles.css`.
- Generated contracts: `frontend/openapi.json`, `frontend/src/api/schema.d.ts`.
- Documentation: this report, `docs/V2_DEMO_GUIDE.md`,
  `docs/V2_FINAL_ENGINEERING_REPORT.md`.

## Remaining limits

Amazon can still block any marketplace or collection session. An ordinary browser
does not share its session with the worker. Cooldown and honest failure reporting
remain necessary; guaranteed automatic CAPTCHA recovery is not claimed. Groq can
still reject requests according to account/model limits, and generated prose still
requires validation. The new product has one real baseline capture: a trend and
capture-to-capture change require more observations over time. Missing history is
never replaced with invented values.
