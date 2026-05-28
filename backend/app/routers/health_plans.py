"""Health plan persistence and tube-style weekly execution dashboard."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.exercise_log import ExerciseLog
from app.models.health_plan import HealthPlan, PlanTask
from app.models.meal import Meal
from app.models.medication import Medication
from app.schemas.health_plan import (
    HealthPlanDetailOut,
    HealthPlanFromChatIn,
    HealthPlanListOut,
    HealthPlanOut,
    PlanTaskOut,
    TubeCompleteIn,
    TubeCompleteOut,
    TubeDayOut,
    TubeTaskProgress,
    TubeWeekOut,
)

router = APIRouter()

_LOCAL_TZ = timezone(timedelta(hours=8))
_TYPES = ("exercise", "medication", "diet")
_TYPE_LABELS = {
    "exercise": "运动",
    "medication": "服药",
    "diet": "饮食",
    "measurement": "监测",
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


def _plan_to_out(db: Session, plan: HealthPlan) -> HealthPlanOut:
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


def _seed_plan_tasks(db: Session, plan: HealthPlan, content: str) -> None:
    wants_med = _has_any(content, ("用药", "服药", "药物", "药片", "补剂", "胰岛素"))
    wants_exercise = _has_any(content, ("运动", "步行", "训练", "拉伸", "康复", "健身", "游泳"))
    wants_diet = _has_any(content, ("饮食", "三餐", "早餐", "午餐", "晚餐", "热量", "控糖"))

    for idx, day in enumerate(_days(plan.start_date, (plan.end_date - plan.start_date).days + 1), start=1):
        day_label = f"第 {idx} 天"
        db.add(PlanTask(
            user_id=plan.user_id,
            plan_id=plan.id,
            date=day,
            task_type="diet",
            title=f"{day_label} 饮食计划",
            description="按计划完成三餐记录，优先选择低负担、控糖友好的食物。",
            target_count=3,
            target_value=1400.0 if wants_diet else None,
            unit="kcal" if wants_diet else None,
            source_type="plan",
            source_ref=f"plan:{plan.id}:{day}:diet",
        ))
        db.add(PlanTask(
            user_id=plan.user_id,
            plan_id=plan.id,
            date=day,
            task_type="exercise",
            title=f"{day_label} 运动任务",
            description="完成一次轻中等强度运动，可选择饭后步行、拉伸或康复动作。",
            target_count=1 if wants_exercise else 1,
            source_type="plan",
            source_ref=f"plan:{plan.id}:{day}:exercise",
        ))
        if wants_med:
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
                description="完成三餐计划或饮食记录，试管橙色层会随进度上升。",
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
        elif not db.execute(
            select(PlanTask.id).where(
                PlanTask.user_id == user_id,
                PlanTask.date == day,
                PlanTask.task_type == "medication",
            ).limit(1)
        ).first():
            db.add(PlanTask(
                user_id=user_id,
                date=day,
                task_type="medication",
                title="完成今日用药/补剂记录",
                description="如今日没有用药，可在后续版本中关闭该默认任务。",
                target_count=1,
                source_type="daily_default",
                source_ref=f"default:{day}:medication",
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


def _progress_for_type(tasks: list[PlanTask], task_type: str, metrics: dict[str, dict[str, float]]) -> TubeTaskProgress:
    typed = [t for t in tasks if t.task_type == task_type]
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

    return TubeTaskProgress(
        task_type=task_type,
        label=_TYPE_LABELS.get(task_type, task_type),
        completed=completed,
        target=target,
        completed_value=round(completed_value, 1) if completed_value is not None else None,
        target_value=round(target_value, 1) if target_value is not None else None,
        unit=unit,
        ratio=round(ratio, 3),
    )


def _day_out(db: Session, user_id: int, day: date) -> TubeDayOut:
    today = _today()
    tasks = db.execute(
        select(PlanTask)
        .where(PlanTask.user_id == user_id, PlanTask.date == day)
        .order_by(PlanTask.task_type.asc(), PlanTask.id.asc())
    ).scalars().all()
    metrics = _external_day_metrics(db, user_id, day)
    progresses = [_progress_for_type(tasks, task_type, metrics) for task_type in _TYPES]
    ratio = 0.0 if day > today else sum(p.ratio for p in progresses) / len(progresses)
    return TubeDayOut(
        date=day,
        weekday=day.weekday() + 1,
        is_today=day == today,
        is_future=day > today,
        completion_ratio=round(ratio, 3),
        tasks=progresses,
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
        background="由 AI 对话保存，并自动拆分为每日饮食、运动、用药执行任务。",
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
    base = _plan_to_out(db, plan)
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
    return HealthPlanListOut(items=[_plan_to_out(db, p) for p in rows])


@router.get("/week", response_model=TubeWeekOut)
def week_tube(
    week_start: date | None = Query(default=None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> TubeWeekOut:
    start = _week_start(week_start or _today())
    end = start + timedelta(days=6)
    _ensure_week_tasks(db, user_id, start, end)
    return TubeWeekOut(
        week_start=start,
        week_end=end,
        today=_today(),
        days=[_day_out(db, user_id, d) for d in _days(start, 7)],
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

    if task.completed_count < max(task.target_count, 1):
        task.completed_count = min(max(task.target_count, 1), task.completed_count + payload.amount)
    if payload.value is not None:
        task.completed_value = min(task.target_value or payload.value, (task.completed_value or 0) + payload.value)
    if task.completed_count >= max(task.target_count, 1) or (
        task.target_value and task.completed_value and task.completed_value >= task.target_value
    ):
        task.status = "completed"
    db.add(task)
    db.commit()
    return TubeCompleteOut(day=_day_out(db, user_id, payload.date))


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
    base = _plan_to_out(db, plan)
    return HealthPlanDetailOut(**base.model_dump(), raw_content=plan.raw_content, tasks=[_task_to_out(t) for t in tasks])
