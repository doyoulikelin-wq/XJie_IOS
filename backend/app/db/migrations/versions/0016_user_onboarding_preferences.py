"""Add onboarding health needs to user settings.

Revision ID: 0016_user_onboarding_preferences
Revises: 0015_health_plan_revisions
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0016_user_onboarding_preferences"
down_revision = "0015_health_plan_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("user_settings", sa.Column("onboarding_target", sa.String(length=80), nullable=True))
    op.add_column("user_settings", sa.Column("onboarding_contents", JSONB, nullable=False, server_default="[]"))
    op.add_column(
        "user_settings",
        sa.Column("onboarding_generate_plan", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "onboarding_generate_plan")
    op.drop_column("user_settings", "onboarding_contents")
    op.drop_column("user_settings", "onboarding_target")
    op.drop_column("user_settings", "onboarding_completed")
