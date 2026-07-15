"""HTTP contracts for the trusted medication loop."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


MealRelation = Literal["unspecified", "before_meal", "after_meal", "with_meal"]
MedicationSourceType = Literal["manual", "prescription_import", "ocr", "history"]
PlanStatus = Literal["active", "paused", "completed", "retracted"]


class MedicationPlanFields(BaseModel):
    generic_name: str = Field(min_length=1, max_length=160)
    purpose: str | None = Field(default=None, max_length=256)
    brand_name: str | None = Field(default=None, max_length=160)
    strength: str | None = Field(default=None, max_length=80)
    dose_text: str | None = Field(default=None, max_length=80)
    dose_quantity: Decimal | None = Field(default=None, gt=0)
    frequency: str | None = Field(default=None, max_length=80)
    schedule_times: list[str] = Field(default_factory=list, max_length=24)
    meal_relation: MealRelation = "unspecified"
    instructions: str | None = Field(default=None, max_length=2000)
    course_start: date | None = None
    course_end: date | None = None
    prescriber: str | None = Field(default=None, max_length=160)
    initial_quantity: Decimal | None = Field(default=None, ge=0)
    inventory_unit: str | None = Field(default=None, max_length=32)
    is_long_term: bool = False
    source_type: MedicationSourceType = "manual"
    source_ref: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _validate_pairs_and_dates(self):
        if self.course_start and self.course_end and self.course_start > self.course_end:
            raise ValueError("course_start cannot be after course_end")
        if (self.initial_quantity is None) != (self.inventory_unit is None):
            raise ValueError("initial_quantity and inventory_unit must be supplied together")
        return self


class MedicationPlanConfirmIn(MedicationPlanFields):
    subject_user_id: int = Field(gt=0)
    client_request_id: str = Field(min_length=1, max_length=80)
    client_event_id: str = Field(min_length=1, max_length=80)
    candidate_id: int | None = Field(default=None, gt=0)
    candidate_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_candidate_pair(self):
        if (self.candidate_id is None) != (self.candidate_version is None):
            raise ValueError("candidate_id and candidate_version must be supplied together")
        return self


class MedicationPlanReviseIn(MedicationPlanFields):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class MedicationPlanStatusIn(BaseModel):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    action: Literal["pause", "resume", "complete", "retract"]
    reason: str | None = Field(default=None, max_length=1000)


class MedicationInventoryEstimateOut(BaseModel):
    is_estimate: Literal[True] = True
    label: Literal["预计剩余"] = "预计剩余"
    estimated_remaining: float | None
    estimated_consumed: float | None
    inventory_unit: str | None
    basis: Literal["user_confirmed_taken_events_only"] = "user_confirmed_taken_events_only"
    unavailable_reason: str | None = None


class MedicationPlanOut(BaseModel):
    plan_id: int
    subject_user_id: int
    generic_name: str
    purpose: str | None
    brand_name: str | None
    strength: str | None
    dose_text: str | None
    dose_quantity: float | None
    frequency: str | None
    schedule_times: list[str]
    meal_relation: MealRelation
    instructions: str | None
    course_start: date | None
    course_end: date | None
    prescriber: str | None
    initial_quantity: float | None
    inventory_unit: str | None
    is_long_term: bool
    source_type: MedicationSourceType
    source_ref: str
    status: PlanStatus
    version: int
    confirmed_at: datetime
    trust_state: Literal["user_confirmed"] = "user_confirmed"
    reminder_management: Literal["client_managed"] = "client_managed"
    reminder_default_enabled: Literal[False] = False
    server_notification_scheduled: Literal[False] = False
    inventory: MedicationInventoryEstimateOut


class MedicationPlanListOut(BaseModel):
    subject_user_id: int
    items: list[MedicationPlanOut]


class LongTermMedicationSummaryItemOut(BaseModel):
    medication_name: str
    purpose: str | None
    started_on: date | None
    is_still_taking: bool
    source: Literal[
        "prescription",
        "user_added",
        "ocr_confirmed",
        "history_confirmed",
    ]
    last_confirmed_at: datetime


class LongTermMedicationSummaryListOut(BaseModel):
    subject_user_id: int
    items: list[LongTermMedicationSummaryItemOut]


class MedicationPrefillCandidateOut(BaseModel):
    candidate_id: int
    subject_user_id: int
    client_event_id: str
    source_type: Literal["ocr", "prescription_import", "history"]
    source_ref: str
    extracted_data: dict[str, Any]
    field_confidences: dict[str, float]
    low_confidence_fields: list[str]
    review_status: Literal["pending_review", "accepted", "rejected"]
    version: int
    trust_state: Literal["unconfirmed_prefill"] = "unconfirmed_prefill"
    requires_user_confirmation: Literal[True] = True
    plan_created: bool
    confirmation_endpoint: Literal[
        "/api/medications/trust/plans/confirm"
    ] = "/api/medications/trust/plans/confirm"


class MedicationPrefillListOut(BaseModel):
    subject_user_id: int
    items: list[MedicationPrefillCandidateOut]


class MedicationPrefillRejectIn(BaseModel):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class MedicationTodayTaskOut(BaseModel):
    occurrence_key: str
    plan_id: int
    plan_version: int
    generic_name: str
    brand_name: str | None
    dose_text: str | None
    scheduled_local_date: date
    scheduled_time: str
    scheduled_at: datetime
    status: Literal[
        "upcoming",
        "awaiting_confirmation",
        "snoozed",
        "possibly_missed",
        "taken",
        "skipped",
    ]
    status_label: str
    status_assertion: Literal["schedule_derived", "user_confirmed"]
    occurrence_version: int
    latest_event_id: int | None
    snoozed_until: datetime | None
    confirmed_at: datetime | None
    possibly_missed_is_not_confirmation: bool
    notification_schedule_status: Literal[
        "not_requested", "client_must_schedule", "client_managed"
    ]


class MedicationTodaySummaryOut(BaseModel):
    subject_user_id: int
    local_date: date
    planned_count: int
    taken_count: int
    awaiting_confirmation_count: int
    possibly_missed_count: int
    skipped_count: int
    snoozed_count: int
    adverse_reaction_count: int
    next_task: MedicationTodayTaskOut | None
    tasks: list[MedicationTodayTaskOut]
    empty_state: str | None
    missed_assertion_policy: Literal[
        "elapsed_time_never_confirms_missed"
    ] = "elapsed_time_never_confirms_missed"


class MedicationDoseActionIn(BaseModel):
    subject_user_id: int = Field(gt=0)
    plan_id: int = Field(gt=0)
    expected_plan_version: int = Field(ge=1)
    client_event_id: str = Field(min_length=1, max_length=80)
    scheduled_local_date: date
    scheduled_time: str = Field(min_length=5, max_length=5)
    expected_occurrence_version: int = Field(ge=0)
    action: Literal["taken", "snooze", "skip", "correct"]
    corrected_status: Literal["taken", "snoozed", "skipped", "pending"] | None = None
    correction_of_event_id: int | None = Field(default=None, gt=0)
    snoozed_until: datetime | None = None
    taken_quantity: Decimal | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _validate_action_shape(self):
        if self.action == "correct":
            if self.corrected_status is None or self.correction_of_event_id is None:
                raise ValueError("correction requires corrected_status and correction_of_event_id")
        elif self.corrected_status is not None or self.correction_of_event_id is not None:
            raise ValueError("correction fields are only valid for action=correct")
        effective = self.corrected_status if self.action == "correct" else {
            "taken": "taken",
            "snooze": "snoozed",
            "skip": "skipped",
        }[self.action]
        if effective == "snoozed" and self.snoozed_until is None:
            raise ValueError("snooze requires snoozed_until")
        if effective != "snoozed" and self.snoozed_until is not None:
            raise ValueError("snoozed_until is only valid for a snoozed result")
        if effective != "taken" and self.taken_quantity is not None:
            raise ValueError("taken_quantity is only valid for a taken result")
        return self


class MedicationDoseEventOut(BaseModel):
    event_id: int
    occurrence_key: str
    occurrence_version: int
    action: Literal["taken", "snooze", "skip", "correct"]
    effective_status: Literal["taken", "snoozed", "skipped", "pending"]
    supersedes_event_id: int | None
    snoozed_until: datetime | None
    taken_quantity: float | None
    reason: str | None
    confirmed_at: datetime
    trust_state: Literal["user_confirmed"] = "user_confirmed"
    notification_schedule_status: Literal[
        "not_requested", "client_must_schedule"
    ]
    reminder_management: Literal["client_managed"] = "client_managed"


class MedicationReactionFields(BaseModel):
    plan_id: int = Field(gt=0)
    symptoms: str = Field(min_length=1, max_length=2000)
    onset_at: datetime
    severity: Literal["mild", "moderate", "severe"]
    duration_minutes: int | None = Field(default=None, ge=0, le=525600)
    related_occurrence_key: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)


class MedicationReactionCreateIn(MedicationReactionFields):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    reaction_key: str = Field(min_length=1, max_length=80)


class MedicationReactionCorrectIn(MedicationReactionFields):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class MedicationReactionRetractIn(BaseModel):
    subject_user_id: int = Field(gt=0)
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class MedicationReactionOut(BaseModel):
    reaction_key: str
    reaction_version: int
    plan_id: int
    symptoms: str
    onset_at: datetime
    severity: Literal["mild", "moderate", "severe"]
    duration_minutes: int | None
    related_occurrence_key: str | None
    notes: str | None
    status: Literal["active", "retracted"]
    causal_attribution: Literal["temporal_association_only"] = "temporal_association_only"
    user_facing_causality: Literal[
        "该症状发生在服药后，不能据此认定由药物导致"
    ] = "该症状发生在服药后，不能据此认定由药物导致"
    safety_guidance: str
    confirmed_at: datetime


class MedicationReactionListOut(BaseModel):
    subject_user_id: int
    items: list[MedicationReactionOut]
