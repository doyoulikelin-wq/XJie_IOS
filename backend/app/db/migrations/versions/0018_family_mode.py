"""Add family mode tables.

Revision ID: 0018_family_mode
Revises: 0017_user_feedback
Create Date: 2026-06-09
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_family_mode"
down_revision = "0017_user_feedback"
branch_labels = None
depends_on = None


FAMILY_TABLES = {
    "family_groups",
    "family_members",
    "family_invites",
    "family_permissions",
    "family_care_events",
    "family_audit_logs",
}


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    existing_family_tables = FAMILY_TABLES.intersection(existing_tables)
    if existing_family_tables == FAMILY_TABLES:
        return
    if existing_family_tables:
        missing = ", ".join(sorted(FAMILY_TABLES - existing_family_tables))
        raise RuntimeError(f"Partial family migration state; missing tables: {missing}")

    op.create_table(
        "family_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_family_groups_owner_user_id", "family_groups", ["owner_user_id"])

    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="member"),
        sa.Column("relation", sa.String(length=40), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "user_id", name="uq_family_members_group_user"),
    )
    op.create_index("ix_family_members_group_id", "family_members", ["group_id"])
    op.create_index("ix_family_members_user_id", "family_members", ["user_id"])
    op.create_index("ix_family_members_role", "family_members", ["role"])
    op.create_index("ix_family_members_status", "family_members", ["status"])
    op.create_index("ix_family_members_user_status", "family_members", ["user_id", "status"])

    op.create_table(
        "family_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("family_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inviter_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invite_code", sa.String(length=32), nullable=False),
        sa.Column("target_phone", sa.String(length=32), nullable=True),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="member"),
        sa.Column("relation", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("invite_code", name="uq_family_invites_invite_code"),
    )
    op.create_index("ix_family_invites_group_id", "family_invites", ["group_id"])
    op.create_index("ix_family_invites_inviter_user_id", "family_invites", ["inviter_user_id"])
    op.create_index("ix_family_invites_invite_code", "family_invites", ["invite_code"])
    op.create_index("ix_family_invites_target_phone", "family_invites", ["target_phone"])
    op.create_index("ix_family_invites_status", "family_invites", ["status"])
    op.create_index("ix_family_invites_expires_at", "family_invites", ["expires_at"])
    op.create_index("ix_family_invites_accepted_by_user_id", "family_invites", ["accepted_by_user_id"])

    op.create_table(
        "family_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewer_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("can_view_glucose_detail", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_view_medication", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_view_health_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_view_documents", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_view_omics", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_view_ai_summary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subject_user_id", "viewer_user_id", name="uq_family_permissions_subject_viewer"),
    )
    op.create_index("ix_family_permissions_subject_user_id", "family_permissions", ["subject_user_id"])
    op.create_index("ix_family_permissions_viewer_user_id", "family_permissions", ["viewer_user_id"])
    op.create_index("ix_family_permissions_viewer_subject", "family_permissions", ["viewer_user_id", "subject_user_id"])

    op.create_table(
        "family_care_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_family_care_events_subject_user_id", "family_care_events", ["subject_user_id"])
    op.create_index("ix_family_care_events_actor_user_id", "family_care_events", ["actor_user_id"])
    op.create_index("ix_family_care_events_event_type", "family_care_events", ["event_type"])
    op.create_index("ix_family_care_events_status", "family_care_events", ["status"])
    op.create_index("ix_family_care_events_created_at", "family_care_events", ["created_at"])
    op.create_index("ix_family_care_events_subject_created", "family_care_events", ["subject_user_id", "created_at"])

    op.create_table(
        "family_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_family_audit_logs_subject_user_id", "family_audit_logs", ["subject_user_id"])
    op.create_index("ix_family_audit_logs_viewer_user_id", "family_audit_logs", ["viewer_user_id"])
    op.create_index("ix_family_audit_logs_action", "family_audit_logs", ["action"])
    op.create_index("ix_family_audit_logs_created_at", "family_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_family_audit_logs_created_at", table_name="family_audit_logs")
    op.drop_index("ix_family_audit_logs_action", table_name="family_audit_logs")
    op.drop_index("ix_family_audit_logs_viewer_user_id", table_name="family_audit_logs")
    op.drop_index("ix_family_audit_logs_subject_user_id", table_name="family_audit_logs")
    op.drop_table("family_audit_logs")

    op.drop_index("ix_family_care_events_subject_created", table_name="family_care_events")
    op.drop_index("ix_family_care_events_created_at", table_name="family_care_events")
    op.drop_index("ix_family_care_events_status", table_name="family_care_events")
    op.drop_index("ix_family_care_events_event_type", table_name="family_care_events")
    op.drop_index("ix_family_care_events_actor_user_id", table_name="family_care_events")
    op.drop_index("ix_family_care_events_subject_user_id", table_name="family_care_events")
    op.drop_table("family_care_events")

    op.drop_index("ix_family_permissions_viewer_subject", table_name="family_permissions")
    op.drop_index("ix_family_permissions_viewer_user_id", table_name="family_permissions")
    op.drop_index("ix_family_permissions_subject_user_id", table_name="family_permissions")
    op.drop_table("family_permissions")

    op.drop_index("ix_family_invites_accepted_by_user_id", table_name="family_invites")
    op.drop_index("ix_family_invites_expires_at", table_name="family_invites")
    op.drop_index("ix_family_invites_status", table_name="family_invites")
    op.drop_index("ix_family_invites_target_phone", table_name="family_invites")
    op.drop_index("ix_family_invites_invite_code", table_name="family_invites")
    op.drop_index("ix_family_invites_inviter_user_id", table_name="family_invites")
    op.drop_index("ix_family_invites_group_id", table_name="family_invites")
    op.drop_table("family_invites")

    op.drop_index("ix_family_members_user_status", table_name="family_members")
    op.drop_index("ix_family_members_status", table_name="family_members")
    op.drop_index("ix_family_members_role", table_name="family_members")
    op.drop_index("ix_family_members_user_id", table_name="family_members")
    op.drop_index("ix_family_members_group_id", table_name="family_members")
    op.drop_table("family_members")

    op.drop_index("ix_family_groups_owner_user_id", table_name="family_groups")
    op.drop_table("family_groups")
