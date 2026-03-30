"""Agent API endpoints – consumed by the chat/dog UI.

All agentic features (daily briefing, pre-meal sim, rescue,
weekly review, proactive dog message, feedback) are exposed here.
"""


from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.agent import AgentAction, FeedbackChoice, OutcomeFeedback
from app.services.agent_service import (
    check_rescue_needed,
    generate_daily_briefing,
    generate_weekly_review,
    get_proactive_message,
    simulate_pre_meal,
)

router = APIRouter()


# ── Request / Response schemas ──────────────────────────────


class PreMealSimRequest(BaseModel):
    kcal: float
    meal_time: str = "now"


class FeedbackRequest(BaseModel):
    action_id: str
    user_feedback: str  # executed / not_executed / partial


# ── Endpoints ────────────────────────────────────────────────


@router.get("/today")
def today_briefing(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Daily metabolic weather – today's glucose status, risk windows, goals."""
    return generate_daily_briefing(db, user_id)


@router.get("/weekly")
def weekly_review(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Weekly review – last 7d analysis, goal progress, next week target."""
    return generate_weekly_review(db, user_id)


@router.post("/premeal-sim")
def premeal_sim(
    payload: PreMealSimRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Pre-meal simulation – predict post-meal glucose & suggest alternatives."""
    return simulate_pre_meal(db, user_id, payload.kcal, payload.meal_time)


@router.get("/rescue")
def rescue_check(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Check if a post-meal rescue is needed right now."""
    result = check_rescue_needed(db, user_id)
    if result is None:
        return {"type": "no_rescue", "message": "当前血糖平稳，无需补救"}
    return result


@router.get("/proactive")
def proactive_message(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Proactive dog message – for the home page bubble."""
    return get_proactive_message(db, user_id)


@router.get("/actions")
def list_actions(
    action_type: str | None = None,
    limit: int = 20,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List recent agent actions (optionally filtered by type)."""
    q = select(AgentAction).where(AgentAction.user_id == user_id)
    if action_type:
        q = q.where(AgentAction.action_type == action_type)
    q = q.order_by(AgentAction.created_ts.desc()).limit(limit)
    actions = db.execute(q).scalars().all()
    return [
        {
            "id": str(a.id),
            "user_id": str(a.user_id),
            "action_type": a.action_type.value if hasattr(a.action_type, 'value') else a.action_type,
            "payload_version": a.payload_version,
            "payload": a.payload,
            "reason_evidence": a.reason_evidence,
            "status": a.status.value if hasattr(a.status, 'value') else a.status,
            "priority": a.priority,
            "error_code": a.error_code,
            "trace_id": a.trace_id,
            "created_ts": a.created_ts.isoformat() if a.created_ts else None,
        }
        for a in actions
    ]


@router.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Submit user feedback on an agent action (executed/not/partial)."""
    # Verify the action belongs to the current user
    action = db.execute(
        select(AgentAction).where(
            AgentAction.id == int(payload.action_id),
            AgentAction.user_id == user_id,
        )
    ).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found or not owned by you")

    feedback = OutcomeFeedback(
        action_id=action.id,
        user_feedback=FeedbackChoice(payload.user_feedback),
        objective_outcome={},
    )
    db.add(feedback)
    db.commit()
    return {"ok": True, "feedback_id": str(feedback.id)}
