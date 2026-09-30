-- SQLite cannot alter an existing CHECK constraint. Preserve product IDs so all
-- existing product contexts and their descendants keep the same references.
CREATE TABLE products_rebuilt (
    id INTEGER PRIMARY KEY,
    asin TEXT NOT NULL CHECK(length(asin) = 10),
    amazon_domain TEXT NOT NULL CHECK(amazon_domain IN ('com', 'in', 'ca', 'co.uk', 'de', 'fr', 'it', 'ae')),
    created_at TEXT NOT NULL,
    UNIQUE(asin, amazon_domain)
);

INSERT INTO products_rebuilt(id, asin, amazon_domain, created_at)
SELECT id, asin, amazon_domain, created_at FROM products;

DROP TABLE products;
ALTER TABLE products_rebuilt RENAME TO products;
