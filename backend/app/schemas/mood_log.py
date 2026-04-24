from datetime import date, datetime

from pydantic import BaseModel, Field


SEGMENTS = ["morning", "noon", "afternoon", "evening", "night"]


class MoodLogIn(BaseModel):
    ts: datetime
    segment: str = Field(..., description="One of morning|noon|afternoon|evening|night")
    mood_level: int = Field(..., ge=1, le=5, description="1=😡 2=😢 3=😟 4=😐 5=😀")
    note: str | None = None


class MoodLogOut(BaseModel):
    id: int
    ts: datetime
    ts_date: date
    segment: str
    mood_level: int
    note: str | None = None


class MoodDay(BaseModel):
    """One day's 5-segment snapshot. Missing segments are None."""
    date: date
    morning: int | None = None
    noon: int | None = None
    afternoon: int | None = None
    evening: int | None = None
    night: int | None = None
    avg: float | None = None


class MoodGlucoseCorrelation(BaseModel):
    """Pearson correlation between segment mood (1..5) and segment-window
    mean glucose. Returns null when fewer than 5 paired samples exist.
    """
    days: int
    paired_samples: int
    pearson_r: float | None = None
    p_value: float | None = None
    interpretation: str  # e.g. "无显著相关" / "弱负相关" / "中等正相关"
