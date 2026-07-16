"""Normalized trust contracts for reports, profile facts, and score deltas.

These tables deliberately sit beside the legacy ``health_documents`` JSON
payload.  A legacy extraction is not a confirmed observation: future write
services must move data through the workflow/candidate/confirmation boundary
before it can be admitted to health trends, the profile, or score inputs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


REPORT_WORKFLOW_STATUSES = (
    "draft",
    "uploading",
    "recognizing",
    "awaiting_confirmation",
    "committing",
    "completed",
    "completed_score_pending",
    "failed",
)
REPORT_TYPES = ("unknown", "exam", "lab", "imaging", "medical_record", "other")
REPORT_CANDIDATE_REVIEW_STATUSES = (
    "pending_review",
    "auto_accepted",
    "confirmed",
    "corrected",
    "rejected",
)
REPORT_CONFIRMATION_EVENT_TYPES = ("confirm", "correct", "reject", "manual_add")
OBSERVATION_STATUSES = ("active", "superseded", "retracted")
PROFILE_CANDIDATE_REVIEW_STATUSES = (
    "pending_review",
    "accepted",
    "rejected",
    "superseded",
    "conflict",
)
PROFILE_FACT_STATUSES = ("active", "superseded", "retracted")
PROFILE_CONFIRMATION_METHODS = ("user", "clinician", "verified_source", "automatic")
PROFILE_SOURCE_TYPES = (
    "report_observation",
    "medication",
    "health_plan",
    "manual",
    "device",
)
PROFILE_REVISION_EVENT_TYPES = ("create", "update", "confirm", "supersede", "retract")
HEALTH_SCORE_KINDS = ("stress", "recovery", "inflammation", "x_age")
# x_age stays schema-compatible for a later versioned score service.  The
# first report-admission service must not consume it.
REPORT_ADMISSION_SCORE_KINDS = frozenset({"stress", "recovery", "inflammation"})
SCORE_CALCULATION_STATUSES = ("pending", "completed", "failed")
SCORE_DIRECTIONS = (
    "higher_is_better",
    "lower_is_better",
    "target_range",
    "informational",
)
SCORE_SEMANTIC_OUTCOMES = ("improved", "worsened", "unchanged", "unknown")


class HealthReportWorkflow(Base):
    """Tenant-bound lifecycle for one uploaded report or legacy document."""

    __tablename__ = "health_report_workflows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["legacy_document_id", "user_id"],
            ["health_documents.id", "health_documents.user_id"],
            name="fk_report_workflow_legacy_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_request_id",
            name="uq_report_workflow_tenant_request",
        ),
        UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            name="uq_report_workflow_tenant_id",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "document_fingerprint",
            name="uq_report_workflow_tenant_fingerprint",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_report_workflow_tenant_confirmation",
        ),
        UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_report_workflow_confirmation_tenant_id",
        ),
        CheckConstraint(
            "status IN ('draft', 'uploading', 'recognizing', "
            "'awaiting_confirmation', 'committing', 'completed', "
            "'completed_score_pending', 'failed')",
            name="ck_report_workflow_status",
        ),
        CheckConstraint(
            "report_type IN ('unknown', 'exam', 'lab', 'imaging', "
            "'medical_record', 'other')",
            name="ck_report_workflow_type",
        ),
        CheckConstraint("version >= 1", name="ck_report_workflow_version"),
        CheckConstraint(
            "length(client_request_id) > 0",
            name="ck_report_workflow_request_nonempty",
        ),
        CheckConstraint(
            "((confirmed_at IS NULL AND confirmation_client_event_id IS NULL "
            "AND confirmed_by_user_id IS NULL) OR "
            "(confirmed_at IS NOT NULL AND confirmation_client_event_id IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL))",
            name="ck_report_workflow_confirmation_complete",
        ),
        CheckConstraint(
            "status NOT IN ('committing', 'completed', 'completed_score_pending') "
            "OR confirmed_at IS NOT NULL",
            name="ck_report_workflow_committed_confirmed",
        ),
        CheckConstraint(
            "confirmed_at IS NULL OR status IN "
            "('committing', 'completed', 'completed_score_pending', 'failed')",
            name="ck_report_workflow_confirmation_state",
        ),
        Index(
            "ix_report_workflow_subject_status",
            "user_id",
            "subject_user_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    legacy_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_request_id: Mapped[str] = mapped_column(String(80), nullable=False)
    document_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unknown", server_default="unknown"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    recognized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_client_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="RESTRICT"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthReportFieldCandidate(Base):
    """One raw and normalized OCR candidate awaiting admission review."""

    __tablename__ = "health_report_field_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_report_candidate_workflow_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workflow_id",
            "user_id",
            "subject_user_id",
            "candidate_key",
            name="uq_report_candidate_workflow_key",
        ),
        UniqueConstraint(
            "id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_candidate_tenant_id",
        ),
        CheckConstraint(
            "review_status IN ('pending_review', 'auto_accepted', 'confirmed', "
            "'corrected', 'rejected')",
            name="ck_report_candidate_review_status",
        ),
        CheckConstraint(
            "abnormal_state IN ('normal', 'abnormal', 'unknown')",
            name="ck_report_candidate_abnormal_state",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_report_candidate_confidence",
        ),
        CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR "
            "reference_low <= reference_high",
            name="ck_report_candidate_reference_range",
        ),
        CheckConstraint("version >= 1", name="ck_report_candidate_version"),
        CheckConstraint(
            "review_status <> 'auto_accepted' OR "
            "(requires_review = false AND abnormal_state = 'normal')",
            name="ck_report_candidate_auto_accept_safe",
        ),
        Index(
            "ix_report_candidate_review_queue",
            "user_id",
            "subject_user_id",
            "workflow_id",
            "review_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(160), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(160), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    reference_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    reference_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    abnormal_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_locator: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_review", server_default="pending_review"
    )
    requires_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=sa_text("true")
    )
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthReportConfirmationEvent(Base):
    """Immutable user-visible review event for a report candidate."""

    __tablename__ = "health_report_confirmation_events"
    __table_args__ = (
        ForeignKeyConstraint(
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
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_report_event_tenant_client",
        ),
        UniqueConstraint(
            "id",
            "candidate_id",
            "workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_report_event_tenant_id",
        ),
        CheckConstraint(
            "event_type IN ('confirm', 'correct', 'reject', 'manual_add')",
            name="ck_report_confirmation_event_type",
        ),
        CheckConstraint("candidate_version >= 1", name="ck_report_event_candidate_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    after_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfirmedHealthObservation(Base):
    """A normalized value admitted only after a recorded confirmation event."""

    __tablename__ = "confirmed_health_observations"
    __table_args__ = (
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_observation_tenant_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "source_candidate_id",
            name="uq_observation_tenant_candidate",
        ),
        UniqueConstraint(
            "id",
            "user_id",
            "subject_user_id",
            name="uq_observation_tenant_id",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_observation_status",
        ),
        CheckConstraint(
            "abnormal_state IN ('normal', 'abnormal', 'unknown')",
            name="ck_observation_abnormal_state",
        ),
        CheckConstraint(
            "((value_numeric IS NOT NULL AND value_text IS NULL) OR "
            "(value_numeric IS NULL AND value_text IS NOT NULL))",
            name="ck_observation_has_value",
        ),
        CheckConstraint(
            "reference_low IS NULL OR reference_high IS NULL OR "
            "reference_low <= reference_high",
            name="ck_observation_reference_range",
        ),
        CheckConstraint("version >= 1", name="ck_observation_version"),
        Index(
            "ix_observation_subject_code_time",
            "user_id",
            "subject_user_id",
            "canonical_code",
            "effective_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmation_event_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    report_confirmation_client_event_id: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    canonical_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    reference_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    reference_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    abnormal_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileFact(Base):
    """Current normalized profile fact; history lives in revision records."""

    __tablename__ = "health_profile_facts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "subject_user_id", "fact_key", name="uq_profile_fact_tenant_key"
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_profile_fact_tenant_id"
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'retracted')",
            name="ck_profile_fact_status",
        ),
        CheckConstraint(
            "confirmation_method IN ('user', 'clinician', 'verified_source', 'automatic')",
            name="ck_profile_fact_confirmation_method",
        ),
        CheckConstraint(
            "is_safety_critical = false OR "
            "(confirmation_method IN ('user', 'clinician') "
            "AND confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL)",
            name="ck_profile_fact_safety_explicit",
        ),
        CheckConstraint("version >= 1", name="ck_profile_fact_version"),
        Index(
            "ix_profile_fact_subject_category",
            "user_id",
            "subject_user_id",
            "category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    value_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    is_safety_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )
    confirmation_method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="RESTRICT"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthProfileCandidate(Base):
    """Proposed profile fact that cannot silently replace a current fact."""

    __tablename__ = "health_profile_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conflict_with_fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_candidate_conflict_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_profile_candidate_tenant_idempotency",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_profile_candidate_tenant_id"
        ),
        CheckConstraint(
            "review_status IN ('pending_review', 'accepted', 'rejected', "
            "'superseded', 'conflict')",
            name="ck_profile_candidate_review_status",
        ),
        CheckConstraint(
            "((review_status = 'conflict' AND conflict_with_fact_id IS NOT NULL) OR "
            "(review_status <> 'conflict' AND conflict_with_fact_id IS NULL))",
            name="ck_profile_candidate_conflict_explicit",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_profile_candidate_confidence",
        ),
        CheckConstraint("version >= 1", name="ck_profile_candidate_version"),
        Index(
            "ix_profile_candidate_review_queue",
            "user_id",
            "subject_user_id",
            "review_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    proposed_value: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    is_safety_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_review", server_default="pending_review"
    )
    conflict_with_fact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class HealthProfileSource(Base):
    """Provenance edge from a profile candidate or fact to its source."""

    __tablename__ = "health_profile_sources"
    __table_args__ = (
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_profile_source_tenant_id"
        ),
        ForeignKeyConstraint(
            ["fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_source_fact_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "user_id", "subject_user_id"],
            [
                "health_profile_candidates.id",
                "health_profile_candidates.user_id",
                "health_profile_candidates.subject_user_id",
            ],
            name="fk_profile_source_candidate_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_observation_id", "user_id", "subject_user_id"],
            [
                "confirmed_health_observations.id",
                "confirmed_health_observations.user_id",
                "confirmed_health_observations.subject_user_id",
            ],
            name="fk_profile_source_observation_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_profile_source_tenant_idempotency",
        ),
        CheckConstraint(
            "((fact_id IS NOT NULL AND candidate_id IS NULL) OR "
            "(fact_id IS NULL AND candidate_id IS NOT NULL))",
            name="ck_profile_source_one_target",
        ),
        CheckConstraint(
            "source_type IN ('report_observation', 'medication', 'health_plan', "
            "'manual', 'device')",
            name="ck_profile_source_type",
        ),
        CheckConstraint(
            "source_type <> 'report_observation' OR source_observation_id IS NOT NULL",
            name="ck_profile_source_report_observation",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_profile_source_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    source_observation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthProfileRevision(Base):
    """Immutable audit revision for profile candidate/fact changes."""

    __tablename__ = "health_profile_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["fact_id", "user_id", "subject_user_id"],
            [
                "health_profile_facts.id",
                "health_profile_facts.user_id",
                "health_profile_facts.subject_user_id",
            ],
            name="fk_profile_revision_fact_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_id", "user_id", "subject_user_id"],
            [
                "health_profile_candidates.id",
                "health_profile_candidates.user_id",
                "health_profile_candidates.subject_user_id",
            ],
            name="fk_profile_revision_candidate_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_profile_revision_tenant_client",
        ),
        CheckConstraint(
            "((fact_id IS NOT NULL AND candidate_id IS NULL) OR "
            "(fact_id IS NULL AND candidate_id IS NOT NULL))",
            name="ck_profile_revision_has_target",
        ),
        CheckConstraint(
            "event_type IN ('create', 'update', 'confirm', 'supersede', 'retract')",
            name="ck_profile_revision_event_type",
        ),
        CheckConstraint("target_version >= 1", name="ck_profile_revision_target_version"),
        Index(
            "ix_profile_revision_fact_history",
            "user_id",
            "subject_user_id",
            "fact_id",
            "target_version",
            "id",
        ),
        Index(
            "ix_profile_revision_candidate_history",
            "user_id",
            "subject_user_id",
            "candidate_id",
            "target_version",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    after_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HealthScoreSnapshot(Base):
    """Versioned before/after score delta caused by one report admission."""

    __tablename__ = "health_score_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "source_report_workflow_id",
            "user_id",
            "subject_user_id",
            name="uq_score_snapshot_workflow_tenant_id",
        ),
        ForeignKeyConstraint(
            ["source_report_workflow_id", "user_id", "subject_user_id"],
            [
                "health_report_workflows.id",
                "health_report_workflows.user_id",
                "health_report_workflows.subject_user_id",
            ],
            name="fk_score_snapshot_report_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "idempotency_key",
            name="uq_score_snapshot_tenant_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "source_report_workflow_id",
            "score_kind",
            "algorithm_version",
            name="uq_score_snapshot_report_kind_version",
        ),
        CheckConstraint(
            "score_kind IN ('stress', 'recovery', 'inflammation', 'x_age')",
            name="ck_score_snapshot_kind",
        ),
        CheckConstraint(
            "calculation_status IN ('pending', 'completed', 'failed')",
            name="ck_score_snapshot_status",
        ),
        CheckConstraint(
            "score_direction IS NULL OR score_direction IN "
            "('higher_is_better', 'lower_is_better', 'target_range', 'informational')",
            name="ck_score_snapshot_direction",
        ),
        CheckConstraint(
            "semantic_outcome IS NULL OR semantic_outcome IN "
            "('improved', 'worsened', 'unchanged', 'unknown')",
            name="ck_score_snapshot_outcome",
        ),
        CheckConstraint(
            "before_confidence IS NULL OR "
            "(before_confidence >= 0 AND before_confidence <= 1)",
            name="ck_score_snapshot_before_confidence",
        ),
        CheckConstraint(
            "after_confidence IS NULL OR "
            "(after_confidence >= 0 AND after_confidence <= 1)",
            name="ck_score_snapshot_after_confidence",
        ),
        CheckConstraint(
            "score_kind = 'x_age' OR before_value IS NULL OR "
            "(before_value >= 0 AND before_value <= 100)",
            name="ck_score_snapshot_before_range",
        ),
        CheckConstraint(
            "score_kind = 'x_age' OR after_value IS NULL OR "
            "(after_value >= 0 AND after_value <= 100)",
            name="ck_score_snapshot_after_range",
        ),
        CheckConstraint(
            "calculation_status <> 'completed' OR "
            "(after_value IS NOT NULL AND score_direction IS NOT NULL "
            "AND semantic_outcome IS NOT NULL)",
            name="ck_score_snapshot_completed_value",
        ),
        Index(
            "ix_score_snapshot_subject_kind",
            "user_id",
            "subject_user_id",
            "score_kind",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_report_workflow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    score_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    algorithm_id: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    before_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    after_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    before_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    after_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    score_direction: Mapped[str | None] = mapped_column(String(24), nullable=True)
    semantic_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    calculation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    missing_inputs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
