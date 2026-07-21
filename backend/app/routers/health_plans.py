"""Health plan persistence and health-tree weekly execution dashboard."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.exercise_log import ExerciseLog
from app.models.health_plan import HealthPlan, PlanAIRevision, PlanTask, PlanTaskEvent
from app.models.meal import Meal
from app.models.medication import Medication
from app.models.omics import OmicsUpload
from app.providers.factory import get_provider
from app.schemas.health_plan import (
    HealthTreeSummaryOut,
    HealthPlanDetailOut,
    HealthPlanFromChatIn,
    HealthPlanQuestionnaireIn,
    HealthPlanListOut,
    HealthPlanOut,
    PlanRevisionApplyIn,
    PlanRevisionGenerateIn,
    PlanRevisionItemOut,
    PlanRevisionProposalOut,
    PlanRevisionReasonOut,
    PlanTaskOut,
    PlanTaskUpdateIn,
    TubeCompleteIn,
    TubeCompleteOut,
    TubeDayOut,
    TubeTaskProgress,
    TubeWeekOut,
)
from app.services.context_builder import build_user_context

router = APIRouter()

_LOCAL_TZ = timezone(timedelta(hours=8))
_TYPES = ("exercise", "medication", "diet", "hydration", "sleep")
_TYPE_LABELS = {
    "exercise": "运动",
    "medication": "服药",
    "diet": "饮食",
    "hydration": "饮水",
    "sleep": "睡眠",
    "measurement": "监测",
}
_CONTENT_LABELS = {
    "fitness": "健身",
    "diet_control": "饮食控制",
    "sleep": "睡眠",
    "hydration": "饮水",
    "medication": "用药",
}
_FREQUENCY_LABELS = {
    "daily": "每天",
    "three_per_week": "每周 3 次",
    "five_per_week": "每周 5 次",
    "weekdays": "工作日",
}


def _today() -> date:
    return datetime.now(_LOCAL_TZ).date()


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


def _local_bounds(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=_LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _active_plan_code_map(db: Session, user_id: int) -> dict[int, str]:
    plans = db.execute(
        select(HealthPlan)
        .where(HealthPlan.user_id == user_id, HealthPlan.status == "active")
        .order_by(HealthPlan.start_date.asc(), HealthPlan.id.asc())
    ).scalars().all()
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return {plan.id: letters[idx] if idx < len(letters) else f"P{idx + 1}" for idx, plan in enumerate(plans)}


def _task_snapshot(task: PlanTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "plan_id": str(task.plan_id) if task.plan_id else None,
        "date": task.date.isoformat(),
        "task_type": _effective_task_type(task),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "target_count": task.target_count,
        "completed_count": task.completed_count,
        "target_value": task.target_value,
        "completed_value": task.completed_value,
        "unit": task.unit,
        "reminder_time": task.reminder_time,
        "source_type": task.source_type,
        "source_ref": task.source_ref,
    }


def _log_plan_event(
    db: Session,
    *,
    user_id: int,
    event_type: str,
    purpose: str,
    task: PlanTask | None = None,
    task_type: str | None = None,
    day: date | None = None,
    execution_item: str | None = None,
    execution_status: str | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
) -> None:
    db.add(PlanTaskEvent(
        user_id=user_id,
        plan_id=task.plan_id if task else None,
        task_id=task.id if task else None,
        date=day or (task.date if task else None),
        task_type=task_type or (_effective_task_type(task) if task else None),
        event_type=event_type,
        purpose=purpose,
        execution_item=execution_item or (task.title if task else None),
        execution_status=execution_status or (task.status if task else None),
        before_data=before_data or {},
        after_data=after_data or (_task_snapshot(task) if task else {}),
    ))


def _task_to_out(task: PlanTask) -> PlanTaskOut:
    return PlanTaskOut(
        id=str(task.id),
        plan_id=str(task.plan_id) if task.plan_id else None,
        date=task.date,
        task_type=task.task_type,
        title=task.title,
        description=task.description,
        status=task.status,
        target_count=task.target_count,
        completed_count=task.completed_count,
        target_value=task.target_value,
        completed_value=task.completed_value,
        unit=task.unit,
        reminder_time=task.reminder_time,
        source_type=task.source_type,
        source_ref=task.source_ref,
    )


def _plan_to_out(db: Session, plan: HealthPlan, plan_code: str | None = None) -> HealthPlanOut:
    totals = db.execute(
        select(
            func.count(PlanTask.id),
            func.coalesce(func.sum(case((PlanTask.status == "completed", 1), else_=0)), 0),
        ).where(PlanTask.plan_id == plan.id)
    ).first()
    task_count = int(totals[0] or 0) if totals else 0
    completed_count = int(totals[1] or 0) if totals else 0
    return HealthPlanOut(
        id=str(plan.id),
        plan_code=plan_code,
        title=plan.title,
        goal=plan.goal,
        background=plan.background,
        start_date=plan.start_date,
        end_date=plan.end_date,
        status=plan.status,
        source_conversation_id=plan.source_conversation_id,
        source_message_id=plan.source_message_id,
        created_by=plan.created_by,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        task_count=task_count,
        completed_task_count=completed_count,
    )


def _title_from_text(text: str) -> str:
    first = re.sub(r"^[#>*\-\s]+", "", text.strip().splitlines()[0] if text.strip() else "")
    first = re.sub(r"[*_`]+", "", first).strip(" ：:。")
    if 4 <= len(first) <= 34:
        return first
    if "控糖" in text:
        return "一周控糖健康计划"
    if "饮食" in text:
        return "一周饮食执行计划"
    if "康复" in text:
        return "一周康复执行计划"
    if "运动" in text:
        return "一周运动执行计划"
    return "一周健康执行计划"


def _goal_from_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return "把 AI 建议拆成每天可执行的饮食、运动和用药任务。"
    return compact[:120].rstrip("，。；;") + ("..." if len(compact) > 120 else "")


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _has_medication_need(text: str) -> bool:
    negative_words = ("无用药", "没有用药", "不用药", "无需用药", "不需要用药")
    med_words = ("用药", "服药", "药物", "药片", "补剂", "胰岛素", "降糖药")
    return _has_any(text, med_words) and not _has_any(text, negative_words)


def _effective_task_type(task: PlanTask) -> str:
    if task.task_type == "measurement":
        marker = f"{task.source_ref or ''} {task.title or ''} {task.description or ''}"
        if _has_any(marker, ("hydration", "饮水", "喝水", "补水", "水分", "水量")):
            return "hydration"
        if _has_any(marker, ("sleep", "睡眠", "入睡", "睡觉", "作息", "熬夜", "起床")):
            return "sleep"
    return task.task_type


def _requested_task_types(content: str) -> tuple[str, ...]:
    wants = {
        "exercise": _has_any(content, ("运动", "步行", "训练", "拉伸", "康复", "健身", "游泳", "骑行")),
        "medication": _has_medication_need(content),
        "diet": _has_any(content, ("饮食", "三餐", "早餐", "午餐", "晚餐", "热量", "控糖", "卡路里")),
        "hydration": _has_any(content, ("饮水", "喝水", "补水", "水分", "水量")),
        "sleep": _has_any(content, ("睡眠", "入睡", "睡觉", "作息", "熬夜", "起床")),
    }
    if not any(wants.values()):
        wants["exercise"] = True
        wants["diet"] = True
    return tuple(task_type for task_type in _TYPES if wants.get(task_type))


def _seed_plan_tasks(db: Session, plan: HealthPlan, content: str) -> None:
    requested_types = _requested_task_types(content)

    for idx, day in enumerate(_days(plan.start_date, (plan.end_date - plan.start_date).days + 1), start=1):
        day_label = f"第 {idx} 天"
        if "exercise" in requested_types:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="exercise",
                title=f"{day_label} 运动任务",
                description="完成一次计划内运动，可选择饭后步行、拉伸、康复动作或其他已约定训练。",
                target_count=1,
                source_type="plan",
                source_ref=f"plan:{plan.id}:{day}:exercise",
            ))
        if "medication" in requested_types:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="medication",
                title=f"{day_label} 用药提醒",
                description="按医生或药品说明完成今日用药/补剂记录。",
                target_count=1,
                source_type="plan",
                source_ref=f"plan:{plan.id}:{day}:medication",
            ))
        if "diet" in requested_types:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="diet",
                title=f"{day_label} 饮食计划",
                description="按计划完成饮食记录，优先选择低负担、控糖友好的食物。",
                target_count=3,
                target_value=1400.0,
                unit="kcal",
                source_type="plan",
                source_ref=f"plan:{plan.id}:{day}:diet",
            ))
        if "hydration" in requested_types:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="hydration",
                title=f"{day_label} 饮水计划",
                description="按计划完成饮水记录；如医生限制饮水量，以医嘱为准。",
                target_count=6,
                unit="杯",
                source_type="plan",
                source_ref=f"plan:{plan.id}:{day}:hydration",
            ))
        if "sleep" in requested_types:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="sleep",
                title=f"{day_label} 睡眠作息",
                description="按计划完成睡眠与作息目标，优先保证固定入睡和起床时间。",
                target_count=1,
                reminder_time="22:30",
                source_type="plan",
                source_ref=f"plan:{plan.id}:{day}:sleep",
            ))


def _questionnaire_summary(payload: HealthPlanQuestionnaireIn) -> str:
    labels = [_CONTENT_LABELS.get(item, item) for item in payload.contents]
    med_text = "需要用药" if payload.medication_needed else "无用药需求"
    lines = [
        f"目标：{payload.target}",
        f"周期：{payload.duration_days} 天",
        f"频次：{_FREQUENCY_LABELS.get(payload.frequency, payload.frequency)}",
        f"涉及内容：{'、'.join(labels) if labels else '综合健康'}",
        f"用药：{med_text}",
    ]
    if payload.notes:
        lines.append(f"补充说明：{payload.notes.strip()}")
    return "\n".join(lines)


def _active_days_for_frequency(start: date, duration_days: int, frequency: str) -> set[date]:
    days = _days(start, duration_days)
    if frequency == "three_per_week":
        return {day for idx, day in enumerate(days) if idx % 7 in (0, 2, 4)}
    if frequency == "five_per_week":
        return {day for idx, day in enumerate(days) if idx % 7 in (0, 1, 2, 3, 4)}
    if frequency == "weekdays":
        return {day for day in days if day.weekday() < 5}
    return set(days)


def _seed_questionnaire_tasks(db: Session, plan: HealthPlan, payload: HealthPlanQuestionnaireIn) -> None:
    contents = set(payload.contents or [])
    if not contents:
        contents = {"fitness", "diet_control"}
    if not payload.medication_needed:
        contents.discard("medication")

    active_days = _active_days_for_frequency(plan.start_date, (plan.end_date - plan.start_date).days + 1, payload.frequency)
    for idx, day in enumerate(_days(plan.start_date, (plan.end_date - plan.start_date).days + 1), start=1):
        if day not in active_days:
            continue
        day_label = f"第 {idx} 天"
        if "fitness" in contents:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="exercise",
                title=f"{day_label} 健身/运动",
                description="按问卷目标完成一次计划内运动或康复训练。",
                target_count=1,
                source_type="questionnaire",
                source_ref=f"questionnaire:{plan.id}:{day}:exercise",
            ))
        if "diet_control" in contents:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="diet",
                title=f"{day_label} 饮食控制",
                description="完成饮食记录并按计划控制总热量、碳水和进餐节奏。",
                target_count=3,
                target_value=1400.0,
                unit="kcal",
                source_type="questionnaire",
                source_ref=f"questionnaire:{plan.id}:{day}:diet",
            ))
        if "hydration" in contents:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="hydration",
                title=f"{day_label} 饮水计划",
                description="按自身情况完成饮水记录；如医生限制饮水量，以医嘱为准。",
                target_count=6,
                unit="杯",
                source_type="questionnaire",
                source_ref=f"questionnaire:{plan.id}:{day}:hydration",
            ))
        if "sleep" in contents:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="sleep",
                title=f"{day_label} 睡眠作息",
                description="记录睡眠与作息执行情况，优先保证固定入睡和起床时间。",
                target_count=1,
                reminder_time="22:30",
                source_type="questionnaire",
                source_ref=f"questionnaire:{plan.id}:{day}:sleep",
            ))
        if "medication" in contents and payload.medication_needed:
            db.add(PlanTask(
                user_id=plan.user_id,
                plan_id=plan.id,
                date=day,
                task_type="medication",
                title=f"{day_label} 用药提醒",
                description="仅按医生或本人确认的用药方案执行。",
                target_count=1,
                source_type="questionnaire",
                source_ref=f"questionnaire:{plan.id}:{day}:medication",
            ))


def _task_exists(db: Session, user_id: int, day: date, task_type: str, source_type: str, source_ref: str) -> bool:
    return db.execute(
        select(PlanTask.id).where(
            PlanTask.user_id == user_id,
            PlanTask.date == day,
            PlanTask.task_type == task_type,
            PlanTask.source_type == source_type,
            PlanTask.source_ref == source_ref,
        ).limit(1)
    ).first() is not None


def _ensure_week_tasks(db: Session, user_id: int, start: date, end: date) -> None:
    today = _today()
    meds = db.execute(
        select(Medication).where(Medication.user_id == user_id, Medication.enabled.is_(True))
    ).scalars().all()

    for day in _days(start, (end - start).days + 1):
        if day > today:
            continue

        has_plan_tasks = db.execute(
            select(PlanTask.id).where(
                PlanTask.user_id == user_id,
                PlanTask.date == day,
                PlanTask.source_type == "plan",
            ).limit(1)
        ).first() is not None

        if not has_plan_tasks:
            if not db.execute(
                select(PlanTask.id).where(
                    PlanTask.user_id == user_id,
                    PlanTask.date == day,
                    PlanTask.task_type == "diet",
                ).limit(1)
            ).first():
                db.add(PlanTask(
                    user_id=user_id,
                    date=day,
                    task_type="diet",
                    title="完成今日饮食计划",
                    description="完成三餐计划或饮食记录，为健康树浇水补给。",
                    target_count=3,
                    target_value=1400.0,
                    unit="kcal",
                    source_type="daily_default",
                    source_ref=f"default:{day}:diet",
                ))

            if not db.execute(
                select(PlanTask.id).where(
                    PlanTask.user_id == user_id,
                    PlanTask.date == day,
                    PlanTask.task_type == "exercise",
                ).limit(1)
            ).first():
                db.add(PlanTask(
                    user_id=user_id,
                    date=day,
                    task_type="exercise",
                    title="完成今日运动任务",
                    description="完成一次轻中等强度运动或康复动作。",
                    target_count=1,
                    source_type="daily_default",
                    source_ref=f"default:{day}:exercise",
                ))

        active_meds = [
            m for m in meds
            if (m.course_start is None or m.course_start <= day)
            and (m.course_end is None or m.course_end >= day)
        ]
        if active_meds:
            for med in active_meds:
                target = max(len(med.schedule_times or []), 1)
                source_ref = f"medication:{med.id}:{day}"
                if _task_exists(db, user_id, day, "medication", "medication", source_ref):
                    continue
                db.add(PlanTask(
                    user_id=user_id,
                    date=day,
                    task_type="medication",
                    title=f"按时服用 {med.name}",
                    description=med.instructions or med.frequency or med.dosage,
                    target_count=target,
                    reminder_time=(med.schedule_times or [None])[0],
                    source_type="medication",
                    source_ref=source_ref,
                ))

    db.commit()


def _external_day_metrics(db: Session, user_id: int, day: date) -> dict[str, dict[str, float]]:
    start, end = _local_bounds(day)
    meals = db.execute(
        select(func.count(Meal.id), func.coalesce(func.sum(Meal.kcal), 0))
        .where(Meal.user_id == user_id, Meal.meal_ts >= start, Meal.meal_ts < end)
    ).first()
    exercises = db.execute(
        select(func.count(ExerciseLog.id), func.coalesce(func.sum(ExerciseLog.calories_kcal), 0))
        .where(ExerciseLog.user_id == user_id, ExerciseLog.started_at >= start, ExerciseLog.started_at < end)
    ).first()
    return {
        "diet": {"count": float(meals[0] or 0), "value": float(meals[1] or 0)},
        "exercise": {"count": float(exercises[0] or 0), "value": float(exercises[1] or 0)},
    }


def _task_detail_lines(
    task_type: str,
    typed: list[PlanTask],
    completed: int,
    target: int,
    completed_value: float | None,
    target_value: float | None,
    unit: str | None,
) -> tuple[str | None, str | None, str | None, list[str]]:
    first = typed[0] if typed else None
    title = first.title if first else _TYPE_LABELS.get(task_type, task_type)
    description = first.description if first else None
    details: list[str] = []

    if task_type == "diet":
        if completed_value is not None and target_value is not None:
            summary = f"{completed}/{target} 餐，{int(completed_value)}/{int(target_value)} kcal"
        else:
            summary = f"{completed}/{target} 餐"
    elif task_type == "exercise":
        summary = f"{completed}/{target} 次"
        if completed_value is not None:
            summary += f"，{int(completed_value)} kcal"
    elif task_type == "medication":
        summary = f"{completed}/{target} 次"
    else:
        summary = f"{completed}/{target}"

    for task in typed[:6]:
        line = task.title
        extras: list[str] = []
        if task.description:
            extras.append(task.description)
        if task.reminder_time:
            extras.append(f"{task.reminder_time} 提醒")
        if task.target_value and task.unit:
            extras.append(f"目标 {int(task.target_value)} {task.unit}")
        if extras:
            line = f"{line}：{'；'.join(extras)}"
        details.append(line)

    if not details and description:
        details.append(description)

    return title, description, summary, details


def _progress_for_type(
    tasks: list[PlanTask],
    task_type: str,
    metrics: dict[str, dict[str, float]],
    plan_code_map: dict[int, str] | None = None,
) -> TubeTaskProgress:
    typed = [t for t in tasks if _effective_task_type(t) == task_type]
    plan_code_map = plan_code_map or {}
    plan_ids = sorted({str(t.plan_id) for t in typed if t.plan_id})
    plan_codes = sorted({plan_code_map.get(t.plan_id, str(t.plan_id)) for t in typed if t.plan_id})
    source_task_ids = [str(t.id) for t in typed]
    target = max(sum(max(t.target_count, 0) for t in typed), 1)
    completed = sum(max(t.completed_count, 0) for t in typed)
    target_value = None
    completed_value = None
    unit = None

    if task_type in metrics:
        completed = max(completed, int(metrics[task_type].get("count", 0)))
        metric_value = metrics[task_type].get("value", 0)
        if task_type == "diet":
            explicit_target = [t.target_value for t in typed if t.target_value]
            target_value = float(explicit_target[0]) if explicit_target else 1400.0
            completed_value = float(metric_value or sum(t.completed_value or 0 for t in typed) or 0)
            unit = "kcal"
        elif metric_value:
            completed_value = float(metric_value)
            explicit_target = [t.target_value for t in typed if t.target_value]
            target_value = float(explicit_target[0]) if explicit_target else None
            unit = "kcal" if target_value else None

    if task_type == "medication":
        unit = None

    count_ratio = min(completed / target, 1.0) if target > 0 else 0.0
    value_ratio = None
    if target_value and target_value > 0 and completed_value is not None:
        value_ratio = min(completed_value / target_value, 1.0)
    ratio = max(count_ratio, value_ratio or 0.0)
    title, description, summary, details = _task_detail_lines(
        task_type,
        typed,
        completed,
        target,
        completed_value,
        target_value,
        unit,
    )

    return TubeTaskProgress(
        task_type=task_type,
        label=_TYPE_LABELS.get(task_type, task_type),
        title=title,
        description=description,
        summary=summary,
        details=details,
        completed=completed,
        target=target,
        completed_value=round(completed_value, 1) if completed_value is not None else None,
        target_value=round(target_value, 1) if target_value is not None else None,
        unit=unit,
        ratio=round(ratio, 3),
        plan_ids=plan_ids,
        plan_codes=plan_codes,
        source_task_ids=source_task_ids,
    )


def _day_out(db: Session, user_id: int, day: date) -> TubeDayOut:
    today = _today()
    tasks = db.execute(
        select(PlanTask)
        .where(PlanTask.user_id == user_id, PlanTask.date == day)
        .order_by(PlanTask.task_type.asc(), PlanTask.id.asc())
    ).scalars().all()
    tasks = [t for t in tasks if not (t.task_type == "medication" and t.source_type == "daily_default")]
    metrics = _external_day_metrics(db, user_id, day)
    plan_code_map = _active_plan_code_map(db, user_id)
    task_types = [task_type for task_type in _TYPES if any(_effective_task_type(t) == task_type for t in tasks)]
    progresses = [_progress_for_type(tasks, task_type, metrics, plan_code_map) for task_type in task_types]
    ratio = 0.0 if day > today or not progresses else sum(p.ratio for p in progresses) / len(progresses)
    return TubeDayOut(
        date=day,
        weekday=day.weekday() + 1,
        is_today=day == today,
        is_future=day > today,
        completion_ratio=round(ratio, 3),
        tasks=progresses,
    )


def _has_omics_data(db: Session, user_id: int) -> bool:
    return db.execute(
        select(OmicsUpload.id)
        .where(OmicsUpload.user_id == user_id)
        .limit(1)
    ).first() is not None


def _revision_item_from_progress(task: TubeTaskProgress) -> dict[str, Any]:
    return {
        "task_key": task.task_type,
        "task_type": task.task_type,
        "label": task.label,
        "title": task.title or task.label,
        "description": task.description,
        "target_count": task.target,
        "target_value": task.target_value,
        "unit": task.unit,
        "reminder_time": None,
        "plan_ids": task.plan_ids,
        "plan_codes": task.plan_codes,
        "source_task_ids": task.source_task_ids,
        "summary": task.summary,
    }


def _revision_items_for_day(db: Session, user_id: int, day: date) -> list[dict[str, Any]]:
    _ensure_week_tasks(db, user_id, _week_start(day), _week_start(day) + timedelta(days=6))
    items = [_revision_item_from_progress(task) for task in _day_out(db, user_id, day).tasks]
    for item in items:
        source_ids = {str(raw) for raw in item.get("source_task_ids", []) if str(raw).isdigit()}
        plan_ids = [int(raw) for raw in item.get("plan_ids", []) if str(raw).isdigit()]
        if plan_ids:
            future_tasks = db.execute(
                select(PlanTask)
                .where(
                    PlanTask.user_id == user_id,
                    PlanTask.plan_id.in_(plan_ids),
                    PlanTask.date >= day,
                    PlanTask.status != "completed",
                )
                .order_by(PlanTask.date.asc(), PlanTask.id.asc())
            ).scalars().all()
            for task in future_tasks:
                if _effective_task_type(task) == item["task_key"]:
                    source_ids.add(str(task.id))
        item["source_task_ids"] = sorted(source_ids, key=lambda raw: int(raw))
    return items


def _context_summary_for_revision(context: dict[str, Any]) -> str:
    parts: list[str] = []
    profile = context.get("user_profile_info") or {}
    if profile:
        parts.append(f"基本信息：{json.dumps(profile, ensure_ascii=False)}")
    glucose = context.get("glucose_summary") or {}
    if glucose:
        parts.append(f"血糖概况：{json.dumps(glucose, ensure_ascii=False)[:600]}")
    meds = context.get("current_medications") or []
    if meds:
        parts.append(f"当前用药：{json.dumps(meds, ensure_ascii=False)[:500]}")
    patient_history = context.get("patient_history") or {}
    if patient_history:
        parts.append(f"病史整理：{json.dumps(patient_history, ensure_ascii=False)[:700]}")
    symptoms = context.get("symptoms_last_7d") or []
    if symptoms:
        parts.append(f"近 7 天身体/心情反馈：{json.dumps(symptoms, ensure_ascii=False)[:500]}")
    health_summary = context.get("health_summary_text") or ""
    if health_summary:
        parts.append(f"健康总结：{health_summary[:700]}")
    return "\n".join(parts)[:3000]


def _parse_revision_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_revision_items(
    original_items: list[dict[str, Any]],
    parsed_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    by_key = {item["task_key"]: item for item in original_items}
    revised: list[dict[str, Any]] = []
    for raw in parsed_items or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("task_key") or raw.get("task_type") or "").strip()
        original = by_key.get(key)
        if not original:
            continue
        item = dict(original)
        for field in ("title", "description", "unit", "reminder_time", "summary"):
            if field in raw:
                item[field] = raw.get(field)
        for field in ("target_count",):
            value = raw.get(field)
            if isinstance(value, (int, float)):
                item[field] = max(int(value), 0)
        value = raw.get("target_value")
        if isinstance(value, (int, float)):
            item["target_value"] = float(value)
        revised.append(item)
    existing_keys = {item["task_key"] for item in revised}
    for item in original_items:
        if item["task_key"] not in existing_keys:
            revised.append(dict(item))
    return revised


def _normalize_revision_reasons(
    original_items: list[dict[str, Any]],
    parsed_reasons: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    valid_keys = {item["task_key"] for item in original_items}
    reasons: list[dict[str, str]] = []
    for raw in parsed_reasons or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("task_key") or "").strip()
        if key not in valid_keys:
            continue
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            continue
        reasons.append({
            "task_key": key,
            "reason": reason[:800],
            "evidence": str(raw.get("evidence") or "")[:500] or None,
        })
    existing_keys = {item["task_key"] for item in reasons}
    for item in original_items:
        if item["task_key"] not in existing_keys:
            reasons.append({
                "task_key": item["task_key"],
                "reason": "结合当前资料未发现必须调整的证据，建议保留原计划并继续观察执行反馈。",
                "evidence": "用户现有健康上下文",
            })
    return reasons


def _revision_to_out(row: PlanAIRevision, daily_limit_used: bool = False) -> PlanRevisionProposalOut:
    return PlanRevisionProposalOut(
        id=str(row.id),
        date=row.revision_date,
        status=row.status,
        purpose=row.purpose,
        original_items=[PlanRevisionItemOut(**item) for item in row.original_items],
        revised_items=[PlanRevisionItemOut(**item) for item in row.revised_items],
        reasons=[PlanRevisionReasonOut(**item) for item in row.reasons],
        context_summary=row.context_summary,
        daily_limit_used=daily_limit_used,
        created_at=row.created_at,
        applied_at=row.applied_at,
    )


@router.post("/from-chat", response_model=HealthPlanDetailOut)
def create_plan_from_chat(
    payload: HealthPlanFromChatIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> HealthPlanDetailOut:
    content = "\n\n".join([payload.content.strip(), (payload.analysis or "").strip()]).strip()
    start = _today()
    end = start + timedelta(days=6)
    plan = HealthPlan(
        user_id=user_id,
        title=(payload.title or _title_from_text(content)).strip()[:160],
        goal=_goal_from_text(content),
        background="由 AI 对话保存，并自动拆分为每日饮食、运动、用药等执行任务。",
        start_date=start,
        end_date=end,
        status="active",
        source_conversation_id=payload.conversation_id,
        source_message_id=payload.message_id,
        created_by="ai",
        raw_content=content,
        notes={"version": "v1", "splitter": "heuristic"},
    )
    db.add(plan)
    db.flush()
    _seed_plan_tasks(db, plan, content)
    db.commit()
    db.refresh(plan)
    tasks = db.execute(
        select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.date.asc(), PlanTask.id.asc())
    ).scalars().all()
    base = _plan_to_out(db, plan, _active_plan_code_map(db, user_id).get(plan.id))
    return HealthPlanDetailOut(**base.model_dump(), raw_content=plan.raw_content, tasks=[_task_to_out(t) for t in tasks])


@router.post("/questionnaire", response_model=HealthPlanDetailOut)
def create_plan_from_questionnaire(
    payload: HealthPlanQuestionnaireIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> HealthPlanDetailOut:
    start = _today()
    duration = max(1, min(payload.duration_days, 90))
    end = start + timedelta(days=duration - 1)
    content = _questionnaire_summary(payload)
    title = (payload.title or f"{payload.target}健康计划").strip()[:160]
    plan = HealthPlan(
        user_id=user_id,
        title=title,
        goal=payload.target.strip(),
        background="由计划问卷创建，并按用户选择的目标、周期、频次和涉及内容拆分任务。",
        start_date=start,
        end_date=end,
        status="active",
        created_by="questionnaire",
        raw_content=content,
        notes={
            "version": "v1",
            "source": "plan_questionnaire",
            "target": payload.target,
            "duration_days": duration,
            "frequency": payload.frequency,
            "contents": payload.contents,
            "medication_needed": payload.medication_needed,
            "notes": payload.notes,
        },
    )
    db.add(plan)
    db.flush()
    _seed_questionnaire_tasks(db, plan, payload)
    db.commit()
    db.refresh(plan)
    tasks = db.execute(
        select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.date.asc(), PlanTask.id.asc())
    ).scalars().all()
    base = _plan_to_out(db, plan, _active_plan_code_map(db, user_id).get(plan.id))
    return HealthPlanDetailOut(**base.model_dump(), raw_content=plan.raw_content, tasks=[_task_to_out(t) for t in tasks])


@router.get("", response_model=HealthPlanListOut)
def list_plans(
    status: str | None = Query(default="active"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> HealthPlanListOut:
    q = select(HealthPlan).where(HealthPlan.user_id == user_id)
    if status:
        q = q.where(HealthPlan.status == status)
    rows = db.execute(q.order_by(HealthPlan.updated_at.desc())).scalars().all()
    code_map = _active_plan_code_map(db, user_id)
    return HealthPlanListOut(items=[_plan_to_out(db, p, code_map.get(p.id)) for p in rows])


@router.get("/week", response_model=TubeWeekOut)
def week_tube(
    week_start: date | None = Query(default=None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> TubeWeekOut:
    start = _week_start(week_start or _today())
    end = start + timedelta(days=6)
    _ensure_week_tasks(db, user_id, start, end)
    days = [_day_out(db, user_id, d) for d in _days(start, 7)]
    task_types = [task_type for task_type in _TYPES if any(
        any(task.task_type == task_type for task in day.tasks) for day in days
    )]
    return TubeWeekOut(
        week_start=start,
        week_end=end,
        today=_today(),
        has_omics_data=_has_omics_data(db, user_id),
        has_medication_need="medication" in task_types,
        task_types=task_types,
        days=days,
    )


@router.post("/tube/complete", response_model=TubeCompleteOut)
def complete_tube_task(
    payload: TubeCompleteIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> TubeCompleteOut:
    today = _today()
    if payload.date > today:
        raise HTTPException(status_code=400, detail="未来日期不能提前完成")
    start = _week_start(payload.date)
    _ensure_week_tasks(db, user_id, start, start + timedelta(days=6))

    task = db.execute(
        select(PlanTask)
        .where(
            PlanTask.user_id == user_id,
            PlanTask.date == payload.date,
            PlanTask.task_type == payload.task_type,
        )
        .order_by(
            case(
                (PlanTask.source_type == "plan", 0),
                (PlanTask.source_type == "medication", 1),
                else_=2,
            ),
            PlanTask.id.asc(),
        )
        .limit(1)
    ).scalars().first()
    if not task and payload.task_type in ("hydration", "sleep"):
        task = db.execute(
            select(PlanTask)
            .where(
                PlanTask.user_id == user_id,
                PlanTask.date == payload.date,
                PlanTask.task_type == "measurement",
                PlanTask.source_ref.like(f"%:{payload.task_type}"),
            )
            .order_by(PlanTask.id.asc())
            .limit(1)
        ).scalars().first()
    if not task:
        task = PlanTask(
            user_id=user_id,
            date=payload.date,
            task_type=payload.task_type,
            title=f"完成{_TYPE_LABELS.get(payload.task_type, payload.task_type)}任务",
            target_count=1,
            source_type="manual",
            source_ref=f"manual:{payload.date}:{payload.task_type}",
        )
        db.add(task)
        db.flush()

    before = _task_snapshot(task)
    if task.completed_count < max(task.target_count, 1):
        task.completed_count = min(max(task.target_count, 1), task.completed_count + payload.amount)
    if payload.value is not None:
        task.completed_value = min(task.target_value or payload.value, (task.completed_value or 0) + payload.value)
    if task.completed_count >= max(task.target_count, 1) or (
        task.target_value and task.completed_value and task.completed_value >= task.target_value
    ):
        task.status = "completed"
    db.add(task)
    _log_plan_event(
        db,
        user_id=user_id,
        event_type="complete",
        purpose="完成每日计划执行项",
        task=task,
        execution_item=task.title,
        execution_status=task.status,
        before_data=before,
        after_data=_task_snapshot(task),
    )
    db.commit()
    return TubeCompleteOut(day=_day_out(db, user_id, payload.date))


def _is_task_completed(task: PlanTask) -> bool:
    if task.status == "completed":
        return True
    if task.completed_count >= max(task.target_count, 1):
        return True
    return bool(task.target_value and task.completed_value and task.completed_value >= task.target_value)


@router.get("/tree-summary", response_model=HealthTreeSummaryOut)
def tree_summary(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> HealthTreeSummaryOut:
    active_plan_count = int(db.execute(
        select(func.count(HealthPlan.id)).where(
            HealthPlan.user_id == user_id,
            HealthPlan.status == "active",
        )
    ).scalar_one() or 0)
    trees_grown = int(db.execute(
        select(func.count(HealthPlan.id)).where(HealthPlan.user_id == user_id)
    ).scalar_one() or 0)

    rows = db.execute(
        select(PlanTask)
        .where(
            PlanTask.user_id == user_id,
            PlanTask.date <= _today(),
            PlanTask.task_type.in_(_TYPES + ("measurement",)),
        )
        .order_by(PlanTask.date.asc(), PlanTask.id.asc())
    ).scalars().all()
    rows = [t for t in rows if not (t.task_type == "medication" and t.source_type == "daily_default")]
    by_day: dict[date, list[PlanTask]] = {}
    for task in rows:
        by_day.setdefault(task.date, []).append(task)
    fruiting_count = sum(
        1 for day, tasks in by_day.items()
        if tasks and _day_out(db, user_id, day).completion_ratio >= 0.92
    )

    return HealthTreeSummaryOut(
        trees_grown=trees_grown,
        fruiting_count=fruiting_count,
        active_plan_count=active_plan_count,
    )


@router.patch("/tasks/{task_id}", response_model=PlanTaskOut)
def update_plan_task(
    task_id: str,
    payload: PlanTaskUpdateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PlanTaskOut:
    try:
        tid = int(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task_id")
    task = db.execute(
        select(PlanTask).where(PlanTask.id == tid, PlanTask.user_id == user_id)
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    before = _task_snapshot(task)
    fields = payload.model_fields_set
    if "title" in fields and payload.title:
        task.title = payload.title.strip()
    if "description" in fields:
        task.description = payload.description.strip() if payload.description else None
    if "target_count" in fields and payload.target_count is not None:
        task.target_count = max(int(payload.target_count), 1)
    if "target_value" in fields:
        task.target_value = payload.target_value
    if "unit" in fields:
        task.unit = payload.unit.strip() if payload.unit else None
    if "reminder_time" in fields:
        task.reminder_time = payload.reminder_time.strip() if payload.reminder_time else None

    db.add(task)
    _log_plan_event(
        db,
        user_id=user_id,
        event_type="manual_edit",
        purpose="手动编辑每日计划执行项",
        task=task,
        execution_item=task.title,
        execution_status=task.status,
        before_data=before,
        after_data=_task_snapshot(task),
    )
    db.commit()
    db.refresh(task)
    return _task_to_out(task)


@router.post("/revision/generate", response_model=PlanRevisionProposalOut)
def generate_plan_revision(
    payload: PlanRevisionGenerateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PlanRevisionProposalOut:
    target_day = payload.date or _today()
    today_start, today_end = _local_bounds(_today())
    existing = db.execute(
        select(PlanAIRevision)
        .where(
            PlanAIRevision.user_id == user_id,
            PlanAIRevision.created_at >= today_start,
            PlanAIRevision.created_at < today_end,
        )
        .order_by(PlanAIRevision.created_at.desc())
        .limit(1)
    ).scalars().first()
    if existing:
        return _revision_to_out(existing, daily_limit_used=True)

    original_items = _revision_items_for_day(db, user_id, target_day)
    if not original_items:
        raise HTTPException(status_code=400, detail="当前日期没有可修正的计划执行项")

    purpose = (payload.purpose or "AI 辅助修正整个健康计划").strip()
    context = build_user_context(
        db,
        str(user_id),
        trusted_health_consumer="daily_advice",
    )
    context_summary = _context_summary_for_revision(context)
    prompt = (
        "请基于用户基本信息、血糖、既往病史、近 7 天身体/心情反馈、当前用药和健康总结，"
        "以今天合并后的每日执行项为入口，对整个健康计划中后续仍需执行的同类任务做个性化修正。只返回 JSON，不要 Markdown。"
        "JSON 格式：{\"items\":[{\"task_key\":\"exercise\",\"title\":\"...\",\"description\":\"...\","
        "\"target_count\":1,\"target_value\":null,\"unit\":null,\"reminder_time\":null}],"
        "\"reasons\":[{\"task_key\":\"exercise\",\"reason\":\"为什么这样改，必须指出来自哪些用户信息\","
        "\"evidence\":\"体重/血糖/病史/心情等依据\"}]}。"
        "task_key 必须来自原计划，不要新增原计划不存在的 task_key。"
        f"\n\n修正目的：{purpose}"
        f"\n\n原计划条目：{json.dumps(original_items, ensure_ascii=False)}"
        f"\n\n用户上下文摘要：{context_summary}"
    )
    result = get_provider().generate_text(context, prompt, skill_prompt="health_plan_revision_json")
    parsed = _parse_revision_json(result.answer_markdown)
    revised_items = _normalize_revision_items(original_items, parsed.get("items") if parsed else None)
    reasons = _normalize_revision_reasons(original_items, parsed.get("reasons") if parsed else None)

    row = PlanAIRevision(
        user_id=user_id,
        revision_date=target_day,
        status="generated",
        purpose=purpose,
        original_items=original_items,
        revised_items=revised_items,
        reasons=reasons,
        context_summary=context_summary,
        llm_raw=result.answer_markdown,
    )
    db.add(row)
    db.flush()
    _log_plan_event(
        db,
        user_id=user_id,
        event_type="ai_revision_generated",
        purpose=purpose,
        day=target_day,
        execution_item="AI 辅助修正整个计划",
        execution_status="generated",
        after_data={"revision_id": str(row.id), "items": revised_items, "reasons": reasons},
    )
    db.commit()
    db.refresh(row)
    return _revision_to_out(row)


@router.post("/revision/{revision_id}/apply", response_model=PlanRevisionProposalOut)
def apply_plan_revision(
    revision_id: str,
    payload: PlanRevisionApplyIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PlanRevisionProposalOut:
    try:
        rid = int(revision_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid revision_id")
    revision = db.execute(
        select(PlanAIRevision).where(PlanAIRevision.id == rid, PlanAIRevision.user_id == user_id)
    ).scalars().first()
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")

    all_keys = [item["task_key"] for item in revision.revised_items]
    if payload.reject_all:
        accepted = set()
    elif payload.accept_all:
        accepted = set(all_keys)
    else:
        accepted = {key for key in payload.accepted_task_keys if key in all_keys}
    rejected = [key for key in all_keys if key not in accepted]

    revised_by_key = {item["task_key"]: item for item in revision.revised_items}
    for key in accepted:
        item = revised_by_key.get(key)
        if not item:
            continue
        ids = [int(raw) for raw in item.get("source_task_ids", []) if str(raw).isdigit()]
        if not ids:
            continue
        tasks = db.execute(
            select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.id.in_(ids))
        ).scalars().all()
        for task in tasks:
            before = _task_snapshot(task)
            task.title = str(item.get("title") or task.title)[:160]
            task.description = item.get("description") or task.description
            target_count = item.get("target_count")
            if isinstance(target_count, (int, float)):
                task.target_count = max(int(target_count), 1)
            target_value = item.get("target_value")
            task.target_value = float(target_value) if isinstance(target_value, (int, float)) else None
            unit = item.get("unit")
            task.unit = str(unit)[:24] if unit else None
            reminder_time = item.get("reminder_time")
            task.reminder_time = str(reminder_time)[:8] if reminder_time else None
            db.add(task)
            _log_plan_event(
                db,
                user_id=user_id,
                event_type="ai_revision_applied",
                purpose=revision.purpose,
                task=task,
                execution_item=task.title,
                execution_status=task.status,
                before_data=before,
                after_data=_task_snapshot(task),
            )

    revision.accepted_keys = sorted(accepted)
    revision.rejected_keys = rejected
    revision.status = "rejected" if payload.reject_all else ("applied" if len(accepted) == len(all_keys) else "partially_applied")
    revision.applied_at = datetime.now(timezone.utc)
    db.add(revision)
    _log_plan_event(
        db,
        user_id=user_id,
        event_type="ai_revision_decision",
        purpose=revision.purpose,
        day=revision.revision_date,
        execution_item="用户选择 AI 修正条目",
        execution_status=revision.status,
        after_data={"revision_id": str(revision.id), "accepted_keys": sorted(accepted), "rejected_keys": rejected},
    )
    db.commit()
    db.refresh(revision)
    return _revision_to_out(revision)


@router.get("/{plan_id}", response_model=HealthPlanDetailOut)
def get_plan(
    plan_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> HealthPlanDetailOut:
    try:
        pid = int(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan_id")
    plan = db.execute(
        select(HealthPlan).where(HealthPlan.id == pid, HealthPlan.user_id == user_id)
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    tasks = db.execute(
        select(PlanTask).where(PlanTask.plan_id == plan.id).order_by(PlanTask.date.asc(), PlanTask.id.asc())
    ).scalars().all()
    base = _plan_to_out(db, plan, _active_plan_code_map(db, user_id).get(plan.id))
    return HealthPlanDetailOut(**base.model_dump(), raw_content=plan.raw_content, tasks=[_task_to_out(t) for t in tasks])
