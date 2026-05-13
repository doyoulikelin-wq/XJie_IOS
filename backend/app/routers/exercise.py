"""锻炼记录路由：首页今日膳食下方模块所用。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.exercise_log import ExerciseLog

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_TYPES = {
    "walking", "running", "cycling", "swimming", "yoga", "strength",
    "hiit", "stretching", "dancing", "ball", "hiking", "other",
}
_VALID_INTENSITY = {"low", "medium", "high"}

# 简单 MET 表用于估算热量（kcal = MET × 体重kg × 小时）
_DEFAULT_MET = {
    "walking": 3.5, "running": 8.0, "cycling": 6.0, "swimming": 7.0,
    "yoga": 2.5, "strength": 5.0, "hiit": 8.5, "stretching": 2.3,
    "dancing": 5.0, "ball": 6.5, "hiking": 6.0, "other": 4.0,
}


class ExerciseIn(BaseModel):
    activity_type: str = Field(min_length=1, max_length=64)
    duration_minutes: int = Field(ge=1, le=1440)
    intensity: str | None = Field(default=None)
    calories_kcal: float | None = Field(default=None, ge=0, le=10000)
    notes: str | None = Field(default=None, max_length=500)
    started_at: datetime | None = None
    """缺省=now"""


class ExerciseOut(BaseModel):
    id: int
    activity_type: str
    duration_minutes: int
    intensity: str | None = None
    calories_kcal: float | None = None
    notes: str | None = None
    started_at: datetime
    created_at: datetime


class ExerciseListOut(BaseModel):
    items: list[ExerciseOut]
    total_minutes: int = 0
    total_kcal: float = 0.0


def _to_out(r: ExerciseLog) -> ExerciseOut:
    return ExerciseOut(
        id=r.id, activity_type=r.activity_type, duration_minutes=r.duration_minutes,
        intensity=r.intensity, calories_kcal=r.calories_kcal, notes=r.notes,
        started_at=r.started_at, created_at=r.created_at,
    )


def _estimate_kcal(activity_type: str, duration_minutes: int, intensity: str | None,
                   weight_kg: float | None) -> float | None:
    if weight_kg is None or weight_kg <= 0:
        return None
    met = _DEFAULT_MET.get(activity_type, 4.0)
    if intensity == "high":
        met *= 1.25
    elif intensity == "low":
        met *= 0.8
    return round(met * weight_kg * (duration_minutes / 60.0), 1)


@router.get("", response_model=ExerciseListOut)
def list_exercises(
    date: str | None = Query(default=None, description="YYYY-MM-DD，默认=今天；传 'all' 返回全部"),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    q = select(ExerciseLog).where(ExerciseLog.user_id == user_id)
    if date != "all":
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now().date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 必须为 YYYY-MM-DD")
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) - timedelta(hours=8)
        end = start + timedelta(days=1)
        q = q.where(ExerciseLog.started_at >= start, ExerciseLog.started_at < end)
    q = q.order_by(ExerciseLog.started_at.desc()).limit(limit)
    rows = db.execute(q).scalars().all()
    items = [_to_out(r) for r in rows]
    total_min = sum(r.duration_minutes for r in rows)
    total_kcal = round(sum((r.calories_kcal or 0.0) for r in rows), 1)
    return ExerciseListOut(items=items, total_minutes=total_min, total_kcal=total_kcal)


@router.post("", response_model=ExerciseOut)
def create_exercise(
    body: ExerciseIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    activity = body.activity_type.strip().lower()
    if activity not in _VALID_TYPES:
        # 容错：不在白名单则归为 other 但保留原文到 notes
        original = body.activity_type.strip()
        body_notes = body.notes or ""
        if original and original.lower() != "other":
            body_notes = (body_notes + f" [原始类型:{original}]").strip()
        activity = "other"
        notes_final = body_notes or None
    else:
        notes_final = body.notes or None

    intensity = body.intensity if body.intensity in _VALID_INTENSITY else None
    started = body.started_at or datetime.now(timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if started > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="开始时间不能在未来")

    kcal = body.calories_kcal
    if kcal is None:
        # 用 UserProfile.weight_kg 估算
        from app.models.user_profile import UserProfile
        profile = db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalars().first()
        kcal = _estimate_kcal(activity, body.duration_minutes, intensity,
                              profile.weight_kg if profile else None)

    row = ExerciseLog(
        user_id=user_id,
        activity_type=activity,
        duration_minutes=body.duration_minutes,
        intensity=intensity,
        calories_kcal=kcal,
        notes=notes_final,
        started_at=started,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Exercise added: user=%s type=%s mins=%s", user_id, activity, body.duration_minutes)
    return _to_out(row)


@router.delete("/{exercise_id}")
def delete_exercise(
    exercise_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(ExerciseLog).where(
            ExerciseLog.id == exercise_id,
            ExerciseLog.user_id == user_id,
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
