CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    asin TEXT NOT NULL CHECK(length(asin) = 10),
    amazon_domain TEXT NOT NULL CHECK(amazon_domain IN ('com', 'ca', 'co.uk', 'de', 'fr', 'it', 'ae')),
    created_at TEXT NOT NULL,
    UNIQUE(asin, amazon_domain)
);

CREATE TABLE product_contexts (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    geo_key TEXT NOT NULL,
    requested_location TEXT,
    is_tracked INTEGER NOT NULL DEFAULT 0 CHECK(is_tracked IN (0, 1)),
    latest_snapshot_id INTEGER REFERENCES product_snapshots(id) ON DELETE SET NULL,
    active_complete_run_id INTEGER REFERENCES competitor_runs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, geo_key)
);

CREATE TABLE product_snapshots (
    id INTEGER PRIMARY KEY,
    context_id INTEGER NOT NULL REFERENCES product_contexts(id) ON DELETE RESTRICT,
    capture_key TEXT NOT NULL,
    requested_asin TEXT NOT NULL,
    resolved_asin TEXT,
    title TEXT,
    canonical_url TEXT,
    captured_at TEXT NOT NULL,
    requested_location TEXT,
    observed_location TEXT,
    location_status TEXT NOT NULL CHECK(location_status IN ('default', 'verified', 'unverified', 'unsupported')),
    brand TEXT,
    price_amount TEXT,
    price_text TEXT,
    currency TEXT,
    price_kind TEXT,
    availability TEXT,
    rating REAL CHECK(rating IS NULL OR (rating >= 0 AND rating <= 5)),
    rating_count INTEGER CHECK(rating_count IS NULL OR rating_count >= 0),
    images_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    category_path_json TEXT NOT NULL DEFAULT '[]',
    product_overview_json TEXT NOT NULL DEFAULT '[]',
    variant TEXT,
    condition TEXT,
    source TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    legacy_payload_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(context_id, capture_key)
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('scrape_product', 'discover_competitors', 'analyze')),
    context_id INTEGER NOT NULL REFERENCES product_contexts(id) ON DELETE RESTRICT,
    request_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    options_json TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    lease_token TEXT,
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE UNIQUE INDEX jobs_one_active_request
    ON jobs(kind, context_id, request_key)
    WHERE status IN ('queued', 'running');

CREATE TABLE competitor_runs (
    id INTEGER PRIMARY KEY,
    parent_context_id INTEGER NOT NULL REFERENCES product_contexts(id) ON DELETE RESTRICT,
    parent_snapshot_id INTEGER NOT NULL REFERENCES product_snapshots(id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    strategy_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
    completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count >= 0),
    failures_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE competitor_run_items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES competitor_runs(id) ON DELETE CASCADE,
    competitor_context_id INTEGER NOT NULL REFERENCES product_contexts(id) ON DELETE RESTRICT,
    snapshot_id INTEGER NOT NULL REFERENCES product_snapshots(id) ON DELETE RESTRICT,
    rank INTEGER NOT NULL CHECK(rank > 0),
    query_text TEXT NOT NULL,
    sponsored INTEGER NOT NULL DEFAULT 0 CHECK(sponsored IN (0, 1)),
    relevance_score REAL,
    UNIQUE(run_id, competitor_context_id)
);

CREATE TABLE analyses (
    id INTEGER PRIMARY KEY,
    parent_snapshot_id INTEGER NOT NULL REFERENCES product_snapshots(id) ON DELETE RESTRICT,
    competitor_run_id INTEGER NOT NULL REFERENCES competitor_runs(id) ON DELETE RESTRICT,
    input_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    output_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')),
    usage_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(parent_snapshot_id, competitor_run_id, input_hash, model, prompt_version, schema_version)
);

CREATE TABLE legacy_imports (
    source_file_hash TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    target_snapshot_id INTEGER REFERENCES product_snapshots(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    report_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(source_file_hash, source_record_id)
);

CREATE INDEX contexts_tracked_updated ON product_contexts(is_tracked, updated_at DESC);
CREATE INDEX snapshots_context_captured ON product_snapshots(context_id, captured_at DESC);
CREATE INDEX runs_parent_created ON competitor_runs(parent_context_id, created_at DESC);
CREATE INDEX jobs_status_created ON jobs(status, created_at);
CREATE INDEX analyses_input_hash ON analyses(input_hash);
