CREATE TABLE marketplace_cooldowns (
    amazon_domain TEXT PRIMARY KEY,
    blocked_until TEXT NOT NULL
);
