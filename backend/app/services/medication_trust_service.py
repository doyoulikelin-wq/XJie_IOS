"""Trusted medication plans, execution records, estimates, and profile proposals."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health_trust import (
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileRevision,
    HealthProfileSource,
)
from app.models.medication_trust import (
    MedicationAdverseReactionEvent,
    MedicationDoseEvent,
    MedicationPlanEvent,
    MedicationPrefillCandidate,
    TrustedMedicationPlan,
)
from app.schemas.medication_trust import (
    MedicationDoseActionIn,
    MedicationPlanConfirmIn,
    MedicationPlanReviseIn,
    MedicationPlanStatusIn,
    MedicationPrefillRejectIn,
    MedicationReactionCorrectIn,
    MedicationReactionCreateIn,
    MedicationReactionRetractIn,
)


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_POSSIBLY_MISSED_AFTER_MINUTES = 120
_PROFILE_FACT_KEY = "medication.long_term_summary"
_PROFILE_ALGORITHM_VERSION = "confirmed-medication-summary.v2"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _bounded_id(prefix: str, value: str, *, limit: int = 80) -> str:
    return f"{prefix}{hashlib.sha256(value.encode('utf-8')).hexdigest()}"[:limit]


def _clean(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def validate_schedule_times(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        value = (raw or "").strip()
        if not _TIME_RE.fullmatch(value):
            raise HTTPException(status_code=422, detail="schedule_times must use HH:MM 24h format")
        result.append(value)
    return sorted(set(result))


def _plan_fields(payload: MedicationPlanConfirmIn | MedicationPlanReviseIn) -> dict[str, Any]:
    generic_name = payload.generic_name.strip()
    if not generic_name:
        raise HTTPException(status_code=422, detail="generic_name cannot be blank")
    schedule_times = validate_schedule_times(payload.schedule_times)
    source_ref = _clean(payload.source_ref)
    if payload.source_type != "ocr" and source_ref is None:
        source_ref = f"{payload.source_type}:user-confirmed"
    return {
        "generic_name": generic_name,
        "purpose": _clean(payload.purpose),
        "brand_name": _clean(payload.brand_name),
        "strength": _clean(payload.strength),
        "dose_text": _clean(payload.dose_text),
        "dose_quantity": payload.dose_quantity,
        "frequency": _clean(payload.frequency),
        "schedule_times": schedule_times,
        "meal_relation": payload.meal_relation,
        "instructions": _clean(payload.instructions),
        "course_start": payload.course_start,
        "course_end": payload.course_end,
        "prescriber": _clean(payload.prescriber),
        "initial_quantity": payload.initial_quantity,
        "inventory_unit": _clean(payload.inventory_unit),
        "is_long_term": payload.is_long_term,
        "source_type": payload.source_type,
        "source_ref": source_ref,
    }


def _plan_snapshot(plan: TrustedMedicationPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.id,
        "generic_name": plan.generic_name,
        "purpose": plan.purpose,
        "brand_name": plan.brand_name,
        "strength": plan.strength,
        "dose_text": plan.dose_text,
        "dose_quantity": str(plan.dose_quantity) if plan.dose_quantity is not None else None,
        "frequency": plan.frequency,
        "schedule_times": list(plan.schedule_times or []),
        "meal_relation": plan.meal_relation,
        "instructions": plan.instructions,
        "course_start": plan.course_start.isoformat() if plan.course_start else None,
        "course_end": plan.course_end.isoformat() if plan.course_end else None,
        "prescriber": plan.prescriber,
        "initial_quantity": str(plan.initial_quantity)
        if plan.initial_quantity is not None
        else None,
        "inventory_unit": plan.inventory_unit,
        "is_long_term": plan.is_long_term,
        "source_type": plan.source_type,
        "source_ref": plan.source_ref,
        "status": plan.status,
        "version": plan.version,
        "confirmed_by_user_id": plan.confirmed_by_user_id,
        "confirmed_at": plan.confirmed_at.isoformat(),
    }


def _latest_dose_events(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    plan_id: int | None = None,
    local_date: date | None = None,
) -> dict[str, MedicationDoseEvent]:
    query = select(MedicationDoseEvent).where(
        MedicationDoseEvent.user_id == user_id,
        MedicationDoseEvent.subject_user_id == subject_user_id,
    )
    if plan_id is not None:
        query = query.where(MedicationDoseEvent.plan_id == plan_id)
    if local_date is not None:
        query = query.where(MedicationDoseEvent.scheduled_local_date == local_date)
    rows = db.execute(
        query.order_by(
            MedicationDoseEvent.occurrence_key,
            MedicationDoseEvent.occurrence_version,
            MedicationDoseEvent.id,
        )
    ).scalars().all()
    latest: dict[str, MedicationDoseEvent] = {}
    for row in rows:
        latest[row.occurrence_key] = row
    return latest


def inventory_estimate(
    db: Session,
    *,
    plan: TrustedMedicationPlan,
) -> dict[str, Any]:
    base = {
        "is_estimate": True,
        "label": "预计剩余",
        "inventory_unit": plan.inventory_unit,
        "basis": "user_confirmed_taken_events_only",
    }
    if plan.initial_quantity is None or plan.inventory_unit is None:
        return {
            **base,
            "estimated_remaining": None,
            "estimated_consumed": None,
            "unavailable_reason": "confirmed_initial_quantity_not_available",
        }
    latest = _latest_dose_events(
        db,
        user_id=plan.user_id,
        subject_user_id=plan.subject_user_id,
        plan_id=plan.id,
    )
    taken = [event for event in latest.values() if event.effective_status == "taken"]
    if any(event.taken_quantity is None for event in taken):
        return {
            **base,
            "estimated_remaining": None,
            "estimated_consumed": None,
            "unavailable_reason": "confirmed_taken_event_missing_quantity",
        }
    consumed = sum((event.taken_quantity or Decimal("0")) for event in taken)
    remaining = max(Decimal("0"), plan.initial_quantity - consumed)
    return {
        **base,
        "estimated_remaining": float(remaining),
        "estimated_consumed": float(consumed),
        "unavailable_reason": None,
    }


def plan_out(db: Session, plan: TrustedMedicationPlan) -> dict[str, Any]:
    return {
        "plan_id": plan.id,
        "subject_user_id": plan.subject_user_id,
        "generic_name": plan.generic_name,
        "purpose": plan.purpose,
        "brand_name": plan.brand_name,
        "strength": plan.strength,
        "dose_text": plan.dose_text,
        "dose_quantity": float(plan.dose_quantity) if plan.dose_quantity is not None else None,
        "frequency": plan.frequency,
        "schedule_times": list(plan.schedule_times or []),
        "meal_relation": plan.meal_relation,
        "instructions": plan.instructions,
        "course_start": plan.course_start,
        "course_end": plan.course_end,
        "prescriber": plan.prescriber,
        "initial_quantity": float(plan.initial_quantity)
        if plan.initial_quantity is not None
        else None,
        "inventory_unit": plan.inventory_unit,
        "is_long_term": plan.is_long_term,
        "source_type": plan.source_type,
        "source_ref": plan.source_ref,
        "status": plan.status,
        "version": plan.version,
        "confirmed_at": plan.confirmed_at,
        "trust_state": "user_confirmed",
        "reminder_management": "client_managed",
        "reminder_default_enabled": False,
        "server_notification_scheduled": False,
        "inventory": inventory_estimate(db, plan=plan),
    }


def list_plans(db: Session, *, user_id: int, subject_user_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == subject_user_id,
        )
        .order_by(TrustedMedicationPlan.updated_at.desc(), TrustedMedicationPlan.id.desc())
    ).scalars().all()
    return [plan_out(db, row) for row in rows]


def _profile_summary_source(source_type: str) -> str:
    return {
        "manual": "user_added",
        "prescription_import": "prescription",
        "ocr": "ocr_confirmed",
        "history": "history_confirmed",
    }[source_type]


def list_confirmed_long_term_medication_summaries(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
) -> list[dict[str, Any]]:
    """Return the exact six-field public profile summary for confirmed plans."""
    rows = list(
        db.execute(
            select(TrustedMedicationPlan)
            .where(
                TrustedMedicationPlan.user_id == user_id,
                TrustedMedicationPlan.subject_user_id == subject_user_id,
                TrustedMedicationPlan.is_long_term.is_(True),
                TrustedMedicationPlan.status.in_(["active", "paused"]),
                TrustedMedicationPlan.confirmed_by_user_id == user_id,
                TrustedMedicationPlan.confirmed_at.is_not(None),
            )
            .order_by(TrustedMedicationPlan.confirmed_at.desc(), TrustedMedicationPlan.id.desc())
        ).scalars().all()
    )
    return [
        {
            "medication_name": plan.brand_name or plan.generic_name,
            "purpose": plan.purpose,
            "started_on": plan.course_start,
            "is_still_taking": plan.status == "active",
            "source": _profile_summary_source(plan.source_type),
            "last_confirmed_at": plan.confirmed_at,
        }
        for plan in rows
    ]


def prefill_out(candidate: MedicationPrefillCandidate) -> dict[str, Any]:
    confidences = {
        str(key): float(value)
        for key, value in dict(candidate.field_confidences or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "candidate_id": candidate.id,
        "subject_user_id": candidate.subject_user_id,
        "client_event_id": candidate.client_event_id,
        "source_type": candidate.source_type,
        "source_ref": candidate.source_ref,
        "extracted_data": dict(candidate.extracted_data or {}),
        "field_confidences": confidences,
        "low_confidence_fields": sorted(
            key for key, value in confidences.items() if value < 0.80
        ),
        "review_status": candidate.review_status,
        "version": candidate.version,
        "trust_state": "unconfirmed_prefill",
        "requires_user_confirmation": True,
        "plan_created": candidate.accepted_plan_id is not None,
        "confirmation_endpoint": "/api/medications/trust/plans/confirm",
    }


def create_ocr_prefill_candidate(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
    raw_text_fingerprint: str,
    extracted_data: dict[str, Any],
    field_confidences: dict[str, float],
) -> MedicationPrefillCandidate:
    request_snapshot = {
        "source_type": "ocr",
        "raw_text_sha256": raw_text_fingerprint,
        "extracted_data": extracted_data,
        "field_confidences": field_confidences,
    }
    existing = db.execute(
        select(MedicationPrefillCandidate).where(
            MedicationPrefillCandidate.user_id == user_id,
            MedicationPrefillCandidate.subject_user_id == subject_user_id,
            MedicationPrefillCandidate.client_event_id == client_event_id,
        )
    ).scalars().first()
    if existing:
        if (existing.source_snapshot or {}).get("raw_text_sha256") != raw_text_fingerprint:
            raise HTTPException(status_code=409, detail="Medication prefill event was reused")
        return existing

    candidate = MedicationPrefillCandidate(
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=client_event_id,
        source_type="ocr",
        source_ref=f"ocr-text-sha256:{raw_text_fingerprint}",
        extracted_data=dict(extracted_data),
        field_confidences=dict(field_confidences),
        source_snapshot={
            "input_kind": "raw_text",
            "raw_text_sha256": raw_text_fingerprint,
            "raw_text_stored": False,
            "request_fingerprint": _fingerprint(request_snapshot),
        },
        review_status="pending_review",
        version=1,
    )
    db.add(candidate)
    db.flush()
    return candidate


def list_prefill_candidates(
    db: Session, *, user_id: int, subject_user_id: int
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(MedicationPrefillCandidate)
        .where(
            MedicationPrefillCandidate.user_id == user_id,
            MedicationPrefillCandidate.subject_user_id == subject_user_id,
        )
        .order_by(MedicationPrefillCandidate.created_at.desc())
    ).scalars().all()
    return [prefill_out(row) for row in rows]


def reject_prefill_candidate(
    db: Session,
    *,
    candidate_id: int,
    user_id: int,
    payload: MedicationPrefillRejectIn,
) -> MedicationPrefillCandidate:
    reused = db.execute(
        select(MedicationPrefillCandidate).where(
            MedicationPrefillCandidate.user_id == user_id,
            MedicationPrefillCandidate.subject_user_id == payload.subject_user_id,
            MedicationPrefillCandidate.review_client_event_id == payload.client_event_id,
        )
    ).scalars().first()
    if reused:
        if reused.id != candidate_id or reused.review_status != "rejected":
            raise HTTPException(status_code=409, detail="Medication review event was reused")
        return reused
    candidate = db.execute(
        select(MedicationPrefillCandidate)
        .where(
            MedicationPrefillCandidate.id == candidate_id,
            MedicationPrefillCandidate.user_id == user_id,
            MedicationPrefillCandidate.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Medication prefill candidate not found")
    if candidate.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Medication prefill version is stale")
    if candidate.review_status != "pending_review":
        raise HTTPException(status_code=409, detail="Medication prefill is already resolved")
    candidate.review_status = "rejected"
    candidate.version += 1
    candidate.reviewed_by_user_id = user_id
    candidate.reviewed_at = utcnow()
    candidate.review_client_event_id = payload.client_event_id
    snapshot = dict(candidate.source_snapshot or {})
    snapshot["review"] = {"action": "reject", "expected_version": payload.expected_version}
    candidate.source_snapshot = snapshot
    db.flush()
    return candidate


def _profile_candidate_snapshot(candidate: HealthProfileCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "fact_key": candidate.fact_key,
        "category": candidate.category,
        "proposed_value": dict(candidate.proposed_value or {}),
        "is_safety_critical": candidate.is_safety_critical,
        "review_status": candidate.review_status,
        "conflict_with_fact_id": candidate.conflict_with_fact_id,
        "version": candidate.version,
    }


def _supersede_long_term_profile_candidates(
    db: Session,
    *,
    candidates: list[HealthProfileCandidate],
    user_id: int,
    subject_user_id: int,
    reason: str,
) -> None:
    for candidate in candidates:
        before = _profile_candidate_snapshot(candidate)
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
                    "med-profile-supersede:",
                    f"{candidate.id}:{candidate.version}:{reason}",
                ),
                event_type="supersede",
                target_version=candidate.version,
                before_data=before,
                after_data={
                    **_profile_candidate_snapshot(candidate),
                    "reason": reason,
                },
            )
        )


def sync_confirmed_long_term_profile_candidate(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    trigger_plan_id: int | None = None,
) -> HealthProfileCandidate | None:
    """Propose, but never auto-confirm, the current long-term medication summary."""
    all_plans = list(
        db.execute(
            select(TrustedMedicationPlan)
            .where(
                TrustedMedicationPlan.user_id == user_id,
                TrustedMedicationPlan.subject_user_id == subject_user_id,
                TrustedMedicationPlan.is_long_term.is_(True),
                TrustedMedicationPlan.confirmed_by_user_id.is_not(None),
                TrustedMedicationPlan.confirmed_at.is_not(None),
            )
            .order_by(TrustedMedicationPlan.generic_name, TrustedMedicationPlan.id)
            .with_for_update()
        ).scalars().all()
    )
    plans = [plan for plan in all_plans if plan.status in {"active", "paused"}]
    prior = list(
        db.execute(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.user_id == user_id,
                HealthProfileCandidate.subject_user_id == subject_user_id,
                HealthProfileCandidate.fact_key == _PROFILE_FACT_KEY,
                HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
            )
            .with_for_update()
        ).scalars().all()
    )
    fact = db.execute(
        select(HealthProfileFact)
        .where(
            HealthProfileFact.user_id == user_id,
            HealthProfileFact.subject_user_id == subject_user_id,
            HealthProfileFact.fact_key == _PROFILE_FACT_KEY,
            HealthProfileFact.status == "active",
        )
        .with_for_update()
    ).scalars().first()

    proposed_items = [
        {
            "medication_name": plan.brand_name or plan.generic_name,
            "purpose": plan.purpose,
            "started_on": plan.course_start.isoformat() if plan.course_start else None,
            "is_still_taking": plan.status == "active",
            "source": _profile_summary_source(plan.source_type),
            "last_confirmed_at": plan.confirmed_at.isoformat(),
        }
        for plan in plans
    ]
    proposed_value = {
        "response_state": "value",
        "kind": "confirmed_long_term_medication_summary",
        "items": proposed_items,
        "algorithm_version": _PROFILE_ALGORITHM_VERSION,
    }
    if not plans and fact is None:
        _supersede_long_term_profile_candidates(
            db,
            candidates=prior,
            user_id=user_id,
            subject_user_id=subject_user_id,
            reason="no_confirmed_profile_fact_or_current_long_term_medication",
        )
        db.flush()
        return None
    if fact is not None and dict(fact.value_data or {}) == proposed_value:
        _supersede_long_term_profile_candidates(
            db,
            candidates=prior,
            user_id=user_id,
            subject_user_id=subject_user_id,
            reason="profile_fact_already_matches_confirmed_medication_state",
        )
        db.flush()
        return None

    source_plans = list(plans)
    if not source_plans:
        trigger_plan = next(
            (plan for plan in all_plans if plan.id == trigger_plan_id),
            None,
        )
        if trigger_plan is None and all_plans:
            trigger_plan = max(
                all_plans,
                key=lambda plan: (plan.updated_at, plan.id),
            )
        if trigger_plan is not None:
            source_plans = [trigger_plan]

    material = [
        {"plan_id": plan.id, "version": plan.version, "status": plan.status}
        for plan in source_plans
    ]
    idempotency_state = {
        "algorithm_version": _PROFILE_ALGORITHM_VERSION,
        "source_plan_versions": material,
        "fact_version": fact.version if fact else None,
        "fact_value_fingerprint": _fingerprint(dict(fact.value_data or {}))
        if fact
        else None,
    }
    idempotency_key = _bounded_id(
        "med-profile:",
        f"{user_id}:{subject_user_id}:{_fingerprint(idempotency_state)}",
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
        return existing

    _supersede_long_term_profile_candidates(
        db,
        candidates=prior,
        user_id=user_id,
        subject_user_id=subject_user_id,
        reason="confirmed_medication_state_changed",
    )
    candidate = HealthProfileCandidate(
        user_id=user_id,
        subject_user_id=subject_user_id,
        fact_key=_PROFILE_FACT_KEY,
        category="medication",
        proposed_value=proposed_value,
        is_safety_critical=False,
        review_status="conflict" if fact else "pending_review",
        conflict_with_fact_id=fact.id if fact else None,
        confidence=Decimal("1.0"),
        idempotency_key=idempotency_key,
        version=1,
    )
    db.add(candidate)
    db.flush()
    for plan in source_plans:
        db.add(
            HealthProfileSource(
                user_id=user_id,
                subject_user_id=subject_user_id,
                fact_id=None,
                candidate_id=candidate.id,
                source_type="medication",
                # Keep the legacy edge shape for old clients; completion/counting
                # canonicalizes the :vN suffix into one independent source.
                source_ref=f"trusted-medication-plan:{plan.id}:v{plan.version}",
                source_observation_id=None,
                source_snapshot={
                    "plan_id": plan.id,
                    "plan_version": plan.version,
                    "confirmed_by_user_id": plan.confirmed_by_user_id,
                    "confirmed_at": plan.confirmed_at.isoformat(),
                    "source_type": plan.source_type,
                    "source_ref": plan.source_ref,
                },
                confidence=Decimal("1.0"),
                idempotency_key=_bounded_id(
                    "med-profile-source:",
                    f"{candidate.id}:{plan.id}:{plan.version}",
                    limit=96,
                ),
            )
        )
    db.add(
        HealthProfileRevision(
            user_id=user_id,
            subject_user_id=subject_user_id,
            fact_id=None,
            candidate_id=candidate.id,
            actor_user_id=user_id,
            client_event_id=_bounded_id(
                "med-profile-create:", f"{candidate.id}:{idempotency_key}"
            ),
            event_type="create",
            target_version=1,
            before_data={},
            after_data={
                **_profile_candidate_snapshot(candidate),
                "source_plan_versions": material,
                "automatic_fact_created": False,
            },
        )
    )
    db.flush()
    return candidate


def _plan_event_replay(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
    request_fingerprint: str,
) -> TrustedMedicationPlan | None:
    event = db.execute(
        select(MedicationPlanEvent).where(
            MedicationPlanEvent.user_id == user_id,
            MedicationPlanEvent.subject_user_id == subject_user_id,
            MedicationPlanEvent.client_event_id == client_event_id,
        )
    ).scalars().first()
    if not event:
        return None
    if event.request_fingerprint != request_fingerprint:
        raise HTTPException(status_code=409, detail="Medication plan event was reused")
    plan = db.execute(
        select(TrustedMedicationPlan).where(
            TrustedMedicationPlan.id == event.plan_id,
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=409, detail="Medication plan event target is unavailable")
    return plan


def confirm_plan(
    db: Session,
    *,
    user_id: int,
    payload: MedicationPlanConfirmIn,
) -> TrustedMedicationPlan:
    fields = _plan_fields(payload)
    request = {
        **payload.model_dump(mode="json"),
        "normalized_schedule_times": fields["schedule_times"],
    }
    request_fingerprint = _fingerprint(request)
    replay = _plan_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
    )
    if replay:
        return replay
    reused_request = db.execute(
        select(TrustedMedicationPlan).where(
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == payload.subject_user_id,
            TrustedMedicationPlan.client_request_id == payload.client_request_id,
        )
    ).scalars().first()
    if reused_request:
        raise HTTPException(status_code=409, detail="Medication client request was reused")

    candidate: MedicationPrefillCandidate | None = None
    if payload.candidate_id is not None:
        candidate = db.execute(
            select(MedicationPrefillCandidate)
            .where(
                MedicationPrefillCandidate.id == payload.candidate_id,
                MedicationPrefillCandidate.user_id == user_id,
                MedicationPrefillCandidate.subject_user_id == payload.subject_user_id,
            )
            .with_for_update()
        ).scalars().first()
        if not candidate:
            raise HTTPException(status_code=404, detail="Medication prefill candidate not found")
        if candidate.version != payload.candidate_version:
            raise HTTPException(status_code=409, detail="Medication prefill version is stale")
        if candidate.review_status != "pending_review":
            raise HTTPException(status_code=409, detail="Medication prefill is already resolved")
        if payload.source_type != "ocr":
            raise HTTPException(status_code=422, detail="OCR candidate confirmation must keep source_type=ocr")
        fields["source_ref"] = f"medication-prefill:{candidate.id}"
    elif payload.source_type == "ocr":
        raise HTTPException(status_code=422, detail="OCR plans require a prefill candidate")

    now = utcnow()
    plan = TrustedMedicationPlan(
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_request_id=payload.client_request_id,
        **fields,
        source_snapshot={
            "confirmation_client_event_id": payload.client_event_id,
            "candidate_id": candidate.id if candidate else None,
            "candidate_version": candidate.version if candidate else None,
            "raw_ocr_stored": False,
        },
        status="active",
        version=1,
        confirmed_by_user_id=user_id,
        confirmed_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.flush()
    if candidate:
        candidate.review_status = "accepted"
        candidate.version += 1
        candidate.reviewed_by_user_id = user_id
        candidate.reviewed_at = now
        candidate.review_client_event_id = payload.client_event_id
        candidate.accepted_plan_id = plan.id
        snapshot = dict(candidate.source_snapshot or {})
        snapshot["review"] = {
            "action": "accept",
            "confirmed_plan_id": plan.id,
            "user_corrected_fields_allowed": True,
        }
        candidate.source_snapshot = snapshot
    db.add(
        MedicationPlanEvent(
            plan_id=plan.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="confirm",
            target_version=1,
            before_data={},
            after_data={**_plan_snapshot(plan), "candidate_id": candidate.id if candidate else None},
        )
    )
    db.flush()
    sync_confirmed_long_term_profile_candidate(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        trigger_plan_id=plan.id,
    )
    return plan


def revise_plan(
    db: Session,
    *,
    plan_id: int,
    user_id: int,
    payload: MedicationPlanReviseIn,
) -> TrustedMedicationPlan:
    fields = _plan_fields(payload)
    request = {
        **payload.model_dump(mode="json"),
        "plan_id": plan_id,
        "normalized_schedule_times": fields["schedule_times"],
    }
    request_fingerprint = _fingerprint(request)
    replay = _plan_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
    )
    if replay:
        if replay.id != plan_id:
            raise HTTPException(status_code=409, detail="Medication plan event target changed")
        return replay
    plan = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.id == plan_id,
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Medication plan not found")
    if plan.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Medication plan version is stale")
    if plan.status == "retracted":
        raise HTTPException(status_code=409, detail="Retracted medication plan cannot be revised")
    before = _plan_snapshot(plan)
    for key, value in fields.items():
        setattr(plan, key, value)
    plan.source_snapshot = {
        **dict(plan.source_snapshot or {}),
        "latest_revision_client_event_id": payload.client_event_id,
    }
    plan.version += 1
    plan.confirmed_by_user_id = user_id
    plan.confirmed_at = utcnow()
    plan.updated_at = plan.confirmed_at
    db.add(
        MedicationPlanEvent(
            plan_id=plan.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="revise",
            target_version=plan.version,
            before_data=before,
            after_data=_plan_snapshot(plan),
        )
    )
    db.flush()
    sync_confirmed_long_term_profile_candidate(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        trigger_plan_id=plan.id,
    )
    return plan


def update_plan_status(
    db: Session,
    *,
    plan_id: int,
    user_id: int,
    payload: MedicationPlanStatusIn,
) -> TrustedMedicationPlan:
    request = {**payload.model_dump(mode="json"), "plan_id": plan_id}
    request_fingerprint = _fingerprint(request)
    replay = _plan_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
    )
    if replay:
        if replay.id != plan_id:
            raise HTTPException(status_code=409, detail="Medication plan event target changed")
        return replay
    plan = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.id == plan_id,
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Medication plan not found")
    if plan.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Medication plan version is stale")
    transitions = {
        "pause": ({"active"}, "paused"),
        "resume": ({"paused"}, "active"),
        "complete": ({"active", "paused"}, "completed"),
        "retract": ({"active", "paused", "completed"}, "retracted"),
    }
    allowed, target = transitions[payload.action]
    if plan.status not in allowed:
        raise HTTPException(status_code=409, detail="Medication plan status transition is invalid")
    before = _plan_snapshot(plan)
    plan.status = target
    plan.version += 1
    plan.confirmed_by_user_id = user_id
    plan.confirmed_at = utcnow()
    plan.updated_at = plan.confirmed_at
    db.add(
        MedicationPlanEvent(
            plan_id=plan.id,
            user_id=user_id,
            subject_user_id=payload.subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type=payload.action,
            target_version=plan.version,
            before_data=before,
            after_data={**_plan_snapshot(plan), "reason": _clean(payload.reason)},
        )
    )
    db.flush()
    sync_confirmed_long_term_profile_candidate(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        trigger_plan_id=plan.id,
    )
    return plan


def occurrence_key(plan_id: int, local_date: date, scheduled_time: str) -> str:
    return _bounded_id(
        "dose:", f"v1:{plan_id}:{local_date.isoformat()}:{scheduled_time}", limit=80
    )


def _task_status(
    *,
    scheduled_at: datetime,
    event: MedicationDoseEvent | None,
    now: datetime,
) -> tuple[str, str, str, datetime | None, datetime | None, str]:
    now = _aware_utc(now)
    scheduled_utc = _aware_utc(scheduled_at)
    if event and event.effective_status == "taken":
        return (
            "taken",
            "已服用",
            "user_confirmed",
            None,
            event.confirmed_at,
            "not_requested",
        )
    if event and event.effective_status == "skipped":
        return (
            "skipped",
            "本次跳过",
            "user_confirmed",
            None,
            event.confirmed_at,
            "not_requested",
        )
    if event and event.effective_status == "snoozed":
        snoozed_until = _aware_utc(event.snoozed_until) if event.snoozed_until else scheduled_utc
        if now <= snoozed_until + timedelta(minutes=_POSSIBLY_MISSED_AFTER_MINUTES):
            return (
                "snoozed",
                "稍后提醒",
                "user_confirmed",
                event.snoozed_until,
                event.confirmed_at,
                "client_managed",
            )
        return (
            "possibly_missed",
            "可能漏服",
            "schedule_derived",
            event.snoozed_until,
            event.confirmed_at,
            "client_managed",
        )
    if event and event.effective_status == "pending":
        event = None
    if now < scheduled_utc:
        return ("upcoming", "时间未到", "schedule_derived", None, None, "not_requested")
    if now <= scheduled_utc + timedelta(minutes=_POSSIBLY_MISSED_AFTER_MINUTES):
        return (
            "awaiting_confirmation",
            "等待确认",
            "schedule_derived",
            None,
            None,
            "not_requested",
        )
    return (
        "possibly_missed",
        "可能漏服",
        "schedule_derived",
        None,
        None,
        "not_requested",
    )


def _latest_reaction_events(
    db: Session, *, user_id: int, subject_user_id: int
) -> dict[str, MedicationAdverseReactionEvent]:
    rows = db.execute(
        select(MedicationAdverseReactionEvent)
        .where(
            MedicationAdverseReactionEvent.user_id == user_id,
            MedicationAdverseReactionEvent.subject_user_id == subject_user_id,
        )
        .order_by(
            MedicationAdverseReactionEvent.reaction_key,
            MedicationAdverseReactionEvent.reaction_version,
            MedicationAdverseReactionEvent.id,
        )
    ).scalars().all()
    latest: dict[str, MedicationAdverseReactionEvent] = {}
    for row in rows:
        latest[row.reaction_key] = row
    return latest


def build_today_summary(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    local_date: date,
    timezone_offset_minutes: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not -840 <= timezone_offset_minutes <= 840:
        raise HTTPException(status_code=422, detail="timezone_offset_minutes is out of range")
    local_tz = timezone(timedelta(minutes=timezone_offset_minutes))
    current = _aware_utc(now or utcnow())
    plans = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == subject_user_id,
            TrustedMedicationPlan.status == "active",
            TrustedMedicationPlan.confirmed_by_user_id.is_not(None),
            TrustedMedicationPlan.confirmed_at.is_not(None),
        )
        .order_by(TrustedMedicationPlan.id)
    ).scalars().all()
    latest = _latest_dose_events(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        local_date=local_date,
    )
    tasks: list[dict[str, Any]] = []
    for plan in plans:
        if plan.course_start and local_date < plan.course_start:
            continue
        if plan.course_end and local_date > plan.course_end:
            continue
        for scheduled_time in validate_schedule_times(list(plan.schedule_times or [])):
            hour, minute = (int(part) for part in scheduled_time.split(":"))
            scheduled_at = datetime.combine(
                local_date, time(hour=hour, minute=minute), tzinfo=local_tz
            )
            key = occurrence_key(plan.id, local_date, scheduled_time)
            event = latest.get(key)
            status, label, assertion, snoozed_until, confirmed_at, notification_status = (
                _task_status(scheduled_at=scheduled_at, event=event, now=current)
            )
            tasks.append(
                {
                    "occurrence_key": key,
                    "plan_id": plan.id,
                    "plan_version": plan.version,
                    "generic_name": plan.generic_name,
                    "brand_name": plan.brand_name,
                    "dose_text": plan.dose_text,
                    "scheduled_local_date": local_date,
                    "scheduled_time": scheduled_time,
                    "scheduled_at": scheduled_at,
                    "status": status,
                    "status_label": label,
                    "status_assertion": assertion,
                    "occurrence_version": event.occurrence_version if event else 0,
                    "latest_event_id": event.id if event else None,
                    "snoozed_until": snoozed_until,
                    "confirmed_at": confirmed_at,
                    "possibly_missed_is_not_confirmation": status == "possibly_missed",
                    "notification_schedule_status": notification_status,
                }
            )
    tasks.sort(key=lambda item: (item["scheduled_at"], item["plan_id"]))
    next_task = next(
        (item for item in tasks if item["status"] not in {"taken", "skipped"}), None
    )
    reaction_count = 0
    for reaction in _latest_reaction_events(
        db, user_id=user_id, subject_user_id=subject_user_id
    ).values():
        onset_local = _aware_utc(reaction.onset_at).astimezone(local_tz).date()
        if reaction.status == "active" and onset_local == local_date:
            reaction_count += 1
    return {
        "subject_user_id": subject_user_id,
        "local_date": local_date,
        "planned_count": len(tasks),
        "taken_count": sum(item["status"] == "taken" for item in tasks),
        "awaiting_confirmation_count": sum(
            item["status"] in {"upcoming", "awaiting_confirmation"} for item in tasks
        ),
        "possibly_missed_count": sum(item["status"] == "possibly_missed" for item in tasks),
        "skipped_count": sum(item["status"] == "skipped" for item in tasks),
        "snoozed_count": sum(item["status"] == "snoozed" for item in tasks),
        "adverse_reaction_count": reaction_count,
        "next_task": next_task,
        "tasks": tasks,
        "empty_state": None
        if tasks
        else "暂无已确认用药计划；可从已确认处方导入或手动添加。",
        "missed_assertion_policy": "elapsed_time_never_confirms_missed",
    }


def record_dose_action(
    db: Session,
    *,
    user_id: int,
    payload: MedicationDoseActionIn,
    now: datetime | None = None,
) -> MedicationDoseEvent:
    validate_schedule_times([payload.scheduled_time])
    request_fingerprint = _fingerprint(payload.model_dump(mode="json"))
    replay = db.execute(
        select(MedicationDoseEvent).where(
            MedicationDoseEvent.user_id == user_id,
            MedicationDoseEvent.subject_user_id == payload.subject_user_id,
            MedicationDoseEvent.client_event_id == payload.client_event_id,
        )
    ).scalars().first()
    if replay:
        if replay.request_fingerprint != request_fingerprint:
            raise HTTPException(status_code=409, detail="Medication dose event was reused")
        return replay
    plan = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.id == payload.plan_id,
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Medication plan not found")
    if plan.version != payload.expected_plan_version:
        raise HTTPException(status_code=409, detail="Medication plan version is stale")
    key = occurrence_key(plan.id, payload.scheduled_local_date, payload.scheduled_time)
    current = db.execute(
        select(MedicationDoseEvent)
        .where(
            MedicationDoseEvent.plan_id == plan.id,
            MedicationDoseEvent.user_id == user_id,
            MedicationDoseEvent.subject_user_id == payload.subject_user_id,
            MedicationDoseEvent.occurrence_key == key,
        )
        .order_by(MedicationDoseEvent.occurrence_version.desc())
        .with_for_update()
    ).scalars().first()
    current_version = current.occurrence_version if current else 0
    if current_version != payload.expected_occurrence_version:
        raise HTTPException(status_code=409, detail="Medication dose occurrence version is stale")
    if current is None:
        if plan.status != "active":
            raise HTTPException(status_code=409, detail="Medication plan is not active")
        if payload.scheduled_time not in validate_schedule_times(list(plan.schedule_times or [])):
            raise HTTPException(status_code=422, detail="Dose occurrence is not in confirmed schedule")
        if plan.course_start and payload.scheduled_local_date < plan.course_start:
            raise HTTPException(status_code=422, detail="Dose occurrence is before confirmed course")
        if plan.course_end and payload.scheduled_local_date > plan.course_end:
            raise HTTPException(status_code=422, detail="Dose occurrence is after confirmed course")
    elif payload.action != "correct" and current.effective_status in {"taken", "skipped"}:
        raise HTTPException(status_code=409, detail="Completed dose action must be corrected explicitly")
    if payload.action == "correct":
        if not current or payload.correction_of_event_id != current.id:
            raise HTTPException(status_code=409, detail="Dose correction target is stale")
        effective_status = payload.corrected_status
        supersedes_event_id = current.id
    else:
        effective_status = {
            "taken": "taken",
            "snooze": "snoozed",
            "skip": "skipped",
        }[payload.action]
        supersedes_event_id = None
    confirmed_at = _aware_utc(now or utcnow())
    snoozed_until = payload.snoozed_until
    if snoozed_until is not None:
        if snoozed_until.tzinfo is None:
            raise HTTPException(status_code=422, detail="snoozed_until must include timezone")
        if _aware_utc(snoozed_until) <= confirmed_at:
            raise HTTPException(status_code=422, detail="snoozed_until must be in the future")
    taken_quantity = payload.taken_quantity
    if effective_status == "taken" and taken_quantity is None:
        taken_quantity = plan.dose_quantity
    event = MedicationDoseEvent(
        plan_id=plan.id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        occurrence_key=key,
        scheduled_local_date=payload.scheduled_local_date,
        scheduled_time=payload.scheduled_time,
        action=payload.action,
        effective_status=effective_status,
        occurrence_version=current_version + 1,
        supersedes_event_id=supersedes_event_id,
        snoozed_until=snoozed_until if effective_status == "snoozed" else None,
        taken_quantity=taken_quantity if effective_status == "taken" else None,
        reason=_clean(payload.reason),
        source_type="user_confirmed",
        confirmed_by_user_id=user_id,
        confirmed_at=confirmed_at,
    )
    db.add(event)
    db.flush()
    return event


def dose_event_out(event: MedicationDoseEvent) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "occurrence_key": event.occurrence_key,
        "occurrence_version": event.occurrence_version,
        "action": event.action,
        "effective_status": event.effective_status,
        "supersedes_event_id": event.supersedes_event_id,
        "snoozed_until": event.snoozed_until,
        "taken_quantity": float(event.taken_quantity)
        if event.taken_quantity is not None
        else None,
        "reason": event.reason,
        "confirmed_at": event.confirmed_at,
        "trust_state": "user_confirmed",
        "notification_schedule_status": "client_must_schedule"
        if event.effective_status == "snoozed"
        else "not_requested",
        "reminder_management": "client_managed",
    }


def _reaction_fingerprint(payload: Any, *, reaction_key: str) -> str:
    return _fingerprint({**payload.model_dump(mode="json"), "reaction_key": reaction_key})


def _reaction_event_replay(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
    request_fingerprint: str,
) -> MedicationAdverseReactionEvent | None:
    event = db.execute(
        select(MedicationAdverseReactionEvent).where(
            MedicationAdverseReactionEvent.user_id == user_id,
            MedicationAdverseReactionEvent.subject_user_id == subject_user_id,
            MedicationAdverseReactionEvent.client_event_id == client_event_id,
        )
    ).scalars().first()
    if event and event.request_fingerprint != request_fingerprint:
        raise HTTPException(status_code=409, detail="Medication reaction event was reused")
    return event


def _require_reaction_plan(
    db: Session, *, plan_id: int, user_id: int, subject_user_id: int
) -> TrustedMedicationPlan:
    plan = db.execute(
        select(TrustedMedicationPlan).where(
            TrustedMedicationPlan.id == plan_id,
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not plan:
        raise HTTPException(status_code=404, detail="Medication plan not found")
    return plan


def _validate_related_occurrence(
    db: Session,
    *,
    occurrence: str | None,
    plan_id: int,
    user_id: int,
    subject_user_id: int,
) -> None:
    if occurrence is None:
        return
    exists = db.execute(
        select(MedicationDoseEvent.id).where(
            MedicationDoseEvent.plan_id == plan_id,
            MedicationDoseEvent.user_id == user_id,
            MedicationDoseEvent.subject_user_id == subject_user_id,
            MedicationDoseEvent.occurrence_key == occurrence,
        )
    ).first()
    if not exists:
        raise HTTPException(status_code=422, detail="Related dose occurrence is not confirmed")


def create_reaction(
    db: Session,
    *,
    user_id: int,
    payload: MedicationReactionCreateIn,
) -> MedicationAdverseReactionEvent:
    fingerprint = _reaction_fingerprint(payload, reaction_key=payload.reaction_key)
    replay = _reaction_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
    )
    if replay:
        return replay
    _require_reaction_plan(
        db, plan_id=payload.plan_id, user_id=user_id, subject_user_id=payload.subject_user_id
    )
    existing = _latest_reaction_events(
        db, user_id=user_id, subject_user_id=payload.subject_user_id
    ).get(payload.reaction_key)
    if existing:
        raise HTTPException(status_code=409, detail="Medication reaction key already exists")
    _validate_related_occurrence(
        db,
        occurrence=payload.related_occurrence_key,
        plan_id=payload.plan_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    )
    if payload.onset_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="onset_at must include timezone")
    event = MedicationAdverseReactionEvent(
        plan_id=payload.plan_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
        reaction_key=payload.reaction_key,
        reaction_version=1,
        event_type="create",
        status="active",
        symptoms=payload.symptoms.strip(),
        onset_at=payload.onset_at,
        severity=payload.severity,
        duration_minutes=payload.duration_minutes,
        related_occurrence_key=payload.related_occurrence_key,
        notes=_clean(payload.notes),
        causal_attribution="temporal_association_only",
        confirmed_by_user_id=user_id,
        confirmed_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def correct_reaction(
    db: Session,
    *,
    reaction_key: str,
    user_id: int,
    payload: MedicationReactionCorrectIn,
) -> MedicationAdverseReactionEvent:
    fingerprint = _reaction_fingerprint(payload, reaction_key=reaction_key)
    replay = _reaction_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
    )
    if replay:
        return replay
    current = _latest_reaction_events(
        db, user_id=user_id, subject_user_id=payload.subject_user_id
    ).get(reaction_key)
    if not current:
        raise HTTPException(status_code=404, detail="Medication reaction not found")
    if current.reaction_version != payload.expected_version or current.status != "active":
        raise HTTPException(status_code=409, detail="Medication reaction version is stale")
    _require_reaction_plan(
        db, plan_id=payload.plan_id, user_id=user_id, subject_user_id=payload.subject_user_id
    )
    _validate_related_occurrence(
        db,
        occurrence=payload.related_occurrence_key,
        plan_id=payload.plan_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    )
    if payload.onset_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="onset_at must include timezone")
    event = MedicationAdverseReactionEvent(
        plan_id=payload.plan_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
        reaction_key=reaction_key,
        reaction_version=current.reaction_version + 1,
        event_type="correct",
        status="active",
        symptoms=payload.symptoms.strip(),
        onset_at=payload.onset_at,
        severity=payload.severity,
        duration_minutes=payload.duration_minutes,
        related_occurrence_key=payload.related_occurrence_key,
        notes=_clean(payload.notes),
        causal_attribution="temporal_association_only",
        confirmed_by_user_id=user_id,
        confirmed_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def retract_reaction(
    db: Session,
    *,
    reaction_key: str,
    user_id: int,
    payload: MedicationReactionRetractIn,
) -> MedicationAdverseReactionEvent:
    fingerprint = _reaction_fingerprint(payload, reaction_key=reaction_key)
    replay = _reaction_event_replay(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
    )
    if replay:
        return replay
    current = _latest_reaction_events(
        db, user_id=user_id, subject_user_id=payload.subject_user_id
    ).get(reaction_key)
    if not current:
        raise HTTPException(status_code=404, detail="Medication reaction not found")
    if current.reaction_version != payload.expected_version or current.status != "active":
        raise HTTPException(status_code=409, detail="Medication reaction version is stale")
    event = MedicationAdverseReactionEvent(
        plan_id=current.plan_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=fingerprint,
        reaction_key=reaction_key,
        reaction_version=current.reaction_version + 1,
        event_type="retract",
        status="retracted",
        symptoms=current.symptoms,
        onset_at=current.onset_at,
        severity=current.severity,
        duration_minutes=current.duration_minutes,
        related_occurrence_key=current.related_occurrence_key,
        notes=current.notes,
        causal_attribution="temporal_association_only",
        confirmed_by_user_id=user_id,
        confirmed_at=utcnow(),
    )
    db.add(event)
    db.flush()
    return event


def reaction_out(event: MedicationAdverseReactionEvent) -> dict[str, Any]:
    guidance = (
        "症状较重，请尽快联系医生、药师；如出现呼吸困难、意识异常或快速加重，请立即联系急救服务。"
        if event.severity == "severe"
        else "如症状持续、加重或影响日常活动，请及时联系医生或药师。"
    )
    return {
        "reaction_key": event.reaction_key,
        "reaction_version": event.reaction_version,
        "plan_id": event.plan_id,
        "symptoms": event.symptoms,
        "onset_at": event.onset_at,
        "severity": event.severity,
        "duration_minutes": event.duration_minutes,
        "related_occurrence_key": event.related_occurrence_key,
        "notes": event.notes,
        "status": event.status,
        "causal_attribution": "temporal_association_only",
        "user_facing_causality": "该症状发生在服药后，不能据此认定由药物导致",
        "safety_guidance": guidance,
        "confirmed_at": event.confirmed_at,
    }


def list_reactions(
    db: Session, *, user_id: int, subject_user_id: int
) -> list[dict[str, Any]]:
    latest = _latest_reaction_events(
        db, user_id=user_id, subject_user_id=subject_user_id
    )
    return [
        reaction_out(event)
        for event in sorted(
            latest.values(), key=lambda item: (item.onset_at, item.id), reverse=True
        )
    ]


def confirmed_medication_context(db: Session, *, user_id: int) -> list[dict[str, Any]]:
    """Return only self-owned, active, explicitly confirmed plans for AI context."""
    rows = db.execute(
        select(TrustedMedicationPlan)
        .where(
            TrustedMedicationPlan.user_id == user_id,
            TrustedMedicationPlan.subject_user_id == user_id,
            TrustedMedicationPlan.status == "active",
            TrustedMedicationPlan.confirmed_by_user_id == user_id,
            TrustedMedicationPlan.confirmed_at.is_not(None),
        )
        .order_by(TrustedMedicationPlan.updated_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        {
            "name": row.generic_name,
            "brand_name": row.brand_name,
            "strength": row.strength,
            "dosage": row.dose_text,
            "frequency": row.frequency,
            "instructions": row.instructions,
            "schedule_times": list(row.schedule_times or []),
            "course_start": row.course_start.isoformat() if row.course_start else None,
            "course_end": row.course_end.isoformat() if row.course_end else None,
            "trust_state": "user_confirmed",
            "confirmed_at": row.confirmed_at.isoformat(),
            "source_ref": f"trusted-medication-plan:{row.id}:v{row.version}",
        }
        for row in rows
    ]
