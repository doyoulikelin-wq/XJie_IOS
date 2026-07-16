"""Fail-closed facade for every AI consumer of confirmed health information."""

from __future__ import annotations

from typing import Any, Literal, cast

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileSource,
    HealthReportWorkflow,
)
from app.models.health_trust_expansion import (
    HealthProfileDeviceSourceLink,
    HealthProfileFactSourceVersion,
    HealthProfileGoal,
    HealthProfileGoalMetric,
    TrustedDeviceProfileObservation,
)
from app.models.medication_trust import TrustedMedicationPlan
from app.services.health_profile_completion_service import sanitize_profile_payload


TrustedHealthConsumer = Literal[
    "chat_question",
    "daily_advice",
    "medication_allergy_risk",
    "long_term_trend_explanation",
]

DECLARED_TRUSTED_HEALTH_CONSUMERS: frozenset[str] = frozenset(
    {
        "chat_question",
        "daily_advice",
        "medication_allergy_risk",
        "long_term_trend_explanation",
    }
)
DENIED_TRUSTED_HEALTH_CONSUMERS: frozenset[str] = frozenset({"x_age"})


class TrustedHealthContextAccessError(ValueError):
    """Raised for undeclared or explicitly denied consumers."""


def require_declared_consumer(consumer: str) -> TrustedHealthConsumer:
    normalized = (consumer or "").strip()
    if normalized in DENIED_TRUSTED_HEALTH_CONSUMERS:
        raise TrustedHealthContextAccessError(
            f"Trusted health context is denied for consumer: {normalized}"
        )
    if normalized not in DECLARED_TRUSTED_HEALTH_CONSUMERS:
        raise TrustedHealthContextAccessError(
            f"Trusted health context consumer is not declared: {normalized or '<empty>'}"
        )
    return cast(TrustedHealthConsumer, normalized)


def _authoritative_medication_summary_items(
    db: Session, *, user_id: int
) -> list[dict[str, Any]] | None:
    """Return current plan-derived items, or None when plans never held authority."""
    history = list(
        db.execute(
            select(TrustedMedicationPlan)
            .where(
                TrustedMedicationPlan.user_id == user_id,
                TrustedMedicationPlan.subject_user_id == user_id,
                TrustedMedicationPlan.is_long_term.is_(True),
                TrustedMedicationPlan.confirmed_by_user_id == user_id,
                TrustedMedicationPlan.confirmed_at.is_not(None),
            )
            .order_by(TrustedMedicationPlan.generic_name, TrustedMedicationPlan.id)
        ).scalars().all()
    )
    if not history:
        return None
    source_labels = {
        "manual": "user_added",
        "prescription_import": "prescription",
        "ocr": "ocr_confirmed",
        "history": "history_confirmed",
    }
    return [
        {
            "medication_name": plan.brand_name or plan.generic_name,
            "purpose": plan.purpose,
            "started_on": plan.course_start.isoformat() if plan.course_start else None,
            "is_still_taking": plan.status == "active",
            "source": source_labels[plan.source_type],
            "last_confirmed_at": plan.confirmed_at.isoformat(),
        }
        for plan in history
        if plan.status in {"active", "paused"}
    ]


def _confirmed_facts(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    # A user-confirmed medication-plan mutation can invalidate an older
    # accepted profile summary before the replacement candidate is reviewed.
    # Hide that stale summary while the server-authoritative replacement is
    # pending; other fact categories keep their last confirmed value.
    stale_medication_fact_keys = set(
        db.execute(
            select(HealthProfileCandidate.fact_key).where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == user_id,
                HealthProfileCandidate.category == "medication",
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
            )
        ).scalars().all()
    )
    authoritative_medication_items = _authoritative_medication_summary_items(
        db, user_id=user_id
    )
    rows = list(
        db.execute(
            select(HealthProfileFact)
            .where(
                HealthProfileFact.user_id == user_id,
                HealthProfileFact.subject_user_id == user_id,
                HealthProfileFact.status == "active",
                HealthProfileFact.confirmation_method.in_(
                    ["user", "clinician", "verified_source"]
                ),
                HealthProfileFact.confirmed_at.is_not(None),
            )
            .order_by(HealthProfileFact.category, HealthProfileFact.fact_key)
        ).scalars().all()
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.fact_key in stale_medication_fact_keys:
            continue
        sanitized_value = sanitize_profile_payload(
            dict(row.value_data or {}), fact_key=row.fact_key, category=row.category
        )
        if (
            row.fact_key == "medication.long_term_summary"
            and authoritative_medication_items is not None
            and (
                not isinstance(sanitized_value, dict)
                or sanitized_value.get("items") != authoritative_medication_items
            )
        ):
            continue
        result.append(
            {
                "fact_key": row.fact_key,
                "category": row.category,
                "value": sanitized_value,
                "version": row.version,
                "confirmed_at": row.confirmed_at.isoformat()
                if row.confirmed_at
                else None,
            }
        )
    return result


def _confirmed_observations(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(ConfirmedHealthObservation)
            .join(
                HealthReportWorkflow,
                HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
            )
            .where(
                ConfirmedHealthObservation.user_id == user_id,
                ConfirmedHealthObservation.subject_user_id == user_id,
                ConfirmedHealthObservation.status == "active",
                HealthReportWorkflow.user_id == user_id,
                HealthReportWorkflow.subject_user_id == user_id,
                HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
                HealthReportWorkflow.confirmed_at.is_not(None),
            )
            .order_by(
                ConfirmedHealthObservation.effective_at.desc(),
                ConfirmedHealthObservation.id.desc(),
            )
            .limit(100)
        ).scalars().all()
    )
    return [
        {
            "observation_id": row.id,
            "canonical_code": row.canonical_code,
            "canonical_name": row.canonical_name,
            "value_numeric": str(row.value_numeric) if row.value_numeric is not None else None,
            "value_text": row.value_text,
            "unit": row.unit,
            "abnormal_state": row.abnormal_state,
            "effective_at": row.effective_at.isoformat(),
            "confirmed_at": row.confirmed_at.isoformat(),
        }
        for row in rows
    ]


def _device_observations(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    # `active` describes the latest immutable device snapshot, not user
    # admission.  An observation is AI-readable only when its copied profile
    # source is frozen into the current version of an active confirmed fact.
    rows = list(
        db.execute(
            select(TrustedDeviceProfileObservation)
            .join(
                HealthProfileDeviceSourceLink,
                and_(
                    HealthProfileDeviceSourceLink.device_observation_id
                    == TrustedDeviceProfileObservation.id,
                    HealthProfileDeviceSourceLink.user_id
                    == TrustedDeviceProfileObservation.user_id,
                    HealthProfileDeviceSourceLink.subject_user_id
                    == TrustedDeviceProfileObservation.subject_user_id,
                ),
            )
            .join(
                HealthProfileSource,
                and_(
                    HealthProfileSource.id
                    == HealthProfileDeviceSourceLink.profile_source_id,
                    HealthProfileSource.user_id == user_id,
                    HealthProfileSource.subject_user_id == user_id,
                    HealthProfileSource.fact_id.is_not(None),
                ),
            )
            .join(
                HealthProfileFact,
                and_(
                    HealthProfileFact.id == HealthProfileSource.fact_id,
                    HealthProfileFact.user_id == user_id,
                    HealthProfileFact.subject_user_id == user_id,
                    HealthProfileFact.status == "active",
                    HealthProfileFact.confirmation_method.in_(
                        ["user", "clinician", "verified_source"]
                    ),
                    HealthProfileFact.confirmed_at.is_not(None),
                ),
            )
            .join(
                HealthProfileFactSourceVersion,
                and_(
                    HealthProfileFactSourceVersion.profile_source_id
                    == HealthProfileSource.id,
                    HealthProfileFactSourceVersion.fact_id == HealthProfileFact.id,
                    HealthProfileFactSourceVersion.fact_version
                    == HealthProfileFact.version,
                    HealthProfileFactSourceVersion.user_id == user_id,
                    HealthProfileFactSourceVersion.subject_user_id == user_id,
                ),
            )
            .where(
                TrustedDeviceProfileObservation.user_id == user_id,
                TrustedDeviceProfileObservation.subject_user_id == user_id,
                TrustedDeviceProfileObservation.status == "active",
            )
            .order_by(
                TrustedDeviceProfileObservation.effective_at.desc(),
                TrustedDeviceProfileObservation.id.desc(),
            )
            .limit(100)
            .distinct()
        ).scalars().all()
    )
    return [
        {
            "observation_id": row.id,
            "fact_key": row.fact_key,
            "value_numeric": str(row.value_numeric) if row.value_numeric is not None else None,
            "value_text": row.value_text,
            "unit": row.unit,
            "effective_at": row.effective_at.isoformat(),
            "mapping_version": row.metric_mapping_version,
        }
        for row in rows
    ]


def _user_goals(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    goals = list(
        db.execute(
            select(HealthProfileGoal)
            .where(
                HealthProfileGoal.user_id == user_id,
                HealthProfileGoal.subject_user_id == user_id,
                HealthProfileGoal.status != "archived",
                HealthProfileGoal.confirmed_by_user_id == user_id,
                HealthProfileGoal.confirmed_at.is_not(None),
            )
            .order_by(HealthProfileGoal.started_on, HealthProfileGoal.id)
        ).scalars().all()
    )
    if not goals:
        return []
    metrics = list(
        db.execute(
            select(HealthProfileGoalMetric)
            .where(
                HealthProfileGoalMetric.user_id == user_id,
                HealthProfileGoalMetric.subject_user_id == user_id,
                HealthProfileGoalMetric.goal_id.in_([goal.id for goal in goals]),
            )
            .order_by(HealthProfileGoalMetric.goal_id, HealthProfileGoalMetric.id)
        ).scalars().all()
    )
    metric_keys: dict[int, list[str]] = {}
    for metric in metrics:
        metric_keys.setdefault(metric.goal_id, []).append(metric.metric_key)
    return [
        {
            "goal_id": goal.id,
            "name": goal.name,
            "status": goal.status,
            "started_on": goal.started_on.isoformat(),
            "metric_keys": metric_keys.get(goal.id, []),
            "version": goal.version,
        }
        for goal in goals
    ]


def _confirmed_medications(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(TrustedMedicationPlan)
            .where(
                TrustedMedicationPlan.user_id == user_id,
                TrustedMedicationPlan.subject_user_id == user_id,
                TrustedMedicationPlan.status.in_(["active", "paused"]),
                TrustedMedicationPlan.confirmed_by_user_id == user_id,
                TrustedMedicationPlan.confirmed_at.is_not(None),
            )
            .order_by(TrustedMedicationPlan.updated_at.desc(), TrustedMedicationPlan.id.desc())
            .limit(50)
        ).scalars().all()
    )
    return [
        {
            "plan_id": row.id,
            "name": row.generic_name,
            "brand_name": row.brand_name,
            "purpose": row.purpose,
            "strength": row.strength,
            "dose_text": row.dose_text,
            "frequency": row.frequency,
            "schedule_times": list(row.schedule_times or []),
            "status": row.status,
            "version": row.version,
            "confirmed_at": row.confirmed_at.isoformat(),
        }
        for row in rows
    ]


def build_trusted_health_context(
    db: Session,
    *,
    user_id: int,
    consumer: str,
) -> dict[str, Any]:
    """Build context from confirmed rows only; there is no permissive default."""
    declared = require_declared_consumer(consumer)
    context: dict[str, Any] = {
        "consumer": declared,
        "profile_facts": _confirmed_facts(db, user_id=user_id),
    }
    if declared in {"chat_question", "daily_advice", "long_term_trend_explanation"}:
        context["goals"] = _user_goals(db, user_id=user_id)
    if declared in {"chat_question", "daily_advice", "medication_allergy_risk"}:
        context["medications"] = _confirmed_medications(db, user_id=user_id)
    if declared in {"chat_question", "long_term_trend_explanation"}:
        context["report_observations"] = _confirmed_observations(db, user_id=user_id)
        context["device_observations"] = _device_observations(db, user_id=user_id)
    return context
