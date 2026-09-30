"""SQLite persistence with short transactions and explicit repository methods."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models import (
    CollectionContext,
    Job,
    JobKind,
    JobStatus,
    ProductKey,
    ProductSnapshot,
    normalize_geo,
)

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
SQLITE_MINIMUM_VERSION = (3, 51, 3)


class DatabaseError(RuntimeError):
    """A predictable persistence failure safe to present to application code."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite() or value < 0:
        raise DatabaseError("Price must be a finite non-negative Decimal")
    return format(value, "f")


def _execute_migration(conn: sqlite3.Connection, sql: str) -> None:
    """Execute SQL statements individually without commits between statements."""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip() and not statement.lstrip().startswith("--"):
        raise DatabaseError("Migration ended with an incomplete SQL statement")


class SQLiteRepository:
    """Creates independent SQLite connections; no connection is shared across threads."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = self.settings.database_path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def migrate(self) -> None:
        if (
            self.settings.strict_sqlite_version
            and sqlite3.sqlite_version_info < SQLITE_MINIMUM_VERSION
        ):
            required = ".".join(map(str, SQLITE_MINIMUM_VERSION))
            raise DatabaseError(
                f"SQLite {required}+ is required for production WAL safety; found {sqlite3.sqlite_version}"
            )
        with self.connection() as conn:
            # Table rebuilds must temporarily disable FK enforcement on this
            # connection. Check every reference before committing the upgrade.
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
                )
                for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                    sql = migration.read_text(encoding="utf-8")
                    checksum = hashlib.sha256(sql.encode()).hexdigest()
                    row = conn.execute(
                        "SELECT checksum FROM schema_migrations WHERE version = ?",
                        (migration.name,),
                    ).fetchone()
                    if row:
                        if row["checksum"] != checksum:
                            raise DatabaseError(
                                f"Applied migration checksum changed: {migration.name}"
                            )
                        continue
                    _execute_migration(conn, sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                        (migration.name, checksum, iso()),
                    )
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise DatabaseError(f"Migration found {len(violations)} foreign-key violations")
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def health(self) -> dict[str, str]:
        self.migrate()
        with self.connection() as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        return {
            "database_path": str(self.path),
            "sqlite_version": sqlite3.sqlite_version,
            "integrity_check": integrity,
            "foreign_key_violations": str(len(foreign_keys)),
        }

    def get_or_create_context(
        self, key: ProductKey, requested_location: str | None, *, tracked: bool = False
    ) -> CollectionContext:
        self.migrate()
        geo_key, requested = normalize_geo(requested_location)
        now = iso()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO products(asin, amazon_domain, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(asin, amazon_domain) DO NOTHING",
                (key.asin, key.domain, now),
            )
            product = conn.execute(
                "SELECT id FROM products WHERE asin=? AND amazon_domain=?", (key.asin, key.domain)
            ).fetchone()
            assert product is not None
            conn.execute(
                "INSERT INTO product_contexts(product_id,geo_key,requested_location,is_tracked,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(product_id,geo_key) DO UPDATE SET "
                "is_tracked=MAX(product_contexts.is_tracked, excluded.is_tracked),updated_at=excluded.updated_at",
                (product["id"], geo_key, requested, int(tracked), now, now),
            )
            row = conn.execute(
                "SELECT c.*,p.asin,p.amazon_domain FROM product_contexts c JOIN products p ON p.id=c.product_id "
                "WHERE c.product_id=? AND c.geo_key=?",
                (product["id"], geo_key),
            ).fetchone()
        assert row is not None
        return self._context(row)

    def get_context(self, context_id: int) -> CollectionContext | None:
        self.migrate()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT c.*,p.asin,p.amazon_domain FROM product_contexts c JOIN products p ON p.id=c.product_id WHERE c.id=?",
                (context_id,),
            ).fetchone()
        return self._context(row) if row else None

    def set_tracked(self, context_id: int, tracked: bool) -> None:
        self.migrate()
        with self.transaction() as conn:
            if (
                conn.execute(
                    "UPDATE product_contexts SET is_tracked=?,updated_at=? WHERE id=?",
                    (int(tracked), iso(), context_id),
                ).rowcount
                != 1
            ):
                raise DatabaseError("Product context does not exist")

    def list_tracked_contexts(self, limit: int, offset: int) -> tuple[list[CollectionContext], int]:
        if limit < 1 or offset < 0:
            raise DatabaseError("Invalid pagination")
        self.migrate()
        with self.connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM product_contexts WHERE is_tracked=1"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT c.*,p.asin,p.amazon_domain FROM product_contexts c JOIN products p ON p.id=c.product_id "
                "WHERE c.is_tracked=1 ORDER BY c.updated_at DESC,c.id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._context(row) for row in rows], total

    def save_snapshot(self, snapshot: ProductSnapshot) -> int:
        self.migrate()
        with self.transaction() as conn:
            identity = conn.execute(
                "SELECT p.asin,p.amazon_domain FROM product_contexts c JOIN products p ON p.id=c.product_id WHERE c.id=?",
                (snapshot.context_id,),
            ).fetchone()
            if identity is None:
                raise DatabaseError("Product context does not exist")
            if (
                identity["asin"] != snapshot.requested_asin
                or identity["amazon_domain"] != snapshot.domain
            ):
                raise DatabaseError("Snapshot identity does not match its context")
            values = (
                snapshot.context_id,
                snapshot.capture_key,
                snapshot.requested_asin,
                snapshot.resolved_asin,
                snapshot.title,
                snapshot.canonical_url,
                iso(snapshot.captured_at),
                snapshot.requested_location,
                snapshot.observed_location,
                snapshot.location_status.value,
                snapshot.brand,
                _decimal_text(snapshot.price_amount),
                snapshot.price_text,
                snapshot.currency,
                snapshot.price_kind,
                snapshot.availability,
                snapshot.rating,
                snapshot.rating_count,
                _json(snapshot.images),
                _json(snapshot.categories),
                _json(snapshot.category_path),
                _json(snapshot.product_overview),
                snapshot.variant,
                snapshot.condition,
                snapshot.source,
                snapshot.extractor_version,
                _json(snapshot.legacy_payload) if snapshot.legacy_payload else None,
                iso(),
            )
            conn.execute(
                "INSERT INTO product_snapshots(context_id,capture_key,requested_asin,resolved_asin,title,canonical_url,captured_at,"
                "requested_location,observed_location,location_status,brand,price_amount,price_text,currency,price_kind,availability,"
                "rating,rating_count,images_json,categories_json,category_path_json,product_overview_json,variant,condition,source,"
                "extractor_version,legacy_payload_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(context_id,capture_key) DO NOTHING",
                values,
            )
            row = conn.execute(
                "SELECT id FROM product_snapshots WHERE context_id=? AND capture_key=?",
                (snapshot.context_id, snapshot.capture_key),
            ).fetchone()
            assert row is not None
            conn.execute(
                "UPDATE product_contexts SET latest_snapshot_id=?,updated_at=? WHERE id=?",
                (row["id"], iso(), snapshot.context_id),
            )
        return int(row["id"])

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        self.migrate()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT s.*,p.asin,p.amazon_domain FROM product_snapshots s JOIN product_contexts c ON c.id=s.context_id "
                "JOIN products p ON p.id=c.product_id WHERE s.id=?",
                (snapshot_id,),
            ).fetchone()
        return self._snapshot(row) if row else None

    def get_latest_snapshot(self, context_id: int) -> dict[str, Any] | None:
        self.migrate()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT s.*,p.asin,p.amazon_domain FROM product_contexts c JOIN product_snapshots s ON s.id=c.latest_snapshot_id "
                "JOIN products p ON p.id=c.product_id WHERE c.id=?",
                (context_id,),
            ).fetchone()
        return self._snapshot(row) if row else None

    def enqueue_job(
        self,
        kind: JobKind,
        context_id: int,
        request_key: str,
        options: dict[str, Any] | None = None,
    ) -> Job:
        self.migrate()
        if not request_key or len(request_key) > 128:
            raise DatabaseError("A bounded request key is required")
        with self.transaction() as conn:
            if not conn.execute(
                "SELECT 1 FROM product_contexts WHERE id=?", (context_id,)
            ).fetchone():
                raise DatabaseError("Product context does not exist")
            active = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if active >= self.settings.max_queue_size:
                raise DatabaseError("The job queue is full")
            existing = conn.execute(
                "SELECT * FROM jobs WHERE kind=? AND context_id=? AND request_key=? AND status IN ('queued','running')",
                (kind.value, context_id, request_key),
            ).fetchone()
            if existing:
                return self._job(existing)
            job_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO jobs(id,kind,context_id,request_key,status,options_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    job_id,
                    kind.value,
                    context_id,
                    request_key,
                    JobStatus.QUEUED.value,
                    _json(options or {}),
                    iso(),
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        assert row is not None
        return self._job(row)

    def get_job(self, job_id: str) -> Job | None:
        self.migrate()
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def claim_next_job(self, worker_id: str, lease_seconds: int = 60) -> Job | None:
        del worker_id
        self.migrate()
        now = utc_now()
        token = str(uuid.uuid4())
        with self.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET status='queued',lease_token=NULL,lease_expires_at=NULL "
                "WHERE status='running' AND lease_expires_at < ? AND attempts < 2",
                (iso(now),),
            )
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            updated = conn.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,lease_token=?,lease_expires_at=?,heartbeat_at=?,"
                "started_at=COALESCE(started_at,?) WHERE id=? AND status='queued'",
                (token, iso(now + timedelta(seconds=lease_seconds)), iso(now), iso(now), row["id"]),
            )
            if updated.rowcount != 1:
                return None
            claimed = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        assert claimed is not None
        return self._job(claimed)

    def heartbeat(
        self, job_id: str, lease_token: str, progress: int, lease_seconds: int = 60
    ) -> bool:
        self.migrate()
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE jobs SET heartbeat_at=?,lease_expires_at=?,progress=? WHERE id=? AND status='running' AND lease_token=?",
                (
                    iso(),
                    iso(utc_now() + timedelta(seconds=lease_seconds)),
                    max(0, min(100, progress)),
                    job_id,
                    lease_token,
                ),
            )
        return updated.rowcount == 1

    def finish_job(
        self,
        job_id: str,
        lease_token: str,
        status: JobStatus,
        *,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        if status not in {
            JobStatus.SUCCEEDED,
            JobStatus.PARTIAL,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            raise DatabaseError("Invalid terminal job status")
        self.migrate()
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE jobs SET status=?,progress=100,result_json=?,error_code=?,error_message=?,finished_at=?,lease_expires_at=NULL "
                "WHERE id=? AND status='running' AND lease_token=?",
                (
                    status.value,
                    _json(result) if result else None,
                    error_code,
                    (error_message or "")[:1000] or None,
                    iso(),
                    job_id,
                    lease_token,
                ),
            )
        return updated.rowcount == 1

    def cancel_job(self, job_id: str) -> bool:
        self.migrate()
        with self.transaction() as conn:
            updated = conn.execute(
                "UPDATE jobs SET status='cancelled',finished_at=? WHERE id=? AND status='queued'",
                (iso(), job_id),
            )
        return updated.rowcount == 1

    def create_competitor_run(
        self, parent_context_id: int, parent_snapshot_id: int, job_id: str
    ) -> int:
        self.migrate()
        with self.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO competitor_runs(parent_context_id,parent_snapshot_id,job_id,strategy_version,status,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    parent_context_id,
                    parent_snapshot_id,
                    job_id,
                    "selenium-v1",
                    JobStatus.RUNNING.value,
                    iso(),
                ),
            )
        if cursor.lastrowid is None:
            raise DatabaseError("Failed to create competitor run")
        return int(cursor.lastrowid)

    def publish_competitor_run(
        self,
        run_id: int,
        status: JobStatus,
        items: list[tuple[int, int, int, str, bool, float | None]],
        failures: list[dict[str, Any]],
        lease_job_id: str,
        lease_token: str,
    ) -> bool:
        self.migrate()
        with self.transaction() as conn:
            if not conn.execute(
                "SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_token=?",
                (lease_job_id, lease_token),
            ).fetchone():
                return False
            for context_id, snapshot_id, rank, query, sponsored, relevance in items:
                conn.execute(
                    "INSERT OR REPLACE INTO competitor_run_items(run_id,competitor_context_id,snapshot_id,rank,query_text,sponsored,relevance_score) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (run_id, context_id, snapshot_id, rank, query, int(sponsored), relevance),
                )
            run = conn.execute(
                "SELECT parent_context_id FROM competitor_runs WHERE id=?", (run_id,)
            ).fetchone()
            if not run:
                raise DatabaseError("Competitor run does not exist")
            conn.execute(
                "UPDATE competitor_runs SET status=?,candidate_count=?,completed_count=?,failures_json=?,completed_at=? WHERE id=?",
                (
                    status.value,
                    len(items) + len(failures),
                    len(items),
                    _json(failures),
                    iso(),
                    run_id,
                ),
            )
            if status == JobStatus.SUCCEEDED:
                conn.execute(
                    "UPDATE product_contexts SET active_complete_run_id=?,updated_at=? WHERE id=?",
                    (run_id, iso(), run["parent_context_id"]),
                )
        return True

    def get_competitor_rows(self, run_id: int) -> list[dict[str, Any]]:
        self.migrate()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT i.rank,i.query_text,i.sponsored,s.*,p.asin,p.amazon_domain FROM competitor_run_items i "
                "JOIN product_snapshots s ON s.id=i.snapshot_id JOIN product_contexts c ON c.id=s.context_id "
                "JOIN products p ON p.id=c.product_id WHERE i.run_id=? ORDER BY i.rank,i.id",
                (run_id,),
            ).fetchall()
        return [
            self._snapshot(row)
            | {"rank": row["rank"], "sponsored": bool(row["sponsored"]), "query": row["query_text"]}
            for row in rows
        ]

    def get_active_run_id(self, context_id: int) -> int | None:
        context = self.get_context(context_id)
        return context.active_complete_run_id if context else None

    def get_analysis_run(self, context_id: int) -> dict[str, Any] | None:
        """Prefer a complete run; otherwise use the newest partial run with evidence."""
        self.migrate()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT r.id,r.parent_snapshot_id,r.status,r.candidate_count,r.completed_count,r.failures_json "
                "FROM product_contexts c JOIN competitor_runs r ON r.parent_context_id=c.id "
                "WHERE c.id=? AND r.completed_count>0 AND "
                "(r.id=c.active_complete_run_id OR "
                "(c.active_complete_run_id IS NULL AND r.status='partial')) "
                "ORDER BY CASE WHEN r.id=c.active_complete_run_id THEN 0 ELSE 1 END, "
                "r.completed_at DESC,r.id DESC LIMIT 1",
                (context_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "parent_snapshot_id": row["parent_snapshot_id"],
            "status": row["status"],
            "candidate_count": row["candidate_count"],
            "completed_count": row["completed_count"],
            "failure_count": len(json.loads(row["failures_json"])),
        }

    def save_analysis(
        self,
        parent_snapshot_id: int,
        run_id: int,
        input_hash: str,
        model: str,
        output: dict[str, Any],
        *,
        status: JobStatus = JobStatus.SUCCEEDED,
        error_message: str | None = None,
    ) -> int:
        self.migrate()
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO analyses(parent_snapshot_id,competitor_run_id,input_hash,model,prompt_version,schema_version,"
                "output_json,status,error_message,created_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(parent_snapshot_id,competitor_run_id,input_hash,model,prompt_version,schema_version) DO UPDATE SET "
                "output_json=excluded.output_json,status=excluded.status,error_message=excluded.error_message,completed_at=excluded.completed_at",
                (
                    parent_snapshot_id,
                    run_id,
                    input_hash,
                    model,
                    "v1",
                    "v1",
                    _json(output),
                    status.value,
                    error_message,
                    iso(),
                    iso(),
                ),
            )
            row = conn.execute(
                "SELECT id FROM analyses WHERE parent_snapshot_id=? AND competitor_run_id=? AND input_hash=? AND model=? "
                "AND prompt_version='v1' AND schema_version='v1'",
                (parent_snapshot_id, run_id, input_hash, model),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def latest_analysis(self, context_id: int) -> dict[str, Any] | None:
        run = self.get_analysis_run(context_id)
        if run is None:
            return None
        self.migrate()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT a.* FROM analyses a WHERE a.competitor_run_id=? AND a.status='succeeded' "
                "ORDER BY a.completed_at DESC LIMIT 1",
                (run["id"],),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["output"] = (
            json.loads(result.pop("output_json")) if result.get("output_json") else None
        )
        return result

    @staticmethod
    def _context(row: sqlite3.Row) -> CollectionContext:
        return CollectionContext(
            int(row["id"]),
            ProductKey(row["asin"], row["amazon_domain"]),
            row["geo_key"],
            row["requested_location"],
            bool(row["is_tracked"]),
            row["latest_snapshot_id"],
            row["active_complete_run_id"],
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            row["id"],
            JobKind(row["kind"]),
            int(row["context_id"]),
            row["request_key"],
            JobStatus(row["status"]),
            json.loads(row["options_json"]),
            int(row["attempts"]),
            row["lease_token"],
            int(row["progress"]),
            row["error_code"],
            row["error_message"],
        )

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in (
            "images_json",
            "categories_json",
            "category_path_json",
            "product_overview_json",
        ):
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
        if result.get("legacy_payload_json"):
            result["legacy_payload"] = json.loads(result["legacy_payload_json"])
        result.pop("legacy_payload_json", None)
        if result.get("price_amount") is not None:
            try:
                result["price_amount"] = Decimal(result["price_amount"])
            except InvalidOperation as exc:
                raise DatabaseError("Stored price is invalid") from exc
        return result


Database = SQLiteRepository
