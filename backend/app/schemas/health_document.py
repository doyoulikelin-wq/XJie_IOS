"""Schemas for health documents (medical records & exam reports)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


# ── Health Summary ──

class HealthSummaryOut(BaseModel):
    summary_text: str
    updated_at: datetime | None = None


# ── Health Document ──

class HealthDocumentOut(BaseModel):
    id: str
    doc_type: str
    source_type: str
    name: str
    hospital: str | None = None
    doc_date: str | None = None
    csv_data: dict | None = None
    abnormal_flags: list | None = None
    ai_brief: str | None = None
    ai_summary: str | None = None
    extraction_status: str
    created_at: datetime
    file_url: str | None = None
    # OCR completion is deliberately separate from trusted report admission.
    # These optional fields keep the legacy upload/document response compatible
    # while giving new clients an explicit workflow to poll and review.
    report_workflow_id: int | None = None
    report_workflow_status: str | None = None
    report_subject_user_id: int | None = None
    report_duplicate: bool = False


class HealthDocumentCreate(BaseModel):
    """Manual creation (for non-photo uploads where user provides name)."""
    doc_type: str = Field(pattern=r"^(record|exam)$")
    name: str = Field(min_length=1, max_length=256)
    hospital: str | None = None
    doc_date: str | None = None  # ISO date string


class UploadPhotoRequest(BaseModel):
    doc_type: str = Field(pattern=r"^(record|exam)$")


class HealthDocumentListOut(BaseModel):
    items: list[HealthDocumentOut]
    total: int


# ── Indicator Trend ──

class IndicatorInfo(BaseModel):
    name: str
    category: str | None = None
    count: int  # how many data points across all exams


class IndicatorListOut(BaseModel):
    indicators: list[IndicatorInfo]


class TrendPoint(BaseModel):
    date: str
    value: float
    abnormal: bool = False
    source: str | None = None
    measured_at: str | None = None
    source_metric: str | None = None
    source_id: str | None = None
    value_kind: str = "numeric"
    display_value: str | None = None
    source_local_date: date | None = None
    timezone_offset_minutes: int | None = None


class IndicatorTrend(BaseModel):
    name: str
    unit: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    points: list[TrendPoint]


class IndicatorTrendOut(BaseModel):
    indicators: list[IndicatorTrend]


class WatchedIndicatorOut(BaseModel):
    indicator_name: str
    category: str | None = None
    display_order: int = 0


class WatchedListOut(BaseModel):
    items: list[WatchedIndicatorOut]


class WatchedIndicatorIn(BaseModel):
    indicator_name: str
    category: str | None = None


# ── Summary generation progress ──

class SummaryProgressEvent(BaseModel):
    type: str  # "progress" | "token" | "done"
    stage: str | None = None  # "l1" | "l2" | "l3"
    current: int | None = None
    total: int | None = None


# ── Background task ──

class SummaryTaskOut(BaseModel):
    task_id: str
    status: str  # pending | running | done | failed
    stage: str | None = None
    stage_current: int = 0
    stage_total: int = 0
    progress_pct: float = 0.0
    token_used: int = 0
    error_message: str | None = None


# ── Patient history ──

class PatientHistoryField(BaseModel):
    value: str = ""
    date_label: str | None = None
    status: str = Field(default="missing", pattern=r"^(missing|none|pending_review|confirmed|documented)$")
    source_type: str = Field(default="user", pattern=r"^(user|document|both|system|unknown)$")
    source_ref: str | None = None
    verified_by_user: bool = False


class PatientHistoryMetricOut(BaseModel):
    name: str
    value: str
    unit: str | None = None
    date_label: str | None = None
    status: str = "pending_review"
    source_type: str | None = None
    source_ref: str | None = None
    focus: str = "exams"


class PatientHistoryEvidenceOut(BaseModel):
    record_count: int = 0
    exam_count: int = 0
    latest_record_date: str | None = None
    latest_exam_date: str | None = None


class MissingSectionOut(BaseModel):
    key: str
    label: str


class PatientHistoryProfileOut(BaseModel):
    doctor_summary: str = ""
    sections: dict[str, PatientHistoryField]
    key_metrics: list[PatientHistoryMetricOut] = []
    evidence_overview: PatientHistoryEvidenceOut
    missing_sections: list[MissingSectionOut] = []
    completeness: float = 0.0
    updated_at: datetime | None = None
    verified_at: datetime | None = None


class PatientHistoryProfileIn(BaseModel):
    doctor_summary: str = ""
    sections: dict[str, PatientHistoryField] = {}
    verified_at: datetime | None = None
