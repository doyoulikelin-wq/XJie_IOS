"""Health document models – medical records & exam reports."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.compat import JSONB


class HealthSummary(Base):
    """AI-generated health summary, one active per user."""

    __tablename__ = "health_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), nullable=False, index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class HealthDocumentSummary(Base):
    """Cached L1/L2 intermediate summaries for hierarchical summarization."""

    __tablename__ = "health_document_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=per-exam-date, 2=per-year
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "2025-01-13" or "2025"
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    abnormal_highlights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_doc_summary_user_level", "user_id", "level"),
        Index("uq_doc_summary_user_level_period", "user_id", "level", "period_key", unique=True),
    )


class WatchedIndicator(Base):
    """User's selected indicators to track over time."""

    __tablename__ = "watched_indicators"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("uq_watched_user_indicator", "user_id", "indicator_name", unique=True),
    )


class SummaryTask(Base):
    """Background task for AI summary generation."""

    __tablename__ = "summary_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending|running|done|failed
    stage: Mapped[str | None] = mapped_column(String(8), nullable=True)  # l1|l2|l3
    stage_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_pct: Mapped[float] = mapped_column(default=0.0)
    token_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class HealthDocument(Base):
    """Uploaded medical record or exam report.

    doc_type:
        - 'record'  → 历史病例
        - 'exam'    → 历史体检报告
    source_type:
        - 'photo'   → 拍照上传 (LLM extracts structured data)
        - 'csv'     → CSV 文件直接上传
        - 'pdf'     → PDF 文件上传
    """

    __tablename__ = "health_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'record' | 'exam'
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'photo' | 'csv' | 'pdf'
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")  # e.g. "北京协和-2026-03-20"
    hospital: Mapped[str | None] = mapped_column(String(256), nullable=True)
    doc_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # path to original photo/file
    csv_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # extracted structured data
    abnormal_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # for exam reports: [{field, value, ref_range, is_abnormal}]
    ai_brief: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ≤10字简要总结
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 整理后的详细内容
    extraction_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | done | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_health_doc_user_type", "user_id", "doc_type"),
        Index("ix_health_doc_user_date", "user_id", "doc_date"),
    )


class PatientHistoryProfile(Base):
    """Structured patient history profile for doctor-facing summaries."""

    __tablename__ = "patient_history_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    doctor_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class IndicatorKnowledge(Base):
    """指标知识库 — 缓存指标的专业解释，优先本地匹配，未命中时 AI 生成后存入。"""

    __tablename__ = "indicator_knowledge"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    alias: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 如 "谷丙转氨酶,ALT,GPT"
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 一句话解释
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")  # 2-3 句详细说明
    normal_range: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clinical_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)  # 偏高/偏低代表什么
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")  # "manual" | "ai"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
