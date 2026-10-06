"""Browser contracts retain decimal precision and explicit UTC timestamps."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.models.schemas import ProductObservationRead


def test_observation_browser_contract() -> None:
    capture = ProductObservationRead(
        id=uuid4(),
        product_id=1,
        job_id=None,
        evidence_artifact_id=uuid4(),
        price_amount=Decimal("12.3400"),
        price_text="$12.34",
        currency="USD",
        availability=None,
        rating=None,
        rating_count=None,
        source_url="https://www.amazon.com/dp/B09XS7JWHH",
        captured_at=datetime(2026, 10, 6, 12, tzinfo=UTC).replace(tzinfo=None),
        collector="playwright-v1",
        extraction_method="json_ld",
        evidence_id="sha256",
    )
    body = capture.model_dump(mode="json")
    assert body["price_amount"] == "12.3400"
    assert body["captured_at"].endswith("Z")
    assert capture.captured_at.tzinfo == UTC
    assert body["location_status"] == "default"
