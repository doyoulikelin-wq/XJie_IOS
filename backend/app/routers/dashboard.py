from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.elderly_checkin import ElderlyCheckin
from app.models.exercise_log import ExerciseLog
from app.models.health_document import HealthDocument, HealthSummary
from app.models.health_plan import PlanTask
from app.models.meal import Meal, MealPhoto
from app.models.medication import Medication
from app.models.mood_log import MoodLog
from app.models.user_settings import UserSettings
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


def _source_label(key: str) -> str:
    return {
        "cgm": "CGM",
        "glucose": "血糖",
        "meal": "饮食",
        "plan": "计划",
        "exercise": "运动",
        "checkin": "状态反馈",
        "medication": "用药",
        "health_record": "健康资料",
        "profile": "注册目标",
    }.get(key, key)


def _today_context(db: Session, user_id: str, day=None) -> dict:
    local_day = day or datetime.now(_LOCAL_TZ).date()
    start, end = _local_bounds(local_day)

    meals = db.execute(
        select(Meal).where(Meal.user_id == user_id, Meal.meal_ts >= start, Meal.meal_ts < end)
    ).scalars().all()
    tasks = db.execute(
        select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.date == local_day)
    ).scalars().all()
    exercises = db.execute(
        select(ExerciseLog).where(
            ExerciseLog.user_id == user_id,
            ExerciseLog.started_at >= start,
            ExerciseLog.started_at < end,
        )
    ).scalars().all()
    mood_count = db.execute(
        select(func.count(MoodLog.id)).where(MoodLog.user_id == user_id, MoodLog.ts_date == local_day)
    ).scalar() or 0
    care_count = db.execute(
        select(func.count(ElderlyCheckin.id)).where(
            ElderlyCheckin.user_id == user_id,
            ElderlyCheckin.created_at >= start,
            ElderlyCheckin.created_at < end,
        )
    ).scalar() or 0
    medication_count = db.execute(
        select(func.count(Medication.id)).where(Medication.user_id == user_id, Medication.enabled.is_(True))
    ).scalar() or 0
    health_doc_count = db.execute(
        select(func.count(HealthDocument.id)).where(
            HealthDocument.user_id == user_id,
            HealthDocument.extraction_status == "done",
        )
    ).scalar() or 0
    has_health_summary = bool(db.execute(
        select(HealthSummary.id).where(HealthSummary.user_id == user_id).limit(1)
    ).scalar())
    settings = db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id).limit(1)
    ).scalar_one_or_none()

    def is_done(task: PlanTask) -> bool:
        return task.status == "completed" or int(task.completed_count or 0) >= int(task.target_count or 1)

    completed_tasks = [task for task in tasks if is_done(task)]
    pending_tasks = [task for task in tasks if not is_done(task)]
    source_keys: list[str] = []
    if meals:
        source_keys.append("meal")
    if tasks:
        source_keys.append("plan")
    if exercises:
        source_keys.append("exercise")
    if mood_count or care_count:
        source_keys.append("checkin")
    if medication_count:
        source_keys.append("medication")
    if health_doc_count or has_health_summary:
        source_keys.append("health_record")
    if settings and (settings.onboarding_target or settings.onboarding_contents):
        source_keys.append("profile")

    return {
        "date": local_day,
        "meals_count": len(meals),
        "kcal_today": sum(m.kcal for m in meals),
        "tasks_total": len(tasks),
        "tasks_completed": len(completed_tasks),
        "pending_tasks": pending_tasks,
        "exercise_count": len(exercises),
        "exercise_minutes": sum(int(e.duration_minutes or 0) for e in exercises),
        "mood_count": int(mood_count),
        "care_count": int(care_count),
        "medication_count": int(medication_count),
        "health_doc_count": int(health_doc_count),
        "has_health_summary": has_health_summary,
        "onboarding_target": settings.onboarding_target if settings else None,
        "onboarding_contents": settings.onboarding_contents if settings else [],
        "source_keys": source_keys,
    }


def _behavior_score(context: dict) -> int:
    score = 12
    if context["tasks_total"]:
        score += 24 * (context["tasks_completed"] / max(1, context["tasks_total"]))
    if context["meals_count"]:
        score += 12
    if context["exercise_count"]:
        score += 12
    if context["mood_count"] or context["care_count"]:
        score += 8
    if context["medication_count"]:
        score += 6
    if context["health_doc_count"] or context["has_health_summary"]:
        score += 14
    if context["onboarding_target"] or context["onboarding_contents"]:
        score += 8
    return int(max(0, min(100, round(score))))


def _confidence(summary: dict, context: dict) -> str:
    reading_count = int(summary.get("reading_count") or 0)
    if reading_count >= 48:
        return "high"
    source_count = len(context["source_keys"]) + (1 if reading_count else 0)
    if reading_count >= 4 or source_count >= 3:
        return "medium"
    return "low"


def _confidence_label(confidence: str) -> str:
    return {
        "high": "依据充分",
        "medium": "依据一般",
        "low": "信息较少",
    }.get(confidence, "信息较少")


def _unique_keys(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


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


def _health_level(summary: dict, context: dict) -> str:
    glucose_level = _metabolic_level(summary)
    if glucose_level != "missing":
        return glucose_level
    if not context["source_keys"]:
        return "missing"
    if context["tasks_total"] and context["tasks_completed"] < context["tasks_total"]:
        return "watch"
    if context["meals_count"] == 0 and context["exercise_count"] == 0:
        return "watch"
    return "stable"


def _metabolic_copy(summary: dict, context: dict | None = None) -> tuple[str, str, str]:
    level = _metabolic_level(summary)
    tir = summary.get("tir_70_180_pct")
    max_value = summary.get("max")
    min_value = summary.get("min")
    variability = summary.get("variability")
    if level == "missing":
        if not context or not context["source_keys"]:
            return "先建立今天的健康基线", "还没有 CGM 或今日行为记录，小捷会先从最容易补齐的数据开始。", "先记录今天第一餐，或上传一份体检/病例资料。"
        if context["tasks_total"] and context["tasks_completed"] < context["tasks_total"]:
            task = context["pending_tasks"][0].title if context["pending_tasks"] else "今日计划"
            return "今日计划待推进", f"没有 CGM 时，先依据计划、饮食和健康资料给出低负担行动；今日还有 {context['tasks_total'] - context['tasks_completed']} 项未完成。", f"先完成今日计划：{task}。"
        if context["meals_count"] == 0:
            return "基于健康资料给出建议", "当前没有 CGM，但已有部分健康资料可用于生成基础建议。", "先记录今天第一餐，帮助小捷判断饮食节奏。"
        if context["exercise_count"] == 0:
            return "今日行为已有记录", f"已记录 {context['meals_count']} 餐；没有 CGM 时，运动和饮食记录是判断趋势的关键依据。", "安排 10 分钟轻活动，作为今天的最小行动。"
        return "今日执行较稳定", "虽然没有 CGM 连续数据，但今日饮食、运动或计划记录已能支持基础判断。", "保持记录节奏，晚间补充一次身体状态反馈。"
    if level == "risk":
        return "今日代谢需要关注", f"出现明显异常区间：最低 {min_value or '--'} mg/dL，最高 {max_value or '--'} mg/dL。", "先记录最近一餐和身体感受，必要时按既定医疗建议处理。"
    if level == "watch":
        reason = f"TIR {tir or 0:.0f}%，波动等级 {variability or 'unknown'}，提示今天仍有可优化空间。"
        return "今日有代谢波动", reason, "优先完成一次餐后 20 分钟轻活动，并补记饮食。"
    return "今日血糖较平稳", f"TIR {tir or 0:.0f}%，血糖主要停留在目标范围内。", "保持当前饮食节奏，晚间避免过量加餐。"


def _metabolic_overview(db: Session, user_id: str, days: int = 7) -> list[dict]:
    today_local = datetime.now(_LOCAL_TZ).date()
    result = []
    for offset in range(days - 1, -1, -1):
        day = today_local - timedelta(days=offset)
        start, end = _local_bounds(day)
        summary = _summary_between(db, user_id, start, end)
        context = _today_context(db, user_id, day)
        headline, reason, action = _metabolic_copy(summary, context)
        confidence = _confidence(summary, context)
        source_keys = _unique_keys((["cgm"] if int(summary.get("reading_count") or 0) >= 48 else (["glucose"] if summary.get("reading_count") else [])) + context["source_keys"])
        score = _metabolic_score(summary) if summary.get("reading_count") else _behavior_score(context)
        result.append({
            "date": day.isoformat(),
            "level": _health_level(summary, context),
            "score": score,
            "headline": headline,
            "reason": reason,
            "action": action,
            "confidence": confidence,
            "data_sources": [_source_label(k) for k in source_keys],
            "missing_sources": [_source_label(k) for k in ("cgm", "meal", "plan") if k not in source_keys],
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
    context = _today_context(db, user_id)
    headline, reason, action = _metabolic_copy(today, context)
    reading_count = int(today.get("reading_count") or 0)
    glucose_sources = ["cgm"] if reading_count >= 48 else (["glucose"] if reading_count else [])
    source_keys = _unique_keys(glucose_sources + context["source_keys"])
    confidence = _confidence(today, context)
    score = _metabolic_score(today) if reading_count else _behavior_score(context)
    return {
        "title": "今日健康状态",
        "date": datetime.now(_LOCAL_TZ).date().isoformat(),
        "level": _health_level(today, context),
        "score": score,
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "data_sources": [_source_label(k) for k in source_keys],
        "missing_sources": [_source_label(k) for k in ("cgm", "meal", "plan", "health_record") if k not in source_keys],
        "primary_basis": _source_label(source_keys[0]) if source_keys else "待补数据",
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
            "meals_count": context["meals_count"],
            "kcal_today": context["kcal_today"],
            "tasks_total": context["tasks_total"],
            "tasks_completed": context["tasks_completed"],
            "exercise_minutes": context["exercise_minutes"],
            "mood_count": context["mood_count"],
            "care_count": context["care_count"],
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
