# V2 completion baseline verification

Verified on 2026-10-06 before implementing Phase 4. Read the approved architecture,
migration and implementation documents and Phase 1–3 reports; inspected the actual
routes, services, collector, repositories, ORM, migrations, tests, Git diff and untracked
source. The Phase 1 report is present and tracked; an initial search missed it.

Incoming HEAD was `098a463`, with accumulated Phase 2–3 changes. While inspection was in
progress, local commit `c46a2b9` captured those changes and the working tree became clean.
That checkpoint is preserved. This report records a new verification checkpoint rather
than duplicating or resetting the foundation work. No push was performed.

The first verification invocation used an incorrect Docker executable path and began
before PostgreSQL was ready, producing connection failures. Docker Desktop was located
under the user's local Programs directory. The isolated PostgreSQL 16.14 container was
started and readiness verified. The complete suite was rerun without changing tests:

- Full pytest: **236 passed**, no skips, 113.17 seconds.
- Ruff check and formatting: passed.
- mypy: passed, 56 source files.
- Backend/Alembic compilation and application/worker/service imports: passed.
- Alembic: single head `002_active_job_dedup`.
- SQLite/PostgreSQL migration, API, queue and browser integration: passed in pytest.
- Git diff whitespace check: passed. Runtime databases, evidence, browser binaries and
  real environment files are not tracked. `.env.example` contains placeholders only.

The existing 14 Alembic path-separator deprecation warnings are non-blocking.
Phase 3's live amazon.com smoke check is recorded in its report; this baseline rerun uses
controlled browser responses and does not fabricate new live collection results.

The next incomplete approved phase is **Phase 4 — Deterministic Matching**. Phase 5–8
work remains deferred until dependencies and each prior phase's checks pass.
