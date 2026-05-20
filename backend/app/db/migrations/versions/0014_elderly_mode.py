"""Add elderly_mode + elderly_checkin table.

Revision ID: 0014_elderly_mode
Revises: 0013_feature_parity
Create Date: 2026-06-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0014_elderly_mode"
down_revision = "0013_feature_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("elderly_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user_settings",
        sa.Column("elderly_checkin_interval_min", sa.Integer(), nullable=False, server_default="180"),
    )

    op.create_table(
        "elderly_checkin",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("prompt_type", sa.String(length=16), nullable=False, server_default="combined"),
        sa.Column("activity", sa.String(length=128), nullable=True),
        sa.Column("body_feeling", sa.String(length=16), nullable=True),
        sa.Column("mood", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="auto_prompt"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_elderly_user_created", "elderly_checkin", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_elderly_user_created", table_name="elderly_checkin")
    op.drop_table("elderly_checkin")
    op.drop_column("user_settings", "elderly_checkin_interval_min")
    op.drop_column("user_settings", "elderly_mode")
