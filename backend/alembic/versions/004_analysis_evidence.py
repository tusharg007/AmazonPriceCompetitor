"""Evidence-linked bounded analysis.

Revision ID: 004_analysis_evidence
Revises: 003_match_evidence
"""

import sqlalchemy as sa
from alembic import op

revision = "004_analysis_evidence"
down_revision = "003_match_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("input_evidence", sa.JSON(), nullable=False),
        sa.Column("raw_output", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["collection_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "input_hash",
            "model",
            "prompt_version",
            "schema_version",
            name="uq_analysis_identity",
        ),
        sa.CheckConstraint("status IN ('succeeded','failed')", name="ck_analysis_status"),
    )
    op.create_index("ix_analysis_runs_product_id", "analysis_runs", ["product_id"])
    op.create_table(
        "analysis_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("claim_type", sa.String(50), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "claim_type IN ('price_comparison','rating_comparison','positioning','recommendation','summary')",
            name="ck_claim_type",
        ),
    )
    op.create_index("ix_analysis_claims_run_id", "analysis_claims", ["run_id"])
    op.create_table(
        "claim_evidence",
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.PrimaryKeyConstraint("claim_id", "observation_id"),
        sa.ForeignKeyConstraint(["claim_id"], ["analysis_claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["product_observations.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "role IN ('baseline','competitor','supporting')", name="ck_claim_evidence_role"
        ),
    )


def downgrade() -> None:
    op.drop_table("claim_evidence")
    op.drop_index("ix_analysis_claims_run_id", table_name="analysis_claims")
    op.drop_table("analysis_claims")
    op.drop_index("ix_analysis_runs_product_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
