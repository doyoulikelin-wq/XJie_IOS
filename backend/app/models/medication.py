"""Medication regimen model.

Each row represents one drug a user is taking, with name, dosage, instructions,
optional course window, and a JSON list of reminder times like
``["08:00","13:00","20:00"]`` interpreted in the user's local timezone.

Clients (iOS/Android) read this table and schedule local notifications.
The backend may also push remote reminders for redundancy.
"""
from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Medication(Base):
    __tablename__ = "medication"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dosage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_times: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    course_start: Mapped[Date | None] = mapped_column(Date, nullable=True)
    course_end: Mapped[Date | None] = mapped_column(Date, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_medication_user_enabled", "user_id", "enabled"),
    )
