"""Admin management endpoints — stats, user list, conversations, omics uploads, token usage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_admin
from app.models.audit import LLMAuditLog
from app.models.conversation import ChatMessage, Conversation
from app.models.health_document import SummaryTask
from app.models.feature_flag import FeatureFlag, Skill
from app.models.health_document import IndicatorKnowledge
from app.models.meal import Meal
from app.models.omics import OmicsUpload
from app.models.user import User
from app.schemas.admin import (
    AdminConversationItem,
    AdminOmicsItem,
    AdminStats,
    AdminTokenDetails,
    AdminTokenStats,
    AdminUserItem,
    SummaryTaskItem,
    UserTokenItem,
)
from app.schemas.feature_flag import (
    FeatureFlagCreate,
    FeatureFlagListOut,
    FeatureFlagOut,
    FeatureFlagUpdate,
    SkillCreate,
    SkillListOut,
    SkillOut,
    SkillUpdate,
)
from app.services.feature_service import invalidate_cache

router = APIRouter()


# ── Dashboard stats ──────────────────────────────────────────


@router.get("/stats", response_model=AdminStats)
def admin_stats(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_users = db.scalar(select(func.count()).select_from(User).where(User.deleted == 0)) or 0

    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    active_users_7d = db.scalar(
        select(func.count(func.distinct(Conversation.user_id)))
        .where(Conversation.updated_at >= since_7d)
    ) or 0

    total_conversations = db.scalar(select(func.count()).select_from(Conversation)) or 0
    total_messages = db.scalar(select(func.count()).select_from(ChatMessage)) or 0
    total_omics = db.scalar(select(func.count()).select_from(OmicsUpload)) or 0
    total_meals = db.scalar(select(func.count()).select_from(Meal)) or 0

    return AdminStats(
        total_users=total_users,
        active_users_7d=active_users_7d,
        total_conversations=total_conversations,
        total_messages=total_messages,
        total_omics_uploads=total_omics,
        total_meals=total_meals,
    )


# ── User list ────────────────────────────────────────────────


@router.get("/users", response_model=list[AdminUserItem])
def admin_users(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    offset = (page - 1) * size

    # Subquery: conversation count per user
    conv_sub = (
        select(Conversation.user_id, func.count().label("conv_count"))
        .group_by(Conversation.user_id)
        .subquery()
    )
    # Subquery: message count per user
    msg_sub = (
        select(
            Conversation.user_id,
            func.count(ChatMessage.id).label("msg_count"),
            func.max(ChatMessage.created_at).label("last_active"),
        )
        .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
        .group_by(Conversation.user_id)
        .subquery()
    )

    stmt = (
        select(
            User.id,
            User.phone,
            User.username,
            User.is_admin,
            User.created_at,
            func.coalesce(conv_sub.c.conv_count, 0).label("conversation_count"),
            func.coalesce(msg_sub.c.msg_count, 0).label("message_count"),
            msg_sub.c.last_active,
        )
        .outerjoin(conv_sub, conv_sub.c.user_id == User.id)
        .outerjoin(msg_sub, msg_sub.c.user_id == User.id)
        .where(User.deleted == 0)
        .order_by(User.id.desc())
        .offset(offset)
        .limit(size)
    )

    rows = db.execute(stmt).all()
    return [
        AdminUserItem(
            id=r.id,
            phone=r.phone,
            username=r.username,
            is_admin=r.is_admin or False,
            created_at=r.created_at,
            conversation_count=r.conversation_count,
            message_count=r.message_count,
            last_active=r.last_active,
        )
        for r in rows
    ]


# ── Conversation list ────────────────────────────────────────


@router.get("/conversations", response_model=list[AdminConversationItem])
def admin_conversations(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    offset = (page - 1) * size

    stmt = (
        select(
            Conversation.id,
            Conversation.user_id,
            User.username,
            Conversation.title,
            Conversation.message_count,
            Conversation.created_at,
            Conversation.updated_at,
        )
        .join(User, User.id == Conversation.user_id)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = db.execute(stmt).all()
    return [
        AdminConversationItem(
            id=r.id,
            user_id=r.user_id,
            username=r.username,
            title=r.title,
            message_count=r.message_count,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


# ── Omics uploads ────────────────────────────────────────────


@router.get("/omics", response_model=list[AdminOmicsItem])
def admin_omics(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    offset = (page - 1) * size

    stmt = (
        select(
            OmicsUpload.id,
            OmicsUpload.user_id,
            User.username,
            OmicsUpload.omics_type,
            OmicsUpload.file_name,
            OmicsUpload.file_size,
            OmicsUpload.risk_level,
            OmicsUpload.llm_summary,
            OmicsUpload.created_at,
        )
        .join(User, User.id == OmicsUpload.user_id)
        .order_by(OmicsUpload.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    rows = db.execute(stmt).all()
    return [
        AdminOmicsItem(
            id=r.id,
            user_id=r.user_id,
            username=r.username,
            omics_type=r.omics_type,
            file_name=r.file_name,
            file_size=r.file_size,
            risk_level=r.risk_level,
            llm_summary=r.llm_summary,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ── Set user admin flag ──────────────────────────────────────


@router.patch("/users/{user_id}/admin")
def toggle_admin(
    user_id: int,
    admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Cannot change own admin status")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = not user.is_admin
    db.commit()
    return {"id": user.id, "is_admin": user.is_admin}


# ── Token usage stats ────────────────────────────────────────


@router.get("/token-stats", response_model=AdminTokenStats)
def admin_token_stats(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return total and per-feature token consumption from LLM audit logs + summary tasks."""
    rows = db.execute(
        select(
            LLMAuditLog.feature,
            func.coalesce(func.sum(LLMAuditLog.prompt_tokens), 0).label("prompt"),
            func.coalesce(func.sum(LLMAuditLog.completion_tokens), 0).label("completion"),
            func.count().label("call_count"),
        )
        .group_by(LLMAuditLog.feature)
    ).all()

    total_prompt = 0
    total_completion = 0
    total_calls = 0
    features: dict[str, dict] = {}
    for r in rows:
        total_prompt += r.prompt
        total_completion += r.completion
        total_calls += r.call_count
        features[r.feature] = {
            "prompt_tokens": r.prompt,
            "completion_tokens": r.completion,
            "total_tokens": r.prompt + r.completion,
            "call_count": r.call_count,
        }

    # Summary tasks token data
    summary_row = db.execute(
        select(
            func.coalesce(func.sum(SummaryTask.token_used), 0).label("tokens"),
            func.count().label("cnt"),
        )
        .where(SummaryTask.status == "done")
    ).one()

    return AdminTokenStats(
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_tokens=total_prompt + total_completion + summary_row.tokens,
        total_calls=total_calls + summary_row.cnt,
        summary_task_tokens=summary_row.tokens,
        summary_task_count=summary_row.cnt,
        by_feature=features,
    )


# ── Token usage details (per-user + recent tasks) ────────────


@router.get("/token-stats/details", response_model=AdminTokenDetails)
def admin_token_details(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Per-user token breakdown and recent summary tasks."""
    # Per-user audit tokens
    audit_sub = (
        select(
            LLMAuditLog.user_id,
            func.coalesce(func.sum(LLMAuditLog.prompt_tokens + LLMAuditLog.completion_tokens), 0).label("audit_tokens"),
            func.count().label("audit_calls"),
        )
        .group_by(LLMAuditLog.user_id)
        .subquery()
    )
    # Per-user summary tokens
    summary_sub = (
        select(
            SummaryTask.user_id,
            func.coalesce(func.sum(SummaryTask.token_used), 0).label("summary_tokens"),
            func.count().label("summary_calls"),
        )
        .where(SummaryTask.status == "done")
        .group_by(SummaryTask.user_id)
        .subquery()
    )

    user_rows = db.execute(
        select(
            User.id,
            User.username,
            User.phone,
            func.coalesce(audit_sub.c.audit_tokens, 0).label("audit_tokens"),
            func.coalesce(audit_sub.c.audit_calls, 0).label("audit_calls"),
            func.coalesce(summary_sub.c.summary_tokens, 0).label("summary_tokens"),
            func.coalesce(summary_sub.c.summary_calls, 0).label("summary_calls"),
        )
        .outerjoin(audit_sub, audit_sub.c.user_id == User.id)
        .outerjoin(summary_sub, summary_sub.c.user_id == User.id)
        .where(User.deleted == 0)
        .where(
            (audit_sub.c.audit_tokens > 0) | (summary_sub.c.summary_tokens > 0)
        )
        .order_by(
            (func.coalesce(audit_sub.c.audit_tokens, 0) + func.coalesce(summary_sub.c.summary_tokens, 0)).desc()
        )
        .limit(100)
    ).all()

    by_user = [
        UserTokenItem(
            user_id=r.id,
            username=r.username,
            phone=r.phone,
            audit_tokens=r.audit_tokens,
            audit_calls=r.audit_calls,
            summary_tokens=r.summary_tokens,
            summary_calls=r.summary_calls,
            total_tokens=r.audit_tokens + r.summary_tokens,
        )
        for r in user_rows
    ]

    # Recent summary tasks
    task_rows = db.execute(
        select(
            SummaryTask.id,
            SummaryTask.user_id,
            User.username,
            SummaryTask.status,
            SummaryTask.stage,
            SummaryTask.token_used,
            SummaryTask.created_at,
            SummaryTask.updated_at,
        )
        .join(User, User.id == SummaryTask.user_id)
        .order_by(SummaryTask.created_at.desc())
        .limit(50)
    ).all()

    recent_tasks = [
        SummaryTaskItem(
            task_id=r.id,
            user_id=r.user_id,
            username=r.username,
            status=r.status,
            stage=r.stage,
            token_used=r.token_used,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in task_rows
    ]

    return AdminTokenDetails(by_user=by_user, recent_tasks=recent_tasks)


# ── Feature Flags CRUD ───────────────────────────────────────


@router.get("/feature-flags", response_model=FeatureFlagListOut)
def list_feature_flags(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(FeatureFlag).order_by(FeatureFlag.key)).scalars().all()
    return FeatureFlagListOut(flags=[
        FeatureFlagOut(id=r.id, key=r.key, enabled=r.enabled, description=r.description,
                       rollout_pct=r.rollout_pct, updated_at=r.updated_at)
        for r in rows
    ])


@router.post("/feature-flags", response_model=FeatureFlagOut, status_code=201)
def create_feature_flag(
    body: FeatureFlagCreate,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(FeatureFlag).where(FeatureFlag.key == body.key)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Flag '{body.key}' already exists")
    flag = FeatureFlag(key=body.key, enabled=body.enabled, description=body.description, rollout_pct=body.rollout_pct)
    db.add(flag)
    db.commit()
    db.refresh(flag)
    invalidate_cache()
    return FeatureFlagOut(id=flag.id, key=flag.key, enabled=flag.enabled,
                          description=flag.description, rollout_pct=flag.rollout_pct, updated_at=flag.updated_at)


@router.patch("/feature-flags/{flag_id}", response_model=FeatureFlagOut)
def update_feature_flag(
    flag_id: int,
    body: FeatureFlagUpdate,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    flag = db.get(FeatureFlag, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    if body.enabled is not None:
        flag.enabled = body.enabled
    if body.description is not None:
        flag.description = body.description
    if body.rollout_pct is not None:
        flag.rollout_pct = body.rollout_pct
    db.commit()
    db.refresh(flag)
    invalidate_cache()
    return FeatureFlagOut(id=flag.id, key=flag.key, enabled=flag.enabled,
                          description=flag.description, rollout_pct=flag.rollout_pct, updated_at=flag.updated_at)


@router.delete("/feature-flags/{flag_id}")
def delete_feature_flag(
    flag_id: int,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    flag = db.get(FeatureFlag, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found")
    db.delete(flag)
    db.commit()
    invalidate_cache()
    return {"ok": True}


# ── Skills CRUD ──────────────────────────────────────────────


@router.get("/skills", response_model=SkillListOut)
def list_skills(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(Skill).order_by(Skill.priority)).scalars().all()
    return SkillListOut(skills=[
        SkillOut(id=r.id, key=r.key, name=r.name, description=r.description, enabled=r.enabled,
                 priority=r.priority, trigger_hint=r.trigger_hint, prompt_template=r.prompt_template,
                 updated_at=r.updated_at)
        for r in rows
    ])


@router.post("/skills", response_model=SkillOut, status_code=201)
def create_skill(
    body: SkillCreate,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.execute(select(Skill).where(Skill.key == body.key)).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Skill '{body.key}' already exists")
    skill = Skill(key=body.key, name=body.name, description=body.description, enabled=body.enabled,
                  priority=body.priority, trigger_hint=body.trigger_hint, prompt_template=body.prompt_template)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    invalidate_cache()
    return SkillOut(id=skill.id, key=skill.key, name=skill.name, description=skill.description,
                    enabled=skill.enabled, priority=skill.priority, trigger_hint=skill.trigger_hint,
                    prompt_template=skill.prompt_template, updated_at=skill.updated_at)


@router.patch("/skills/{skill_id}", response_model=SkillOut)
def update_skill(
    skill_id: int,
    body: SkillUpdate,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    for field in ("name", "description", "enabled", "priority", "trigger_hint", "prompt_template"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(skill, field, val)
    db.commit()
    db.refresh(skill)
    invalidate_cache()
    return SkillOut(id=skill.id, key=skill.key, name=skill.name, description=skill.description,
                    enabled=skill.enabled, priority=skill.priority, trigger_hint=skill.trigger_hint,
                    prompt_template=skill.prompt_template, updated_at=skill.updated_at)


@router.delete("/skills/{skill_id}")
def delete_skill(
    skill_id: int,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    db.delete(skill)
    db.commit()
    invalidate_cache()
    return {"ok": True}


# ── Indicator Knowledge ──────────────────────────────────────


@router.get("/indicators")
def list_indicators(
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(IndicatorKnowledge).order_by(IndicatorKnowledge.name.asc())
    ).scalars().all()
    return {
        "indicators": [
            {
                "id": r.id,
                "name": r.name,
                "alias": r.alias,
                "category": r.category,
                "brief": r.brief,
                "detail": r.detail,
                "normal_range": r.normal_range,
                "clinical_meaning": r.clinical_meaning,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/indicators")
def create_indicator(
    body: dict,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    existing = db.execute(
        select(IndicatorKnowledge).where(IndicatorKnowledge.name == name)
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Indicator '{name}' already exists")
    ind = IndicatorKnowledge(
        name=name,
        alias=body.get("alias", ""),
        category=body.get("category", ""),
        brief=body.get("brief", ""),
        detail=body.get("detail", ""),
        normal_range=body.get("normal_range", ""),
        clinical_meaning=body.get("clinical_meaning", ""),
        source="manual",
    )
    db.add(ind)
    db.commit()
    db.refresh(ind)
    return {"ok": True, "id": ind.id}


@router.patch("/indicators/{indicator_id}")
def update_indicator(
    indicator_id: int,
    body: dict,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ind = db.get(IndicatorKnowledge, indicator_id)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    for field in ("name", "alias", "category", "brief", "detail", "normal_range", "clinical_meaning"):
        if field in body:
            setattr(ind, field, body[field])
    if "source" not in body:
        ind.source = "manual"
    db.commit()
    return {"ok": True}


@router.delete("/indicators/{indicator_id}")
def delete_indicator(
    indicator_id: int,
    _admin_id: int = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ind = db.get(IndicatorKnowledge, indicator_id)
    if not ind:
        raise HTTPException(status_code=404, detail="Indicator not found")
    db.delete(ind)
    db.commit()
    return {"ok": True}
