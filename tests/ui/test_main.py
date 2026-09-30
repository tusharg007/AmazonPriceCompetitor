from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.db import SQLiteRepository
from src.jobs import enqueue_scrape
from src.models import ProductKey


def test_empty_app_renders_input_form(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "ui.sqlite3"))
    monkeypatch.setenv("APP_JOB_POLL_SECONDS", "0")
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "main.py")
    app.run()
    assert not app.exception
    assert app.title[0].value == "Amazon Competitor Analysis"
    assert app.text_input[0].label == "ASIN"


def test_running_challenge_shows_browser_link(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "ui-challenge.sqlite3"))
    monkeypatch.setenv("APP_JOB_POLL_SECONDS", "0")
    monkeypatch.setenv("APP_BROWSER_RECOVERY_URL", "http://localhost:7900/")
    repo = SQLiteRepository()
    context = repo.get_or_create_context(ProductKey("B0CX23VSAS", "in"), "273015", tracked=True)
    enqueue_scrape(repo, context.id)
    job = repo.claim_next_job("test-worker")
    assert job and job.lease_token
    assert repo.set_challenge_notice(job.id, job.lease_token, True)

    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "main.py")
    app.session_state["last_job_id"] = job.id
    app.session_state["selected_context_id"] = context.id
    app.run()
    assert not app.exception
    assert any("human check" in warning.value for warning in app.warning)
    assert any("Open scraping browser" in button.label for button in app.get("link_button"))
