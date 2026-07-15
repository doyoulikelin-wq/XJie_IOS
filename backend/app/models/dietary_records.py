"""Trusted, explicitly confirmed dietary-record models.

Legacy ``Meal`` rows remain untouched for older clients.  These tables form a
separate trust boundary: recognition output is a draft and only a user-confirm
event can create a formal dietary record.
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
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


DIETARY_SOURCE_TYPES = (
    "camera",
    "photo_library",
    "text",
    "voice",
    "recent",
    "chat",
    "manual",
)
DIETARY_MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
DIETARY_DRAFT_STATUSES = ("pending_confirmation", "confirmed", "rejected")
DIETARY_RECORD_STATUSES = ("user_confirmed", "modified", "deleted")
DIETARY_DAY_STATES = (
    "open",
    "waiting_confirmation",
    "incomplete",
    "ready",
    "stale",
    "recalculating",
    "failed",
)


class DietaryDraft(Base):
    __tablename__ = "dietary_drafts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "event_scope",
            "client_event_id",
            name="uq_dietary_draft_tenant_scope_event",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_draft_tenant_id"
        ),
        CheckConstraint(
            "source_type IN ('camera', 'photo_library', 'text', 'voice', 'recent', 'chat', 'manual')",
            name="ck_dietary_draft_source_type",
        ),
        CheckConstraint(
            "event_scope IN ('create', 'photo', 'reuse')",
            name="ck_dietary_draft_event_scope",
        ),
        CheckConstraint(
            "meal_type IS NULL OR meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_dietary_draft_meal_type",
        ),
        CheckConstraint(
            "status IN ('pending_confirmation', 'confirmed', 'rejected')",
            name="ck_dietary_draft_status",
        ),
        CheckConstraint("version >= 1", name="ck_dietary_draft_version"),
        CheckConstraint(
            "recognition_confidence IS NULL OR (recognition_confidence >= 0 AND recognition_confidence <= 1)",
            name="ck_dietary_draft_confidence",
        ),
        Index(
            "ix_dietary_draft_subject_date_status",
            "user_id",
            "subject_user_id",
            "diet_date",
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
    event_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="create"
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    image_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recognition_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recognition_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="not_required",
        server_default="not_required",
    )
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    diet_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    food_items: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'"), nullable=False
    )
    portion_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    structure: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    estimated_nutrition: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    field_confidences: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    recognition_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending_confirmation",
        server_default="pending_confirmation",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DietaryRecord(Base):
    __tablename__ = "dietary_records"
    __table_args__ = (
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_record_tenant_id"
        ),
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "confirmation_client_event_id",
            name="uq_dietary_record_tenant_confirm_event",
        ),
        UniqueConstraint(
            "source_draft_id",
            "user_id",
            "subject_user_id",
            name="uq_dietary_record_tenant_draft",
        ),
        ForeignKeyConstraint(
            ["source_draft_id", "user_id", "subject_user_id"],
            [
                "dietary_drafts.id",
                "dietary_drafts.user_id",
                "dietary_drafts.subject_user_id",
            ],
            name="fk_dietary_record_draft_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_dietary_record_meal_type",
        ),
        CheckConstraint(
            "source_type IN ('camera', 'photo_library', 'text', 'voice', 'recent', 'chat', 'manual')",
            name="ck_dietary_record_source_type",
        ),
        CheckConstraint(
            "status IN ('user_confirmed', 'modified', 'deleted')",
            name="ck_dietary_record_status",
        ),
        CheckConstraint(
            "confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL",
            name="ck_dietary_record_user_confirmed",
        ),
        CheckConstraint("version >= 1", name="ck_dietary_record_version"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_dietary_record_confidence",
        ),
        Index(
            "ix_dietary_record_subject_date_meal",
            "user_id",
            "subject_user_id",
            "diet_date",
            "meal_type",
            "eaten_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_draft_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    confirmation_client_event_id: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    confirmation_request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    diet_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    eaten_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    food_items: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'"), nullable=False
    )
    portion_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    structure: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    estimated_nutrition: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    field_confidences: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="user_confirmed",
        server_default="user_confirmed",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    confirmed_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DietaryRecordEvent(Base):
    __tablename__ = "dietary_record_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "event_type",
            "client_event_id",
            name="uq_dietary_record_event_tenant_type_event",
        ),
        ForeignKeyConstraint(
            ["record_id", "user_id", "subject_user_id"],
            [
                "dietary_records.id",
                "dietary_records.user_id",
                "dietary_records.subject_user_id",
            ],
            name="fk_dietary_record_event_record_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "event_type IN ('confirm', 'update', 'delete', 'reuse')",
            name="ck_dietary_record_event_type",
        ),
        CheckConstraint("target_version >= 1", name="ck_dietary_record_event_version"),
        Index(
            "ix_dietary_record_event_history",
            "user_id",
            "subject_user_id",
            "record_id",
            "target_version",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    client_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    before_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    after_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DietaryDay(Base):
    __tablename__ = "dietary_days"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "diet_date",
            name="uq_dietary_day_tenant_date",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_day_tenant_id"
        ),
        CheckConstraint(
            "state IN ('open', 'waiting_confirmation', 'incomplete', 'ready', 'stale', 'recalculating', 'failed')",
            name="ck_dietary_day_state",
        ),
        CheckConstraint(
            "close_method IS NULL OR close_method IN ('automatic', 'manual')",
            name="ck_dietary_day_close_method",
        ),
        CheckConstraint("record_version >= 0", name="ck_dietary_day_record_version"),
        CheckConstraint(
            "confirmed_meal_count >= 0", name="ck_dietary_day_confirmed_count"
        ),
        CheckConstraint("pending_count >= 0", name="ck_dietary_day_pending_count"),
        Index(
            "ix_dietary_day_subject_state_date",
            "user_id",
            "subject_user_id",
            "state",
            "diet_date",
        ),
        Index(
            "ix_dietary_day_open_due",
            "closed_at",
            "auto_close_due_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    diet_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    auto_close_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="open", server_default="open"
    )
    record_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    close_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    close_client_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    close_request_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    exclude_pending_on_close: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    record_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    confirmed_meal_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pending_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    structure_summary: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DietaryDailySummary(Base):
    __tablename__ = "dietary_daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "diet_date",
            "record_version",
            name="uq_dietary_summary_tenant_date_version",
        ),
        UniqueConstraint(
            "id", "user_id", "subject_user_id", name="uq_dietary_summary_tenant_id"
        ),
        ForeignKeyConstraint(
            ["day_id", "user_id", "subject_user_id"],
            ["dietary_days.id", "dietary_days.user_id", "dietary_days.subject_user_id"],
            name="fk_dietary_summary_day_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "record_version >= 1", name="ck_dietary_summary_record_version"
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_dietary_summary_confidence",
        ),
        Index(
            "ix_dietary_summary_subject_date_version",
            "user_id",
            "subject_user_id",
            "diet_date",
            "record_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    diet_date: Mapped[date] = mapped_column(Date, nullable=False)
    record_version: Mapped[int] = mapped_column(Integer, nullable=False)
    close_method: Mapped[str] = mapped_column(String(16), nullable=False)
    record_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmed_meal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False)
    structure_summary: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    today_suggestion: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    evidence: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    template_version: Mapped[str] = mapped_column(String(80), nullable=False)
    recalculated_after_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class DietaryRecognitionCache(Base):
    __tablename__ = "dietary_recognition_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_user_id",
            "image_fingerprint",
            "recognition_version",
            name="uq_dietary_recognition_tenant_fingerprint_version",
        ),
        CheckConstraint(
            "length(image_fingerprint) = 64",
            name="ck_dietary_recognition_fingerprint",
        ),
        Index(
            "ix_dietary_recognition_subject_fingerprint",
            "user_id",
            "subject_user_id",
            "image_fingerprint",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    image_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    recognition_version: Mapped[str] = mapped_column(String(80), nullable=False)
    result_snapshot: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
