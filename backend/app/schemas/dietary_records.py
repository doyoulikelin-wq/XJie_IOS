"""HTTP contracts for trusted dietary records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DietarySource = Literal[
    "camera", "photo_library", "text", "voice", "recent", "chat", "manual"
]
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class DietaryFoodItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    portion_text: str | None = Field(default=None, max_length=160)
    categories: list[str] = Field(default_factory=list, max_length=12)
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_estimated: bool = True


class DietaryDraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    source_type: DietarySource
    source_ref: str | None = Field(default=None, max_length=256)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    diet_date: date | None = None
    meal_type: MealType | None = None
    eaten_at: datetime
    raw_input: str | None = Field(default=None, max_length=4000)
    food_items: list[DietaryFoodItem] = Field(default_factory=list, max_length=64)
    portion_text: str | None = Field(default=None, max_length=256)
    structure: dict[str, Any] = Field(default_factory=dict)
    estimated_nutrition: dict[str, Any] = Field(default_factory=dict)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    recognition_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _require_aware_time_and_bounded_confidences(self):
        if self.eaten_at.tzinfo is None or self.eaten_at.utcoffset() is None:
            raise ValueError("eaten_at must include timezone")
        if any(value < 0 or value > 1 for value in self.field_confidences.values()):
            raise ValueError("field_confidences values must be between 0 and 1")
        return self


class DietaryDraftCreateIn(DietaryDraftFields):
    client_event_id: str = Field(min_length=1, max_length=80)


class DietaryDraftConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    diet_date: date
    meal_type: MealType
    eaten_at: datetime
    food_items: list[DietaryFoodItem] = Field(min_length=1, max_length=64)
    portion_text: str | None = Field(default=None, max_length=256)
    structure: dict[str, Any] = Field(default_factory=dict)
    estimated_nutrition: dict[str, Any] = Field(default_factory=dict)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    recognition_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _require_aware_time_and_bounded_confidences(self):
        if self.eaten_at.tzinfo is None or self.eaten_at.utcoffset() is None:
            raise ValueError("eaten_at must include timezone")
        if any(value < 0 or value > 1 for value in self.field_confidences.values()):
            raise ValueError("field_confidences values must be between 0 and 1")
        return self


class DietaryDraftRetryRecognitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class DietaryDraftOut(BaseModel):
    draft_id: int
    subject_user_id: int
    source_type: DietarySource
    source_ref: str | None
    diet_date: date
    timezone: str
    meal_type: MealType | None
    eaten_at: datetime
    food_items: list[DietaryFoodItem]
    portion_text: str | None
    structure: dict[str, Any]
    estimated_nutrition: dict[str, Any]
    field_confidences: dict[str, float]
    recognition_confidence: float | None
    recognition_status: str
    recognition_cache_reused: bool = False
    low_confidence_fields: list[str]
    status: Literal["pending_confirmation", "confirmed", "rejected"]
    version: int
    requires_user_confirmation: Literal[True] = True
    formal_record_created: bool
    created_at: datetime
    updated_at: datetime


class DietaryRecordOut(BaseModel):
    record_id: int
    source_draft_id: int
    subject_user_id: int
    diet_date: date
    timezone: str
    meal_type: MealType
    eaten_at: datetime
    source_type: DietarySource
    source_ref: str
    food_items: list[DietaryFoodItem]
    portion_text: str | None
    structure: dict[str, Any]
    estimated_nutrition: dict[str, Any]
    field_confidences: dict[str, float]
    confidence: float | None
    status: Literal["user_confirmed", "modified", "deleted"]
    version: int
    trust_state: Literal["user_confirmed"] = "user_confirmed"
    confirmed_at: datetime
    created_at: datetime
    updated_at: datetime


class DietaryRecordUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    diet_date: date | None = None
    meal_type: MealType | None = None
    eaten_at: datetime | None = None
    food_items: list[DietaryFoodItem] | None = Field(
        default=None, min_length=1, max_length=64
    )
    portion_text: str | None = Field(default=None, max_length=256)
    structure: dict[str, Any] | None = None
    estimated_nutrition: dict[str, Any] | None = None
    field_confidences: dict[str, float] | None = None
    recognition_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_optional_time_and_confidences(self):
        for field_name in (
            "timezone",
            "diet_date",
            "meal_type",
            "eaten_at",
            "food_items",
            "structure",
            "estimated_nutrition",
            "field_confidences",
        ):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null when supplied")
        if self.eaten_at is not None and (
            self.eaten_at.tzinfo is None or self.eaten_at.utcoffset() is None
        ):
            raise ValueError("eaten_at must include timezone")
        if self.field_confidences and any(
            value < 0 or value > 1 for value in self.field_confidences.values()
        ):
            raise ValueError("field_confidences values must be between 0 and 1")
        return self


class DietaryRecordDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class DietaryRecordReuseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    diet_date: date | None = None
    meal_type: MealType
    eaten_at: datetime

    @model_validator(mode="after")
    def _require_aware_time(self):
        if self.eaten_at.tzinfo is None or self.eaten_at.utcoffset() is None:
            raise ValueError("eaten_at must include timezone")
        return self


class DietaryDayCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_user_id: int | None = Field(default=None, gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    complete_with_confirmed_only: bool = False


class DietarySummaryOut(BaseModel):
    summary_id: int
    subject_user_id: int
    diet_date: date
    close_method: Literal["automatic", "manual"]
    record_complete: bool
    confirmed_meal_count: int
    pending_count: int
    structure_summary: dict[str, Any]
    conclusion: str
    today_suggestion: str
    confidence: float
    evidence: dict[str, Any]
    rule_version: str
    template_version: str
    record_version: int
    recalculated_after_edit: bool
    generated_at: datetime


class DietaryDailySummaryDisplayOut(BaseModel):
    conclusion: str
    today_suggestion: str
    confirmed_meal_count: int
    confidence: float
    generation_source: Literal["ai", "rule_fallback"]
    retry_pending: bool
    generated_at: datetime


class DietaryDailySummaryStatusOut(BaseModel):
    status: Literal[
        "available", "never_recorded", "no_yesterday_records", "processing"
    ]
    target_date: date
    message: str | None
    summary: DietaryDailySummaryDisplayOut | None


class DietaryDayOut(BaseModel):
    subject_user_id: int
    diet_date: date
    state: Literal[
        "open",
        "waiting_confirmation",
        "incomplete",
        "ready",
        "stale",
        "recalculating",
        "failed",
    ]
    record_version: int
    close_method: Literal["automatic", "manual"] | None
    record_complete: bool
    confirmed_meal_count: int
    pending_count: int
    summary: DietarySummaryOut | None


class DietaryWeeklyReviewOut(BaseModel):
    window_start: date
    window_end: date
    recorded_day_count: int
    complete_day_count: int
    protein_low_days: int
    vegetables_adequate_days: int
    uses_score: Literal[False] = False


class DietaryDashboardOut(BaseModel):
    subject_user_id: int
    selected_date: date
    is_today: bool
    recorded_meal_count: int
    pending_count: int
    streak_days: int
    day_state: Literal[
        "open",
        "waiting_confirmation",
        "incomplete",
        "ready",
        "stale",
        "recalculating",
        "failed",
    ]
    records: list[DietaryRecordOut]
    pending_drafts: list[DietaryDraftOut]
    selected_day_summary: DietarySummaryOut | None
    displayed_summary: DietarySummaryOut | None
    displayed_summary_date: date
    weekly_review: DietaryWeeklyReviewOut


class DietaryRecentOut(BaseModel):
    subject_user_id: int
    items: list[DietaryRecordOut]
