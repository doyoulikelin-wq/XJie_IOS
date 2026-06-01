"""Add health plan revision and execution audit tables.

Revision ID: 0015_health_plan_revisions
Revises: 0014_elderly_mode
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0015_health_plan_revisions"
down_revision = "0014_elderly_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=True),
        sa.Column("task_id", sa.BigInteger(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("task_type", sa.String(length=24), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("purpose", sa.String(length=160), nullable=False),
        sa.Column("execution_item", sa.Text(), nullable=True),
        sa.Column("execution_status", sa.String(length=40), nullable=True),
        sa.Column("before_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("after_data", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_plan_task_events_user_id", "plan_task_events", ["user_id"])
    op.create_index("ix_plan_task_events_plan_id", "plan_task_events", ["plan_id"])
    op.create_index("ix_plan_task_events_task_id", "plan_task_events", ["task_id"])
    op.create_index("ix_plan_task_events_date", "plan_task_events", ["date"])
    op.create_index("ix_plan_task_events_task_type", "plan_task_events", ["task_type"])
    op.create_index("ix_plan_task_events_event_type", "plan_task_events", ["event_type"])
    op.create_index("ix_plan_task_events_created_at", "plan_task_events", ["created_at"])
    op.create_index("ix_plan_task_events_user_created", "plan_task_events", ["user_id", "created_at"])

    op.create_table(
        "plan_ai_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("original_items", JSONB, nullable=False, server_default="[]"),
        sa.Column("revised_items", JSONB, nullable=False, server_default="[]"),
        sa.Column("reasons", JSONB, nullable=False, server_default="[]"),
        sa.Column("accepted_keys", JSONB, nullable=False, server_default="[]"),
        sa.Column("rejected_keys", JSONB, nullable=False, server_default="[]"),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("llm_raw", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plan_ai_revisions_user_id", "plan_ai_revisions", ["user_id"])
    op.create_index("ix_plan_ai_revisions_revision_date", "plan_ai_revisions", ["revision_date"])
    op.create_index("ix_plan_ai_revisions_status", "plan_ai_revisions", ["status"])
    op.create_index("ix_plan_ai_revisions_created_at", "plan_ai_revisions", ["created_at"])
    op.create_index("ix_plan_ai_revisions_user_date", "plan_ai_revisions", ["user_id", "revision_date"])


def downgrade() -> None:
    op.drop_index("ix_plan_ai_revisions_user_date", table_name="plan_ai_revisions")
    op.drop_index("ix_plan_ai_revisions_created_at", table_name="plan_ai_revisions")
    op.drop_index("ix_plan_ai_revisions_status", table_name="plan_ai_revisions")
    op.drop_index("ix_plan_ai_revisions_revision_date", table_name="plan_ai_revisions")
    op.drop_index("ix_plan_ai_revisions_user_id", table_name="plan_ai_revisions")
    op.drop_table("plan_ai_revisions")

    op.drop_index("ix_plan_task_events_user_created", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_created_at", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_event_type", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_task_type", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_date", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_task_id", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_plan_id", table_name="plan_task_events")
    op.drop_index("ix_plan_task_events_user_id", table_name="plan_task_events")
    op.drop_table("plan_task_events")
