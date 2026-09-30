from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.config import Settings
from src.db import SQLiteRepository
from src.models import JobKind, JobStatus, LocationStatus, ProductKey, ProductSnapshot


def settings_for(path: Path) -> Settings:
    return Settings(
        path, True, None, 30, 10, 900, 0, 20, 2, 3, 20, "fake", path.parent / "artifacts", False
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
