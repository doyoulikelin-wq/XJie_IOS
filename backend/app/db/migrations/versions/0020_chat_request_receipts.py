"""Add database-backed chat request idempotency leases.

Revision ID: 0020_chat_request_receipts
Revises: 0019_app_releases
Create Date: 2026-07-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0020_chat_request_receipts"
down_revision = "0019_app_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_request_receipts" in inspector.get_table_names():
        return

    op.create_table(
        "chat_request_receipts",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_message_id", sa.String(length=80), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("user_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("lease_id", sa.String(length=36), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "client_message_id", name="pk_chat_request_receipts"),
        sa.UniqueConstraint("user_message_id", name="uq_chat_request_receipts_user_message"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_request_receipts" in inspector.get_table_names():
        op.drop_table("chat_request_receipts")
