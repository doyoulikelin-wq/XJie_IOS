"""Health plan and execution task models."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


class HealthPlan(Base):
    """A structured plan saved from AI chat or created manually."""

    __tablename__ = "health_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(24), default="ai", nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlanTask(Base):
    """A dated execution task used by the plan detail and tube weekly view."""

    __tablename__ = "plan_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("health_plans.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    target_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reminder_time: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="plan", nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


Index("ix_plan_tasks_user_date_type", PlanTask.user_id, PlanTask.date, PlanTask.task_type)
Index("ix_plan_tasks_source", PlanTask.user_id, PlanTask.source_type, PlanTask.source_ref)
