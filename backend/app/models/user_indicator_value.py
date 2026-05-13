"""UserIndicatorValue — 用户手动录入的指标数值（独立于体检报告 OCR）。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserIndicatorValue(Base):
    __tablename__ = "user_indicator_values"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), nullable=False, index=True
    )
    indicator_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    """优先使用 IndicatorKnowledge.name，自由文本也允许。"""
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    """manual / cgm / device"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
