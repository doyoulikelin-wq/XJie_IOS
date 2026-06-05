"""Add user feedback table.

Revision ID: 0017_user_feedback
Revises: 0016_user_onboarding_preferences
Create Date: 2026-06-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_user_feedback"
down_revision = "0016_user_onboarding_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(length=128), nullable=True),
        sa.Column("app_platform", sa.String(length=24), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("device_info", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="new"),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_feedback_user_id", "user_feedback", ["user_id"])
    op.create_index("ix_user_feedback_status", "user_feedback", ["status"])
    op.create_index("ix_user_feedback_created_at", "user_feedback", ["created_at"])
    op.create_index("ix_user_feedback_user_created", "user_feedback", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_user_feedback_user_created", table_name="user_feedback")
    op.drop_index("ix_user_feedback_created_at", table_name="user_feedback")
    op.drop_index("ix_user_feedback_status", table_name="user_feedback")
    op.drop_index("ix_user_feedback_user_id", table_name="user_feedback")
    op.drop_table("user_feedback")
