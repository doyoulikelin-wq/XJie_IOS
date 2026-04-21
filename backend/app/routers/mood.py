"""Mood emoji 5-segment check-in API.

Endpoints (mounted under /api/mood):
    POST   /logs               upsert one segment
    GET    /logs?days=7        flat list of logs
    GET    /days?days=7        per-day 5-segment snapshots + daily avg
    GET    /correlation?days=14   Pearson r vs glucose

The 5 segments map to fixed clock windows used for matching with glucose:
    morning   06:00-10:00
    noon      10:00-14:00
    afternoon 14:00-17:00
    evening   17:00-21:00
    night     21:00-26:00 (overflows into next day)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.glucose import GlucoseReading
from app.models.mood_log import SEGMENTS, MoodLog
from app.schemas.mood_log import MoodDay, MoodGlucoseCorrelation, MoodLogIn, MoodLogOut

router = APIRouter()

# Clock windows (24h) for matching mood segments to glucose readings.
SEGMENT_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (6, 10),
    "noon": (10, 14),
    "afternoon": (14, 17),
    "evening": (17, 21),
    "night": (21, 26),  # 02:00 next day; handled by modulo in matcher
}


def _validate_segment(segment: str) -> None:
    if segment not in SEGMENTS:
        raise HTTPException(status_code=400, detail=f"segment must be one of {SEGMENTS}")


@router.post("/logs", response_model=MoodLogOut)
def upsert_mood_log(
    payload: MoodLogIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MoodLogOut:
    _validate_segment(payload.segment)
    ts_date = payload.ts.date()
    existing = db.execute(
        select(MoodLog).where(
            MoodLog.user_id == user_id,
            MoodLog.ts_date == ts_date,
            MoodLog.segment == payload.segment,
        )
    ).scalar_one_or_none()

    if existing is None:
        row = MoodLog(
            user_id=user_id,
            ts=payload.ts,
            ts_date=ts_date,
            segment=payload.segment,
            mood_level=payload.mood_level,
            note=payload.note,
        )
        db.add(row)
    else:
        existing.ts = payload.ts
        existing.mood_level = payload.mood_level
        existing.note = payload.note
        row = existing
    db.commit()
    db.refresh(row)
    return MoodLogOut(
        id=row.id,
        ts=row.ts,
        ts_date=row.ts_date,
        segment=row.segment,
        mood_level=row.mood_level,
        note=row.note,
    )


@router.get("/logs", response_model=list[MoodLogOut])
def list_mood_logs(
    days: int = Query(7, ge=1, le=90),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[MoodLogOut]:
    since = date.today() - timedelta(days=days - 1)
    rows = db.execute(
        select(MoodLog)
        .where(MoodLog.user_id == user_id, MoodLog.ts_date >= since)
        .order_by(MoodLog.ts.desc())
    ).scalars().all()
    return [
        MoodLogOut(
            id=r.id,
            ts=r.ts,
            ts_date=r.ts_date,
            segment=r.segment,
            mood_level=r.mood_level,
            note=r.note,
        )
        for r in rows
    ]


@router.get("/days", response_model=list[MoodDay])
def get_mood_days(
    days: int = Query(7, ge=1, le=90),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[MoodDay]:
    since = date.today() - timedelta(days=days - 1)
    rows = db.execute(
        select(MoodLog)
        .where(MoodLog.user_id == user_id, MoodLog.ts_date >= since)
        .order_by(MoodLog.ts_date.asc())
    ).scalars().all()

    # Build a date -> {segment: level} map
    by_day: dict[date, dict[str, int]] = {}
    for r in rows:
        by_day.setdefault(r.ts_date, {})[r.segment] = r.mood_level

    out: list[MoodDay] = []
    for i in range(days):
        d = since + timedelta(days=i)
        slots = by_day.get(d, {})
        levels = [slots[s] for s in SEGMENTS if s in slots]
        avg = round(sum(levels) / len(levels), 2) if levels else None
        out.append(
            MoodDay(
                date=d,
                morning=slots.get("morning"),
                noon=slots.get("noon"),
                afternoon=slots.get("afternoon"),
                evening=slots.get("evening"),
                night=slots.get("night"),
                avg=avg,
            )
        )
    return out


@router.delete("/logs/{log_id}", status_code=204)
def delete_mood_log(
    log_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> None:
    row = db.execute(
        select(MoodLog).where(MoodLog.id == log_id, MoodLog.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="mood log not found")
    db.delete(row)
    db.commit()


# ---------- correlation with glucose -----------------------------------------


def _segment_glucose_avg(
    readings: Iterable[GlucoseReading], target_date: date, segment: str
) -> float | None:
    start_hour, end_hour = SEGMENT_WINDOWS[segment]
    # Window is [start_hour, end_hour) on target_date; for night (21,26) the
    # tail extends into target_date+1 0:00..2:00.
    start = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=start_hour)
    if end_hour <= 24:
        end = start.replace(hour=end_hour)
    else:
        end = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=end_hour - 24
        )
    bucket = [
        r.glucose_mgdl
        for r in readings
        if r.ts is not None and start <= r.ts.astimezone(timezone.utc) < end
    ]
    if not bucket:
        return None
    return sum(bucket) / len(bucket)


def _interpret_pearson(r: float, p: float | None) -> str:
    if p is not None and p > 0.05:
        return "无显著相关"
    abs_r = abs(r)
    direction = "正" if r > 0 else "负"
    if abs_r < 0.2:
        return "无明显相关"
    if abs_r < 0.4:
        return f"弱{direction}相关"
    if abs_r < 0.6:
        return f"中等{direction}相关"
    return f"强{direction}相关"


@router.get("/correlation", response_model=MoodGlucoseCorrelation)
def mood_glucose_correlation(
    days: int = Query(14, ge=3, le=90),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MoodGlucoseCorrelation:
    since = date.today() - timedelta(days=days - 1)
    moods = db.execute(
        select(MoodLog).where(MoodLog.user_id == user_id, MoodLog.ts_date >= since)
    ).scalars().all()
    if not moods:
        return MoodGlucoseCorrelation(days=days, paired_samples=0, interpretation="暂无情绪打卡数据")

    # Pull glucose readings spanning the same window (+1 day for night tail)
    g_start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    g_end = datetime.combine(date.today() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    glucose = db.execute(
        select(GlucoseReading)
        .where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.ts >= g_start,
            GlucoseReading.ts < g_end,
        )
    ).scalars().all()

    pairs: list[tuple[int, float]] = []
    for m in moods:
        avg = _segment_glucose_avg(glucose, m.ts_date, m.segment)
        if avg is not None:
            pairs.append((m.mood_level, avg))

    if len(pairs) < 5:
        return MoodGlucoseCorrelation(
            days=days,
            paired_samples=len(pairs),
            interpretation=f"配对样本不足 5 对（当前 {len(pairs)}），暂无法计算相关",
        )

    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is a hard dep
        return MoodGlucoseCorrelation(
            days=days, paired_samples=len(pairs), interpretation="计算依赖缺失"
        )
    x = np.array([p[0] for p in pairs], dtype=float)
    y = np.array([p[1] for p in pairs], dtype=float)
    if x.std() == 0 or y.std() == 0:
        return MoodGlucoseCorrelation(
            days=days,
            paired_samples=len(pairs),
            pearson_r=0.0,
            interpretation="样本无方差，无法计算相关",
        )
    r = float(np.corrcoef(x, y)[0, 1])
    # Approximate p-value via t-distribution; use scipy if present, else None.
    p_value: float | None = None
    try:
        from scipy import stats

        n = len(pairs)
        if n > 2 and abs(r) < 1.0:
            t = r * (n - 2) ** 0.5 / (1 - r * r) ** 0.5
            p_value = float(2 * (1 - stats.t.cdf(abs(t), df=n - 2)))
    except Exception:
        p_value = None

    return MoodGlucoseCorrelation(
        days=days,
        paired_samples=len(pairs),
        pearson_r=round(r, 4),
        p_value=round(p_value, 4) if p_value is not None else None,
        interpretation=_interpret_pearson(r, p_value),
    )
