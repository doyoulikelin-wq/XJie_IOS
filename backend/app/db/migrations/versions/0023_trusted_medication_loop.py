"""Add the user-confirmed medication execution loop.

Revision ID: 0023_trusted_medication_loop
Revises: 0022_health_trust_contracts
Create Date: 2026-07-15

This migration is expand-only: it creates new normalized tables and does not
backfill, reinterpret, update, or delete legacy ``medication`` rows.  Existing
rows therefore remain ``legacy_unverified`` until a user confirms them through
the trusted medication API.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0023_trusted_medication_loop"
down_revision = "0022_health_trust_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trusted_medication_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_request_id", sa.String(length=80), nullable=False),
        sa.Column("generic_name", sa.String(length=160), nullable=False),
        sa.Column("brand_name", sa.String(length=160), nullable=True),
        sa.Column("strength", sa.String(length=80), nullable=True),
        sa.Column("dose_text", sa.String(length=80), nullable=True),
        sa.Column("dose_quantity", sa.Numeric(14, 4), nullable=True),
        sa.Column("frequency", sa.String(length=80), nullable=True),
        sa.Column("schedule_times", JSONB, nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "meal_relation",
            sa.String(length=24),
            nullable=False,
            server_default="unspecified",
        ),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("course_start", sa.Date(), nullable=True),
        sa.Column("course_end", sa.Date(), nullable=True),
        sa.Column("prescriber", sa.String(length=160), nullable=True),
        sa.Column("initial_quantity", sa.Numeric(14, 4), nullable=True),
        sa.Column("inventory_unit", sa.String(length=32), nullable=True),
        sa.Column("is_long_term", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("source_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_request_id",
            name="uq_trusted_med_plan_tenant_request",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_trusted_med_plan_tenant_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'retracted')",
            name="ck_trusted_med_plan_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'prescription_import', 'ocr', 'history')",
            name="ck_trusted_med_plan_source_type",
        ),
        sa.CheckConstraint(
            "meal_relation IN ('unspecified', 'before_meal', 'after_meal', 'with_meal')",
            name="ck_trusted_med_plan_meal_relation",
        ),
        sa.CheckConstraint("version >= 1", name="ck_trusted_med_plan_version"),
        sa.CheckConstraint(
            "course_start IS NULL OR course_end IS NULL OR course_start <= course_end",
            name="ck_trusted_med_plan_course_window",
        ),
        sa.CheckConstraint(
            "dose_quantity IS NULL OR dose_quantity > 0",
            name="ck_trusted_med_plan_dose_quantity",
        ),
        sa.CheckConstraint(
            "initial_quantity IS NULL OR initial_quantity >= 0",
            name="ck_trusted_med_plan_initial_quantity",
        ),
        sa.CheckConstraint(
            "((initial_quantity IS NULL AND inventory_unit IS NULL) OR "
            "(initial_quantity IS NOT NULL AND inventory_unit IS NOT NULL))",
            name="ck_trusted_med_plan_inventory_pair",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL",
            name="ck_trusted_med_plan_user_confirmed",
        ),
    )
    op.create_index(
        "ix_trusted_med_plan_subject_status",
        "trusted_medication_plans",
        ["user_id", "subject_user_id", "status"],
    )

    op.create_table(
        "medication_prefill_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="ocr"),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("extracted_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("field_confidences", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "review_status",
            sa.String(length=24),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_client_event_id", sa.String(length=80), nullable=True),
        sa.Column("accepted_plan_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_prefill_accepted_plan_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_prefill_tenant_event",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "review_client_event_id",
            name="uq_med_prefill_tenant_review_event",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_med_prefill_tenant_id"
        ),
        sa.CheckConstraint(
            "source_type IN ('ocr', 'prescription_import', 'history')",
            name="ck_med_prefill_source_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'accepted', 'rejected')",
            name="ck_med_prefill_review_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_med_prefill_version"),
        sa.CheckConstraint(
            "(review_status = 'pending_review' AND reviewed_at IS NULL "
            "AND reviewed_by_user_id IS NULL AND review_client_event_id IS NULL "
            "AND accepted_plan_id IS NULL) OR "
            "(review_status = 'accepted' AND reviewed_at IS NOT NULL "
            "AND reviewed_by_user_id IS NOT NULL AND review_client_event_id IS NOT NULL "
            "AND accepted_plan_id IS NOT NULL) OR "
            "(review_status = 'rejected' AND reviewed_at IS NOT NULL "
            "AND reviewed_by_user_id IS NOT NULL AND review_client_event_id IS NOT NULL "
            "AND accepted_plan_id IS NULL)",
            name="ck_med_prefill_review_complete",
        ),
    )
    op.create_index(
        "ix_med_prefill_subject_status",
        "medication_prefill_candidates",
        ["user_id", "subject_user_id", "review_status"],
    )

    op.create_table(
        "medication_plan_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("before_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_plan_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_account.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_plan_event_tenant_client",
        ),
        sa.CheckConstraint(
            "event_type IN ('confirm', 'revise', 'pause', 'resume', 'complete', 'retract')",
            name="ck_med_plan_event_type",
        ),
        sa.CheckConstraint("target_version >= 1", name="ck_med_plan_event_target_version"),
    )

    op.create_table(
        "medication_dose_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("occurrence_key", sa.String(length=80), nullable=False),
        sa.Column("scheduled_local_date", sa.Date(), nullable=False),
        sa.Column("scheduled_time", sa.String(length=5), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("effective_status", sa.String(length=16), nullable=False),
        sa.Column("occurrence_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_event_id", sa.Integer(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("taken_quantity", sa.Numeric(14, 4), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "source_type", sa.String(length=24), nullable=False, server_default="user_confirmed"
        ),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_dose_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id", "plan_id", "user_id", "subject_user_id"],
            [
                "medication_dose_events.id",
                "medication_dose_events.plan_id",
                "medication_dose_events.user_id",
                "medication_dose_events.subject_user_id",
            ],
            name="fk_med_dose_event_supersedes_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_account.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "id",
            "plan_id",
            "user_id",
            "subject_user_id",
            name="uq_med_dose_event_tenant_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_dose_event_tenant_client",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "user_id",
            "subject_user_id",
            "occurrence_key",
            "occurrence_version",
            name="uq_med_dose_event_occurrence_version",
        ),
        sa.CheckConstraint(
            "action IN ('taken', 'snooze', 'skip', 'correct')",
            name="ck_med_dose_event_action",
        ),
        sa.CheckConstraint(
            "effective_status IN ('taken', 'snoozed', 'skipped', 'pending')",
            name="ck_med_dose_event_effective_status",
        ),
        sa.CheckConstraint("occurrence_version >= 1", name="ck_med_dose_event_version"),
        sa.CheckConstraint(
            "(action = 'correct' AND supersedes_event_id IS NOT NULL) OR "
            "(action <> 'correct' AND supersedes_event_id IS NULL)",
            name="ck_med_dose_event_correction_target",
        ),
        sa.CheckConstraint(
            "(effective_status = 'snoozed' AND snoozed_until IS NOT NULL) OR "
            "(effective_status <> 'snoozed' AND snoozed_until IS NULL)",
            name="ck_med_dose_event_snooze_time",
        ),
        sa.CheckConstraint(
            "(effective_status = 'taken' AND "
            "(taken_quantity IS NULL OR taken_quantity > 0)) OR "
            "(effective_status <> 'taken' AND taken_quantity IS NULL)",
            name="ck_med_dose_event_taken_quantity",
        ),
        sa.CheckConstraint(
            "(action = 'taken' AND effective_status = 'taken') OR "
            "(action = 'snooze' AND effective_status = 'snoozed') OR "
            "(action = 'skip' AND effective_status = 'skipped') OR action = 'correct'",
            name="ck_med_dose_event_action_result",
        ),
    )
    op.create_index(
        "ix_med_dose_event_occurrence",
        "medication_dose_events",
        ["user_id", "subject_user_id", "scheduled_local_date", "occurrence_key"],
    )

    op.create_table(
        "medication_adverse_reaction_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reaction_key", sa.String(length=80), nullable=False),
        sa.Column("reaction_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("symptoms", sa.Text(), nullable=False),
        sa.Column("onset_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("related_occurrence_key", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "causal_attribution",
            sa.String(length=40),
            nullable=False,
            server_default="temporal_association_only",
        ),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_reaction_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_account.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_reaction_event_tenant_client",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "reaction_key",
            "reaction_version",
            name="uq_med_reaction_event_version",
        ),
        sa.CheckConstraint(
            "event_type IN ('create', 'correct', 'retract')",
            name="ck_med_reaction_event_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retracted')", name="ck_med_reaction_event_status"
        ),
        sa.CheckConstraint(
            "severity IN ('mild', 'moderate', 'severe')",
            name="ck_med_reaction_event_severity",
        ),
        sa.CheckConstraint("reaction_version >= 1", name="ck_med_reaction_event_version"),
        sa.CheckConstraint(
            "causal_attribution = 'temporal_association_only'",
            name="ck_med_reaction_temporal_only",
        ),
        sa.CheckConstraint(
            "(event_type = 'retract' AND status = 'retracted') OR "
            "(event_type <> 'retract' AND status = 'active')",
            name="ck_med_reaction_event_status_match",
        ),
    )
    op.create_index(
        "ix_med_reaction_subject_onset",
        "medication_adverse_reaction_events",
        ["user_id", "subject_user_id", "onset_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_med_reaction_subject_onset",
        table_name="medication_adverse_reaction_events",
    )
    op.drop_table("medication_adverse_reaction_events")
    op.drop_index("ix_med_dose_event_occurrence", table_name="medication_dose_events")
    op.drop_table("medication_dose_events")
    op.drop_table("medication_plan_events")
    op.drop_index("ix_med_prefill_subject_status", table_name="medication_prefill_candidates")
    op.drop_table("medication_prefill_candidates")
    op.drop_index("ix_trusted_med_plan_subject_status", table_name="trusted_medication_plans")
    op.drop_table("trusted_medication_plans")
