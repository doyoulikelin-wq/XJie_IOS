"""Add normalized health trust and admission contracts.

Revision ID: 0022_health_trust_contracts
Revises: 0021_device_indicator_identity
Create Date: 2026-07-15

This is deliberately an expand-only migration.  It does not backfill legacy
``health_documents`` rows and therefore does not treat an old ``done`` OCR
result as user-confirmed health data.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB


revision = "0022_health_trust_contracts"
down_revision = "0021_device_indicator_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A workflow may reference a legacy document only through the same owner.
    # subject_user_id remains separate so delegated/family workflows cannot
    # silently reinterpret ownership of the original document.
    with op.batch_alter_table("health_documents") as batch_op:
        batch_op.create_unique_constraint(
            "uq_health_documents_id_user",
            ["id", "user_id"],
        )

    op.create_table(
        "health_report_workflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_document_id", sa.Integer(), nullable=True),
        sa.Column("client_request_id", sa.String(length=80), nullable=False),
        sa.Column("document_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("report_type", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("workflow_metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("recognized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_client_event_id", sa.String(length=80), nullable=True),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["legacy_document_id", "user_id"],
            ["health_documents.id", "health_documents.user_id"],
            name="fk_report_workflow_legacy_owner",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_request_id",
            name="uq_report_workflow_tenant_request",
        ),
        sa.UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            name="uq_report_workflow_tenant_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "document_fingerprint",
            name="uq_report_workflow_tenant_fingerprint",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_report_workflow_tenant_confirmation",
        ),
        sa.UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_report_workflow_confirmation_tenant_id",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'uploading', 'recognizing', "
            "'awaiting_confirmation', 'committing', 'completed', "
            "'completed_score_pending', 'failed')",
            name="ck_report_workflow_status",
        ),
        sa.CheckConstraint(
            "report_type IN ('unknown', 'exam', 'lab', 'imaging', "
            "'medical_record', 'other')",
            name="ck_report_workflow_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_report_workflow_version"),
        sa.CheckConstraint(
            "length(client_request_id) > 0",
            name="ck_report_workflow_request_nonempty",
        ),
        sa.CheckConstraint(
            "((confirmed_at IS NULL AND confirmation_client_event_id IS NULL "
            "AND confirmed_by_user_id IS NULL) OR "
            "(confirmed_at IS NOT NULL AND confirmation_client_event_id IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL))",
            name="ck_report_workflow_confirmation_complete",
        ),
        sa.CheckConstraint(
            "status NOT IN ('committing', 'completed', 'completed_score_pending') "
            "OR confirmed_at IS NOT NULL",
            name="ck_report_workflow_committed_confirmed",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR status IN "
            "('committing', 'completed', 'completed_score_pending', 'failed')",
            name="ck_report_workflow_confirmation_state",
        ),
    )
    op.create_index(
        "ix_report_workflow_subject_status",
        "health_report_workflows",
        ["user_id", "subject_user_id", "status"],
    )

    op.create_table(
        "health_report_field_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_key", sa.String(length=128), nullable=False),
        sa.Column("canonical_code", sa.String(length=80), nullable=True),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("raw_name", sa.String(length=160), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("raw_unit", sa.String(length=64), nullable=True),
        sa.Column("normalized_value", sa.Numeric(24, 8), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("normalized_unit", sa.String(length=64), nullable=True),
        sa.Column("reference_low", sa.Numeric(24, 8), nullable=True),
        sa.Column("reference_high", sa.Numeric(24, 8), nullable=True),
        sa.Column("reference_text", sa.String(length=256), nullable=True),
        sa.Column("abnormal_state", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_locator", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("review_status", sa.String(length=24), nullable=False, server_default="pending_review"),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("model_version", sa.String(length=80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_candidate_workflow_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "candidate_key",
            name="uq_report_candidate_workflow_key",
        ),
        sa.UniqueConstraint(
            "id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_candidate_tenant_id",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'auto_accepted', 'confirmed', "
            "'corrected', 'rejected')",
            name="ck_report_candidate_review_status",
        ),
        sa.CheckConstraint(
            "abnormal_state IN ('normal', 'abnormal', 'unknown')",
            name="ck_report_candidate_abnormal_state",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_report_candidate_confidence",
        ),
        sa.CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR "
            "reference_low <= reference_high",
            name="ck_report_candidate_reference_range",
        ),
        sa.CheckConstraint("version >= 1", name="ck_report_candidate_version"),
        sa.CheckConstraint(
            "review_status <> 'auto_accepted' OR "
            "(requires_review = false AND abnormal_state = 'normal')",
            name="ck_report_candidate_auto_accept_safe",
        ),
    )
    op.create_index(
        "ix_report_candidate_review_queue",
        "health_report_field_candidates",
        ["user_id", "subject_user_id", "workflow_id", "review_status"],
    )

    op.create_table(
        "health_report_confirmation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column("before_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["candidate_id", "workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_field_candidates.id",
                "health_report_field_candidates.workflow_id",
                "health_report_field_candidates.user_id",
                "health_report_field_candidates.subject_user_id",
            ],
            name="fk_report_event_candidate_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_account.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_report_event_tenant_client",
        ),
        sa.UniqueConstraint(
            "id",
            "candidate_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_event_tenant_id",
        ),
        sa.CheckConstraint(
            "event_type IN ('confirm', 'correct', 'reject', 'manual_add')",
            name="ck_report_confirmation_event_type",
        ),
        sa.CheckConstraint(
            "candidate_version >= 1", name="ck_report_event_candidate_version"
        ),
    )

    op.create_table(
        "confirmed_health_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("source_candidate_id", sa.Integer(), nullable=False),
        sa.Column("confirmation_event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "report_confirmation_client_event_id",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("canonical_code", sa.String(length=80), nullable=True),
        sa.Column("canonical_name", sa.String(length=160), nullable=False),
        sa.Column("value_numeric", sa.Numeric(24, 8), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("reference_low", sa.Numeric(24, 8), nullable=True),
        sa.Column("reference_high", sa.Numeric(24, 8), nullable=True),
        sa.Column("reference_text", sa.String(length=256), nullable=True),
        sa.Column("abnormal_state", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            [
                "workflow_id",
                "user_id",
                "subject_user_id",
                "report_confirmation_client_event_id",
            ],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
                "health_report_workflows.confirmation_client_event_id",
            ],
            name="fk_observation_report_confirmation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "confirmation_event_id",
                "source_candidate_id",
                "workflow_id",
                "user_id",
                "subject_user_id",
            ],
            [
                "health_report_confirmation_events.id",
                "health_report_confirmation_events.candidate_id",
                "health_report_confirmation_events.workflow_id",
                "health_report_confirmation_events.user_id",
                "health_report_confirmation_events.subject_user_id",
            ],
            name="fk_observation_confirmation_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_observation_tenant_idempotency",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "source_candidate_id",
            name="uq_observation_tenant_candidate",
        ),
        sa.UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            name="uq_observation_tenant_id",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_observation_status",
        ),
        sa.CheckConstraint(
            "abnormal_state IN ('normal', 'abnormal', 'unknown')",
            name="ck_observation_abnormal_state",
        ),
        sa.CheckConstraint(
            "((value_numeric IS NOT NULL AND value_text IS NULL) OR "
            "(value_numeric IS NULL AND value_text IS NOT NULL))",
            name="ck_observation_has_value",
        ),
        sa.CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR "
            "reference_low <= reference_high",
            name="ck_observation_reference_range",
        ),
        sa.CheckConstraint("version >= 1", name="ck_observation_version"),
    )
    op.create_index(
        "ix_observation_subject_code_time",
        "confirmed_health_observations",
        ["user_id", "subject_user_id", "canonical_code", "effective_at"],
    )

    op.create_table(
        "health_profile_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_key", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("value_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_safety_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmation_method", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["user_account.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "user_id", "subject_user_id", "fact_key", name="uq_profile_fact_tenant_key"
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_profile_fact_tenant_id"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_profile_fact_status",
        ),
        sa.CheckConstraint(
            "confirmation_method IN ('user', 'clinician', 'verified_source', 'automatic')",
            name="ck_profile_fact_confirmation_method",
        ),
        sa.CheckConstraint(
            "is_safety_critical = false OR "
            "(confirmation_method IN ('user', 'clinician') "
            "AND confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL)",
            name="ck_profile_fact_safety_explicit",
        ),
        sa.CheckConstraint("version >= 1", name="ck_profile_fact_version"),
    )
    op.create_index(
        "ix_profile_fact_subject_category",
        "health_profile_facts",
        ["user_id", "subject_user_id", "category"],
    )

    op.create_table(
        "health_profile_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_key", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=48), nullable=False),
        sa.Column("proposed_value", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_safety_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("review_status", sa.String(length=24), nullable=False, server_default="pending_review"),
        sa.Column("conflict_with_fact_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conflict_with_fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_candidate_conflict_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_profile_candidate_tenant_idempotency",
        ),
        sa.UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_profile_candidate_tenant_id"
        ),
        sa.CheckConstraint(
            "review_status IN ('pending_review', 'accepted', 'rejected', "
            "'superseded', 'conflict')",
            name="ck_profile_candidate_review_status",
        ),
        sa.CheckConstraint(
            "((review_status = 'conflict' AND conflict_with_fact_id IS NOT NULL) OR "
            "(review_status <> 'conflict' AND conflict_with_fact_id IS NULL))",
            name="ck_profile_candidate_conflict_explicit",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_profile_candidate_confidence",
        ),
        sa.CheckConstraint("version >= 1", name="ck_profile_candidate_version"),
    )
    op.create_index(
        "ix_profile_candidate_review_queue",
        "health_profile_candidates",
        ["user_id", "subject_user_id", "review_status"],
    )

    op.create_table(
        "health_profile_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("source_observation_id", sa.Integer(), nullable=True),
        sa.Column("source_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_source_fact_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "user_id", "subject_user_id"],
            [
                "health_profile_candidates.id",
                "health_profile_candidates.user_id",
                "health_profile_candidates.subject_user_id",
            ],
            name="fk_profile_source_candidate_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id", "user_id", "subject_user_id"],
            [
                "confirmed_health_observations.id",
                "confirmed_health_observations.user_id",
                "confirmed_health_observations.subject_user_id",
            ],
            name="fk_profile_source_observation_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_profile_source_tenant_idempotency",
        ),
        sa.CheckConstraint(
            "((fact_id IS NOT NULL AND candidate_id IS NULL) OR "
            "(fact_id IS NULL AND candidate_id IS NOT NULL))",
            name="ck_profile_source_one_target",
        ),
        sa.CheckConstraint(
            "source_type IN ('report_observation', 'medication', 'health_plan', "
            "'manual', 'device')",
            name="ck_profile_source_type",
        ),
        sa.CheckConstraint(
            "source_type <> 'report_observation' OR source_observation_id IS NOT NULL",
            name="ck_profile_source_report_observation",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_profile_source_confidence",
        ),
    )

    op.create_table(
        "health_profile_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("client_event_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("before_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_data", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_revision_fact_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "user_id", "subject_user_id"],
            [
                "health_profile_candidates.id",
                "health_profile_candidates.user_id",
                "health_profile_candidates.subject_user_id",
            ],
            name="fk_profile_revision_candidate_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user_account.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_profile_revision_tenant_client",
        ),
        sa.CheckConstraint(
            "((fact_id IS NOT NULL AND candidate_id IS NULL) OR "
            "(fact_id IS NULL AND candidate_id IS NOT NULL))",
            name="ck_profile_revision_has_target",
        ),
        sa.CheckConstraint(
            "event_type IN ('create', 'update', 'confirm', 'supersede', 'retract')",
            name="ck_profile_revision_event_type",
        ),
        sa.CheckConstraint(
            "target_version >= 1", name="ck_profile_revision_target_version"
        ),
    )

    op.create_table(
        "health_score_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=False),
        sa.Column("source_report_workflow_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("score_kind", sa.String(length=24), nullable=False),
        sa.Column("algorithm_id", sa.String(length=80), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("before_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("after_value", sa.Numeric(8, 3), nullable=True),
        sa.Column("before_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("after_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("score_direction", sa.String(length=24), nullable=True),
        sa.Column("semantic_outcome", sa.String(length=16), nullable=True),
        sa.Column("calculation_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("missing_inputs", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_report_workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_score_snapshot_report_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_score_snapshot_tenant_idempotency",
        ),
        sa.UniqueConstraint(
            "user_id",
            "subject_user_id",
            "source_report_workflow_id",
            "score_kind",
            "algorithm_version",
            name="uq_score_snapshot_report_kind_version",
        ),
        sa.CheckConstraint(
            "score_kind IN ('stress', 'recovery', 'inflammation', 'x_age')",
            name="ck_score_snapshot_kind",
        ),
        sa.CheckConstraint(
            "calculation_status IN ('pending', 'completed', 'failed')",
            name="ck_score_snapshot_status",
        ),
        sa.CheckConstraint(
            "score_direction IS NULL OR score_direction IN "
            "('higher_is_better', 'lower_is_better', 'target_range', 'informational')",
            name="ck_score_snapshot_direction",
        ),
        sa.CheckConstraint(
            "semantic_outcome IS NULL OR semantic_outcome IN "
            "('improved', 'worsened', 'unchanged', 'unknown')",
            name="ck_score_snapshot_outcome",
        ),
        sa.CheckConstraint(
            "before_confidence IS NULL OR "
            "(before_confidence >= 0 AND before_confidence <= 1)",
            name="ck_score_snapshot_before_confidence",
        ),
        sa.CheckConstraint(
            "after_confidence IS NULL OR "
            "(after_confidence >= 0 AND after_confidence <= 1)",
            name="ck_score_snapshot_after_confidence",
        ),
        sa.CheckConstraint(
            "score_kind = 'x_age' OR before_value IS NULL OR "
            "(before_value >= 0 AND before_value <= 100)",
            name="ck_score_snapshot_before_range",
        ),
        sa.CheckConstraint(
            "score_kind = 'x_age' OR after_value IS NULL OR "
            "(after_value >= 0 AND after_value <= 100)",
            name="ck_score_snapshot_after_range",
        ),
        sa.CheckConstraint(
            "calculation_status <> 'completed' OR "
            "(after_value IS NOT NULL AND score_direction IS NOT NULL "
            "AND semantic_outcome IS NOT NULL)",
            name="ck_score_snapshot_completed_value",
        ),
    )
    op.create_index(
        "ix_score_snapshot_subject_kind",
        "health_score_snapshots",
        ["user_id", "subject_user_id", "score_kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("health_score_snapshots")
    op.drop_table("health_profile_revisions")
    op.drop_table("health_profile_sources")
    op.drop_table("health_profile_candidates")
    op.drop_table("health_profile_facts")
    op.drop_table("confirmed_health_observations")
    op.drop_table("health_report_confirmation_events")
    op.drop_table("health_report_field_candidates")
    op.drop_table("health_report_workflows")

    with op.batch_alter_table("health_documents") as batch_op:
        batch_op.drop_constraint("uq_health_documents_id_user", type_="unique")
