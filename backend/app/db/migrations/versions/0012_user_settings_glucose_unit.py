"""Add glucose_unit column to user_settings.

Revision ID: 0012_user_settings_glucose_unit
Revises: 0011_mood_logs
Create Date: 2026-04-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0012_user_settings_glucose_unit"
down_revision = "0011_mood_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "glucose_unit",
            sa.String(length=8),
            nullable=False,
            server_default="mg_dl",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "glucose_unit")
