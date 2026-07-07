"""Omics data models — metabolomics uploads and analysis results."""

from __future__ import annotations

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.compat import JSONB
from app.db.base import Base


class OmicsUpload(Base):
    """A user's uploaded omics data file."""

    __tablename__ = "omics_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), index=True, nullable=False)
    omics_type: Mapped[str] = mapped_column(String(30), nullable=False)  # "metabolomics" / "proteomics" / "genomics"
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # extracted text sent to LLM
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OmicsModelTask(Base):
    """Placeholder for external analysis model tasks."""

    __tablename__ = "omics_model_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), index=True, nullable=False)
    upload_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("omics_uploads.id", ondelete="CASCADE"), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/running/completed/failed
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
