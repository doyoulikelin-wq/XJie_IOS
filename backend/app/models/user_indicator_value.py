"""UserIndicatorValue — 用户手动录入的指标数值（独立于体检报告 OCR）。"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserIndicatorValue(Base):
    __tablename__ = "user_indicator_values"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_user_indicator_value_id_user"),
        Index(
            "uq_user_indicator_source_sample",
            "user_id",
            "source",
            "source_id",
            unique=True,
            postgresql_where=sa_text("source_id IS NOT NULL"),
            sqlite_where=sa_text("source_id IS NOT NULL"),
        ),
        Index(
            "ix_user_indicator_source_metric_time",
            "user_id",
            "source",
            "source_metric",
            "measured_at",
        ),
        Index(
            "ix_user_indicator_source_local_date",
            "user_id",
            "source",
            "source_metric",
            "source_local_date",
        ),
        CheckConstraint(
            "value_kind IN ('numeric', 'category')",
            name="ck_user_indicator_value_kind",
        ),
        CheckConstraint(
            "timezone_offset_minutes IS NULL OR "
            "timezone_offset_minutes BETWEEN -840 AND 840",
            name="ck_user_indicator_timezone_offset",
        ),
    )

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
    """manual / apple_health / cgm / device"""
    source_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """设备侧指标标识，例如 HealthKit quantity type 的稳定映射。"""
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """设备侧样本标识；非空时在同一用户和来源内唯一。"""
    value_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="numeric", server_default="numeric"
    )
    """numeric / category；category 的 value 保存原始编码。"""
    display_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """类别值的用户可读标签；numeric 可为空。"""
    source_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    """来源设备明确给出的本地日，用于跨时区日界线。"""
    timezone_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
