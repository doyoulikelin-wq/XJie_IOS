"""Add feature_parity table for iOS/Android sync tracking.

Revision ID: 0013_feature_parity
Revises: 0012_user_settings_glucose_unit
Create Date: 2026-05-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_feature_parity"
down_revision = "0012_user_settings_glucose_unit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_parity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("priority", sa.String(length=4), nullable=False, server_default="P1"),
        sa.Column("ios_status", sa.String(length=16), nullable=False, server_default="not_started"),
        sa.Column("android_status", sa.String(length=16), nullable=False, server_default="not_started"),
        sa.Column("ios_version", sa.String(length=32), nullable=True),
        sa.Column("android_version", sa.String(length=32), nullable=True),
        sa.Column("backend_apis", sa.Text(), nullable=True),
        sa.Column("spec_link", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_feature_parity_module", "feature_parity", ["module"])
    op.create_index("ix_feature_parity_priority", "feature_parity", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_feature_parity_priority", table_name="feature_parity")
    op.drop_index("ix_feature_parity_module", table_name="feature_parity")
    op.drop_table("feature_parity")
