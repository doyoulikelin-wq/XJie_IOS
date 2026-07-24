"""Add persisted doctor-facing medical assistant overview snapshots.

Revision ID: 0026_medical_assistant
Revises: 0025_dietary_records
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0026_medical_assistant"
down_revision = "0025_dietary_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "medical_assistant_overviews",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_latest_upload_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_workflow_ids", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_document_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_medical_assistant_overviews_user_id",
        "medical_assistant_overviews",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_medical_assistant_overviews_user_id",
        table_name="medical_assistant_overviews",
    )
    op.drop_table("medical_assistant_overviews")
