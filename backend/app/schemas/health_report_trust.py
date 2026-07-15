"""HTTP contracts for explicit report review and trusted admission."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.health_document import HealthDocumentOut


class HealthReportCandidateOut(BaseModel):
    candidate_id: int
    candidate_key: str
    version: int
    canonical_code: str | None = None
    canonical_name: str
    raw_name: str
    raw_value: str | None = None
    raw_unit: str | None = None
    normalized_value: float | None = None
    normalized_text: str | None = None
    normalized_unit: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = None
    abnormal_state: str
    confidence: float | None = None
    effective_at: datetime | None = None
    source_locator: dict
    model_version: str | None = None
    review_status: str
    requires_review: bool
    # Server-owned review semantics. Clients must not recreate thresholds or
    # infer conflicts from ``requires_review``.
    low_confidence: bool = False
    conflict_reasons: list[str] = Field(default_factory=list)


class HealthReportFailureRecoveryOut(BaseModel):
    """Server-owned recovery semantics for a failed recognition workflow."""

    failure_code: str
    recovery_action: str
    retryable: bool
    allows_manual_candidate: bool


class HealthReportReviewOut(BaseModel):
    workflow_id: int
    legacy_document_id: int | None = None
    subject_user_id: int
    status: str
    version: int
    report_type: str
    document_fingerprint: str | None = None
    recognized_at: datetime | None = None
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    confirmation_client_event_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    failure_recovery: HealthReportFailureRecoveryOut | None = None
    pending_review_count: int
    auto_accepted_count: int
    admitted_observation_count: int
    requires_report_confirmation: bool
    can_confirm: bool
    document: HealthDocumentOut | None = None
    candidates: list[HealthReportCandidateOut]


class HealthReportConfirmationEventOut(BaseModel):
    event_id: int
    candidate_id: int
    event_type: str
    candidate_version: int
    before_data: dict
    after_data: dict
    created_at: datetime


class HealthReportObservationOut(BaseModel):
    observation_id: int
    source_candidate_id: int
    confirmation_event_id: int
    canonical_code: str | None = None
    canonical_name: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = None
    abnormal_state: str
    effective_at: datetime
    confirmed_at: datetime


class HealthReportProfileImpactOut(BaseModel):
    profile_candidate_id: int
    source_id: int
    source_observation_id: int
    fact_key: str
    category: str
    proposed_value: dict
    review_status: str
    confidence: float | None = None


class HealthReportScoreSnapshotOut(BaseModel):
    snapshot_id: int
    score_kind: str
    algorithm_id: str
    algorithm_version: str
    before_value: float | None = None
    after_value: float | None = None
    before_confidence: float | None = None
    after_confidence: float | None = None
    score_direction: str | None = None
    semantic_outcome: str | None = None
    calculation_status: str
    evidence: dict
    missing_inputs: dict
    failure_code: str | None = None
    computed_at: datetime | None = None
    job_item_status: str | None = None
    method_summary: dict | None = None
    input_basis: list[dict] = Field(default_factory=list)
    failure: dict | None = None


class HealthReportFollowUpDetailOut(BaseModel):
    item_id: int
    item_code: str
    message: dict
    due_at: datetime | None = None
    evidence: list[dict] = Field(default_factory=list)


class HealthReportFollowUpOut(BaseModel):
    available: bool
    items: list[str] = Field(default_factory=list)
    details: list[HealthReportFollowUpDetailOut] = Field(default_factory=list)
    unavailable_reason: str | None = None


class HealthReportInterpretationOut(BaseModel):
    """Evidence-bounded post-admission interpretation and provenance."""

    workflow_id: int
    subject_user_id: int
    status: str
    available: bool
    unavailable_reason: str | None = None
    non_diagnostic_notice: str
    document: HealthDocumentOut | None = None
    candidates: list[HealthReportCandidateOut] = Field(default_factory=list)
    confirmation_events: list[HealthReportConfirmationEventOut] = Field(default_factory=list)
    structured_additions: list[HealthReportObservationOut] = Field(default_factory=list)
    major_abnormalities: list[HealthReportObservationOut] = Field(default_factory=list)
    follow_up: HealthReportFollowUpOut
    profile_impacts: list[HealthReportProfileImpactOut] = Field(default_factory=list)
    score_state: Literal["pending", "completed", "partial_failed", "failed", "unavailable"]
    score_pending: bool
    score_details: dict[str, dict] = Field(default_factory=dict)
    score_snapshots: list[HealthReportScoreSnapshotOut] = Field(default_factory=list)


class HealthReportDecisionIn(BaseModel):
    candidate_id: int
    candidate_version: int = Field(ge=1)
    action: Literal["confirm", "correct", "reject"]
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str | None = Field(default=None, max_length=64)


class HealthReportConfirmIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    workflow_version: int = Field(ge=1)
    decisions: list[HealthReportDecisionIn] = Field(default_factory=list)


class HealthReportManualCandidateIn(BaseModel):
    """One explicit manual field proposal that still requires normal review."""

    subject_user_id: int
    workflow_version: int = Field(ge=1)
    client_event_id: str = Field(min_length=1, max_length=80)
    canonical_code: str | None = Field(default=None, max_length=80)
    canonical_name: str = Field(min_length=1, max_length=160)
    raw_name: str = Field(min_length=1, max_length=160)
    value_numeric: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    value_text: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=64)
    reference_low: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    reference_high: Decimal | None = Field(default=None, max_digits=24, decimal_places=8)
    reference_text: str | None = Field(default=None, max_length=256)
    effective_at: datetime | None = None

    @field_validator("client_event_id", "canonical_name", "raw_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("canonical_code", "unit", "reference_text")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("value_text")
    @classmethod
    def _manual_text_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value_text must not be blank")
        return normalized

    @model_validator(mode="after")
    def _validate_manual_value_and_reference(self):
        if (self.value_numeric is None) == (self.value_text is None):
            raise ValueError("exactly one of value_numeric or value_text is required")
        for value in (self.value_numeric, self.reference_low, self.reference_high):
            if value is not None and not value.is_finite():
                raise ValueError("numeric values must be finite")
        if (
            self.reference_low is not None
            and self.reference_high is not None
            and self.reference_low > self.reference_high
        ):
            raise ValueError("reference_low must not exceed reference_high")
        return self


class HealthReportPrimaryActionOut(BaseModel):
    code: str
    enabled: bool
    pending_count: int = 0
    target_workflow_id: int | None = None


class HealthReportRuntimeOut(BaseModel):
    workflow_id: int
    workflow_version: int = Field(ge=1)
    subject_user_id: int
    state: str
    workflow_status: str
    failure_code: str | None = None
    primary_action: HealthReportPrimaryActionOut | None = None


class HealthReportDuplicateDecisionIn(BaseModel):
    subject_user_id: int
    workflow_version: int = Field(ge=1)
    client_event_id: str = Field(min_length=1, max_length=80)
    action: Literal["use_existing", "continue_new"]


class HealthReportDuplicateDecisionOut(BaseModel):
    workflow_id: int
    matched_workflow_id: int
    decision_status: str
    similarity: float
    workflow_version: int


class HealthReportUploadSessionIn(BaseModel):
    subject_user_id: int
    client_request_id: str = Field(min_length=1, max_length=80)
    media_kind: Literal["camera", "photo_library", "pdf", "csv", "legacy"]
    expected_page_count: int | None = Field(default=None, ge=1, le=100)


class HealthReportAssetOut(BaseModel):
    asset_id: int
    asset_index: int
    client_asset_id: str
    filename: str
    mime_type: str
    byte_size: int
    sha256: str


class HealthReportAssetRecoveryOut(HealthReportAssetOut):
    """Replacement result plus the reopened upload-session state."""

    asset_set_id: int
    session_status: str
    received_asset_count: int


class HealthReportUploadSessionOut(BaseModel):
    asset_set_id: int
    subject_user_id: int
    status: str
    media_kind: str
    expected_page_count: int | None = None
    received_asset_count: int
    aggregate_sha256: str | None = None


class HealthReportSealIn(BaseModel):
    subject_user_id: int
    report_type: Literal["unknown", "exam", "lab", "imaging", "medical_record", "other"]
    title: str = Field(min_length=1, max_length=256)
    hospital: str | None = Field(default=None, max_length=256)
    report_date: date | None = None


class HealthReportSealOut(BaseModel):
    asset_set_id: int
    status: str
    workflow_id: int | None = None
    duplicate: bool = False
    failure_code: str | None = None
    recovery_action: str | None = None
    problem_asset_indices: list[int] = Field(default_factory=list)
    missing_page_indices: list[int] = Field(default_factory=list)


class HealthReportHistoryItemOut(BaseModel):
    workflow_id: int
    status: str
    report_type: str
    title: str
    hospital: str | None = None
    report_date: date | None = None
    created_at: datetime


class HealthReportHistoryOut(BaseModel):
    items: list[HealthReportHistoryItemOut] = Field(default_factory=list)


class HealthReportTraceOut(BaseModel):
    workflow: dict
    assets: list[dict] = Field(default_factory=list)
    pages: list[dict] = Field(default_factory=list)
    locators: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    confirmation_events: list[dict] = Field(default_factory=list)
    observations: list[dict] = Field(default_factory=list)
    score_jobs: list[dict] = Field(default_factory=list)
    score_items: list[dict] = Field(default_factory=list)
    score_snapshots: list[dict] = Field(default_factory=list)
    follow_ups: list[dict] = Field(default_factory=list)


class HealthReportScoreRetryOut(BaseModel):
    job_id: int
    status: str
