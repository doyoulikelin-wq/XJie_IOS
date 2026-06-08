from __future__ import annotations

import secrets
import string
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.elderly_checkin import ElderlyCheckin
from app.models.family import (
    FamilyAuditLog,
    FamilyCareEvent,
    FamilyGroup,
    FamilyInvite,
    FamilyMember,
    FamilyPermission,
)
from app.models.health_plan import PlanTask
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.family import (
    FamilyCareEventCreate,
    FamilyCareEventOut,
    FamilyGroupCreate,
    FamilyGroupOut,
    FamilyInviteAccept,
    FamilyInviteCreate,
    FamilyInviteOut,
    FamilyMemberOut,
    FamilyPermissionOut,
    FamilyPermissionUpdate,
    FamilySubjectOut,
    FamilySubjectSummaryOut,
)
from app.services.glucose_service import compute_gaps_hours, compute_tir, get_glucose_points, variability_label

router = APIRouter()
_LOCAL_TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_bounds(day) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=_LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _summary_between(db: Session, user_id: int, start: datetime, end: datetime) -> dict:
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


def _today_context(db: Session, user_id: int, day) -> dict:
    start, end = _local_bounds(day)
    tasks = db.execute(
        select(PlanTask).where(PlanTask.user_id == user_id, PlanTask.date == day)
    ).scalars().all()
    care_count = db.execute(
        select(func.count(ElderlyCheckin.id)).where(
            ElderlyCheckin.user_id == user_id,
            ElderlyCheckin.created_at >= start,
            ElderlyCheckin.created_at < end,
        )
    ).scalar() or 0

    def is_done(task: PlanTask) -> bool:
        return task.status == "completed" or int(task.completed_count or 0) >= int(task.target_count or 1)

    completed_tasks = [task for task in tasks if is_done(task)]
    return {
        "tasks_total": len(tasks),
        "tasks_completed": len(completed_tasks),
        "care_count": int(care_count),
    }


def _health_level(summary: dict, context: dict) -> str:
    if summary.get("reading_count"):
        if (summary.get("min") or 999) < 70 or (summary.get("max") or 0) > 250:
            return "risk"
        if (summary.get("tir_70_180_pct") or 0) < 70 or summary.get("variability") == "high":
            return "watch"
        return "stable"
    if context["tasks_total"] and context["tasks_completed"] < context["tasks_total"]:
        return "watch"
    return "missing"


def _display_name(user: User | None, profile: UserProfile | None, fallback: str = "家人") -> str:
    if profile and profile.display_name:
        return profile.display_name
    if user and user.username:
        return user.username
    if user and user.phone:
        return user.phone
    return fallback


def _permission_out(row: FamilyPermission | None, subject_user_id: int, viewer_user_id: int) -> FamilyPermissionOut:
    if not row:
        return FamilyPermissionOut(subject_user_id=subject_user_id, viewer_user_id=viewer_user_id)
    return FamilyPermissionOut(
        id=row.id,
        subject_user_id=row.subject_user_id,
        viewer_user_id=row.viewer_user_id,
        can_view_glucose_detail=row.can_view_glucose_detail,
        can_view_medication=row.can_view_medication,
        can_view_health_data=row.can_view_health_data,
        can_view_documents=row.can_view_documents,
        can_view_omics=row.can_view_omics,
        can_view_ai_summary=row.can_view_ai_summary,
    )


def _member_out(db: Session, row: FamilyMember) -> FamilyMemberOut:
    user = db.get(User, row.user_id)
    profile = db.execute(select(UserProfile).where(UserProfile.user_id == row.user_id).limit(1)).scalar_one_or_none()
    return FamilyMemberOut(
        id=row.id,
        group_id=row.group_id,
        user_id=row.user_id,
        role=row.role,
        relation=row.relation,
        display_name=row.display_name,
        status=row.status,
        phone=user.phone if user else None,
        username=user.username if user else None,
        profile_name=profile.display_name if profile else None,
        created_at=row.created_at,
    )


def _invite_out(row: FamilyInvite) -> FamilyInviteOut:
    return FamilyInviteOut(
        id=row.id,
        group_id=row.group_id,
        invite_code=row.invite_code,
        target_phone=row.target_phone,
        relation=row.relation,
        role=row.role,
        status=row.status,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


def _subject_out(
    db: Session,
    subject_id: int,
    viewer_id: int,
    relation: str | None = None,
    group_id: int | None = None,
    member_id: int | None = None,
) -> FamilySubjectOut:
    user = db.get(User, subject_id)
    profile = db.execute(select(UserProfile).where(UserProfile.user_id == subject_id).limit(1)).scalar_one_or_none()
    permission = db.execute(
        select(FamilyPermission).where(
            FamilyPermission.subject_user_id == subject_id,
            FamilyPermission.viewer_user_id == viewer_id,
        )
    ).scalar_one_or_none()
    if subject_id == viewer_id:
        perm = FamilyPermissionOut(
            subject_user_id=subject_id,
            viewer_user_id=viewer_id,
            can_view_glucose_detail=True,
            can_view_medication=True,
            can_view_health_data=True,
            can_view_documents=True,
            can_view_omics=True,
            can_view_ai_summary=True,
        )
    else:
        perm = _permission_out(permission, subject_id, viewer_id)
    return FamilySubjectOut(
        user_id=subject_id,
        display_name=_display_name(user, profile),
        relation=relation,
        group_id=group_id,
        member_id=member_id,
        permissions=perm,
    )


def _ensure_group_owner(db: Session, group_id: int, user_id: int) -> FamilyGroup:
    group = db.get(FamilyGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="家庭不存在")
    if group.owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="只有家庭创建者可以操作")
    return group


def _default_group(db: Session, user_id: int) -> FamilyGroup:
    group = db.execute(
        select(FamilyGroup).where(FamilyGroup.owner_user_id == user_id).order_by(FamilyGroup.created_at.asc()).limit(1)
    ).scalar_one_or_none()
    if group:
        return group
    group = FamilyGroup(name="我的家庭", owner_user_id=user_id)
    db.add(group)
    db.flush()
    db.add(FamilyMember(group_id=group.id, user_id=user_id, role="owner", status="active"))
    db.flush()
    return group


def _generate_invite_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        exists = db.execute(select(FamilyInvite.id).where(FamilyInvite.invite_code == code)).scalar()
        if not exists:
            return code


def _can_view_subject(db: Session, subject_id: int, viewer_id: int) -> bool:
    if subject_id == viewer_id:
        return True
    exists = db.execute(
        select(FamilyPermission.id).where(
            FamilyPermission.subject_user_id == subject_id,
            FamilyPermission.viewer_user_id == viewer_id,
        )
    ).scalar()
    return bool(exists)


def _audit(db: Session, subject_id: int, viewer_id: int, action: str, scope: str) -> None:
    db.add(FamilyAuditLog(subject_user_id=subject_id, viewer_user_id=viewer_id, action=action, scope=scope))


@router.post("/groups", response_model=FamilyGroupOut)
def create_group(
    payload: FamilyGroupCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyGroupOut:
    group = FamilyGroup(name=payload.name, owner_user_id=user_id)
    db.add(group)
    db.flush()
    db.add(FamilyMember(group_id=group.id, user_id=user_id, role="owner", status="active"))
    db.commit()
    db.refresh(group)
    return FamilyGroupOut(id=group.id, name=group.name, owner_user_id=group.owner_user_id, created_at=group.created_at)


@router.get("/groups", response_model=list[FamilyGroupOut])
def list_groups(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[FamilyGroupOut]:
    rows = db.execute(
        select(FamilyGroup)
        .join(FamilyMember, FamilyMember.group_id == FamilyGroup.id)
        .where(FamilyMember.user_id == user_id, FamilyMember.status == "active")
        .order_by(FamilyGroup.created_at.asc())
    ).scalars().all()
    return [FamilyGroupOut(id=r.id, name=r.name, owner_user_id=r.owner_user_id, created_at=r.created_at) for r in rows]


@router.get("/members", response_model=list[FamilyMemberOut])
def list_members(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[FamilyMemberOut]:
    group_ids = db.execute(
        select(FamilyMember.group_id).where(FamilyMember.user_id == user_id, FamilyMember.status == "active")
    ).scalars().all()
    if not group_ids:
        return []
    rows = db.execute(
        select(FamilyMember)
        .where(FamilyMember.group_id.in_(group_ids), FamilyMember.status == "active")
        .order_by(FamilyMember.group_id.asc(), FamilyMember.created_at.asc())
    ).scalars().all()
    return [_member_out(db, row) for row in rows]


@router.delete("/members/{member_id}")
def remove_member(
    member_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    member = db.get(FamilyMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")
    group = db.get(FamilyGroup, member.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="家庭不存在")
    if group.owner_user_id != user_id and member.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权移除该成员")
    member.status = "removed"
    db.execute(
        delete(FamilyPermission).where(
            or_(
                (
                    (FamilyPermission.subject_user_id == group.owner_user_id)
                    & (FamilyPermission.viewer_user_id == member.user_id)
                ),
                (
                    (FamilyPermission.subject_user_id == member.user_id)
                    & (FamilyPermission.viewer_user_id == group.owner_user_id)
                ),
            )
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/invites", response_model=FamilyInviteOut)
def create_invite(
    payload: FamilyInviteCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyInviteOut:
    group = _default_group(db, user_id) if payload.group_id is None else _ensure_group_owner(db, payload.group_id, user_id)
    code = _generate_invite_code(db)
    invite = FamilyInvite(
        group_id=group.id,
        inviter_user_id=user_id,
        invite_code=code,
        target_phone=payload.target_phone,
        role=payload.role or "member",
        relation=payload.relation,
        status="pending",
        expires_at=_now() + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return _invite_out(invite)


@router.post("/invites/accept", response_model=FamilyMemberOut)
def accept_invite(
    payload: FamilyInviteAccept,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyMemberOut:
    code = (payload.invite_code or "").upper()
    invite = db.execute(select(FamilyInvite).where(FamilyInvite.invite_code == code)).scalar_one_or_none()
    if not invite or invite.status != "pending":
        raise HTTPException(status_code=404, detail="邀请码无效")
    if invite.expires_at < _now():
        invite.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="邀请码已过期")
    user = db.get(User, user_id)
    if invite.target_phone and user and user.phone and invite.target_phone != user.phone:
        raise HTTPException(status_code=403, detail="邀请码与当前账号不匹配")
    existing = db.execute(
        select(FamilyMember).where(FamilyMember.group_id == invite.group_id, FamilyMember.user_id == user_id)
    ).scalar_one_or_none()
    if existing:
        existing.status = "active"
        existing.display_name = payload.display_name or existing.display_name
        member = existing
    else:
        member = FamilyMember(
            group_id=invite.group_id,
            user_id=user_id,
            role=invite.role or "member",
            relation=invite.relation,
            display_name=payload.display_name,
            status="active",
        )
        db.add(member)
    permission = db.execute(
        select(FamilyPermission).where(
            FamilyPermission.subject_user_id == invite.inviter_user_id,
            FamilyPermission.viewer_user_id == user_id,
        )
    ).scalar_one_or_none()
    if not permission and invite.inviter_user_id != user_id:
        db.add(FamilyPermission(subject_user_id=invite.inviter_user_id, viewer_user_id=user_id))
    invite.status = "accepted"
    invite.accepted_by_user_id = user_id
    invite.accepted_at = _now()
    db.commit()
    db.refresh(member)
    return _member_out(db, member)


@router.get("/subjects", response_model=list[FamilySubjectOut])
def list_subjects(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)) -> list[FamilySubjectOut]:
    subjects: dict[int, FamilySubjectOut] = {
        user_id: _subject_out(db, user_id, user_id, relation="本人", group_id=None, member_id=None)
    }
    permission_rows = db.execute(
        select(FamilyPermission).where(FamilyPermission.viewer_user_id == user_id)
    ).scalars().all()
    for permission in permission_rows:
        if permission.subject_user_id not in subjects:
            subjects[permission.subject_user_id] = _subject_out(
                db,
                permission.subject_user_id,
                user_id,
                relation="家人",
            )
    return list(subjects.values())


@router.get("/subjects/{subject_id}/summary", response_model=FamilySubjectSummaryOut)
def subject_summary(
    subject_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilySubjectSummaryOut:
    if not _can_view_subject(db, subject_id, user_id):
        raise HTTPException(status_code=403, detail="未获得该用户授权")

    today_local = datetime.now(_LOCAL_TZ).date()
    start, end = _local_bounds(today_local)
    glucose = _summary_between(db, subject_id, start, end)
    context = _today_context(db, subject_id, today_local)
    subject = _subject_out(db, subject_id, user_id)
    permission = subject.permissions
    status_level = _health_level(glucose, context)
    task_total = int(context["tasks_total"] or 0)
    task_done = int(context["tasks_completed"] or 0)
    last_checkin = db.execute(
        select(ElderlyCheckin)
        .where(ElderlyCheckin.user_id == subject_id)
        .order_by(ElderlyCheckin.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    pending_care = db.execute(
        select(func.count(FamilyCareEvent.id)).where(
            FamilyCareEvent.subject_user_id == subject_id,
            FamilyCareEvent.status == "new",
        )
    ).scalar() or 0
    alerts: list[str] = []
    if status_level == "risk":
        alerts.append("今日健康状态需要关注")
    if task_total and task_done < task_total:
        alerts.append(f"今日计划还有 {task_total - task_done} 项未完成")
    if not glucose.get("reading_count"):
        alerts.append("今日暂无连续血糖数据")

    health_status = {
        "level": status_level,
        "reading_count": int(glucose.get("reading_count") or 0),
        "avg": glucose.get("avg") if permission.can_view_glucose_detail else None,
        "tir_70_180_pct": glucose.get("tir_70_180_pct") if permission.can_view_glucose_detail else None,
        "min": glucose.get("min") if permission.can_view_glucose_detail else None,
        "max": glucose.get("max") if permission.can_view_glucose_detail else None,
    }
    plan = {
        "date": today_local.isoformat(),
        "tasks_total": task_total,
        "tasks_completed": task_done,
        "completion_pct": round(task_done / task_total * 100) if task_total else 0,
    }
    care = {
        "today_checkins": int(context["care_count"] or 0),
        "last_checkin_at": last_checkin.created_at.isoformat() if last_checkin else None,
        "pending_care_events": int(pending_care),
    }
    _audit(db, subject_id, user_id, "view_summary", "family_summary")
    db.commit()
    return FamilySubjectSummaryOut(
        subject=subject,
        health_status=health_status,
        plan=plan,
        care=care,
        permissions=permission,
        alerts=alerts,
        generated_at=_now(),
    )


@router.get("/permissions/{viewer_user_id}", response_model=FamilyPermissionOut)
def get_permission(
    viewer_user_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyPermissionOut:
    row = db.execute(
        select(FamilyPermission).where(
            FamilyPermission.subject_user_id == user_id,
            FamilyPermission.viewer_user_id == viewer_user_id,
        )
    ).scalar_one_or_none()
    return _permission_out(row, user_id, viewer_user_id)


@router.patch("/permissions/{viewer_user_id}", response_model=FamilyPermissionOut)
def update_permission(
    viewer_user_id: int,
    payload: FamilyPermissionUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyPermissionOut:
    if viewer_user_id == user_id:
        raise HTTPException(status_code=400, detail="无需授权自己")
    my_group_ids = select(FamilyMember.group_id).where(
        FamilyMember.user_id == user_id,
        FamilyMember.status == "active",
    )
    member_exists = db.execute(
        select(FamilyMember.id).where(
            FamilyMember.group_id.in_(my_group_ids),
            FamilyMember.user_id == viewer_user_id,
            FamilyMember.status == "active",
        )
    ).scalar()
    if not member_exists:
        raise HTTPException(status_code=403, detail="只能授权同一家庭中的成员")
    row = db.execute(
        select(FamilyPermission).where(
            FamilyPermission.subject_user_id == user_id,
            FamilyPermission.viewer_user_id == viewer_user_id,
        )
    ).scalar_one_or_none()
    if not row:
        row = FamilyPermission(subject_user_id=user_id, viewer_user_id=viewer_user_id)
        db.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, bool(value))
    _audit(db, user_id, viewer_user_id, "update_permission", ",".join(payload.model_dump(exclude_unset=True).keys()))
    db.commit()
    db.refresh(row)
    return _permission_out(row, user_id, viewer_user_id)


@router.post("/care-events", response_model=FamilyCareEventOut)
def create_care_event(
    payload: FamilyCareEventCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FamilyCareEventOut:
    if not _can_view_subject(db, payload.subject_user_id, user_id):
        raise HTTPException(status_code=403, detail="未获得该用户授权")
    row = FamilyCareEvent(
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        event_type=payload.event_type or "care_reminder",
        message=payload.message,
        status="new",
    )
    db.add(row)
    _audit(db, payload.subject_user_id, user_id, "create_care_event", row.event_type)
    db.commit()
    db.refresh(row)
    return FamilyCareEventOut(
        id=row.id,
        subject_user_id=row.subject_user_id,
        actor_user_id=row.actor_user_id,
        event_type=row.event_type,
        message=row.message,
        status=row.status,
        created_at=row.created_at,
        handled_at=row.handled_at,
    )


@router.get("/care-events", response_model=list[FamilyCareEventOut])
def list_care_events(
    subject_user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[FamilyCareEventOut]:
    subject_ids = {subject_user_id} if subject_user_id else {
        item.subject_user_id for item in db.execute(
            select(FamilyPermission).where(FamilyPermission.viewer_user_id == user_id)
        ).scalars().all()
    }
    subject_ids.add(user_id)
    allowed = [sid for sid in subject_ids if sid is not None and _can_view_subject(db, sid, user_id)]
    if not allowed:
        return []
    rows = db.execute(
        select(FamilyCareEvent)
        .where(FamilyCareEvent.subject_user_id.in_(allowed))
        .order_by(FamilyCareEvent.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        FamilyCareEventOut(
            id=row.id,
            subject_user_id=row.subject_user_id,
            actor_user_id=row.actor_user_id,
            event_type=row.event_type,
            message=row.message,
            status=row.status,
            created_at=row.created_at,
            handled_at=row.handled_at,
        )
        for row in rows
    ]
