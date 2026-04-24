"""mood logs (C4 emoji 5-segment check-in)

Revision ID: 0011_mood_logs
Revises: 0010_literature
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0011_mood_logs"
down_revision = "0010_literature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mood_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ts_date", sa.Date(), nullable=False),
        sa.Column("segment", sa.String(16), nullable=False),
        sa.Column("mood_level", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "ts_date", "segment", name="uq_mood_user_date_segment"),
    )
    op.create_index("ix_mood_logs_user_id", "mood_logs", ["user_id"])
    op.create_index("ix_mood_logs_ts_date", "mood_logs", ["ts_date"])
    op.create_index("ix_mood_user_ts", "mood_logs", ["user_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_mood_user_ts", table_name="mood_logs")
    op.drop_index("ix_mood_logs_ts_date", table_name="mood_logs")
    op.drop_index("ix_mood_logs_user_id", table_name="mood_logs")
    op.drop_table("mood_logs")
