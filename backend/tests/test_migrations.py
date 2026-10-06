"""Exercise the actual Alembic schema, including portable provenance/idempotency constraints."""

import asyncio
import importlib.util
import io
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import Settings
from app.core.database import create_engine_and_session_factory
from app.models.entities import CollectionJob, Product, ProductObservation
from sqlalchemy import UniqueConstraint, insert, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex, CreateTable

BACKEND = Path(__file__).resolve().parents[1]


def config() -> Config:
    return Config(str(BACKEND / "alembic.ini"))


def test_migration_import_and_single_head() -> None:
    assert ScriptDirectory.from_config(config()).get_heads() == ["002_active_job_dedup"]
    spec = importlib.util.spec_from_file_location(
        "phase1_initial", BACKEND / "alembic/versions/001_initial_schema.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "001_initial"
    assert callable(module.upgrade) and callable(module.downgrade)
    spec = importlib.util.spec_from_file_location(
        "phase2_dedup", BACKEND / "alembic/versions/002_active_job_dedup.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "002_active_job_dedup" and module.down_revision == "001_initial"


def test_sqlite_upgrade_constraints_orm_match_and_downgrade(monkeypatch, test_settings) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: test_settings)
    cfg = config()
    command.upgrade(cfg, "head")
    command.check(cfg)
    db_file = test_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(db_file) as db:
        db.execute("PRAGMA foreign_keys=ON")
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "002_active_job_dedup",
        )
        db.execute("INSERT INTO products(asin,domain) VALUES ('B000000001','com')")
        row = (
            "1" * 32,
            1,
            "https://www.amazon.com/dp/B000000001",
            "2026-10-06 06:00:00",
            "playwright_amazon",
            "structured_dom",
            "a" * 64,
        )
        sql = "INSERT INTO product_observations(id,product_id,source_url,captured_at,collector,extraction_method,evidence_id) VALUES (?,?,?,?,?,?,?)"
        db.execute(sql, row)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, ("2" * 32, *row[1:]))
        db.execute(sql, ("3" * 32, row[1], row[2], "2026-10-07 06:00:00", *row[4:]))
        for index in range(2, 7):
            missing = list(row)
            missing[0] = str(index) * 32
            missing[index] = None
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql, missing)
        assert db.execute("SELECT COUNT(*) FROM product_observations").fetchone() == (2,)
    command.downgrade(cfg, "base")
    with sqlite3.connect(db_file) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='products'").fetchone()
    command.upgrade(cfg, "head")


def test_existing_phase1_records_survive_phase2_upgrade(monkeypatch, test_settings) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: test_settings)
    cfg = config()
    command.upgrade(cfg, "001_initial")
    file = test_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(file) as db:
        db.execute("INSERT INTO products(asin,domain) VALUES ('B000000001','com')")
        db.execute(
            "INSERT INTO collection_jobs(id,kind,product_id,request_key) VALUES (?,?,?,?)",
            ("a" * 32, "scrape_product", 1, "legacy-key"),
        )
        db.execute(
            "INSERT INTO product_observations(id,product_id,source_url,captured_at,collector,extraction_method,evidence_id) VALUES (?,?,?,?,?,?,?)",
            (
                "b" * 32,
                1,
                "https://amazon.com/dp/B000000001",
                "2026-10-06 06:00:00",
                "playwright_amazon",
                "json_ld",
                "c" * 64,
            ),
        )
    command.upgrade(cfg, "head")
    command.check(cfg)
    with sqlite3.connect(file) as db:
        assert db.execute("SELECT COUNT(*) FROM products").fetchone() == (1,)
        assert db.execute("SELECT evidence_id FROM product_observations").fetchone() == ("c" * 64,)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO collection_jobs(id,kind,product_id,request_key,status) VALUES (?,?,?,?,?)",
                ("d" * 32, "scrape_product", 1, "legacy-key", "running"),
            )
        db.execute(
            "INSERT INTO collection_jobs(id,kind,product_id,request_key,status) VALUES (?,?,?,?,?)",
            ("e" * 32, "scrape_product", 1, "legacy-key", "succeeded"),
        )
    command.downgrade(cfg, "001_initial")
    with sqlite3.connect(file) as db:
        assert db.execute("SELECT COUNT(*) FROM product_observations").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM collection_jobs").fetchone() == (2,)
    command.upgrade(cfg, "head")


def test_postgresql_offline_upgrade_and_orm_constraint_match(monkeypatch, tmp_path) -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://aci:aci@localhost/aci_test", evidence_dir=tmp_path
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    output = io.StringIO()
    cfg = config()
    cfg.output_buffer = output
    command.upgrade(cfg, "head", sql=True)
    ddl = output.getvalue()
    expected = "UNIQUE (product_id, captured_at, collector, evidence_id)"
    assert expected in ddl
    assert "evidence_id VARCHAR(64) NOT NULL" in ddl
    assert "ck_observation_provenance" in ddl
    assert "CREATE UNIQUE INDEX idx_jobs_active_dedup" in ddl
    assert "WHERE status IN ('queued', 'running')" in ddl
    index = next(
        index for index in CollectionJob.__table__.indexes if index.name == "idx_jobs_active_dedup"
    )
    assert "WHERE status IN ('queued', 'running')" in str(
        CreateIndex(index).compile(dialect=postgresql.dialect())
    )
    assert expected in str(
        CreateTable(ProductObservation.__table__).compile(dialect=postgresql.dialect())
    )
    constraints = [
        c for c in ProductObservation.__table__.constraints if isinstance(c, UniqueConstraint)
    ]
    assert [[col.name for col in c.columns] for c in constraints] == [
        ["product_id", "captured_at", "collector", "evidence_id"]
    ]


@pytest.mark.skipif(
    not os.environ.get("ACI_TEST_POSTGRES_URL"),
    reason="Requires a disposable PostgreSQL test database",
)
def test_postgresql_upgrade_and_constraint_enforcement(monkeypatch, tmp_path) -> None:
    url = os.environ["ACI_TEST_POSTGRES_URL"]
    # This test upgrades/downgrades its schema: accept only an explicitly named test database.
    assert (make_url(url).database or "").endswith("_test")
    settings = Settings(database_url=url, evidence_dir=tmp_path)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    cfg = config()
    command.upgrade(cfg, "head")
    command.check(cfg)

    async def verify() -> None:
        engine, _ = create_engine_and_session_factory(settings)
        try:
            async with engine.begin() as conn:
                product_id = (
                    await conn.execute(
                        insert(Product)
                        .values(asin="B000000001", domain="com")
                        .returning(Product.id)
                    )
                ).scalar_one()
                values = {
                    "product_id": product_id,
                    "source_url": "https://www.amazon.com/dp/B000000001",
                    "captured_at": datetime.now(UTC),
                    "collector": "playwright_amazon",
                    "extraction_method": "structured_dom",
                    "evidence_id": "a" * 64,
                }
                await conn.execute(insert(ProductObservation).values(id=uuid.uuid4(), **values))
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(
                            insert(ProductObservation).values(id=uuid.uuid4(), **values)
                        )
                later = {**values, "captured_at": values["captured_at"] + timedelta(days=1)}
                await conn.execute(insert(ProductObservation).values(id=uuid.uuid4(), **later))
                for field in (
                    "source_url",
                    "captured_at",
                    "collector",
                    "extraction_method",
                    "evidence_id",
                ):
                    missing = {**values, field: None}
                    with pytest.raises(IntegrityError):
                        async with conn.begin_nested():
                            await conn.execute(
                                insert(ProductObservation).values(id=uuid.uuid4(), **missing)
                            )
                rows = (await conn.execute(select(ProductObservation))).all()
                assert len(rows) == 2
        finally:
            await engine.dispose()

    try:
        asyncio.run(verify())
    finally:
        command.downgrade(cfg, "base")
