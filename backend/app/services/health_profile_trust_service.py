"""Server-authoritative health-profile confirmation, provenance, and completeness."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileRevision,
    HealthProfileSource,
    HealthReportWorkflow,
)
from app.models.health_trust_expansion import (
    HealthProfileDeviceSourceLink,
    HealthProfileFactSourceVersion,
    HealthProfileGoal,
    HealthProfileGoalMetric,
    HealthProfileGoalRevision,
    TrustedDeviceProfileObservation,
)
from app.models.health_plan import HealthPlan, PlanTask
from app.models.user_indicator_value import UserIndicatorValue
from app.schemas.health_profile_trust import (
    HealthProfileCandidateReviewIn,
    HealthProfileFactRetractIn,
    HealthProfileFactUpsertIn,
    HealthProfileGoalCreateIn,
    HealthProfileGoalStatusIn,
    HealthProfileGoalUpdateIn,
)
from app.services.health_profile_completion_service import (
    build_profile_completion,
    canonical_source_identity,
    sanitize_medication_payload,
    sanitize_profile_payload,
)


PROFILE_CANDIDATE_ALGORITHM_VERSION = "profile-candidate.repeated-abnormal.v1"
DEVICE_PROFILE_MAPPING_VERSION = "device-profile.height-weight.v1"

LEGACY_SECTION_FACT_MAP: dict[str, tuple[str, str, bool]] = {
    "diagnoses": ("long_term_health.diagnoses", "long_term_health", False),
    "surgeries": ("safety.major_surgery", "safety", True),
    "medications": ("medication.long_term_summary", "medication", False),
    "allergies": ("safety.other_allergy", "safety", True),
    "recent_findings": ("long_term_health.recent_findings", "long_term_health", False),
    "care_goals": ("goal.primary", "goal", False),
    "family_history": ("long_term_health.family_history", "long_term_health", False),
    "lifestyle_risks": ("basic.lifestyle", "basic", False),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_id(prefix: str, value: str, *, limit: int = 80) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"[:limit]


def _json_fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _fact_snapshot(fact: HealthProfileFact | None) -> dict[str, Any]:
    if fact is None:
        return {}
    return {
        "fact_id": fact.id,
        "fact_key": fact.fact_key,
        "category": fact.category,
        "value_data": dict(fact.value_data or {}),
        "is_safety_critical": fact.is_safety_critical,
        "confirmation_method": fact.confirmation_method,
        "status": fact.status,
        "version": fact.version,
        "confirmed_by_user_id": fact.confirmed_by_user_id,
        "confirmed_at": fact.confirmed_at.isoformat() if fact.confirmed_at else None,
    }


def _candidate_snapshot(candidate: HealthProfileCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "fact_key": candidate.fact_key,
        "category": candidate.category,
        "proposed_value": dict(candidate.proposed_value or {}),
        "is_safety_critical": candidate.is_safety_critical,
        "review_status": candidate.review_status,
        "conflict_with_fact_id": candidate.conflict_with_fact_id,
        "confidence": str(candidate.confidence) if candidate.confidence is not None else None,
        "version": candidate.version,
    }


def _candidate_review_request(payload: HealthProfileCandidateReviewIn) -> dict[str, Any]:
    return {
        "candidate_version": payload.candidate_version,
        "action": payload.action,
    }


def _manual_upsert_request(payload: HealthProfileFactUpsertIn) -> dict[str, Any]:
    return {
        "fact_key": payload.fact_key,
        "category": payload.category,
        "response_state": payload.response_state,
        "value": payload.value,
        "is_safety_critical": payload.is_safety_critical,
        "expected_version": payload.expected_version,
    }


def _retract_request(payload: HealthProfileFactRetractIn) -> dict[str, Any]:
    return {"expected_version": payload.expected_version}


def _validate_safety_classification(
    *,
    fact_key: str,
    category: str,
    is_safety_critical: bool,
    status_code: int,
) -> None:
    key_is_safety = fact_key.startswith("safety.")
    category_is_safety = category == "safety"
    if key_is_safety != category_is_safety:
        raise HTTPException(status_code=status_code, detail="Safety fact key and category must match")
    if category_is_safety != is_safety_critical:
        raise HTTPException(
            status_code=status_code,
            detail="Safety facts must be explicitly classified as safety critical",
        )


def _source_out(source: HealthProfileSource) -> dict[str, Any]:
    return {
        "source_id": source.id,
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "confidence": source.confidence,
        "source_snapshot": sanitize_medication_payload(dict(source.source_snapshot or {}))
        if source.source_type == "medication"
        else dict(source.source_snapshot or {}),
        "created_at": source.created_at,
    }


def _sources_by_target(
    sources: Iterable[HealthProfileSource],
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    facts: dict[int, list[dict[str, Any]]] = defaultdict(list)
    candidates: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        if source.fact_id is not None:
            facts[source.fact_id].append(_source_out(source))
        if source.candidate_id is not None:
            candidates[source.candidate_id].append(_source_out(source))
    return facts, candidates


def build_profile(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
) -> dict[str, Any]:
    facts = list(
        db.execute(
            select(HealthProfileFact)
            .where(
                HealthProfileFact.user_id == user_id,
                HealthProfileFact.subject_user_id == subject_user_id,
                HealthProfileFact.status == "active",
            )
            .order_by(HealthProfileFact.category, HealthProfileFact.fact_key)
        ).scalars().all()
    )
    candidates = list(
        db.execute(
            select(HealthProfileCandidate)
            .where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
            )
            .order_by(HealthProfileCandidate.created_at, HealthProfileCandidate.id)
        ).scalars().all()
    )
    goals = list(
        db.execute(
            select(HealthProfileGoal)
            .where(
                HealthProfileGoal.user_id == user_id,
                HealthProfileGoal.subject_user_id == subject_user_id,
                HealthProfileGoal.status != "archived",
            )
            .order_by(HealthProfileGoal.started_on, HealthProfileGoal.id)
        ).scalars().all()
    )
    # HealthPlan predates subject-aware profile data and is scoped only by
    # account owner. Expose it solely for the owner's own profile; projecting
    # it into a family/member subject would silently cross subject boundaries.
    management_plans: list[HealthPlan] = []
    management_plan_counts: dict[int, tuple[int, int]] = {}
    if subject_user_id == user_id:
        management_plans = list(
            db.execute(
                select(HealthPlan)
                .where(
                    HealthPlan.user_id == user_id,
                    HealthPlan.status == "active",
                )
                .order_by(HealthPlan.updated_at.desc(), HealthPlan.id.desc())
            ).scalars().all()
        )
        if management_plans:
            count_rows = db.execute(
                select(
                    PlanTask.plan_id,
                    func.count(PlanTask.id),
                    func.coalesce(
                        func.sum(case((PlanTask.status == "completed", 1), else_=0)),
                        0,
                    ),
                )
                .where(
                    PlanTask.user_id == user_id,
                    PlanTask.plan_id.in_([plan.id for plan in management_plans]),
                )
                .group_by(PlanTask.plan_id)
            ).all()
            management_plan_counts = {
                int(plan_id): (int(task_count or 0), int(completed_count or 0))
                for plan_id, task_count, completed_count in count_rows
                if plan_id is not None
            }
    goal_metrics: dict[int, list[HealthProfileGoalMetric]] = defaultdict(list)
    if goals:
        metric_rows = list(
            db.execute(
                select(HealthProfileGoalMetric)
                .where(
                    HealthProfileGoalMetric.user_id == user_id,
                    HealthProfileGoalMetric.subject_user_id == subject_user_id,
                    HealthProfileGoalMetric.goal_id.in_([goal.id for goal in goals]),
                )
                .order_by(HealthProfileGoalMetric.goal_id, HealthProfileGoalMetric.id)
            ).scalars().all()
        )
        for metric in metric_rows:
            goal_metrics[metric.goal_id].append(metric)
    fact_ids = [item.id for item in facts]
    candidate_ids = [item.id for item in candidates]
    source_filters = []
    if fact_ids:
        source_filters.append(HealthProfileSource.fact_id.in_(fact_ids))
    if candidate_ids:
        source_filters.append(HealthProfileSource.candidate_id.in_(candidate_ids))
    sources: list[HealthProfileSource] = []
    if source_filters:
        from sqlalchemy import or_

        sources = list(
            db.execute(
                select(HealthProfileSource)
                .where(
                    HealthProfileSource.user_id == user_id,
                    HealthProfileSource.subject_user_id == subject_user_id,
                    or_(*source_filters),
                )
                .order_by(HealthProfileSource.created_at, HealthProfileSource.id)
            ).scalars().all()
        )
    fact_sources, candidate_sources = _sources_by_target(sources)

    overview, profile_status = build_profile_completion(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        facts=facts,
        candidates=candidates,
        sources=sources,
        goals=goals,
    )

    return {
        "subject_user_id": subject_user_id,
        "profile_status": profile_status,
        "overview": overview,
        "facts": [
            {
                "fact_id": fact.id,
                "fact_key": fact.fact_key,
                "category": fact.category,
                "value_data": sanitize_profile_payload(
                    dict(fact.value_data or {}),
                    fact_key=fact.fact_key,
                    category=fact.category,
                ),
                "is_safety_critical": fact.is_safety_critical,
                "confirmation_method": fact.confirmation_method,
                "version": fact.version,
                "confirmed_at": fact.confirmed_at,
                "updated_at": fact.updated_at,
                "sources": fact_sources.get(fact.id, []),
            }
            for fact in facts
        ],
        "candidates": [
            {
                "candidate_id": candidate.id,
                "fact_key": candidate.fact_key,
                "category": candidate.category,
                "proposed_value": sanitize_profile_payload(
                    dict(candidate.proposed_value or {}),
                    fact_key=candidate.fact_key,
                    category=candidate.category,
                ),
                "is_safety_critical": candidate.is_safety_critical,
                "review_status": candidate.review_status,
                "conflict_with_fact_id": candidate.conflict_with_fact_id,
                "confidence": candidate.confidence,
                "version": candidate.version,
                "created_at": candidate.created_at,
                "updated_at": candidate.updated_at,
                "sources": candidate_sources.get(candidate.id, []),
            }
            for candidate in candidates
        ],
        "goals": [
            {
                "goal_id": goal.id,
                "name": goal.name,
                "status": goal.status,
                "started_on": goal.started_on,
                "version": goal.version,
                "confirmed_at": goal.confirmed_at,
                "metrics": [
                    {
                        "metric_key": metric.metric_key,
                        "display_label": metric.display_label,
                    }
                    for metric in goal_metrics.get(goal.id, [])
                ],
            }
            for goal in goals
        ],
        "management_plans": [
            {
                "plan_id": plan.id,
                "title": plan.title,
                "goal": plan.goal,
                "start_date": plan.start_date,
                "end_date": plan.end_date,
                "status": plan.status,
                "created_by": plan.created_by,
                "updated_at": plan.updated_at,
                "task_count": management_plan_counts.get(plan.id, (0, 0))[0],
                "completed_task_count": management_plan_counts.get(plan.id, (0, 0))[1],
            }
            for plan in management_plans
        ],
    }


def _revision_for_client_event(
    db: Session, *, user_id: int, subject_user_id: int, client_event_id: str
) -> HealthProfileRevision | None:
    return db.execute(
        select(HealthProfileRevision).where(
            HealthProfileRevision.user_id == user_id,
            HealthProfileRevision.subject_user_id == subject_user_id,
            HealthProfileRevision.client_event_id == client_event_id,
        )
    ).scalars().first()


def _copy_candidate_sources_to_fact(
    db: Session,
    *,
    candidate: HealthProfileCandidate,
    fact: HealthProfileFact,
) -> list[HealthProfileSource]:
    """Copy and return only the sources admitted by this candidate."""
    sources = db.execute(
        select(HealthProfileSource).where(
            HealthProfileSource.user_id == candidate.user_id,
            HealthProfileSource.subject_user_id == candidate.subject_user_id,
            HealthProfileSource.candidate_id == candidate.id,
        )
    ).scalars().all()
    admitted_sources: list[HealthProfileSource] = []
    for source in sources:
        idempotency_key = _bounded_id(
            "fact-source:", f"{fact.id}:{source.id}", limit=96
        )
        existing = db.execute(
            select(HealthProfileSource).where(
                HealthProfileSource.user_id == fact.user_id,
                HealthProfileSource.subject_user_id == fact.subject_user_id,
                HealthProfileSource.idempotency_key == idempotency_key,
            )
        ).scalars().first()
        if existing:
            admitted_sources.append(existing)
            continue
        fact_source = HealthProfileSource(
            user_id=fact.user_id,
            subject_user_id=fact.subject_user_id,
            fact_id=fact.id,
            candidate_id=None,
            source_type=source.source_type,
            source_ref=source.source_ref,
            source_observation_id=source.source_observation_id,
            source_snapshot=dict(source.source_snapshot or {}),
            confidence=source.confidence,
            idempotency_key=idempotency_key,
        )
        db.add(fact_source)
        db.flush()
        admitted_sources.append(fact_source)
        device_link = db.execute(
            select(HealthProfileDeviceSourceLink).where(
                HealthProfileDeviceSourceLink.profile_source_id == source.id,
                HealthProfileDeviceSourceLink.user_id == source.user_id,
                HealthProfileDeviceSourceLink.subject_user_id == source.subject_user_id,
            )
        ).scalars().first()
        if device_link is not None:
            db.add(
                HealthProfileDeviceSourceLink(
                    profile_source_id=fact_source.id,
                    device_observation_id=device_link.device_observation_id,
                    user_id=fact.user_id,
                    subject_user_id=fact.subject_user_id,
                )
            )
    return admitted_sources


def _record_fact_source_version(
    db: Session,
    *,
    fact: HealthProfileFact,
    sources: Iterable[HealthProfileSource],
) -> None:
    """Freeze the exact canonical source set for the current fact version."""
    seen: set[tuple[str, str]] = set()
    for source in sources:
        if (
            source.fact_id != fact.id
            or source.user_id != fact.user_id
            or source.subject_user_id != fact.subject_user_id
        ):
            raise ValueError("Fact-version source does not belong to the target fact tenant")
        source_type, source_identity = canonical_source_identity(
            source.source_type, source.source_ref
        )
        identity = (source_type, source_identity)
        if identity in seen:
            continue
        seen.add(identity)
        existing = db.execute(
            select(HealthProfileFactSourceVersion).where(
                HealthProfileFactSourceVersion.fact_id == fact.id,
                HealthProfileFactSourceVersion.user_id == fact.user_id,
                HealthProfileFactSourceVersion.subject_user_id == fact.subject_user_id,
                HealthProfileFactSourceVersion.fact_version == fact.version,
                HealthProfileFactSourceVersion.source_identity == source_identity,
            )
        ).scalars().first()
        if existing is not None:
            continue
        db.add(
            HealthProfileFactSourceVersion(
                fact_id=fact.id,
                user_id=fact.user_id,
                subject_user_id=fact.subject_user_id,
                fact_version=fact.version,
                profile_source_id=source.id,
                source_type=source_type,
                source_identity=source_identity,
                source_snapshot=dict(source.source_snapshot or {}),
            )
        )


def review_candidate(
    db: Session,
    *,
    candidate_id: int,
    user_id: int,
    payload: HealthProfileCandidateReviewIn,
) -> dict[str, Any]:
    request_snapshot = _candidate_review_request(payload)
    existing_revision = _revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if existing_revision:
        if (
            existing_revision.candidate_id != candidate_id
            or (existing_revision.after_data or {}).get("request") != request_snapshot
        ):
            raise HTTPException(status_code=409, detail="Profile client event was reused")
        return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)

    candidate = db.execute(
        select(HealthProfileCandidate)
        .where(
            HealthProfileCandidate.id == candidate_id,
            HealthProfileCandidate.user_id == user_id,
            HealthProfileCandidate.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Profile candidate not found")
    if candidate.version != payload.candidate_version:
        raise HTTPException(status_code=409, detail="Profile candidate version is stale")
    if candidate.review_status not in {"pending_review", "conflict"}:
        raise HTTPException(status_code=409, detail="Profile candidate is already resolved")
    _validate_safety_classification(
        fact_key=candidate.fact_key,
        category=candidate.category,
        is_safety_critical=candidate.is_safety_critical,
        status_code=409,
    )
    if payload.action == "accept" and candidate.category in {"safety", "goal"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Safety candidates require the dedicated safety editor"
                if candidate.category == "safety"
                else "AI/profile candidates cannot create user health goals"
            ),
        )

    before_candidate = _candidate_snapshot(candidate)
    if payload.action == "reject":
        candidate.review_status = "rejected"
        candidate.conflict_with_fact_id = None
        candidate.version += 1
        revision = HealthProfileRevision(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=None,
            candidate_id=candidate.id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            event_type="confirm",
            target_version=candidate.version,
            before_data=before_candidate,
            after_data={
                **_candidate_snapshot(candidate),
                "action": "reject",
                "request": request_snapshot,
            },
        )
        db.add(revision)
        db.flush()
        return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)

    now = _utcnow()
    fact = db.execute(
        select(HealthProfileFact)
        .where(
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == payload.subject_user_id,
            HealthProfileFact.fact_key == candidate.fact_key,
        )
        .with_for_update()
    ).scalars().first()
    before_fact = _fact_snapshot(fact)
    if fact is None:
        fact = HealthProfileFact(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_key=candidate.fact_key,
            category=candidate.category,
            value_data=dict(candidate.proposed_value or {}),
            is_safety_critical=candidate.is_safety_critical,
            confirmation_method="user",
            status="active",
            version=1,
            confirmed_by_user_id=user_id,
            confirmed_at=now,
            updated_at=now,
        )
        db.add(fact)
        db.flush()
        fact_event_type = "create"
    else:
        if candidate.review_status == "conflict" and candidate.conflict_with_fact_id != fact.id:
            raise HTTPException(status_code=409, detail="Profile conflict target changed")
        fact.category = candidate.category
        fact.value_data = dict(candidate.proposed_value or {})
        fact.is_safety_critical = candidate.is_safety_critical
        fact.confirmation_method = "user"
        fact.status = "active"
        fact.version += 1
        fact.confirmed_by_user_id = user_id
        fact.confirmed_at = now
        fact.updated_at = now
        fact_event_type = "update"

    admitted_sources = _copy_candidate_sources_to_fact(
        db, candidate=candidate, fact=fact
    )
    db.flush()
    _record_fact_source_version(db, fact=fact, sources=admitted_sources)
    candidate.review_status = "accepted"
    candidate.conflict_with_fact_id = None
    candidate.version += 1
    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=None,
            candidate_id=candidate.id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            event_type="confirm",
            target_version=candidate.version,
            before_data=before_candidate,
            after_data={
                **_candidate_snapshot(candidate),
                "action": "accept",
                "confirmed_fact_id": fact.id,
                "request": request_snapshot,
            },
        )
    )
    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=fact.id,
            candidate_id=None,
            actor_user_id=user_id,
            client_event_id=_bounded_id("fact:", payload.client_event_id),
            event_type=fact_event_type,
            target_version=fact.version,
            before_data=before_fact,
            after_data={**_fact_snapshot(fact), "source_candidate_id": candidate.id},
        )
    )
    db.flush()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


def upsert_manual_fact(
    db: Session,
    *,
    user_id: int,
    payload: HealthProfileFactUpsertIn,
    source_ref: str | None = None,
) -> dict[str, Any]:
    request_snapshot = _manual_upsert_request(payload)
    existing_revision = _revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if existing_revision:
        after = existing_revision.after_data or {}
        if after.get("request_action") != "upsert" or after.get("request") != request_snapshot:
            raise HTTPException(status_code=409, detail="Profile client event was reused")
        return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)

    if payload.response_state == "value" and payload.value is None:
        raise HTTPException(status_code=422, detail="A value response requires a value")
    if payload.response_state != "value" and payload.value is not None:
        raise HTTPException(status_code=422, detail="Non-value responses cannot carry a value")
    _validate_safety_classification(
        fact_key=payload.fact_key,
        category=payload.category,
        is_safety_critical=payload.is_safety_critical,
        status_code=422,
    )

    fact = db.execute(
        select(HealthProfileFact)
        .where(
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == payload.subject_user_id,
            HealthProfileFact.fact_key == payload.fact_key,
        )
        .with_for_update()
    ).scalars().first()
    if fact is None and payload.expected_version is not None:
        raise HTTPException(status_code=409, detail="Profile fact does not exist at expected version")
    if fact is not None and payload.expected_version != fact.version:
        raise HTTPException(status_code=409, detail="Profile fact version is stale")

    before = _fact_snapshot(fact)
    now = _utcnow()
    value_data = {"response_state": payload.response_state}
    if payload.response_state == "value":
        value_data["value"] = payload.value
    if fact is None:
        fact = HealthProfileFact(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_key=payload.fact_key,
            category=payload.category,
            value_data=value_data,
            is_safety_critical=payload.is_safety_critical,
            confirmation_method="user",
            status="active",
            version=1,
            confirmed_by_user_id=user_id,
            confirmed_at=now,
            updated_at=now,
        )
        db.add(fact)
        db.flush()
        event_type = "create"
    else:
        fact.category = payload.category
        fact.value_data = value_data
        fact.is_safety_critical = payload.is_safety_critical
        fact.confirmation_method = "user"
        fact.status = "active"
        fact.version += 1
        fact.confirmed_by_user_id = user_id
        fact.confirmed_at = now
        fact.updated_at = now
        event_type = "update"

    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=fact.id,
            candidate_id=None,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            event_type=event_type,
            target_version=fact.version,
            before_data=before,
            after_data={
                **_fact_snapshot(fact),
                "request_action": "upsert",
                "request": request_snapshot,
            },
        )
    )
    manual_source_ref = source_ref or f"manual-fact:{payload.fact_key}"
    source_idempotency_key = _bounded_id(
        "manual-source:",
        f"{user_id}:{payload.subject_user_id}:{fact.id}:{manual_source_ref}",
        limit=96,
    )
    existing_source = db.execute(
        select(HealthProfileSource).where(
            HealthProfileSource.user_id == user_id,
            HealthProfileSource.subject_user_id == payload.subject_user_id,
            HealthProfileSource.idempotency_key == source_idempotency_key,
        )
    ).scalars().first()
    if existing_source is None:
        existing_source = HealthProfileSource(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=fact.id,
            candidate_id=None,
            source_type="manual",
            source_ref=manual_source_ref,
            source_observation_id=None,
            source_snapshot={
                "fact_key": payload.fact_key,
                "response_state": payload.response_state,
            },
            confidence=Decimal("1.0"),
            idempotency_key=source_idempotency_key,
        )
        db.add(existing_source)
    db.flush()
    _record_fact_source_version(db, fact=fact, sources=[existing_source])
    _reconcile_device_candidates_after_manual_fact(db, fact=fact)
    db.flush()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


def retract_fact(
    db: Session,
    *,
    fact_id: int,
    user_id: int,
    payload: HealthProfileFactRetractIn,
) -> dict[str, Any]:
    request_snapshot = _retract_request(payload)
    existing_revision = _revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if existing_revision:
        if existing_revision.fact_id != fact_id or (existing_revision.after_data or {}).get(
            "request_action"
        ) != "retract" or (existing_revision.after_data or {}).get("request") != request_snapshot:
            raise HTTPException(status_code=409, detail="Profile client event was reused")
        return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)

    fact = db.execute(
        select(HealthProfileFact)
        .where(
            HealthProfileFact.id == fact_id,
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not fact:
        raise HTTPException(status_code=404, detail="Profile fact not found")
    if fact.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Profile fact version is stale")
    if fact.status != "active":
        raise HTTPException(status_code=409, detail="Profile fact is not active")
    before = _fact_snapshot(fact)
    fact.status = "retracted"
    fact.version += 1
    fact.confirmed_by_user_id = user_id
    fact.confirmed_at = _utcnow()
    fact.updated_at = fact.confirmed_at
    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            fact_id=fact.id,
            candidate_id=None,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            event_type="retract",
            target_version=fact.version,
            before_data=before,
            after_data={
                **_fact_snapshot(fact),
                "request_action": "retract",
                "request": request_snapshot,
            },
        )
    )
    db.flush()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


def _goal_metrics(db: Session, *, goal: HealthProfileGoal) -> list[HealthProfileGoalMetric]:
    return list(
        db.execute(
            select(HealthProfileGoalMetric)
            .where(
                HealthProfileGoalMetric.goal_id == goal.id,
                HealthProfileGoalMetric.user_id == goal.user_id,
                HealthProfileGoalMetric.subject_user_id == goal.subject_user_id,
            )
            .order_by(HealthProfileGoalMetric.id)
        ).scalars().all()
    )


def _goal_snapshot(db: Session, goal: HealthProfileGoal) -> dict[str, Any]:
    return {
        "goal_id": goal.id,
        "name": goal.name,
        "status": goal.status,
        "started_on": goal.started_on.isoformat(),
        "version": goal.version,
        "confirmed_by_user_id": goal.confirmed_by_user_id,
        "confirmed_at": goal.confirmed_at.isoformat(),
        "metrics": [
            {
                "metric_key": metric.metric_key,
                "display_label": metric.display_label,
            }
            for metric in _goal_metrics(db, goal=goal)
        ],
    }


def _goal_request_fingerprint(value: dict[str, Any]) -> str:
    return _json_fingerprint(value)


def _goal_revision_for_client_event(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
) -> HealthProfileGoalRevision | None:
    return db.execute(
        select(HealthProfileGoalRevision).where(
            HealthProfileGoalRevision.user_id == user_id,
            HealthProfileGoalRevision.subject_user_id == subject_user_id,
            HealthProfileGoalRevision.client_event_id == client_event_id,
        )
    ).scalars().first()


def _goal_by_id(
    db: Session,
    *,
    goal_id: int,
    user_id: int,
    subject_user_id: int,
    for_update: bool = False,
) -> HealthProfileGoal:
    query = select(HealthProfileGoal).where(
        HealthProfileGoal.id == goal_id,
        HealthProfileGoal.user_id == user_id,
        HealthProfileGoal.subject_user_id == subject_user_id,
    )
    if for_update:
        query = query.with_for_update()
    goal = db.execute(query).scalars().first()
    if goal is None:
        raise HTTPException(status_code=404, detail="Health profile goal not found")
    return goal


def _normalized_goal_metrics(metrics: Iterable[Any]) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for metric in metrics:
        key = metric.metric_key.strip()
        if key in seen:
            raise HTTPException(status_code=422, detail="Goal metric keys must be unique")
        seen.add(key)
        label = (metric.display_label or "").strip() or None
        result.append({"metric_key": key, "display_label": label})
    return result


def _replace_goal_metrics(
    db: Session,
    *,
    goal: HealthProfileGoal,
    metrics: list[dict[str, str | None]],
) -> None:
    db.execute(
        delete(HealthProfileGoalMetric).where(
            HealthProfileGoalMetric.goal_id == goal.id,
            HealthProfileGoalMetric.user_id == goal.user_id,
            HealthProfileGoalMetric.subject_user_id == goal.subject_user_id,
        )
    )
    for metric in metrics:
        db.add(
            HealthProfileGoalMetric(
                goal_id=goal.id,
                user_id=goal.user_id,
                subject_user_id=goal.subject_user_id,
                metric_key=metric["metric_key"],
                display_label=metric["display_label"],
            )
        )
    db.flush()


def create_profile_goal(
    db: Session,
    *,
    user_id: int,
    payload: HealthProfileGoalCreateIn,
) -> HealthProfileGoal:
    """Create a goal only from an authenticated user action."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Goal name cannot be blank")
    metrics = _normalized_goal_metrics(payload.metrics)
    request = {
        "action": "create",
        "name": name,
        "started_on": payload.started_on.isoformat(),
        "metrics": metrics,
    }
    fingerprint = _goal_request_fingerprint(request)
    replay = _goal_revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if replay is not None:
        if replay.event_type != "create" or replay.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Goal client event was reused")
        return _goal_by_id(
            db,
            goal_id=replay.goal_id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
        )

    now = _utcnow()
    goal = HealthProfileGoal(
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        creation_client_event_id=payload.client_event_id,
        name=name,
        status="active",
        started_on=payload.started_on,
        version=1,
        confirmed_by_user_id=user_id,
        confirmed_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.flush()
    _replace_goal_metrics(db, goal=goal, metrics=metrics)
    db.add(
        HealthProfileGoalRevision(
            goal_id=goal.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
            event_type="create",
            target_version=1,
            before_data={},
            after_data={**_goal_snapshot(db, goal), "request": request},
        )
    )
    db.flush()
    return goal


def update_profile_goal(
    db: Session,
    *,
    goal_id: int,
    user_id: int,
    payload: HealthProfileGoalUpdateIn,
) -> HealthProfileGoal:
    metrics = _normalized_goal_metrics(payload.metrics or []) if payload.metrics is not None else None
    request = {
        "action": "update",
        "goal_id": goal_id,
        "expected_version": payload.expected_version,
        "name": payload.name.strip() if payload.name is not None else None,
        "started_on": payload.started_on.isoformat() if payload.started_on else None,
        "metrics": metrics,
    }
    fingerprint = _goal_request_fingerprint(request)
    replay = _goal_revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if replay is not None:
        if replay.goal_id != goal_id or replay.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Goal client event was reused")
        return _goal_by_id(
            db,
            goal_id=goal_id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
        )

    goal = _goal_by_id(
        db,
        goal_id=goal_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        for_update=True,
    )
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Health profile goal version is stale")
    if goal.status == "archived":
        raise HTTPException(status_code=409, detail="Archived goals cannot be edited")
    before = _goal_snapshot(db, goal)
    if payload.name is not None:
        if not request["name"]:
            raise HTTPException(status_code=422, detail="Goal name cannot be blank")
        goal.name = str(request["name"])
    if payload.started_on is not None:
        goal.started_on = payload.started_on
    if metrics is not None:
        _replace_goal_metrics(db, goal=goal, metrics=metrics)
    goal.version += 1
    goal.confirmed_by_user_id = user_id
    goal.confirmed_at = _utcnow()
    goal.updated_at = goal.confirmed_at
    db.flush()
    db.add(
        HealthProfileGoalRevision(
            goal_id=goal.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
            event_type="update",
            target_version=goal.version,
            before_data=before,
            after_data={**_goal_snapshot(db, goal), "request": request},
        )
    )
    db.flush()
    return goal


def update_profile_goal_status(
    db: Session,
    *,
    goal_id: int,
    user_id: int,
    payload: HealthProfileGoalStatusIn,
) -> HealthProfileGoal:
    request = {
        "action": payload.action,
        "goal_id": goal_id,
        "expected_version": payload.expected_version,
    }
    fingerprint = _goal_request_fingerprint(request)
    replay = _goal_revision_for_client_event(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
    )
    if replay is not None:
        if replay.goal_id != goal_id or replay.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Goal client event was reused")
        return _goal_by_id(
            db,
            goal_id=goal_id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
        )

    goal = _goal_by_id(
        db,
        goal_id=goal_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        for_update=True,
    )
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Health profile goal version is stale")
    transitions = {
        ("active", "pause"): "paused",
        ("paused", "resume"): "active",
        ("active", "complete"): "completed",
        ("paused", "complete"): "completed",
        ("active", "archive"): "archived",
        ("paused", "archive"): "archived",
        ("completed", "archive"): "archived",
    }
    target = transitions.get((goal.status, payload.action))
    if target is None:
        raise HTTPException(status_code=409, detail="Goal status transition is not allowed")
    before = _goal_snapshot(db, goal)
    goal.status = target
    goal.version += 1
    goal.confirmed_by_user_id = user_id
    goal.confirmed_at = _utcnow()
    goal.updated_at = goal.confirmed_at
    db.flush()
    db.add(
        HealthProfileGoalRevision(
            goal_id=goal.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
            event_type="archive" if payload.action == "archive" else "status_change",
            target_version=goal.version,
            before_data=before,
            after_data={**_goal_snapshot(db, goal), "request": request},
        )
    )
    db.flush()
    return goal


def list_fact_revisions(
    db: Session,
    *,
    fact_id: int,
    user_id: int,
    subject_user_id: int,
    after_revision_id: int | None,
    limit: int,
) -> dict[str, Any]:
    fact = db.execute(
        select(HealthProfileFact).where(
            HealthProfileFact.id == fact_id,
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if fact is None:
        raise HTTPException(status_code=404, detail="Profile fact not found")
    query = select(HealthProfileRevision).where(
        HealthProfileRevision.user_id == user_id,
        HealthProfileRevision.subject_user_id == subject_user_id,
        HealthProfileRevision.fact_id == fact_id,
    )
    if after_revision_id is not None:
        query = query.where(HealthProfileRevision.id > after_revision_id)
    rows = list(
        db.execute(
            query.order_by(
                HealthProfileRevision.target_version,
                HealthProfileRevision.created_at,
                HealthProfileRevision.id,
            ).limit(limit + 1)
        ).scalars().all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    medication_scope = fact.category == "medication" or fact.fact_key.startswith("medication.")
    return {
        "subject_user_id": subject_user_id,
        "target_kind": "fact",
        "target_id": fact_id,
        "items": [
            {
                "revision_id": row.id,
                "event_type": row.event_type,
                "target_version": row.target_version,
                "actor_user_id": row.actor_user_id,
                "before_data": sanitize_medication_payload(dict(row.before_data or {}))
                if medication_scope
                else dict(row.before_data or {}),
                "after_data": sanitize_medication_payload(dict(row.after_data or {}))
                if medication_scope
                else dict(row.after_data or {}),
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "next_after_revision_id": rows[-1].id if has_more and rows else None,
    }


def list_goal_revisions(
    db: Session,
    *,
    goal_id: int,
    user_id: int,
    subject_user_id: int,
    after_revision_id: int | None,
    limit: int,
) -> dict[str, Any]:
    _goal_by_id(
        db,
        goal_id=goal_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
    )
    query = select(HealthProfileGoalRevision).where(
        HealthProfileGoalRevision.user_id == user_id,
        HealthProfileGoalRevision.subject_user_id == subject_user_id,
        HealthProfileGoalRevision.goal_id == goal_id,
    )
    if after_revision_id is not None:
        query = query.where(HealthProfileGoalRevision.id > after_revision_id)
    rows = list(
        db.execute(
            query.order_by(
                HealthProfileGoalRevision.target_version,
                HealthProfileGoalRevision.created_at,
                HealthProfileGoalRevision.id,
            ).limit(limit + 1)
        ).scalars().all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "subject_user_id": subject_user_id,
        "target_kind": "goal",
        "target_id": goal_id,
        "items": [
            {
                "revision_id": row.id,
                "event_type": row.event_type,
                "target_version": row.target_version,
                "actor_user_id": row.actor_user_id,
                "before_data": dict(row.before_data or {}),
                "after_data": dict(row.after_data or {}),
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "next_after_revision_id": rows[-1].id if has_more and rows else None,
    }


def _normalize_device_profile_measurement(
    row: UserIndicatorValue,
) -> tuple[str, Decimal, str] | None:
    if row.value_kind != "numeric":
        return None
    metric = (row.source_metric or "").strip().lower()
    name = "".join((row.indicator_name or "").strip().lower().split())
    unit = (row.unit or "").strip().lower()
    value = Decimal(str(row.value))
    height_metric = metric in {
        "bodyheight",
        "height",
        "hkquantitytypeidentifierheight",
    } or name in {"身高", "height", "bodyheight"}
    weight_metric = metric in {
        "bodyweight",
        "bodymass",
        "weight",
        "hkquantitytypeidentifierbodymass",
    } or name in {"体重", "weight", "bodyweight", "bodymass"}
    if height_metric:
        if unit in {"cm", "厘米", "公分"}:
            normalized = value
        elif unit in {"m", "米"}:
            normalized = value * Decimal("100")
        elif unit in {"mm", "毫米"}:
            normalized = value / Decimal("10")
        else:
            return None
        if not Decimal("80") <= normalized <= Decimal("250"):
            return None
        return "basic.height", normalized.quantize(Decimal("0.00000001")), "cm"
    if weight_metric:
        if unit in {"kg", "千克", "公斤"}:
            normalized = value
        elif unit in {"g", "克"}:
            normalized = value / Decimal("1000")
        elif unit in {"lb", "lbs", "磅"}:
            normalized = value * Decimal("0.45359237")
        else:
            return None
        if not Decimal("20") <= normalized <= Decimal("400"):
            return None
        return "basic.weight", normalized.quantize(Decimal("0.00000001")), "kg"
    return None


def _fact_measurement_value(fact: HealthProfileFact, *, fact_key: str) -> Decimal | None:
    value_data = dict(fact.value_data or {})
    value = value_data.get("value")
    direct_key = "height_cm" if fact_key == "basic.height" else "weight_kg"
    if isinstance(value, dict):
        if isinstance(value.get(direct_key), (int, float, str)):
            try:
                return Decimal(str(value[direct_key]))
            except ArithmeticError:
                return None
        nested = value.get("value")
        unit = str(value.get("unit") or "").lower()
        if isinstance(nested, (int, float, str)):
            try:
                number = Decimal(str(nested))
            except ArithmeticError:
                return None
            if fact_key == "basic.height" and unit == "m":
                return number * Decimal("100")
            if fact_key == "basic.weight" and unit == "g":
                return number / Decimal("1000")
            return number
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        import re

        match = re.search(r"\d+(?:\.\d+)?", value)
        if not match:
            return None
        number = Decimal(match.group(0))
        lowered = value.lower()
        if fact_key == "basic.height" and (" m" in lowered or lowered.endswith("m")) and "cm" not in lowered:
            return number * Decimal("100")
        if fact_key == "basic.weight" and (" g" in lowered or lowered.endswith("g")) and "kg" not in lowered:
            return number / Decimal("1000")
        return number
    return None


def _supersede_device_candidates(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    observation_ids: list[int],
) -> None:
    if not observation_ids:
        return
    candidates = list(
        db.execute(
            select(HealthProfileCandidate)
            .join(HealthProfileSource, HealthProfileSource.candidate_id == HealthProfileCandidate.id)
            .join(
                HealthProfileDeviceSourceLink,
                HealthProfileDeviceSourceLink.profile_source_id == HealthProfileSource.id,
            )
            .where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
                HealthProfileDeviceSourceLink.device_observation_id.in_(observation_ids),
            )
            .distinct()
        ).scalars().all()
    )
    for candidate in candidates:
        before = _candidate_snapshot(candidate)
        candidate.review_status = "superseded"
        candidate.conflict_with_fact_id = None
        candidate.version += 1
        db.add(
            HealthProfileRevision(
                user_id=user_id,
                subject_user_id=subject_user_id,
                fact_id=None,
                candidate_id=candidate.id,
                actor_user_id=user_id,
                client_event_id=_bounded_id(
                    "device-supersede:", f"{candidate.id}:{candidate.version}", limit=80
                ),
                event_type="supersede",
                target_version=candidate.version,
                before_data=before,
                after_data={
                    **_candidate_snapshot(candidate),
                    "request_action": "device_source_superseded",
                },
            )
        )


def sync_device_profile_observation(
    db: Session,
    *,
    user_id: int,
    source: str,
    indicator_value: UserIndicatorValue,
) -> TrustedDeviceProfileObservation | None:
    """Mirror a height/weight row into immutable profile evidence and a review candidate."""
    if indicator_value.id is None:
        return None
    locked_indicator = db.execute(
        select(UserIndicatorValue)
        .where(
            UserIndicatorValue.id == indicator_value.id,
            UserIndicatorValue.user_id == user_id,
        )
        .with_for_update()
    ).scalars().first()
    if locked_indicator is None:
        return None
    indicator_value = locked_indicator
    normalized = _normalize_device_profile_measurement(indicator_value)
    if normalized is None:
        return None
    fact_key, normalized_value, normalized_unit = normalized
    content = {
        "indicator_value_id": indicator_value.id,
        "source": source,
        "source_metric": indicator_value.source_metric,
        "source_id": indicator_value.source_id,
        "fact_key": fact_key,
        "value": str(normalized_value),
        "unit": normalized_unit,
        "effective_at": indicator_value.measured_at.isoformat(),
    }
    content_hash = _json_fingerprint(content)
    existing_rows = list(
        db.execute(
            select(TrustedDeviceProfileObservation)
            .where(
                TrustedDeviceProfileObservation.user_id == user_id,
                TrustedDeviceProfileObservation.subject_user_id == user_id,
                TrustedDeviceProfileObservation.user_indicator_value_id == indicator_value.id,
            )
            .order_by(
                TrustedDeviceProfileObservation.version.desc(),
                TrustedDeviceProfileObservation.id.desc(),
            )
            .with_for_update()
        ).scalars().all()
    )
    active_rows = [row for row in existing_rows if row.status == "active"]
    active_matches = [
        row
        for row in active_rows
        if row.source_content_hash == content_hash
        and row.metric_mapping_version == DEVICE_PROFILE_MAPPING_VERSION
    ]
    if len(active_rows) == 1 and active_matches:
        return active_matches[0]

    _supersede_device_candidates(
        db,
        user_id=user_id,
        subject_user_id=user_id,
        observation_ids=[row.id for row in active_rows],
    )
    for row in active_rows:
        row.status = "superseded"
        row.active_slot = None
    # Release the database-enforced single-active slot before inserting the
    # replacement.  The locked indicator row serializes writers for this
    # source identity on PostgreSQL.
    db.flush()
    version = max((row.version for row in existing_rows), default=0) + 1
    observation = TrustedDeviceProfileObservation(
        user_id=user_id,
        subject_user_id=user_id,
        user_indicator_value_id=indicator_value.id,
        idempotency_key=_bounded_id(
            "device-profile:",
            f"{user_id}:{indicator_value.id}:v{version}:{content_hash}:"
            f"{DEVICE_PROFILE_MAPPING_VERSION}",
            limit=96,
        ),
        source_content_hash=content_hash,
        metric_mapping_version=DEVICE_PROFILE_MAPPING_VERSION,
        fact_key=fact_key,
        value_numeric=normalized_value,
        value_text=None,
        unit=normalized_unit,
        effective_at=indicator_value.measured_at,
        source_snapshot={
            "source": source,
            "source_metric": indicator_value.source_metric,
            "source_id": indicator_value.source_id,
            "indicator_name": indicator_value.indicator_name,
            "raw_value": indicator_value.value,
            "raw_unit": indicator_value.unit,
            "source_local_date": indicator_value.source_local_date.isoformat()
            if indicator_value.source_local_date
            else None,
            "timezone_offset_minutes": indicator_value.timezone_offset_minutes,
        },
        status="active",
        active_slot=1,
        version=version,
    )
    db.add(observation)
    db.flush()

    fact = db.execute(
        select(HealthProfileFact).where(
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == user_id,
            HealthProfileFact.fact_key == fact_key,
            HealthProfileFact.status == "active",
        )
    ).scalars().first()
    current_value = _fact_measurement_value(fact, fact_key=fact_key) if fact else None
    is_conflict = fact is not None and (
        current_value is None or abs(current_value - normalized_value) > Decimal("0.0001")
    )
    candidate = HealthProfileCandidate(
        user_id=user_id,
        subject_user_id=user_id,
        fact_key=fact_key,
        category="basic",
        proposed_value={
            "response_state": "value",
            "value": {
                "height_cm" if fact_key == "basic.height" else "weight_kg": float(
                    normalized_value
                ),
                "value": float(normalized_value),
                "unit": normalized_unit,
                "effective_at": indicator_value.measured_at.isoformat(),
            },
            "mapping_version": DEVICE_PROFILE_MAPPING_VERSION,
        },
        is_safety_critical=False,
        review_status="conflict" if is_conflict else "pending_review",
        conflict_with_fact_id=fact.id if is_conflict and fact else None,
        confidence=Decimal("1.0"),
        idempotency_key=_bounded_id(
            "device-candidate:", f"{observation.id}:{content_hash}", limit=96
        ),
        version=1,
    )
    db.add(candidate)
    db.flush()
    stable_sample = indicator_value.source_id or f"indicator-row:{indicator_value.id}"
    profile_source = HealthProfileSource(
        user_id=user_id,
        subject_user_id=user_id,
        fact_id=None,
        candidate_id=candidate.id,
        source_type="device",
        source_ref=f"device:{source}:{stable_sample}",
        source_observation_id=None,
        source_snapshot={
            "device_observation_id": observation.id,
            "indicator_value_id": indicator_value.id,
            "mapping_version": DEVICE_PROFILE_MAPPING_VERSION,
            "source_content_hash": content_hash,
        },
        confidence=Decimal("1.0"),
        idempotency_key=_bounded_id(
            "device-profile-source:", f"{candidate.id}:{observation.id}", limit=96
        ),
    )
    db.add(profile_source)
    db.flush()
    db.add(
        HealthProfileDeviceSourceLink(
            profile_source_id=profile_source.id,
            device_observation_id=observation.id,
            user_id=user_id,
            subject_user_id=user_id,
        )
    )
    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=user_id,
            fact_id=None,
            candidate_id=candidate.id,
            actor_user_id=user_id,
            client_event_id=_bounded_id(
                "device-candidate-create:", f"{candidate.id}:{observation.id}", limit=80
            ),
            event_type="create",
            target_version=1,
            before_data={},
            after_data={
                **_candidate_snapshot(candidate),
                "device_observation_id": observation.id,
                "automatic_fact_created": False,
            },
        )
    )
    db.flush()
    return observation


def _reconcile_device_candidates_after_manual_fact(
    db: Session,
    *,
    fact: HealthProfileFact,
) -> None:
    candidates = list(
        db.execute(
            select(HealthProfileCandidate)
            .join(HealthProfileSource, HealthProfileSource.candidate_id == HealthProfileCandidate.id)
            .where(
                HealthProfileCandidate.user_id == fact.user_id,
                HealthProfileCandidate.subject_user_id == fact.subject_user_id,
                HealthProfileCandidate.fact_key == fact.fact_key,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
                HealthProfileSource.source_type == "device",
            )
            .distinct()
        ).scalars().all()
    )
    for candidate in candidates:
        if candidate.review_status == "conflict" and candidate.conflict_with_fact_id == fact.id:
            continue
        before = _candidate_snapshot(candidate)
        candidate.review_status = "conflict"
        candidate.conflict_with_fact_id = fact.id
        candidate.version += 1
        db.add(
            HealthProfileRevision(
                user_id=fact.user_id,
                subject_user_id=fact.subject_user_id,
                fact_id=None,
                candidate_id=candidate.id,
                actor_user_id=fact.confirmed_by_user_id,
                client_event_id=_bounded_id(
                    "device-manual-conflict:",
                    f"{candidate.id}:{candidate.version}:{fact.id}:{fact.version}",
                    limit=80,
                ),
                event_type="update",
                target_version=candidate.version,
                before_data=before,
                after_data={
                    **_candidate_snapshot(candidate),
                    "request_action": "manual_fact_preserved",
                },
            )
        )


def generate_candidates_from_admitted_observations(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
) -> list[HealthProfileCandidate]:
    observations = list(
        db.execute(
            select(ConfirmedHealthObservation)
            .join(HealthReportWorkflow, HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id)
            .where(
                ConfirmedHealthObservation.user_id == user_id,
                ConfirmedHealthObservation.subject_user_id == subject_user_id,
                ConfirmedHealthObservation.status == "active",
                ConfirmedHealthObservation.abnormal_state == "abnormal",
                HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
            )
            .order_by(ConfirmedHealthObservation.effective_at, ConfirmedHealthObservation.id)
        ).scalars().all()
    )
    grouped: dict[str, list[ConfirmedHealthObservation]] = defaultdict(list)
    for observation in observations:
        group_key = observation.canonical_code or observation.canonical_name.strip().lower()
        if group_key:
            grouped[group_key].append(observation)

    created: list[HealthProfileCandidate] = []
    for group_key, rows in grouped.items():
        workflow_ids = {item.workflow_id for item in rows}
        if len(workflow_ids) < 2:
            continue
        latest = rows[-1]
        source_ids = [item.id for item in rows]
        fact_key = f"long_term_health.repeated_abnormal.{hashlib.sha256(group_key.encode()).hexdigest()[:16]}"
        idempotency_key = _bounded_id(
            "profile-candidate:",
            f"{PROFILE_CANDIDATE_ALGORITHM_VERSION}:{user_id}:{subject_user_id}:{source_ids}",
            limit=96,
        )
        existing = db.execute(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.idempotency_key == idempotency_key,
            )
        ).scalars().first()
        if existing:
            continue

        fact = db.execute(
            select(HealthProfileFact).where(
                HealthProfileFact.user_id == user_id,
                HealthProfileFact.subject_user_id == subject_user_id,
                HealthProfileFact.fact_key == fact_key,
                HealthProfileFact.status == "active",
            )
        ).scalars().first()
        prior_candidates = db.execute(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.fact_key == fact_key,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
            )
        ).scalars().all()
        for prior in prior_candidates:
            prior.review_status = "superseded"
            prior.conflict_with_fact_id = None
            prior.version += 1

        proposed = {
            "response_state": "value",
            "kind": "repeated_abnormal_metric",
            "canonical_code": latest.canonical_code,
            "canonical_name": latest.canonical_name,
            "occurrence_count": len(workflow_ids),
            "latest_value_numeric": str(latest.value_numeric) if latest.value_numeric is not None else None,
            "latest_value_text": latest.value_text,
            "latest_unit": latest.unit,
            "latest_effective_at": latest.effective_at.isoformat(),
            "algorithm_version": PROFILE_CANDIDATE_ALGORITHM_VERSION,
        }
        candidate = HealthProfileCandidate(
            user_id=user_id,
            subject_user_id=subject_user_id,
            fact_key=fact_key,
            category="long_term_health",
            proposed_value=proposed,
            is_safety_critical=False,
            review_status="conflict" if fact else "pending_review",
            conflict_with_fact_id=fact.id if fact else None,
            confidence=Decimal(str(min(0.95, 0.60 + 0.10 * len(workflow_ids)))),
            idempotency_key=idempotency_key,
            version=1,
        )
        db.add(candidate)
        db.flush()
        for observation in rows:
            db.add(
                HealthProfileSource(
                    user_id=user_id,
                    subject_user_id=subject_user_id,
                    fact_id=None,
                    candidate_id=candidate.id,
                    source_type="report_observation",
                    source_ref=f"report-observation:{observation.id}",
                    source_observation_id=observation.id,
                    source_snapshot={
                        "canonical_name": observation.canonical_name,
                        "value_numeric": str(observation.value_numeric)
                        if observation.value_numeric is not None
                        else None,
                        "value_text": observation.value_text,
                        "unit": observation.unit,
                        "effective_at": observation.effective_at.isoformat(),
                    },
                    confidence=Decimal("1.0"),
                    idempotency_key=_bounded_id(
                        "candidate-source:", f"{candidate.id}:{observation.id}", limit=96
                    ),
                )
            )
        created.append(candidate)
    db.flush()
    return created


def refresh_candidates_after_observation_retraction(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    workflow_id: int,
) -> None:
    """Invalidate unreviewed candidates whose evidence was withdrawn.

    User-confirmed facts remain revisioned facts; they are not silently
    deleted when one source disappears. Pending/conflicting proposals, on the
    other hand, must never remain actionable after their evidence is retracted.
    """
    observation_ids = list(
        db.execute(
            select(ConfirmedHealthObservation.id).where(
                ConfirmedHealthObservation.workflow_id == workflow_id,
                ConfirmedHealthObservation.user_id == user_id,
                ConfirmedHealthObservation.subject_user_id == subject_user_id,
            )
        ).scalars().all()
    )
    if not observation_ids:
        return

    candidates = list(
        db.execute(
            select(HealthProfileCandidate)
            .join(
                HealthProfileSource,
                HealthProfileSource.candidate_id == HealthProfileCandidate.id,
            )
            .where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
                HealthProfileSource.source_observation_id.in_(observation_ids),
            )
            .distinct()
        ).scalars().all()
    )
    for candidate in candidates:
        before = _candidate_snapshot(candidate)
        candidate.review_status = "superseded"
        candidate.conflict_with_fact_id = None
        candidate.version += 1
        db.add(
            HealthProfileRevision(
                user_id=user_id,
                subject_user_id=subject_user_id,
                fact_id=None,
                candidate_id=candidate.id,
                actor_user_id=user_id,
                client_event_id=_bounded_id(
                    "source-withdrawal:",
                    f"{workflow_id}:{candidate.id}:{candidate.version}",
                ),
                event_type="supersede",
                target_version=candidate.version,
                before_data=before,
                after_data={
                    **_candidate_snapshot(candidate),
                    "request_action": "source_withdrawal",
                    "source_workflow_id": workflow_id,
                },
            )
        )
    db.flush()
    generate_candidates_from_admitted_observations(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
    )


def confirmed_profile_context(db: Session, *, user_id: int) -> dict[str, Any]:
    facts = db.execute(
        select(HealthProfileFact)
        .where(
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == user_id,
            HealthProfileFact.status == "active",
            HealthProfileFact.confirmation_method.in_(["user", "clinician", "verified_source"]),
            HealthProfileFact.confirmed_at.is_not(None),
        )
        .order_by(HealthProfileFact.category, HealthProfileFact.fact_key)
    ).scalars().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        grouped[fact.category].append(
            {
                "fact_key": fact.fact_key,
                "value": sanitize_profile_payload(
                    dict(fact.value_data or {}),
                    fact_key=fact.fact_key,
                    category=fact.category,
                ),
                "confirmed_at": fact.confirmed_at.isoformat() if fact.confirmed_at else None,
                "version": fact.version,
            }
        )
    return dict(grouped)


def import_verified_legacy_sections(
    db: Session,
    *,
    user_id: int,
    sections: dict[str, dict[str, object]],
) -> None:
    """Mirror only explicitly user-verified legacy fields into confirmed facts."""
    for section_key, (fact_key, category, is_safety) in LEGACY_SECTION_FACT_MAP.items():
        section = sections.get(section_key) or {}
        value = str(section.get("value") or "").strip()
        if not bool(section.get("verified_by_user")) or not value:
            continue
        existing = db.execute(
            select(HealthProfileFact).where(
                HealthProfileFact.user_id == user_id,
                HealthProfileFact.subject_user_id == user_id,
                HealthProfileFact.fact_key == fact_key,
            )
        ).scalars().first()
        if (
            existing is not None
            and existing.status == "active"
            and existing.category == category
            and dict(existing.value_data or {})
            == {"response_state": "value", "value": value}
            and existing.is_safety_critical == is_safety
        ):
            continue
        event_material = {
            "section_key": section_key,
            "value": value,
            "date_label": section.get("date_label"),
            "source_type": section.get("source_type"),
            "source_ref": section.get("source_ref"),
            "previous_version": existing.version if existing else 0,
        }
        payload = HealthProfileFactUpsertIn(
            subject_user_id=user_id,
            client_event_id=_bounded_id(
                "legacy-profile:", _json_fingerprint(event_material), limit=80
            ),
            fact_key=fact_key,
            category=category,
            response_state="value",
            value=value,
            is_safety_critical=is_safety,
            expected_version=existing.version if existing else None,
        )
        upsert_manual_fact(
            db,
            user_id=user_id,
            payload=payload,
            source_ref=f"legacy-patient-history:{section_key}",
        )
