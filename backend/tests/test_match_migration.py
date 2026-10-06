"""Phase 4 migration preserves existing identities, observations and relationships."""

import sqlite3

from alembic import command

from backend.tests.test_migrations import config


def test_phase4_upgrade_and_downgrade_preserve_prior_data(monkeypatch, test_settings):
    monkeypatch.setattr("app.core.config.get_settings", lambda: test_settings)
    cfg = config()
    command.upgrade(cfg, "002_active_job_dedup")
    path = test_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO products(asin,domain) VALUES ('B000000001','com'),('B000000002','com')"
        )
        db.execute(
            "INSERT INTO product_observations(id,product_id,source_url,captured_at,collector,extraction_method,evidence_id) VALUES (?,?,?,?,?,?,?)",
            (
                "a" * 32,
                1,
                "https://www.amazon.com/dp/B000000001",
                "2026-10-06 06:00:00",
                "playwright_amazon",
                "structured_dom",
                "f" * 64,
            ),
        )
        db.execute(
            "INSERT INTO competitor_relationships(id,baseline_product_id,competitor_product_id,match_score) VALUES (?,?,?,?)",
            ("b" * 32, 1, 2, 0.75),
        )
    command.upgrade(cfg, "003_match_evidence")
    command.upgrade(cfg, "head")
    command.check(cfg)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM products").fetchone() == (2,)
        assert db.execute("SELECT evidence_id FROM product_observations").fetchone() == ("f" * 64,)
        assert db.execute("SELECT match_score FROM competitor_relationships").fetchone() == (0.75,)
        assert db.execute("SELECT count(*) FROM match_evidence").fetchone() == (0,)
    command.downgrade(cfg, "002_active_job_dedup")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM products").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM product_observations").fetchone() == (1,)
        assert db.execute("SELECT match_score FROM competitor_relationships").fetchone() == (0.75,)
    command.upgrade(cfg, "head")
