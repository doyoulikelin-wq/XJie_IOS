"""PasswordResetCode — 密码重置/手机号验证码（开发模式直接日志输出，生产对接 SMS）。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PasswordResetCode(Base):
    __tablename__ = "password_reset_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    """6 位数字验证码"""
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """0=未使用 1=已使用"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
