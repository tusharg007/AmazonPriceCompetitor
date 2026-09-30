"""Offline, idempotent TinyDB JSON import; TinyDB is never imported at runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.db import SQLiteRepository, iso
from src.models import LocationStatus, ProductKey, ProductSnapshot, ValidationError


def legacy_records(source: Path) -> list[tuple[str, dict[str, Any]]]:
    document = json.loads(source.read_text(encoding="utf-8"))
    table = document.get("products") or document.get("_default") or document
    if not isinstance(table, dict):
        raise TypeError("Expected a TinyDB table object containing product records")
    records: list[tuple[str, dict[str, Any]]] = []
    for key, value in table.items():
        if isinstance(value, dict):
            records.append((str(key), value))
    return records


def decimal_from_legacy(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def import_records(repo: SQLiteRepository, source: Path, apply: bool) -> dict[str, int]:
    file_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {"read": 0, "imported": 0, "already_present": 0, "quarantined": 0}
    for record_id, record in legacy_records(source):
        report["read"] += 1
        asin = record.get("asin")
        domain = record.get("amazon_domain")
        try:
            key = ProductKey(str(asin), str(domain))
        except (ValidationError, TypeError):
            report["quarantined"] += 1
            continue
        if not apply:
            continue
        with repo.connection() as conn:
            existing = conn.execute(
                "SELECT 1 FROM legacy_imports WHERE source_file_hash=? AND source_record_id=?",
                (file_hash, record_id),
            ).fetchone()
        if existing:
            report["already_present"] += 1
            continue
        context = repo.get_or_create_context(
            key, record.get("geo_location"), tracked=not record.get("parent_asin")
        )
        created = parse_timestamp(record.get("created_at"))
        snapshot = ProductSnapshot(
            context_id=context.id,
            requested_asin=key.asin,
            resolved_asin=record.get("asin"),
            title=record.get("title"),
            canonical_url=record.get("url"),
            captured_at=created,
            capture_key=hashlib.sha256(f"legacy:{file_hash}:{record_id}".encode()).hexdigest(),
            domain=key.domain,
            requested_location=record.get("geo_location"),
            location_status=LocationStatus.UNVERIFIED,
            brand=record.get("brand"),
            price_amount=decimal_from_legacy(record.get("price")),
            price_text=str(record["price"]) if record.get("price") is not None else None,
            currency=record.get("currency"),
            availability=record.get("stock"),
            rating=record.get("rating") if isinstance(record.get("rating"), (int, float)) else None,
            images=tuple(item for item in record.get("images", []) if isinstance(item, str)),
            categories=tuple(str(item) for item in record.get("categories", []) if item),
            category_path=tuple(str(item) for item in record.get("category_path", []) if item),
            product_overview=tuple(
                str(item) for item in record.get("product_overview", []) if item
            ),
            source="tinydb-import",
            extractor_version="legacy-v1",
            legacy_payload=record,
        )
        snapshot_id = repo.save_snapshot(snapshot)
        with repo.transaction() as conn:
            conn.execute(
                "INSERT INTO legacy_imports(source_file_hash,source_record_id,target_snapshot_id,status,report_json,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (file_hash, record_id, snapshot_id, "imported", "{}", iso()),
            )
        report["imported"] += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run == args.apply:
        parser.error("Select exactly one of --dry-run or --apply")
    if not args.source.is_file():
        parser.error("The legacy source file does not exist")
    repo = SQLiteRepository()
    repo.migrate()
    print(json.dumps(import_records(repo, args.source, args.apply), indent=2))


if __name__ == "__main__":
    main()
