from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class HealthPlanFromChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    analysis: str | None = Field(default=None, max_length=12000)
    conversation_id: str | None = Field(default=None, max_length=80)
    message_id: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=160)


class HealthPlanOut(BaseModel):
    id: str
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


class HealthPlanDetailOut(HealthPlanOut):
    raw_content: str | None = None
    tasks: list[PlanTaskOut] = []


class TubeTaskProgress(BaseModel):
    task_type: str
    label: str
    completed: int
    target: int
    completed_value: float | None = None
    target_value: float | None = None
    unit: str | None = None
    ratio: float


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
    days: list[TubeDayOut]


class TubeCompleteIn(BaseModel):
    date: date
    task_type: str = Field(pattern="^(diet|exercise|medication|measurement)$")
    amount: int = Field(default=1, ge=1, le=20)
    value: float | None = Field(default=None, ge=0, le=100000)


class TubeCompleteOut(BaseModel):
    day: TubeDayOut
