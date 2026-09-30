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

The worker retries only a stale lease once. A browser block, CAPTCHA, login wall, location mismatch, malformed page, or failed item is persisted as an outcome. A partial or failed refresh does not replace the previous completed competitor run. Investigate selector changes with sanitized fixtures or private, time-limited artifacts.

Docker runs a visible Selenium browser on `http://localhost:7900` and saves its profile in `browser-profiles`. Set `APP_BROWSER_VNC_PASSWORD` in `.env` (the example default is `secret`). When a running job displays **Open scraping browser to complete the check**, open that view, click **Connect**, and complete Amazon's check manually within the configured wait. The worker sends heartbeats while waiting and resumes the same browser afterward. An unresolved block starts a per-marketplace cooldown; the app shows the remaining wait on the next scrape request. The old completed competitor run remains available. Never publish the browser port without authentication, and never commit its profile or credentials.

Docker Compose binds both the UI and noVNC browser to localhost and uses persistent `app-data` and `browser-profiles` volumes. Run it with `docker compose build` and `docker compose up -d`. The worker connects to the pinned Selenium standalone Chromium image. Local Python execution still uses its own Chrome installation; with `APP_BROWSER_HEADLESS=false`, its browser window is visible for human checks. The production image installs no development dependencies and the containers use `uv run --no-sync`, so startup does not modify the image environment. Supply production secrets through the deployment platform, not a committed `.env`. Add an authenticated TLS gateway before any public exposure.

When updating a deployment from the original seven-marketplace schema, migration `002_amazon_in.sql` rebuilds `products` to accept `amazon.in` while retaining product IDs and related records. Back up the live volume with `docker compose exec app uv run --no-sync python -m scripts.db_admin backup --destination /app/data/pre-india-upgrade.sqlite3` before rebuilding. `docker compose up -d --build --force-recreate` runs the migration before starting the app and worker. Verify the result with `docker compose exec app uv run --no-sync python -m scripts.db_admin health`; `integrity_check` must be `ok` and foreign-key violations must be `0`. Keep the Compose volume; `docker compose down -v` would delete its database.
