from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_empty_app_renders_input_form(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_DATABASE_PATH", str(tmp_path / "ui.sqlite3"))
    app = AppTest.from_file(Path(__file__).resolve().parents[2] / "main.py")
    app.run()
    assert not app.exception
    assert app.title[0].value == "Amazon Competitor Analysis"
    assert app.text_input[0].label == "ASIN"
