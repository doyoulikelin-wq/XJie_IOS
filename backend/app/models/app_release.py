"""Mobile app release configuration for in-app update prompts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppRelease(Base):
    """Latest release metadata by mobile platform."""

    __tablename__ = "app_releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    latest_version: Mapped[str] = mapped_column(String(32), nullable=False)
    latest_build: Mapped[int] = mapped_column(Integer, nullable=False)
    min_supported_build: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    force_update: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="发现新版本")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    download_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    store_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
