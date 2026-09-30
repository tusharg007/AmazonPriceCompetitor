# Architecture

The Streamlit process only validates input, enqueues durable work, and renders saved results. `src.worker` claims one SQLite job at a time, owns one Selenium browser session for that job, and records snapshots before publishing a competitor run. The app and worker share one local SQLite volume.

`products` uniquely identifies `(ASIN, marketplace)`. `product_contexts` adds the requested delivery location and is the identity used by UI selection, jobs, competitor runs, and LLM analysis. Each observation is a `product_snapshot`; refreshes preserve history. A completed competitor run points at frozen snapshots, so a later refresh cannot silently change an existing analysis.

SQLite uses WAL, foreign keys, FULL synchronous mode, short `BEGIN IMMEDIATE` writes, and a busy timeout. One host is required; do not place this database on a network filesystem or run multiple worker writers. The database runtime version is recorded by `db_admin health`. Set `APP_STRICT_SQLITE_VERSION=true` only with a Python/runtime build containing SQLite 3.51.3 or a documented vendor backport of its WAL-reset fix.

Selenium creates a fresh Chrome profile for each job and always quits the driver and deletes its profile. It uses explicit waits and named selector groups. It records blocked, timeout, location-verification, not-found, and variant-mismatch outcomes instead of presenting them as success. It does not use Oxylabs, direct HTTP page fetching, proxy rotation, anti-CAPTCHA services, or stealth drivers.

The LLM receives bounded JSON generated from frozen snapshots, not database access or browser tools. It is instructed to treat product text as untrusted data and is rejected if it names a competitor ASIN absent from its evidence.
