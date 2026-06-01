from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.health_plan import PlanTask
from app.models.meal import Meal, MealPhoto
from app.services.glucose_service import compute_gaps_hours, compute_tir, get_glucose_points, get_glucose_summary, variability_label

router = APIRouter()

_LOCAL_TZ = timezone(timedelta(hours=8))


def _local_bounds(day) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=_LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _summary_between(db: Session, user_id: str, start: datetime, end: datetime) -> dict:
    rows = get_glucose_points(db, user_id, start, end)
    readings = [row.glucose_mgdl for row in rows]
    ts = [row.ts for row in rows]
    return {
        "avg": round(sum(readings) / len(readings), 2) if readings else None,
        "min": min(readings) if readings else None,
        "max": max(readings) if readings else None,
        "tir_70_180_pct": round(compute_tir(readings), 2) if readings else None,
        "variability": variability_label(readings),
        "gaps_hours": compute_gaps_hours(ts),
        "reading_count": len(readings),
    }


def _metabolic_score(summary: dict) -> int:
    if not summary.get("reading_count"):
        return 0
    tir = float(summary.get("tir_70_180_pct") or 0)
    score = min(55, tir * 0.55)
    if summary.get("avg") is not None:
        avg = float(summary["avg"])
        score += max(0, 20 - abs(avg - 112) * 0.25)
    if summary.get("max") and summary["max"] <= 180:
        score += 10
    if summary.get("min") and summary["min"] >= 70:
        score += 8
    score += {"low": 7, "medium": 4, "high": 0}.get(summary.get("variability"), 2)
    if float(summary.get("gaps_hours") or 0) > 2:
        score -= 8
    return int(max(0, min(100, round(score))))


def _metabolic_level(summary: dict) -> str:
    if not summary.get("reading_count"):
        return "missing"
    if (summary.get("min") or 999) < 70 or (summary.get("max") or 0) > 250:
        return "risk"
    if (summary.get("tir_70_180_pct") or 0) < 70 or summary.get("variability") == "high":
        return "watch"
    if (summary.get("tir_70_180_pct") or 0) >= 85:
        return "stable"
    return "watch"


def _metabolic_copy(summary: dict) -> tuple[str, str, str]:
    level = _metabolic_level(summary)
    if level == "missing":
        return "等待 CGM 数据", "今天还没有足够连续血糖读数。", "连接或同步 CGM，先完成今天的数据基线。"
    tir = summary.get("tir_70_180_pct")
    max_value = summary.get("max")
    min_value = summary.get("min")
    variability = summary.get("variability")
    if level == "risk":
        return "今日代谢需要关注", f"出现明显异常区间：最低 {min_value or '--'} mg/dL，最高 {max_value or '--'} mg/dL。", "先记录最近一餐和身体感受，必要时按既定医疗建议处理。"
    if level == "watch":
        reason = f"TIR {tir or 0:.0f}%，波动等级 {variability or 'unknown'}，提示今天仍有可优化空间。"
        return "今日有代谢波动", reason, "优先完成一次餐后 20 分钟轻活动，并补记饮食。"
    return "今日代谢较平稳", f"TIR {tir or 0:.0f}%，血糖主要停留在目标范围内。", "保持当前饮食节奏，晚间避免过量加餐。"


def _metabolic_overview(db: Session, user_id: str, days: int = 7) -> list[dict]:
    today_local = datetime.now(_LOCAL_TZ).date()
    result = []
    for offset in range(days - 1, -1, -1):
        day = today_local - timedelta(days=offset)
        start, end = _local_bounds(day)
        summary = _summary_between(db, user_id, start, end)
        headline, reason, action = _metabolic_copy(summary)
        result.append({
            "date": day.isoformat(),
            "level": _metabolic_level(summary),
            "score": _metabolic_score(summary),
            "headline": headline,
            "reason": reason,
            "action": action,
            "avg": summary.get("avg"),
            "tir_70_180_pct": summary.get("tir_70_180_pct"),
            "reading_count": summary.get("reading_count", 0),
        })
    return result


def _cgm_quality(db: Session, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=14)
    rows = get_glucose_points(db, user_id, start, now)
    reading_count = len(rows)
    timestamps = [row.ts for row in rows]
    expected = 14 * 24 * 12
    active_days = len({row.ts.astimezone(_LOCAL_TZ).date().isoformat() for row in rows})
    completeness = min(100, round(reading_count / expected * 100)) if expected else 0
    gaps = compute_gaps_hours(timestamps)
    latest = max(timestamps).isoformat() if timestamps else None
    status = "good" if completeness >= 80 and active_days >= 10 else ("watch" if reading_count else "missing")
    message = (
        "连续数据质量良好，可用于代谢状态判断。"
        if status == "good"
        else ("数据仍有缺口，建议检查 CGM 同步。" if status == "watch" else "尚未检测到 CGM 连续数据。")
    )
    return {
        "window_days": 14,
        "active_days": active_days,
        "reading_count": reading_count,
        "expected_readings": expected,
        "completeness_pct": completeness,
        "gap_hours": gaps,
        "latest_ts": latest,
        "status": status,
        "message": message,
    }


def _weekly_validation(db: Session, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    current = _summary_between(db, user_id, now - timedelta(days=7), now)
    previous = _summary_between(db, user_id, now - timedelta(days=14), now - timedelta(days=7))
    total, completed = db.execute(
        select(
            func.count(PlanTask.id),
            func.coalesce(func.sum(case((PlanTask.status == "completed", 1), else_=0)), 0),
        ).where(
            PlanTask.user_id == user_id,
            PlanTask.date >= (datetime.now(_LOCAL_TZ).date() - timedelta(days=6)),
            PlanTask.date <= datetime.now(_LOCAL_TZ).date(),
        )
    ).first()
    total = int(total or 0)
    completed = int(completed or 0)
    adherence = round(completed / total * 100) if total else 0
    tir_delta = None
    if current.get("tir_70_180_pct") is not None and previous.get("tir_70_180_pct") is not None:
        tir_delta = round(current["tir_70_180_pct"] - previous["tir_70_180_pct"], 1)
    avg_delta = None
    if current.get("avg") is not None and previous.get("avg") is not None:
        avg_delta = round(current["avg"] - previous["avg"], 1)
    if total == 0 and current.get("reading_count", 0) == 0:
        headline = "等待本周验证数据"
    elif tir_delta is not None and tir_delta > 3:
        headline = "本周控糖结果改善"
    elif adherence >= 70:
        headline = "执行情况稳定"
    else:
        headline = "本周仍需提高执行率"
    return {
        "headline": headline,
        "adherence_pct": adherence,
        "completed_actions": completed,
        "total_actions": total,
        "tir_delta_pct": tir_delta,
        "avg_delta_mgdl": avg_delta,
        "summary": f"完成 {completed}/{total} 项计划；TIR 较上周 {tir_delta:+.1f}%" if tir_delta is not None else f"完成 {completed}/{total} 项计划。",
    }


def _metabolic_state(db: Session, user_id: str) -> dict:
    now = datetime.now(timezone.utc)
    today = _summary_between(db, user_id, now - timedelta(hours=24), now)
    headline, reason, action = _metabolic_copy(today)
    return {
        "date": datetime.now(_LOCAL_TZ).date().isoformat(),
        "level": _metabolic_level(today),
        "score": _metabolic_score(today),
        "headline": headline,
        "reason": reason,
        "action": action,
        "metrics": {
            "avg": today.get("avg"),
            "tir_70_180_pct": today.get("tir_70_180_pct"),
            "min": today.get("min"),
            "max": today.get("max"),
            "variability": today.get("variability"),
            "reading_count": today.get("reading_count", 0),
        },
        "overview": _metabolic_overview(db, user_id),
    }


@router.get("/health")
def dashboard_health(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    summary_24h = get_glucose_summary(db, user_id, "24h")
    summary_7d = get_glucose_summary(db, user_id, "7d")

    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    meals_today = db.execute(
        select(Meal)
        .where(Meal.user_id == user_id, Meal.meal_ts >= day_start, Meal.meal_ts < now)
        .order_by(Meal.meal_ts.asc())
    ).scalars().all()

    return {
        "glucose": {
            "last_24h": summary_24h,
            "last_7d": summary_7d,
        },
        "kcal_today": sum(m.kcal for m in meals_today),
        "meals_today": [
            {
                "id": str(m.id),
                "ts": m.meal_ts,
                "kcal": m.kcal,
                "tags": m.tags,
                "source": m.meal_ts_source.value,
            }
            for m in meals_today
        ],
        "data_quality": {
            "glucose_gaps_hours": summary_24h["gaps_hours"],
            "variability": summary_24h["variability"],
        },
        "metabolic_state": _metabolic_state(db, user_id),
        "weekly_validation": _weekly_validation(db, user_id),
        "cgm_quality": _cgm_quality(db, user_id),
    }


@router.get("/meals")
def dashboard_meals(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    rows = db.execute(
        select(MealPhoto)
        .where(MealPhoto.user_id == user_id)
        .order_by(MealPhoto.uploaded_at.desc())
        .limit(50)
    ).scalars().all()

    return [
        {
            "id": str(photo.id),
            "uploaded_at": photo.uploaded_at,
            "status": photo.status.value,
            "calorie_estimate_kcal": photo.calorie_estimate_kcal,
            "confidence": photo.confidence,
            "vision_json": photo.vision_json,
        }
        for photo in rows
    ]


@router.get("/chat_threads")
def dashboard_chat_threads():
    return []
