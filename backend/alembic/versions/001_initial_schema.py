"""Initial schema for products, observations, provenance, and relationships.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-06 06:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. products
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asin", sa.String(length=10), nullable=False),
        sa.Column("domain", sa.String(length=20), nullable=False),
        sa.Column("geo_key", sa.String(length=50), nullable=False, server_default="__default__"),
        sa.Column("requested_location", sa.String(length=50), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asin", "domain", "geo_key", name="uq_product_identity"),
    )
    op.create_index(op.f("ix_products_asin"), "products", ["asin"], unique=False)
    op.create_index(op.f("ix_products_domain"), "products", ["domain"], unique=False)
    op.create_index(op.f("ix_products_geo_key"), "products", ["geo_key"], unique=False)
    op.create_index(op.f("ix_products_is_tracked"), "products", ["is_tracked"], unique=False)

    # 2. evidence_artifacts
    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("content_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("collector", sa.String(length=100), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evidence_artifacts_content_hash"),
        "evidence_artifacts",
        ["content_hash"],
        unique=False,
    )

    # 3. collection_jobs
    op.create_table(
        "collection_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="queued", nullable=False),
        sa.Column("request_key", sa.String(length=100), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("lease_token", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collection_jobs_product_id"), "collection_jobs", ["product_id"], unique=False
    )
    op.create_index(op.f("ix_collection_jobs_status"), "collection_jobs", ["status"], unique=False)

    # 4. product_observations
    op.create_table(
        "product_observations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("evidence_artifact_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("price_amount", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("price_text", sa.String(length=100), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("availability", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=True),
        sa.Column("price_kind", sa.String(length=50), nullable=True),
        sa.Column(
            "location_status", sa.String(length=50), server_default="default", nullable=False
        ),
        sa.Column("observed_location", sa.String(length=100), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("variant", sa.String(length=255), nullable=True),
        sa.Column("condition", sa.String(length=100), nullable=True),
        sa.Column("categories", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("images", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("raw_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("collector", sa.String(length=100), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_artifact_id"], ["evidence_artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["collection_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "captured_at",
            "collector",
            "evidence_id",
            name="uq_observation_evidence",
        ),
        sa.CheckConstraint(
            "length(source_url) > 0 AND length(collector) > 0 "
            "AND length(extraction_method) > 0 AND length(evidence_id) > 0",
            name="ck_observation_provenance",
        ),
    )
    op.create_index(
        op.f("ix_product_observations_captured_at"),
        "product_observations",
        ["captured_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_observations_evidence_artifact_id"),
        "product_observations",
        ["evidence_artifact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_observations_evidence_id"),
        "product_observations",
        ["evidence_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_observations_job_id"), "product_observations", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_product_observations_product_id"),
        "product_observations",
        ["product_id"],
        unique=False,
    )

    # 5. competitor_relationships
    op.create_table(
        "competitor_relationships",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("baseline_product_id", sa.Integer(), nullable=False),
        sa.Column("competitor_product_id", sa.Integer(), nullable=False),
        sa.Column("match_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column(
            "match_method", sa.String(length=50), server_default="deterministic", nullable=False
        ),
        sa.Column("match_status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("search_rank", sa.Integer(), nullable=True),
        sa.Column("sponsored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("search_query", sa.String(length=255), nullable=True),
        sa.Column("evidence_summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["baseline_product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competitor_product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_product_id", "competitor_product_id", name="uq_competitor_pair"
        ),
    )
    op.create_index(
        op.f("ix_competitor_relationships_baseline_product_id"),
        "competitor_relationships",
        ["baseline_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_relationships_competitor_product_id"),
        "competitor_relationships",
        ["competitor_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_relationships_match_status"),
        "competitor_relationships",
        ["match_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("competitor_relationships")
    op.drop_table("product_observations")
    op.drop_table("collection_jobs")
    op.drop_table("evidence_artifacts")
    op.drop_table("products")
