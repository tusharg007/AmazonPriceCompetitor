"""Store observation-backed deterministic match audit records.

Revision ID: 003_match_evidence
Revises: 002_active_job_dedup
"""

import sqlalchemy as sa
from alembic import op

revision = "003_match_evidence"
down_revision = "002_active_job_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_observation_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_observation_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("evidence_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["competitor_relationships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_observation_id"], ["product_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_observation_id"], ["product_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["collection_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id",
            "baseline_observation_id",
            "candidate_observation_id",
            "policy_version",
            name="uq_match_capture_policy",
        ),
    )
    op.create_index("ix_match_evidence_match_id", "match_evidence", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_match_evidence_match_id", table_name="match_evidence")
    op.drop_table("match_evidence")
