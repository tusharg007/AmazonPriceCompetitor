from decimal import Decimal

from src.relevance import select_comparable_competitors


def test_relevance_excludes_misleading_and_out_of_tier_listings() -> None:
    parent = {
        "brand": "Visit the Samsung Store",
        "price_amount": Decimal(15549),
        "currency": "INR",
        "requested_location": "273015",
        "location_status": "verified",
    }
    rows = [
        {
            "asin": "DIRECT",
            "title": "Samsung Galaxy Buds4 Pro",
            "brand": "Visit the Samsung Store",
            "price_amount": Decimal(20343),
            "currency": "INR",
            "location_status": "verified",
        },
        {
            "asin": "MISLEADING",
            "title": "Samsung Galaxy Buds 3 Pro Wireless Earbuds",
            "brand": "Brand: OtherBrand",
            "price_amount": Decimal(14999),
            "currency": "INR",
            "location_status": "verified",
        },
        {
            "asin": "ACCESSORY",
            "title": "Earbuds for Samsung Galaxy Buds 3 Pro",
            "brand": "Brand: OtherBrand",
            "price_amount": Decimal(9999),
            "currency": "INR",
            "location_status": "verified",
        },
        {
            "asin": "BUDGET",
            "title": "Wireless Earbuds Pro 3",
            "brand": "Brand: BudgetBrand",
            "price_amount": Decimal(1647),
            "currency": "INR",
            "location_status": "verified",
        },
        {
            "asin": "IMPORT",
            "title": "Samsung Galaxy Buds3 (CAD Version & Warranty)",
            "brand": "Visit the Samsung Store",
            "price_amount": Decimal(18802),
            "currency": "INR",
            "location_status": "verified",
        },
        {
            "asin": "UNPRICED",
            "title": "Samsung Galaxy Buds3 FE",
            "brand": "Visit the Samsung Store",
            "price_amount": None,
            "currency": "INR",
            "location_status": "verified",
        },
    ]
    included, excluded = select_comparable_competitors(parent, rows)
    assert [row["asin"] for row in included] == ["DIRECT"]
    assert included[0]["price_comparable"] is True
    assert excluded == {
        "title and brand disagree": 1,
        "compatibility listing": 1,
        "outside comparable price band": 1,
        "different market version": 1,
        "price unavailable": 1,
    }
