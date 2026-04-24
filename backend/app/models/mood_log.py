"""Mood emoji check-in model.

Each user can check in their mood at 5 fixed time segments per day:
morning / noon / afternoon / evening / night (encoded 1..5).

Mood level uses the same 1..5 scale as the C4 emoji palette in the
innovation roadmap report:
    1 = 😡 angry
    2 = 😢 sad
    3 = 😟 anxious
    4 = 😐 neutral
    5 = 😀 happy

A unique constraint (user_id, ts_date, segment) makes idempotent upserts
trivial: re-checking the same segment overwrites the previous value.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


SEGMENTS = ("morning", "noon", "afternoon", "evening", "night")


class MoodLog(Base):
    __tablename__ = "mood_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    ts_date: Mapped[Date] = mapped_column(Date, nullable=False, index=True)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    mood_level: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "ts_date", "segment", name="uq_mood_user_date_segment"),
        Index("ix_mood_user_ts", "user_id", "ts"),
    )
