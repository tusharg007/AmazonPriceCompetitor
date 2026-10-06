"""Construct explicit observation-backed comparison records."""

from typing import Any

from app.models.entities import Product, ProductObservation


def observation_record(product: Product, observation: ProductObservation) -> dict[str, Any]:
    snapshot = observation.raw_metadata.get("_listing", {})
    return {
        "asin": product.asin,
        "domain": product.domain,
        "geo_key": product.geo_key,
        "requested_location": product.requested_location,
        "title": snapshot.get("title", product.title),
        "brand": snapshot.get("brand", product.brand),
        "price_amount": observation.price_amount,
        "price_text": observation.price_text,
        "currency": observation.currency,
        "rating": observation.rating,
        "rating_count": observation.rating_count,
        "availability": observation.availability,
        "categories": observation.categories,
        "variant": observation.variant,
        "location_status": observation.location_status,
        "raw_metadata": observation.raw_metadata,
        "observation_id": str(observation.id),
        "source_url": observation.source_url,
        "captured_at": observation.captured_at.isoformat(),
        "collector": observation.collector,
        "extraction_method": observation.extraction_method,
        "evidence_id": observation.evidence_id,
        "evidence_artifact_id": str(observation.evidence_artifact_id)
        if observation.evidence_artifact_id
        else None,
    }
