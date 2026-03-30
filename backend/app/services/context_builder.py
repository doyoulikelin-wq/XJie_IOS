import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import ChatMessage, Conversation
from app.models.meal import Meal
from app.models.omics import OmicsUpload
from app.models.symptom import Symptom
from app.models.feature import FeatureSnapshot
from app.models.user_profile import UserProfile
from app.services.glucose_service import get_glucose_summary

logger = logging.getLogger(__name__)


def build_user_context(db: Session, user_id: str) -> dict:
    now = datetime.now(timezone.utc)

    summary_24h = get_glucose_summary(db, user_id, "24h")
    summary_7d = get_glucose_summary(db, user_id, "7d")

    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    meals = db.execute(
        select(Meal)
        .where(Meal.user_id == user_id, Meal.meal_ts >= day_start, Meal.meal_ts < now)
        .order_by(Meal.meal_ts.asc())
    ).scalars().all()

    symptoms = db.execute(
        select(Symptom)
        .where(Symptom.user_id == user_id, Symptom.ts >= now - timedelta(days=7), Symptom.ts < now)
        .order_by(Symptom.ts.desc())
        .limit(20)
    ).scalars().all()

    kcal_today = sum(m.kcal for m in meals) if meals else 0

    profile_info = _get_profile_info(db, user_id)

    # Build health report text for Liver subjects
    health_report_text = _get_health_report_text(profile_info)

    return {
        "profile": {},
        "glucose_summary": {
            "last_24h": summary_24h,
            "last_7d": summary_7d,
        },
        "meals_today": [
            {
                "ts": meal.meal_ts.isoformat(),
                "kcal": meal.kcal,
                "tags": meal.tags,
                "source": meal.meal_ts_source.value,
                "photo_id": str(meal.photo_id) if meal.photo_id else None,
            }
            for meal in meals
        ],
        "symptoms_last_7d": [
            {
                "ts": s.ts.isoformat(),
                "severity": s.severity,
                "text": s.text,
            }
            for s in symptoms
        ],
        "data_quality": {
            "glucose_gaps_hours": summary_24h["gaps_hours"],
            "kcal_today": kcal_today,
        },
        "agent_features": _get_agent_features(db, user_id),
        "user_profile_info": profile_info,
        "health_report_text": health_report_text,
        "omics_analyses": _get_omics_analyses(db, user_id),
        "recent_conversation_summaries": _get_recent_conversation_summaries(db, user_id),
    }


def _get_agent_features(db: Session, user_id: str) -> dict:
    """Fetch latest feature snapshots for agent context."""
    result = {}
    for window in ("24h", "7d", "28d"):
        snap = db.execute(
            select(FeatureSnapshot)
            .where(FeatureSnapshot.user_id == user_id, FeatureSnapshot.window == window)
            .order_by(FeatureSnapshot.computed_at.desc())
            .limit(1)
        ).scalars().first()
        if snap:
            result[window] = snap.features
    return result


def _get_profile_info(db: Session, user_id: str) -> dict:
    """Fetch user profile info for agent context."""
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if not profile:
        return {}
    return {
        "subject_id": profile.subject_id,
        "cohort": profile.cohort,
        "liver_risk_level": profile.liver_risk_level,
    }


def _get_health_report_text(profile_info: dict) -> str:
    """Build a text summary of health exam report data for the chat prompt.

    Uses lazy import to avoid circular dependency with health_reports router.
    """
    sid = profile_info.get("subject_id", "")
    cohort = profile_info.get("cohort", "")
    if not sid or not sid.startswith("Liver"):
        return ""
    try:
        from app.routers.health_reports import _build_report_data, _build_health_data_prompt
        report = _build_report_data(sid, cohort, None)  # db not used for Liver XLS parsing
        if not report.get("phases"):
            return ""
        return _build_health_data_prompt(report)
    except Exception:
        logger.warning("Failed to build health report text for chat context", exc_info=True)
        return ""


def _get_omics_analyses(db: Session, user_id: str) -> list[dict]:
    """Fetch user's latest omics analysis results for LLM context."""
    uploads = db.execute(
        select(OmicsUpload)
        .where(OmicsUpload.user_id == user_id, OmicsUpload.llm_summary.isnot(None))
        .order_by(OmicsUpload.created_at.desc())
        .limit(3)
    ).scalars().all()
    return [
        {
            "type": u.omics_type,
            "file_name": u.file_name,
            "risk_level": u.risk_level,
            "summary": u.llm_summary,
            "analysis": (u.llm_analysis or "")[:500],
        }
        for u in uploads
    ]


def _get_recent_conversation_summaries(db: Session, user_id: str) -> list[dict]:
    """Load assistant summaries from recent conversations for cross-session memory."""
    recent_convs = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(5)
    ).scalars().all()

    summaries = []
    for conv in recent_convs:
        msgs = db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conv.id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.seq.desc())
            .limit(2)
        ).scalars().all()
        if msgs:
            summaries.append({
                "conv_title": conv.title,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
                "messages": [
                    {"content": m.content[:200], "analysis_snippet": (m.analysis or "")[:150]}
                    for m in reversed(msgs)
                ],
            })
    return summaries
