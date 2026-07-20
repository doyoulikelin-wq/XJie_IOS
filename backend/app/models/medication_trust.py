"""Server-authoritative, user-confirmed medication loop.

The legacy :mod:`app.models.medication` table remains a compatibility list for
older clients.  Nothing in this module treats a legacy row, an OCR extraction,
an elapsed reminder, or a client notification setting as a confirmed health
fact.  Trusted plans and events are always tenant-bound and explicitly
confirmed by the authenticated user.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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


MEDICATION_PLAN_STATUSES = ("active", "paused", "completed", "retracted")
MEDICATION_SOURCE_TYPES = ("manual", "prescription_import", "ocr", "history")
MEDICATION_MEAL_RELATIONS = ("unspecified", "before_meal", "after_meal", "with_meal")
MEDICATION_PREFILL_STATUSES = ("pending_review", "accepted", "rejected")
MEDICATION_PLAN_EVENT_TYPES = ("confirm", "revise", "pause", "resume", "complete", "retract")
MEDICATION_DOSE_ACTIONS = ("taken", "snooze", "skip", "correct")
MEDICATION_DOSE_EFFECTIVE_STATUSES = ("taken", "snoozed", "skipped", "pending")
MEDICATION_REACTION_EVENT_TYPES = ("create", "correct", "retract")
MEDICATION_REACTION_STATUSES = ("active", "retracted")
MEDICATION_REACTION_SEVERITIES = ("mild", "moderate", "severe")


class TrustedMedicationPlan(Base):
    """One explicitly user-confirmed medication regimen."""

    __tablename__ = "trusted_medication_plans"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_request_id",
            name="uq_trusted_med_plan_tenant_request",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_trusted_med_plan_tenant_id"
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'retracted')",
            name="ck_trusted_med_plan_status",
        ),
        CheckConstraint(
            "source_type IN ('manual', 'prescription_import', 'ocr', 'history')",
            name="ck_trusted_med_plan_source_type",
        ),
        CheckConstraint(
            "meal_relation IN ('unspecified', 'before_meal', 'after_meal', 'with_meal')",
            name="ck_trusted_med_plan_meal_relation",
        ),
        CheckConstraint("version >= 1", name="ck_trusted_med_plan_version"),
        CheckConstraint(
            "course_start IS NULL OR course_end IS NULL OR course_start <= course_end",
            name="ck_trusted_med_plan_course_window",
        ),
        CheckConstraint(
            "dose_quantity IS NULL OR dose_quantity > 0",
            name="ck_trusted_med_plan_dose_quantity",
        ),
        CheckConstraint(
            "initial_quantity IS NULL OR initial_quantity >= 0",
            name="ck_trusted_med_plan_initial_quantity",
        ),
        CheckConstraint(
            "((initial_quantity IS NULL AND inventory_unit IS NULL) OR "
            "(initial_quantity IS NOT NULL AND inventory_unit IS NOT NULL))",
            name="ck_trusted_med_plan_inventory_pair",
        ),
        CheckConstraint(
            "confirmed_at IS NOT NULL AND confirmed_by_user_id IS NOT NULL",
            name="ck_trusted_med_plan_user_confirmed",
        ),
        Index(
            "ix_trusted_med_plan_subject_status",
            "user_id",
            "subject_user_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(80), nullable=False)
    generic_name: Mapped[str] = mapped_column(String(160), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    strength: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dose_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dose_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_times: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sa_text("'[]'")
    )
    meal_relation: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unspecified", server_default="unspecified"
    )
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    course_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    course_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    prescriber: Mapped[str | None] = mapped_column(String(160), nullable=True)
    initial_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    inventory_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_long_term: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa_text("false")
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    confirmed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # Migration 0024 adds this nullable column to the 0023 table.  Keep the ORM
    # declaration at the physical append position so the candidate manifest
    # remains byte-for-byte comparable with a real PostgreSQL upgrade.
    purpose: Mapped[str | None] = mapped_column(String(256), nullable=True)


class MedicationPrefillCandidate(Base):
    """OCR/import output that is never a medication plan by itself."""

    __tablename__ = "medication_prefill_candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["accepted_plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_prefill_accepted_plan_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_prefill_tenant_event",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "review_client_event_id",
            name="uq_med_prefill_tenant_review_event",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_med_prefill_tenant_id"
        ),
        CheckConstraint(
            "source_type IN ('ocr', 'prescription_import', 'history')",
            name="ck_med_prefill_source_type",
        ),
        CheckConstraint(
            "review_status IN ('pending_review', 'accepted', 'rejected')",
            name="ck_med_prefill_review_status",
        ),
        CheckConstraint("version >= 1", name="ck_med_prefill_version"),
        CheckConstraint(
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
        Index(
            "ix_med_prefill_subject_status",
            "user_id",
            "subject_user_id",
            "review_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ocr", server_default="ocr"
    )
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    extracted_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    field_confidences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=sa_text("'{}'")
    )
    review_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_review", server_default="pending_review"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_client_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accepted_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MedicationPlanEvent(Base):
    """Immutable audit event for every confirmed plan mutation."""

    __tablename__ = "medication_plan_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_plan_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_plan_event_tenant_client",
        ),
        CheckConstraint(
            "event_type IN ('confirm', 'revise', 'pause', 'resume', 'complete', 'retract')",
            name="ck_med_plan_event_type",
        ),
        CheckConstraint("target_version >= 1", name="ck_med_plan_event_target_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
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


class MedicationDoseEvent(Base):
    """Append-only user action for one scheduled dose occurrence."""

    __tablename__ = "medication_dose_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_dose_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
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
        UniqueConstraint(
            "id",
            "plan_id",
            "user_id",
            "subject_user_id",
            name="uq_med_dose_event_tenant_id",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_dose_event_tenant_client",
        ),
        UniqueConstraint(
            "plan_id",
            "user_id",
            "subject_user_id",
            "occurrence_key",
            "occurrence_version",
            name="uq_med_dose_event_occurrence_version",
        ),
        CheckConstraint(
            "action IN ('taken', 'snooze', 'skip', 'correct')",
            name="ck_med_dose_event_action",
        ),
        CheckConstraint(
            "effective_status IN ('taken', 'snoozed', 'skipped', 'pending')",
            name="ck_med_dose_event_effective_status",
        ),
        CheckConstraint("occurrence_version >= 1", name="ck_med_dose_event_version"),
        CheckConstraint(
            "(action = 'correct' AND supersedes_event_id IS NOT NULL) OR "
            "(action <> 'correct' AND supersedes_event_id IS NULL)",
            name="ck_med_dose_event_correction_target",
        ),
        CheckConstraint(
            "(effective_status = 'snoozed' AND snoozed_until IS NOT NULL) OR "
            "(effective_status <> 'snoozed' AND snoozed_until IS NULL)",
            name="ck_med_dose_event_snooze_time",
        ),
        CheckConstraint(
            "(effective_status = 'taken' AND "
            "(taken_quantity IS NULL OR taken_quantity > 0)) OR "
            "(effective_status <> 'taken' AND taken_quantity IS NULL)",
            name="ck_med_dose_event_taken_quantity",
        ),
        CheckConstraint(
            "(action = 'taken' AND effective_status = 'taken') OR "
            "(action = 'snooze' AND effective_status = 'snoozed') OR "
            "(action = 'skip' AND effective_status = 'skipped') OR action = 'correct'",
            name="ck_med_dose_event_action_result",
        ),
        Index(
            "ix_med_dose_event_occurrence",
            "user_id",
            "subject_user_id",
            "scheduled_local_date",
            "occurrence_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scheduled_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[str] = mapped_column(String(5), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurrence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    taken_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="user_confirmed", server_default="user_confirmed"
    )
    confirmed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MedicationAdverseReactionEvent(Base):
    """Append-only, correctable temporal association reported by the user."""

    __tablename__ = "medication_adverse_reaction_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "user_id", "subject_user_id"],
            [
                "trusted_medication_plans.id",
                "trusted_medication_plans.user_id",
                "trusted_medication_plans.subject_user_id",
            ],
            name="fk_med_reaction_event_plan_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "client_event_id",
            name="uq_med_reaction_event_tenant_client",
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "reaction_key",
            "reaction_version",
            name="uq_med_reaction_event_version",
        ),
        CheckConstraint(
            "event_type IN ('create', 'correct', 'retract')",
            name="ck_med_reaction_event_type",
        ),
        CheckConstraint(
            "status IN ('active', 'retracted')", name="ck_med_reaction_event_status"
        ),
        CheckConstraint(
            "severity IN ('mild', 'moderate', 'severe')",
            name="ck_med_reaction_event_severity",
        ),
        CheckConstraint("reaction_version >= 1", name="ck_med_reaction_event_version"),
        CheckConstraint(
            "causal_attribution = 'temporal_association_only'",
            name="ck_med_reaction_temporal_only",
        ),
        CheckConstraint(
            "(event_type = 'retract' AND status = 'retracted') OR "
            "(event_type <> 'retract' AND status = 'active')",
            name="ck_med_reaction_event_status_match",
        ),
        Index(
            "ix_med_reaction_subject_onset",
            "user_id",
            "subject_user_id",
            "onset_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reaction_key: Mapped[str] = mapped_column(String(80), nullable=False)
    reaction_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    onset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_occurrence_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    causal_attribution: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="temporal_association_only",
        server_default="temporal_association_only",
    )
    confirmed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
