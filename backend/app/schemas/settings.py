from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserSettingsOut(BaseModel):
    intervention_level: Literal["L1", "L2", "L3", "L4", "L5"] = "L2"
    daily_reminder_limit: int | None = None
    allow_auto_escalation: bool = False
    glucose_unit: Literal["mg_dl", "mmol_l"] = "mg_dl"
    elderly_mode: bool = False
    elderly_checkin_interval_min: int = 180
    onboarding_completed: bool = False
    onboarding_target: str | None = None
    onboarding_contents: list[str] = Field(default_factory=list)
    onboarding_generate_plan: bool = False
    updated_at: datetime | None = None

    # Resolved strategy params (read-only, computed from level)
    strategy: InterventionStrategyOut | None = None

    model_config = {"from_attributes": True}


class InterventionStrategyOut(BaseModel):
    """Resolved trigger strategy for the current level (read-only)."""

    trigger_min_risk: str
    daily_reminder_limit: int
    per_meal_reminder_limit: int
    suggestion_count_min: int
    suggestion_count_max: int
    review_required: str
    escalation_consecutive_days: int | None


class UserSettingsUpdate(BaseModel):
    intervention_level: Literal["L1", "L2", "L3", "L4", "L5"] | None = None
    daily_reminder_limit: int | None = Field(default=None, ge=0, le=10)
    allow_auto_escalation: bool | None = None
    glucose_unit: Literal["mg_dl", "mmol_l"] | None = None
    elderly_mode: bool | None = None
    elderly_checkin_interval_min: int | None = Field(default=None, ge=30, le=1440)


class OnboardingNeedsIn(BaseModel):
    target: str | None = Field(default=None, max_length=80)
    contents: list[str] = Field(default_factory=list)
    generate_plan: bool = False
    completed: bool = True


class OnboardingNeedsOut(BaseModel):
    target: str | None = None
    contents: list[str] = Field(default_factory=list)
    generate_plan: bool = False
    completed: bool = False
    updated_at: datetime | None = None


# Update forward ref now that InterventionStrategyOut is defined
UserSettingsOut.model_rebuild()
