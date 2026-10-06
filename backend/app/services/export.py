"""Bounded CSV export with provenance and spreadsheet formula neutralization."""

import csv
import io
from datetime import datetime

from app.core.exceptions import ApplicationError
from app.services.catalog import CatalogService


def csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r"))
        else text
    )


async def observations_csv(
    service: CatalogService, product_id: int, start: datetime | None, end: datetime | None
) -> str:
    product = await service.require_product(product_id)
    captures = await service.history(product_id, start, end, 10001)
    if len(captures) > 10000:
        raise ApplicationError(
            "Export exceeds 10,000 captures; narrow the date range.", "export_too_large", 413
        )
    fields = [
        "asin",
        "domain",
        "geo_key",
        "observation_id",
        "captured_at",
        "price_amount",
        "price_text",
        "currency",
        "availability",
        "rating",
        "rating_count",
        "location_status",
        "source_url",
        "collector",
        "extraction_method",
        "evidence_id",
        "evidence_artifact_id",
    ]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for capture in captures:
        row = capture.model_dump(mode="json") | {
            "asin": product.asin,
            "domain": product.domain,
            "geo_key": product.geo_key,
            "observation_id": str(capture.id),
        }
        writer.writerow([csv_cell(row.get(field)) for field in fields])
    return stream.getvalue()
