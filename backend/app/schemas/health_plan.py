from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class HealthPlanFromChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    analysis: str | None = Field(default=None, max_length=12000)
    conversation_id: str | None = Field(default=None, max_length=80)
    message_id: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=160)


class HealthPlanQuestionnaireIn(BaseModel):
    target: str = Field(min_length=1, max_length=80)
    duration_days: int = Field(default=7, ge=1, le=90)
    frequency: str = Field(default="daily", max_length=40)
    contents: list[str] = Field(default_factory=list)
    medication_needed: bool = False
    notes: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=160)


class HealthPlanOut(BaseModel):
    id: str
    plan_code: str | None = None
    title: str
    goal: str | None = None
    background: str | None = None
    start_date: date
    end_date: date
    status: str
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    task_count: int = 0
    completed_task_count: int = 0


class HealthPlanListOut(BaseModel):
    items: list[HealthPlanOut]


class PlanTaskOut(BaseModel):
    id: str
    plan_id: str | None = None
    date: date
    task_type: str
    title: str
    description: str | None = None
    status: str
    target_count: int
    completed_count: int
    target_value: float | None = None
    completed_value: float | None = None
    unit: str | None = None
    reminder_time: str | None = None
    source_type: str
    source_ref: str


class PlanTaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1200)
    target_count: int | None = Field(default=None, ge=0, le=200)
    target_value: float | None = Field(default=None, ge=0, le=100000)
    unit: str | None = Field(default=None, max_length=24)
    reminder_time: str | None = Field(default=None, max_length=8)


class HealthPlanDetailOut(HealthPlanOut):
    raw_content: str | None = None
    tasks: list[PlanTaskOut] = []


class TubeTaskProgress(BaseModel):
    task_type: str
    label: str
    title: str | None = None
    description: str | None = None
    summary: str | None = None
    details: list[str] = []
    completed: int
    target: int
    completed_value: float | None = None
    target_value: float | None = None
    unit: str | None = None
    ratio: float
    plan_ids: list[str] = []
    plan_codes: list[str] = []
    source_task_ids: list[str] = []


class TubeDayOut(BaseModel):
    date: date
    weekday: int
    is_today: bool
    is_future: bool
    completion_ratio: float
    tasks: list[TubeTaskProgress]


class TubeWeekOut(BaseModel):
    week_start: date
    week_end: date
    today: date
    has_omics_data: bool = False
    has_medication_need: bool = False
    task_types: list[str] = []
    days: list[TubeDayOut]


class TubeCompleteIn(BaseModel):
    date: date
    task_type: str = Field(pattern="^(diet|exercise|medication|measurement|hydration|sleep)$")
    amount: int = Field(default=1, ge=1, le=20)
    value: float | None = Field(default=None, ge=0, le=100000)


class TubeCompleteOut(BaseModel):
    day: TubeDayOut


class HealthTreeSummaryOut(BaseModel):
    trees_grown: int = 0
    fruiting_count: int = 0
    active_plan_count: int = 0


class PlanRevisionGenerateIn(BaseModel):
    date: date | None = None
    purpose: str | None = Field(default=None, max_length=500)


class PlanRevisionItemOut(BaseModel):
    task_key: str
    task_type: str
    label: str
    title: str
    description: str | None = None
    target_count: int = 1
    target_value: float | None = None
    unit: str | None = None
    reminder_time: str | None = None
    plan_ids: list[str] = []
    plan_codes: list[str] = []
    source_task_ids: list[str] = []
    summary: str | None = None


class PlanRevisionReasonOut(BaseModel):
    task_key: str
    reason: str
    evidence: str | None = None


class PlanRevisionProposalOut(BaseModel):
    id: str
    date: date
    status: str
    purpose: str
    original_items: list[PlanRevisionItemOut] = []
    revised_items: list[PlanRevisionItemOut] = []
    reasons: list[PlanRevisionReasonOut] = []
    context_summary: str | None = None
    daily_limit_used: bool = False
    created_at: datetime
    applied_at: datetime | None = None


class PlanRevisionApplyIn(BaseModel):
    accepted_task_keys: list[str] = []
    accept_all: bool = False
    reject_all: bool = False
