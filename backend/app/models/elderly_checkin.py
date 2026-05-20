"""Elderly care check-in log.

Records periodic prompts asked by the app while the user has
``elderly_mode`` enabled. Each row captures one self-report containing:
    - activity:     ��� the user said they're doing
    - body_feeling: how they physically feel (great/good/ok/uncomfortable/bad)
    - mood:         emotional state (happy/calm/anxious/sad/angry)
    - note:         optional free text

Source distinguishes ``auto_prompt`` (system-triggered) vs ``manual``
(user-initiated). Used to drive history view + intervention decisions.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


BODY_FEELINGS = ("great", "good", "ok", "uncomfortable", "bad")
MOODS = ("happy", "calm", "anxious", "sad", "angry")


class ElderlyCheckin(Base):
    __tablename__ = "elderly_checkin"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    prompt_type: Mapped[str] = mapped_column(String(16), default="combined", nullable=False)
    activity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    body_feeling: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mood: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="auto_prompt", nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_elderly_user_created", "user_id", "created_at"),
    )
