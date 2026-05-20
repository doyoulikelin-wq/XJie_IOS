"""老年人关怀模式：主动询问签到记录路由。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.elderly_checkin import BODY_FEELINGS, MOODS, ElderlyCheckin
from app.models.user_settings import UserSettings

logger = logging.getLogger(__name__)
router = APIRouter()

PROMPT_TYPES = ("combined", "medication", "sleep", "water", "activity")
# 除 combined 外，同一天同一种类型只保留一条（后提交覆盖前一次）。
SINGLE_PER_DAY_KINDS = ("medication", "sleep", "water", "activity")


class CheckinIn(BaseModel):
    activity: str | None = Field(default=None, max_length=128)
    body_feeling: str | None = Field(default=None)
    mood: str | None = Field(default=None)
    note: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default="auto_prompt")
    prompt_type: str | None = Field(default="combined")


class CheckinOut(BaseModel):
    id: int
    activity: str | None
    body_feeling: str | None
    mood: str | None
    note: str | None
    source: str
    prompt_type: str
    created_at: datetime


class CheckinListOut(BaseModel):
    items: list[CheckinOut]


class CheckinStatusOut(BaseModel):
    """`/today` 查询：是否需要弹出主动询问。"""
    enabled: bool
    interval_min: int
    last_checkin_at: datetime | None = None
    minutes_since_last: int | None = None
    should_prompt: bool = False
    today_count: int = 0


def _to_out(r: ElderlyCheckin) -> CheckinOut:
    return CheckinOut(
        id=r.id,
        activity=r.activity,
        body_feeling=r.body_feeling,
        mood=r.mood,
        note=r.note,
        source=r.source,
        prompt_type=r.prompt_type or "combined",
        created_at=r.created_at,
    )


def _get_settings(db: Session, user_id: int) -> UserSettings | None:
    return db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()


@router.get("/today", response_model=CheckinStatusOut)
def today_status(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> CheckinStatusOut:
    uid = int(user_id)
    settings = _get_settings(db, uid)
    enabled = bool(settings and settings.elderly_mode)
    interval = int(settings.elderly_checkin_interval_min) if settings else 180

    last = db.scalars(
        select(ElderlyCheckin)
        .where(ElderlyCheckin.user_id == uid)
        .order_by(desc(ElderlyCheckin.created_at))
        .limit(1)
    ).first()

    last_at = last.created_at if last else None
    mins = None
    should = False
    if enabled:
        if last_at is None:
            should = True
        else:
            now = datetime.now(timezone.utc)
            la = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
            mins = int((now - la).total_seconds() // 60)
            should = mins >= interval

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.scalar(
        select(ElderlyCheckin.id).where(
            ElderlyCheckin.user_id == uid,
            ElderlyCheckin.created_at >= today_start,
        )
    )
    # ↑ scalar returns first id or None; need actual count
    from sqlalchemy import func as _func
    cnt = db.scalar(
        select(_func.count(ElderlyCheckin.id)).where(
            ElderlyCheckin.user_id == uid,
            ElderlyCheckin.created_at >= today_start,
        )
    ) or 0

    return CheckinStatusOut(
        enabled=enabled,
        interval_min=interval,
        last_checkin_at=last_at,
        minutes_since_last=mins,
        should_prompt=should,
        today_count=int(cnt),
    )


@router.post("/checkin", response_model=CheckinOut)
def create_checkin(
    payload: CheckinIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> CheckinOut:
    uid = int(user_id)
    if payload.body_feeling is not None and payload.body_feeling not in BODY_FEELINGS:
        raise HTTPException(status_code=422, detail=f"body_feeling must be one of {BODY_FEELINGS}")
    if payload.mood is not None and payload.mood not in MOODS:
        raise HTTPException(status_code=422, detail=f"mood must be one of {MOODS}")
    if all(v is None or (isinstance(v, str) and not v.strip())
           for v in (payload.activity, payload.body_feeling, payload.mood, payload.note)):
        raise HTTPException(status_code=422, detail="至少填写一项")
    src = payload.source if payload.source in ("auto_prompt", "manual") else "auto_prompt"
    pt = payload.prompt_type if payload.prompt_type in PROMPT_TYPES else "combined"

    # 同一天同一种专项签到（用药/睡眠/饮水/活动）只保留最新一条，避免重复记录。
    if pt in SINGLE_PER_DAY_KINDS:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        existing = db.scalars(
            select(ElderlyCheckin).where(
                ElderlyCheckin.user_id == uid,
                ElderlyCheckin.prompt_type == pt,
                ElderlyCheckin.created_at >= today_start,
            )
        ).all()
        if existing:
            row = existing[0]
            row.activity = (payload.activity or None)
            row.body_feeling = payload.body_feeling
            row.mood = payload.mood
            row.note = (payload.note or None)
            row.source = src
            row.created_at = datetime.now(timezone.utc)
            for extra in existing[1:]:
                db.delete(extra)
            db.commit()
            db.refresh(row)
            return _to_out(row)

    row = ElderlyCheckin(
        user_id=uid,
        prompt_type=pt,
        activity=(payload.activity or None),
        body_feeling=payload.body_feeling,
        mood=payload.mood,
        note=(payload.note or None),
        source=src,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("", response_model=CheckinListOut)
def list_checkins(
    limit: int = Query(default=50, ge=1, le=200),
    days: int = Query(default=30, ge=1, le=365),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> CheckinListOut:
    uid = int(user_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.scalars(
        select(ElderlyCheckin)
        .where(ElderlyCheckin.user_id == uid, ElderlyCheckin.created_at >= since)
        .order_by(desc(ElderlyCheckin.created_at))
        .limit(limit)
    ).all()
    return CheckinListOut(items=[_to_out(r) for r in rows])


@router.delete("/{checkin_id}", status_code=204)
def delete_checkin(
    checkin_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> None:
    uid = int(user_id)
    row = db.scalars(
        select(ElderlyCheckin).where(
            ElderlyCheckin.id == checkin_id,
            ElderlyCheckin.user_id == uid,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="checkin not found")
    db.delete(row)
    db.commit()
