# Validation record

## Implemented checks

- `uv lock` resolved the new Selenium and direct Pydantic dependencies and removed TinyDB.
- `uv sync --locked --group dev` completed with Python 3.13.14.
- `ruff check .`, `ruff format --check .`, and `mypy src main.py` pass.
- `pytest -q --basetemp .test-tmp` passes 41 tests covering ASIN/domain/location validation, locale money parsing including INR, Groq and container browser configuration, downstream job prerequisites, SQLite migration/rollback/identity/snapshot/job idempotency, preservation of an existing database while adding `amazon.in`, partial competitor analysis, conservative comparison selection, bounded LLM output, stale-element recovery, persistent browser profile locking, one browser per job, paced navigation, bounded human challenge recovery, durable marketplace cooldowns, and a Streamlit form smoke test.
- `pip-audit` passes with no known vulnerabilities after locking `langchain-groq` 1.1.3, the Groq SDK 0.37.1, and their transitive dependencies.
- A real Selenium session starts and exits successfully in the production worker image with its pinned Chromium and ChromeDriver 154 pair.

## Environment evidence

The installed Python 3.13.14 runtime reports SQLite 3.50.4. It passes integrity and foreign-key checks, but is below the 3.51.3 WAL-reset-fix gate. Development therefore uses `APP_STRICT_SQLITE_VERSION=false`; production must use a vetted SQLite runtime and enable that setting. No Groq live calls were made during implementation. The eight marketplaces have shared selector support and parser coverage; live validation remains required for each marketplace before production claims.

A containerized live check of `amazon.in` verified PIN `273015`, parsed an INR product price, and returned competitor-search candidates without failures. This confirms the India adapter path; the other marketplaces still require their own live validation before equivalent production claims.

After the stale-element recovery change, a containerized retry of ASIN `B0H3TV3MLG` on `amazon.in` succeeded and saved a product snapshot with a parsed INR price and verified PIN `273015`.

The challenge recovery tests use simulated browser pages. A real CAPTCHA still needs a human in the visible browser; passing tests do not establish that Amazon will allow any particular visit.

## Next operational validation

Verify the chosen browser image starts Chrome with a matching driver, run an explicitly opted-in live product check per marketplace, and record selector/browser/runtime versions and outcomes here. Then enable strict SQLite-version enforcement in that vetted deployment environment.
