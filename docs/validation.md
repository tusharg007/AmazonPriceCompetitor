# Validation record

## Implemented checks

- `uv lock` resolved the new Selenium and direct Pydantic dependencies and removed TinyDB.
- `uv sync --locked --group dev` completed with Python 3.13.14.
- `ruff check .`, `ruff format --check .`, and `mypy src main.py` pass.
- `pytest -q --basetemp .test-tmp` passes 14 tests covering ASIN/domain/location validation, locale money parsing, SQLite migration/rollback/identity/snapshot/job idempotency, and a Streamlit form smoke test.
- `pip-audit` passes with no known vulnerabilities after upgrading LangChain to 1.4.3, langchain-openai to 1.6.6, Streamlit to 1.64.0, Selenium to 4.49.0, and their transitive dependencies.

## Environment evidence

The installed Python 3.13.14 runtime reports SQLite 3.50.4. It passes integrity and foreign-key checks, but is below the 3.51.3 WAL-reset-fix gate. Development therefore uses `APP_STRICT_SQLITE_VERSION=false`; production must use a vetted SQLite runtime and enable that setting. No Amazon or paid OpenAI live calls were made during implementation. The seven marketplaces have shared selector support and parser coverage; live validation remains required for each marketplace before production claims.

## Next operational validation

Verify the chosen browser image starts Chrome with a matching driver, run an explicitly opted-in live product check per marketplace, and record selector/browser/runtime versions and outcomes here. Then enable strict SQLite-version enforcement in that vetted deployment environment.
