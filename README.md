# Amazon Competitor Analysis

A Streamlit application that gathers Amazon product and competitor evidence through Selenium, stores immutable observations in SQLite, and produces grounded Groq analysis from saved snapshots.

## What changed

- Oxylabs and TinyDB are removed from the runtime stack.
- Selenium WebDriver is the only product and search page acquisition path.
- SQLite replaces append-only JSON storage with product/location contexts, snapshots, durable jobs, competitor runs, analyses, migrations, and backups.
- Browser work runs in a separate worker so Streamlit reruns do not create duplicate scraping or LLM requests.
- Analysis uses Groq-hosted open-weight models, is tied to the exact saved snapshots it used, and rejects competitor ASINs that are not in those records.
- Saved search observations remain visible, while Groq receives a conservative comparison cohort: matching currency and verified delivery location, a price within 0.5–2 times the tracked product when its price is known, and no obvious compatibility or different-market-version listing. This is a relevance screen, not an authenticity check.

## Quick start

Install Python 3.13 and uv, copy `.env.example` to `.env`, then fill `GROQ_API_KEY` only if analysis is needed.

```powershell
uv sync --locked --group dev
uv run python -m scripts.db_admin migrate
uv run python -m src.worker
```

In a second terminal:

```powershell
uv run streamlit run main.py
```

Submit an ASIN, marketplace, and optional delivery location. The UI creates a durable job. The worker processes it, and the UI displays saved status/results on later reruns. Start competitor and analysis jobs only from their explicit buttons.

## Quality checks

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src main.py
uv run pytest -q --basetemp .test-tmp
uv run pip-audit
```

Automated tests never contact Amazon or Groq. Live Selenium checks are intentionally separate because Amazon access, location controls, and selectors vary by marketplace.

## Legacy TinyDB import

The importer uses only the standard library and leaves the source JSON untouched.

```powershell
uv run python -m scripts.migrate_tinydb --source data.json --dry-run
uv run python -m scripts.migrate_tinydb --source data.json --apply
```

Review the dry-run report first. The importer records file-hash and record IDs so importing the same source again does not create duplicate observations.

## Deployment boundary

This release is designed for one host, one worker, one active browser job, and a persistent local SQLite volume. The database must be on a local filesystem. Run `uv run python -m scripts.db_admin health` before deployment and use SQLite 3.51.3 or a documented backport of its WAL-reset fix with `APP_STRICT_SQLITE_VERSION=true` in production.

`docker compose build` and `docker compose up -d` start the migration, UI, and worker services. The supplied configuration binds Streamlit to localhost. Add an authenticated TLS gateway before public exposure.

## Limits

Selenium does not guarantee Amazon access. CAPTCHA, sign-in, blocked pages, unsupported delivery controls, price/variant differences, and selector changes are recorded as failures or partial results. The app does not use stealth automation, proxy rotation, CAPTCHA solving, or direct HTTP scrape fallbacks. Prices are not currency-converted, and the LLM’s recommendations are generated interpretation rather than verified marketplace facts. Groq provides hosted inference and its free tier is rate-limited; the hosted API is not itself open source.

See [architecture](docs/architecture.md), [operations](docs/operations.md), and [validation](docs/validation.md) for the data model, runbook, and verification evidence.
