"""Add trusted dietary drafts, records, day state, and cached summaries.

Revision ID: 0025_dietary_records
Revises: 0024_health_profile_report_completion
Create Date: 2026-07-15

This is an additive migration.  The legacy ``meals`` and ``meal_photos``
tables are deliberately unchanged so existing clients remain compatible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0025_dietary_records"
down_revision = "0024_health_profile_report_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dietary_drafts",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_scope", sa.String(length=16), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_ref", sa.String(length=256), nullable=True),
        sa.Column("image_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("recognition_version", sa.String(length=80), nullable=True),
        sa.Column(
            "recognition_status",
            sa.String(length=40),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("diet_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=16), nullable=True),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column(
            "input_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("food_items", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("portion_text", sa.String(length=256), nullable=True),
        sa.Column("structure", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "estimated_nutrition", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "field_confidences", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("recognition_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="pending_confirmation",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint(
            "source_type IN ('camera', 'photo_library', 'text', 'voice', 'recent', 'chat', 'manual')",
            name="ck_dietary_draft_source_type",
        ),
        sa.CheckConstraint(
            "event_scope IN ('create', 'photo', 'reuse')",
            name="ck_dietary_draft_event_scope",
        ),
        sa.CheckConstraint(
            "meal_type IS NULL OR meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_dietary_draft_meal_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending_confirmation', 'confirmed', 'rejected')",
            name="ck_dietary_draft_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_dietary_draft_version"),
        sa.CheckConstraint(
            "recognition_confidence IS NULL OR (recognition_confidence >= 0 AND recognition_confidence <= 1)",
            name="ck_dietary_draft_confidence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_user_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "event_scope",
            "client_event_id",
            name="uq_dietary_draft_tenant_scope_event",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_draft_tenant_id"
        ),
    )
    op.create_index(
        "ix_dietary_draft_subject_date_status",
        "dietary_drafts",
        ["user_id", "subject_user_id", "diet_date", "status"],
        unique=False,
    )

    op.create_table(
        "dietary_records",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("source_draft_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("confirmation_client_event_id", sa.String(length=80), nullable=False),
        sa.Column(
            "confirmation_request_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column("diet_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("meal_type", sa.String(length=16), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_ref", sa.String(length=256), nullable=False),
        sa.Column(
            "source_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("food_items", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("portion_text", sa.String(length=256), nullable=True),
        sa.Column("structure", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "estimated_nutrition", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "field_confidences", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="user_confirmed",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_dietary_record_meal_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('camera', 'photo_library', 'text', 'voice', 'recent', 'chat', 'manual')",
            name="ck_dietary_record_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('user_confirmed', 'modified', 'deleted')",
            name="ck_dietary_record_status",
        ),
        sa.CheckConstraint(
            "confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL",
            name="ck_dietary_record_user_confirmed",
        ),
        sa.CheckConstraint("version >= 1", name="ck_dietary_record_version"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_dietary_record_confidence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_user_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_draft_id", "user_id", "subject_user_id"],
            [
                "dietary_drafts.id",
                "dietary_drafts.user_id",
                "dietary_drafts.subject_user_id",
            ],
            name="fk_dietary_record_draft_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_record_tenant_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_dietary_record_tenant_confirm_event",
        ),
        sa.UniqueConstraint(
            "source_draft_id",
            "user_id",
            "subject_user_id",
            name="uq_dietary_record_tenant_draft",
        ),
    )
    op.create_index(
        "ix_dietary_record_subject_date_meal",
        "dietary_records",
        ["user_id", "subject_user_id", "diet_date", "meal_type", "eaten_at"],
        unique=False,
    )

    op.create_table(
        "dietary_record_events",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column(
            "before_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "after_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('confirm', 'update', 'delete', 'reuse')",
            name="ck_dietary_record_event_type",
        ),
        sa.CheckConstraint(
            "target_version >= 1", name="ck_dietary_record_event_version"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "user_id", "subject_user_id"],
            [
                "dietary_records.id",
                "dietary_records.user_id",
                "dietary_records.subject_user_id",
            ],
            name="fk_dietary_record_event_record_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "event_type",
            "client_event_id",
            name="uq_dietary_record_event_tenant_type_event",
        ),
    )
    op.create_index(
        "ix_dietary_record_event_history",
        "dietary_record_events",
        ["user_id", "subject_user_id", "record_id", "target_version", "id"],
        unique=False,
    )

    op.create_table(
        "dietary_days",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("diet_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("auto_close_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("record_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("close_method", sa.String(length=16), nullable=True),
        sa.Column("close_client_event_id", sa.String(length=80), nullable=True),
        sa.Column("close_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "exclude_pending_on_close",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "record_complete", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "confirmed_meal_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "structure_summary", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('open', 'waiting_confirmation', 'incomplete', 'ready', 'stale', 'recalculating', 'failed')",
            name="ck_dietary_day_state",
        ),
        sa.CheckConstraint(
            "close_method IS NULL OR close_method IN ('automatic', 'manual')",
            name="ck_dietary_day_close_method",
        ),
        sa.CheckConstraint("record_version >= 0", name="ck_dietary_day_record_version"),
        sa.CheckConstraint(
            "confirmed_meal_count >= 0", name="ck_dietary_day_confirmed_count"
        ),
        sa.CheckConstraint("pending_count >= 0", name="ck_dietary_day_pending_count"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_user_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "diet_date",
            name="uq_dietary_day_tenant_date",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_day_tenant_id"
        ),
    )
    op.create_index(
        "ix_dietary_day_subject_state_date",
        "dietary_days",
        ["user_id", "subject_user_id", "state", "diet_date"],
        unique=False,
    )
    op.create_index(
        "ix_dietary_day_open_due",
        "dietary_days",
        ["closed_at", "auto_close_due_at", "id"],
        unique=False,
    )

    op.create_table(
        "dietary_daily_summaries",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("day_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("diet_date", sa.Date(), nullable=False),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("close_method", sa.String(length=16), nullable=False),
        sa.Column("record_complete", sa.Boolean(), nullable=False),
        sa.Column("confirmed_meal_count", sa.Integer(), nullable=False),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column(
            "structure_summary", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("today_suggestion", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("template_version", sa.String(length=80), nullable=False),
        sa.Column(
            "recalculated_after_edit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_dietary_summary_record_version"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_dietary_summary_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["day_id", "user_id", "subject_user_id"],
            ["dietary_days.id", "dietary_days.user_id", "dietary_days.subject_user_id"],
            name="fk_dietary_summary_day_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "diet_date",
            "record_version",
            name="uq_dietary_summary_tenant_date_version",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_summary_tenant_id"
        ),
    )
    op.create_index(
        "ix_dietary_summary_subject_date_version",
        "dietary_daily_summaries",
        ["user_id", "subject_user_id", "diet_date", "record_version"],
        unique=False,
    )

    op.create_table(
        "dietary_recognition_cache",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("image_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("recognition_version", sa.String(length=80), nullable=False),
        sa.Column(
            "result_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(image_fingerprint) = 64",
            name="ck_dietary_recognition_fingerprint",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subject_user_id"], ["user_account.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "image_fingerprint",
            "recognition_version",
            name="uq_dietary_recognition_tenant_fingerprint_version",
        ),
    )
    op.create_index(
        "ix_dietary_recognition_subject_fingerprint",
        "dietary_recognition_cache",
        ["user_id", "subject_user_id", "image_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("dietary_recognition_cache")
    op.drop_table("dietary_daily_summaries")
    op.drop_table("dietary_days")
    op.drop_table("dietary_record_events")
    op.drop_table("dietary_records")
    op.drop_table("dietary_drafts")
