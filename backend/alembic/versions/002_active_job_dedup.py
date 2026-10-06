"""Enforce the approved active collection-job deduplication contract.

Revision ID: 002_active_job_dedup
Revises: 001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "002_active_job_dedup"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_jobs_active_dedup",
        "collection_jobs",
        ["kind", "product_id", "request_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_active_dedup", table_name="collection_jobs")
