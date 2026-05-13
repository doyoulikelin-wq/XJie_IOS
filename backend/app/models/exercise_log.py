"""ExerciseLog — 用户锻炼记录（首页今日膳食下方模块）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExerciseLog(Base):
    __tablename__ = "exercise_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    """运动类型: walking / running / cycling / swimming / yoga / strength / other"""
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    intensity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    """low / medium / high"""
    calories_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
