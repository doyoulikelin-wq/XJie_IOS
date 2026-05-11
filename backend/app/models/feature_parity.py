"""Feature parity tracking between iOS and Android clients."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


PLATFORM_STATUS_VALUES = ("not_started", "in_progress", "shipped", "deprecated")
PRIORITY_VALUES = ("P0", "P1", "P2", "P3")


class FeatureParity(Base):
    """A single feature tracked across iOS and Android."""

    __tablename__ = "feature_parity"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    priority: Mapped[str] = mapped_column(String(4), nullable=False, default="P1", index=True)
    ios_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    android_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    ios_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    android_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backend_apis: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
