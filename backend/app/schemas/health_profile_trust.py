"""HTTP contracts for confirmed health-profile facts and review candidates."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ProfileResponseState = Literal[
    "value",
    "none",
    "not_applicable",
    "prefer_not_to_answer",
]


class HealthProfileSourceOut(BaseModel):
    source_id: int
    source_type: str
    source_ref: str
    confidence: float | None = None
    source_snapshot: dict = Field(default_factory=dict)
    created_at: datetime


class HealthProfileFactOut(BaseModel):
    fact_id: int
    fact_key: str
    category: str
    value_data: dict
    is_safety_critical: bool
    confirmation_method: str
    version: int
    confirmed_at: datetime | None = None
    updated_at: datetime
    sources: list[HealthProfileSourceOut] = Field(default_factory=list)


class HealthProfileCandidateOut(BaseModel):
    candidate_id: int
    fact_key: str
    category: str
    proposed_value: dict
    is_safety_critical: bool
    review_status: str
    conflict_with_fact_id: int | None = None
    confidence: float | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    sources: list[HealthProfileSourceOut] = Field(default_factory=list)


class HealthProfilePrimaryActionOut(BaseModel):
    kind: Literal["review_updates", "complete_profile", "edit_profile"]
    item_count: int = Field(ge=0)
    localization_key: str
    route: str


class HealthProfileOverviewOut(BaseModel):
    completeness_percent: int
    resolved_required_weight: int
    total_required_weight: int
    missing_required_fact_keys: list[str]
    pending_update_count: int
    independent_source_count: int
    primary_action: HealthProfilePrimaryActionOut


class HealthProfileGoalMetricIn(BaseModel):
    metric_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.:-]+$")
    display_label: str | None = Field(default=None, max_length=160)


class HealthProfileGoalMetricOut(BaseModel):
    metric_key: str
    display_label: str | None = None


class HealthProfileGoalOut(BaseModel):
    goal_id: int
    name: str
    status: Literal["active", "paused", "completed", "archived"]
    started_on: date
    version: int
    confirmed_at: datetime
    metrics: list[HealthProfileGoalMetricOut] = Field(default_factory=list)


class HealthProfileManagementPlanOut(BaseModel):
    """Read-only projection of a confirmed plan owned by the profile account."""

    plan_id: int
    title: str
    goal: str | None = None
    start_date: date
    end_date: date
    status: str
    created_by: str
    updated_at: datetime
    task_count: int = 0
    completed_task_count: int = 0


class HealthProfileOut(BaseModel):
    subject_user_id: int
    profile_status: Literal["updated", "needs_attention"]
    overview: HealthProfileOverviewOut
    facts: list[HealthProfileFactOut]
    candidates: list[HealthProfileCandidateOut]
    goals: list[HealthProfileGoalOut] = Field(default_factory=list)
    management_plans: list[HealthProfileManagementPlanOut] = Field(default_factory=list)


class HealthProfileCandidateReviewIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    candidate_version: int = Field(ge=1)
    action: Literal["accept", "reject"]


class HealthProfileFactUpsertIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    fact_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_.:-]+$")
    category: Literal["basic", "long_term_health", "safety", "medication", "goal"]
    response_state: ProfileResponseState
    value: object | None = None
    is_safety_critical: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class HealthProfileFactRetractIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)


class HealthProfileGoalCreateIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    started_on: date
    metrics: list[HealthProfileGoalMetricIn] = Field(default_factory=list, max_length=32)


class HealthProfileGoalUpdateIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    started_on: date | None = None
    metrics: list[HealthProfileGoalMetricIn] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _requires_change(self):
        if self.name is None and self.started_on is None and self.metrics is None:
            raise ValueError("Goal update requires at least one changed field")
        return self


class HealthProfileGoalStatusIn(BaseModel):
    subject_user_id: int
    client_event_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    action: Literal["pause", "resume", "complete", "archive"]


class HealthProfileRevisionItemOut(BaseModel):
    revision_id: int
    event_type: str
    target_version: int
    actor_user_id: int | None = None
    before_data: dict = Field(default_factory=dict)
    after_data: dict = Field(default_factory=dict)
    created_at: datetime


class HealthProfileRevisionListOut(BaseModel):
    subject_user_id: int
    target_kind: Literal["fact", "goal"]
    target_id: int
    items: list[HealthProfileRevisionItemOut]
    next_after_revision_id: int | None = None
