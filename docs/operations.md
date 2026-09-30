# Operations runbook

Start locally with two processes after `uv sync --locked --group dev`:

```powershell
uv run python -m scripts.db_admin migrate
uv run python -m src.worker
uv run streamlit run main.py
```

Set `GROQ_API_KEY` in the process environment before requesting an analysis. `APP_GROQ_MODEL` is optional and defaults to `openai/gpt-oss-20b`. Keep these values in the deployment platform's secret store rather than source control.

Use `uv run python -m scripts.db_admin health` before deployment. It reports the database path, SQLite runtime version, integrity check, and foreign-key check. Browser availability is an external deployment prerequisite; Selenium Manager helps local development, while a production image must provide a supported browser/driver pair.

Back up a live database through SQLite's backup API:

```powershell
uv run python -m scripts.db_admin backup --destination backups/amazon.sqlite3
uv run python -m scripts.db_admin restore-verify --source backups/amazon.sqlite3 --destination restore-check.sqlite3
```

Do not copy only the main SQLite file while the app is writing; WAL data can be separate. Restore into a new destination, verify it, stop app and worker, back up the current database, and then perform the controlled switchover.

The worker retries only a stale lease once. A browser block, CAPTCHA, login wall, location mismatch, malformed page, or failed item is persisted as an outcome. A partial or failed refresh does not replace the previous completed competitor run. Investigate selector changes with sanitized fixtures or private, time-limited artifacts; never add bypass tooling.

Docker Compose binds the UI to localhost and uses a persistent `app-data` volume. Run it with `docker compose build` and `docker compose up -d`. The worker pins `/usr/bin/chromium` and enables the container-specific no-sandbox and shared-memory options; local execution leaves both options disabled by default. The production image installs no development dependencies and the containers use `uv run --no-sync`, so startup does not modify the image environment. Supply production secrets through the deployment platform, not a committed `.env`. Add an authenticated TLS gateway before any public exposure.
