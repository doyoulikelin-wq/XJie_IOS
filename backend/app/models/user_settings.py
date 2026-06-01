
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


from app.db.base import Base
from app.db.compat import JSONB


class UserSettings(Base):
    """User-facing preferences for the Agentic service.

    One row per user.  Created lazily on first access.
    """

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), unique=True, index=True, nullable=False
    )

    # Intervention level: L1 (温和) / L2 (标准) / L3 (积极)
    intervention_level: Mapped[str] = mapped_column(String(4), default="L2", nullable=False)

    # Daily reminder cap override (must be <= level max)
    daily_reminder_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Allow consecutive-anomaly auto-escalation suggestion
    allow_auto_escalation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Display unit for glucose values: "mg_dl" (default) or "mmol_l".
    # 1 mmol/L = 18.018 mg/dL.
    glucose_unit: Mapped[str] = mapped_column(String(8), default="mg_dl", nullable=False)

    # 老年人关怀模式：启用后双端切换大字/大按钮 UI，
    # 同时启用主动关怀询问（在干什么 / 身体感觉 / 心情）。
    elderly_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 主动关怀询问频率（分钟），默认 180min = 3h 一次
    elderly_checkin_interval_min: Mapped[int] = mapped_column(Integer, default=180, nullable=False)

    # 注册末步采集的健康管理需求，用于首个计划生成和后续个性化推荐。
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onboarding_target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    onboarding_contents: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    onboarding_generate_plan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
