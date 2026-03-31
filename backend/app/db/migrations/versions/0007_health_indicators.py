"""Add health_document_summaries, watched_indicators tables; add version col to health_summaries.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # health_document_summaries – L1/L2 cached summaries
    op.create_table(
        "health_document_summaries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("summary_text", sa.Text, nullable=False, server_default=""),
        sa.Column("abnormal_highlights", JSONB, nullable=True),
        sa.Column("doc_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_doc_summary_user_level", "health_document_summaries", ["user_id", "level"])
    op.create_index(
        "uq_doc_summary_user_level_period",
        "health_document_summaries",
        ["user_id", "level", "period_key"],
        unique=True,
    )

    # watched_indicators
    op.create_table(
        "watched_indicators",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("indicator_name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("uq_watched_user_indicator", "watched_indicators", ["user_id", "indicator_name"], unique=True)

    # Add version column to health_summaries
    op.add_column("health_summaries", sa.Column("version", sa.Integer, nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("health_summaries", "version")
    op.drop_table("watched_indicators")
    op.drop_table("health_document_summaries")
