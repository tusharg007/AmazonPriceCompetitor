import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

import src.db as db_module
from src.config import PROJECT_ROOT, Settings
from src.db import DatabaseError, SQLiteRepository
from src.jobs import enqueue_analysis, enqueue_competitors
from src.llm import build_analysis_input
from src.models import JobKind, JobStatus, LocationStatus, ProductKey, ProductSnapshot


def settings_for(path: Path) -> Settings:
    return Settings(
        database_path=path,
        browser_headless=True,
        browser_binary=None,
        browser_no_sandbox=False,
        browser_disable_dev_shm_usage=False,
        job_poll_seconds=0,
        page_timeout_seconds=30,
        element_timeout_seconds=10,
        job_timeout_seconds=900,
        min_navigation_interval_seconds=0,
        max_queue_size=20,
        max_search_pages=2,
        max_search_queries=3,
        max_competitors=20,
        groq_model="fake",
        artifact_dir=path.parent / "artifacts",
        strict_sqlite_version=False,
    )


def snapshot(context_id: int) -> ProductSnapshot:
    return ProductSnapshot(
        context_id=context_id,
        requested_asin="B0CX23VSAS",
        resolved_asin="B0CX23VSAS",
        title="Example product",
        canonical_url="https://www.amazon.com/dp/B0CX23VSAS",
        captured_at=datetime.now(UTC),
        capture_key="fixed-capture",
        domain="com",
        requested_location="00123",
        location_status=LocationStatus.VERIFIED,
        price_amount=Decimal("12.50"),
        price_text="$12.50",
        currency="USD",
    )


def test_context_identity_snapshot_history_and_job_idempotency(tmp_path: Path) -> None:
    repo = SQLiteRepository(settings_for(tmp_path / "app.sqlite3"))
    first = repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "00123", tracked=True)
    again = repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "00123", tracked=True)
    other_location = repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "90210")
    other_domain = repo.get_or_create_context(ProductKey("B0CX23VSAS", "ca"), "00123")
    assert first.id == again.id
    assert len({first.id, other_location.id, other_domain.id}) == 3

    snapshot_id = repo.save_snapshot(snapshot(first.id))
    assert repo.save_snapshot(snapshot(first.id)) == snapshot_id
    stored = repo.get_latest_snapshot(first.id)
    assert stored and stored["price_amount"] == Decimal("12.50")

    first_job = repo.enqueue_job(JobKind.SCRAPE_PRODUCT, first.id, "scrape-product")
    same_job = repo.enqueue_job(JobKind.SCRAPE_PRODUCT, first.id, "scrape-product")
    assert first_job.id == same_job.id
    claimed = repo.claim_next_job("test-worker")
    assert claimed and claimed.status == JobStatus.RUNNING and claimed.lease_token
    assert repo.finish_job(claimed.id, claimed.lease_token, JobStatus.SUCCEEDED)
    assert repo.health()["integrity_check"] == "ok"


def test_rollback_does_not_persist_changes(tmp_path: Path) -> None:
    repo = SQLiteRepository(settings_for(tmp_path / "rollback.sqlite3"))
    repo.migrate()
    try:
        with repo.transaction() as conn:
            conn.execute(
                "INSERT INTO products(asin,amazon_domain,created_at) VALUES (?,?,?)",
                ("B0CX23VSAS", "com", "now"),
            )
            raise RuntimeError("abort")
    except RuntimeError:
        pass
    with repo.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0


def test_downstream_jobs_require_completed_inputs(tmp_path: Path) -> None:
    repo = SQLiteRepository(settings_for(tmp_path / "jobs.sqlite3"))
    context = repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "00123")

    with pytest.raises(DatabaseError, match="Scrape the product"):
        enqueue_competitors(repo, context.id)
    with pytest.raises(DatabaseError, match="at least one competitor"):
        enqueue_analysis(repo, context.id)

    repo.save_snapshot(snapshot(context.id))
    assert enqueue_competitors(repo, context.id).kind == JobKind.DISCOVER_COMPETITORS
    with pytest.raises(DatabaseError, match="at least one competitor"):
        enqueue_analysis(repo, context.id)


def test_partial_competitor_evidence_can_be_analyzed_without_replacing_complete_run(
    tmp_path: Path,
) -> None:
    repo = SQLiteRepository(settings_for(tmp_path / "partial.sqlite3"))
    parent = repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "00123", tracked=True)
    competitor = repo.get_or_create_context(ProductKey("B0DLBH8CBZ", "com"), "00123")
    parent_snapshot_id = repo.save_snapshot(snapshot(parent.id))
    competitor_snapshot_id = repo.save_snapshot(
        replace(
            snapshot(competitor.id),
            requested_asin="B0DLBH8CBZ",
            resolved_asin="B0DLBH8CBZ",
            canonical_url="https://www.amazon.com/dp/B0DLBH8CBZ",
        )
    )
    queued = enqueue_competitors(repo, parent.id)
    claimed = repo.claim_next_job("test-worker")
    assert claimed and claimed.id == queued.id and claimed.lease_token
    run_id = repo.create_competitor_run(parent.id, parent_snapshot_id, claimed.id)
    assert repo.publish_competitor_run(
        run_id,
        JobStatus.PARTIAL,
        [(competitor.id, competitor_snapshot_id, 1, "watch", False, None)],
        [{"asin": "B0MISSING1", "code": "blocked", "message": "Blocked"}],
        claimed.id,
        claimed.lease_token,
    )
    assert repo.finish_job(claimed.id, claimed.lease_token, JobStatus.PARTIAL)
    assert repo.get_active_run_id(parent.id) is None

    later_snapshot_id = repo.save_snapshot(
        replace(snapshot(parent.id), capture_key="later-capture", title="Later product title")
    )
    assert later_snapshot_id != parent_snapshot_id

    run = repo.get_analysis_run(parent.id)
    assert run and run["id"] == run_id and run["status"] == "partial"
    assert run["completed_count"] == 1 and run["failure_count"] == 1
    frozen_parent_id, selected_run_id, evidence, input_hash = build_analysis_input(repo, parent.id)
    assert frozen_parent_id == parent_snapshot_id
    assert selected_run_id == run_id
    assert evidence["product"]["title"] == "Example product"
    assert evidence["competitors"][0]["asin"] == "B0DLBH8CBZ"
    assert evidence["rules"]["competitor_run_status"] == "partial"
    assert enqueue_analysis(repo, parent.id).kind == JobKind.ANALYZE

    repo.save_analysis(
        frozen_parent_id,
        run_id,
        input_hash,
        "fake",
        {"summary": "Limited evidence", "positioning": "Unknown", "top_competitors": []},
    )
    analysis = repo.latest_analysis(parent.id)
    assert analysis and analysis["output"]["summary"] == "Limited evidence"
    repo.get_or_create_context(ProductKey("B0CX23VSAS", "com"), "90210", tracked=True)
    assert repo.default_tracked_context_id() == parent.id


def test_amazon_in_migration_preserves_existing_relationships(tmp_path: Path) -> None:
    path = tmp_path / "existing.sqlite3"
    initial = (PROJECT_ROOT / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(initial)
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES (?,?,?)",
            ("001_initial.sql", hashlib.sha256(initial.encode()).hexdigest(), "now"),
        )
        conn.execute("INSERT INTO products VALUES (7,'B0CX23VSAS','com','now')")
        conn.execute(
            "INSERT INTO product_contexts"
            "(id,product_id,geo_key,requested_location,is_tracked,created_at,updated_at)"
            "VALUES (8,7,'00123','00123',1,'now','now')"
        )
        conn.execute(
            "INSERT INTO product_snapshots"
            "(id,context_id,capture_key,requested_asin,captured_at,location_status,source,extractor_version,created_at)"
            "VALUES (9,8,'old','B0CX23VSAS','now','verified','selenium','1','now')"
        )
        conn.execute("UPDATE product_contexts SET latest_snapshot_id=9 WHERE id=8")
        conn.execute(
            "INSERT INTO jobs(id,kind,context_id,request_key,status,created_at) "
            "VALUES ('old-job','scrape_product',8,'old','succeeded','now')"
        )
        conn.execute(
            "INSERT INTO competitor_runs"
            "(id,parent_context_id,parent_snapshot_id,job_id,strategy_version,status,created_at)"
            "VALUES (10,8,9,'old-job','selenium-v1','succeeded','now')"
        )
        conn.execute(
            "INSERT INTO competitor_run_items"
            "(run_id,competitor_context_id,snapshot_id,rank,query_text) "
            "VALUES (10,8,9,1,'watch')"
        )
        conn.execute(
            "INSERT INTO analyses"
            "(parent_snapshot_id,competitor_run_id,input_hash,model,prompt_version,schema_version,status,created_at)"
            "VALUES (9,10,'hash','model','v1','v1','succeeded','now')"
        )
        conn.execute(
            "INSERT INTO legacy_imports"
            "(source_file_hash,source_record_id,target_snapshot_id,status,created_at)"
            "VALUES ('source','row',9,'imported','now')"
        )

    repo = SQLiteRepository(settings_for(path))
    repo.migrate()
    india = repo.get_or_create_context(ProductKey("B0FCVFWFS4", "in"), "273015", tracked=True)
    assert india.key.domain == "in"
    assert repo.get_context(8) is not None
    assert repo.get_latest_snapshot(8) is not None
    assert repo.get_competitor_rows(10)
    with repo.connection() as conn:
        assert conn.execute("SELECT id FROM products WHERE asin='B0CX23VSAS'").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
    repo.migrate()  # A restarted app must not replay the table rebuild.


def test_failed_migration_rolls_back_every_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SQLiteRepository(settings_for(tmp_path / "rollback-migration.sqlite3"))
    repo.migrate()
    migration_dir = tmp_path / "bad-migrations"
    migration_dir.mkdir()
    (migration_dir / "003_broken.sql").write_text(
        "CREATE TABLE migration_probe (id INTEGER);\n"
        "INSERT INTO migration_probe VALUES (1);\n"
        "INSERT INTO nonexistent_table VALUES (1);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migration_dir)

    with pytest.raises(sqlite3.OperationalError):
        repo.migrate()
    with repo.connection() as conn:
        assert (
            conn.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchone()
            is None
        )
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
