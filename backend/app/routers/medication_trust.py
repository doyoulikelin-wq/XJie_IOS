"""Authenticated routes for the trusted medication execution loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.schemas.medication_trust import (
    LongTermMedicationSummaryListOut,
    MedicationDoseActionIn,
    MedicationDoseEventOut,
    MedicationPlanConfirmIn,
    MedicationPlanListOut,
    MedicationPlanOut,
    MedicationPlanReviseIn,
    MedicationPlanStatusIn,
    MedicationPrefillCandidateOut,
    MedicationPrefillListOut,
    MedicationPrefillRejectIn,
    MedicationReactionCorrectIn,
    MedicationReactionCreateIn,
    MedicationReactionListOut,
    MedicationReactionOut,
    MedicationReactionRetractIn,
    MedicationTodaySummaryOut,
)
from app.services.medication_trust_service import (
    build_today_summary,
    confirm_plan,
    correct_reaction,
    create_reaction,
    dose_event_out,
    list_plans,
    list_confirmed_long_term_medication_summaries,
    list_prefill_candidates,
    list_reactions,
    plan_out,
    prefill_out,
    reaction_out,
    record_dose_action,
    reject_prefill_candidate,
    retract_reaction,
    revise_plan,
    update_plan_status,
)


router = APIRouter(prefix="/trust")


def _self_subject(user_id: str, requested: int | None) -> tuple[int, int]:
    uid = int(user_id)
    subject_user_id = requested if requested is not None else uid
    if subject_user_id != uid:
        raise HTTPException(
            status_code=403,
            detail="Medication subject access requires explicit delegated authorization",
        )
    return uid, subject_user_id


@router.get("/plans", response_model=MedicationPlanListOut)
def get_trusted_medication_plans(
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPlanListOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    return MedicationPlanListOut(
        subject_user_id=subject,
        items=list_plans(db, user_id=uid, subject_user_id=subject),
    )


@router.get("/long-term-summary", response_model=LongTermMedicationSummaryListOut)
def get_confirmed_long_term_medication_summary(
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> LongTermMedicationSummaryListOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    return LongTermMedicationSummaryListOut(
        subject_user_id=subject,
        items=list_confirmed_long_term_medication_summaries(
            db,
            user_id=uid,
            subject_user_id=subject,
        ),
    )


@router.post("/plans/confirm", response_model=MedicationPlanOut)
def confirm_trusted_medication_plan(
    payload: MedicationPlanConfirmIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPlanOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    plan = confirm_plan(db, user_id=uid, payload=payload)
    db.commit()
    db.refresh(plan)
    return MedicationPlanOut(**plan_out(db, plan))


@router.post("/plans/{plan_id}/revise", response_model=MedicationPlanOut)
def revise_trusted_medication_plan(
    plan_id: int,
    payload: MedicationPlanReviseIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPlanOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    plan = revise_plan(db, plan_id=plan_id, user_id=uid, payload=payload)
    db.commit()
    db.refresh(plan)
    return MedicationPlanOut(**plan_out(db, plan))


@router.post("/plans/{plan_id}/status", response_model=MedicationPlanOut)
def change_trusted_medication_plan_status(
    plan_id: int,
    payload: MedicationPlanStatusIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPlanOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    plan = update_plan_status(db, plan_id=plan_id, user_id=uid, payload=payload)
    db.commit()
    db.refresh(plan)
    return MedicationPlanOut(**plan_out(db, plan))


@router.get("/prefill-candidates", response_model=MedicationPrefillListOut)
def get_medication_prefill_candidates(
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPrefillListOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    return MedicationPrefillListOut(
        subject_user_id=subject,
        items=list_prefill_candidates(db, user_id=uid, subject_user_id=subject),
    )


@router.post(
    "/prefill-candidates/{candidate_id}/reject",
    response_model=MedicationPrefillCandidateOut,
)
def reject_medication_prefill(
    candidate_id: int,
    payload: MedicationPrefillRejectIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationPrefillCandidateOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    candidate = reject_prefill_candidate(
        db, candidate_id=candidate_id, user_id=uid, payload=payload
    )
    db.commit()
    db.refresh(candidate)
    return MedicationPrefillCandidateOut(**prefill_out(candidate))


@router.get("/today", response_model=MedicationTodaySummaryOut)
def get_today_medication_tasks(
    subject_user_id: int | None = Query(default=None, gt=0),
    local_date: date | None = Query(default=None),
    timezone_offset_minutes: int = Query(default=480, ge=-840, le=840),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationTodaySummaryOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    effective_date = local_date or datetime.now(
        timezone(timedelta(minutes=timezone_offset_minutes))
    ).date()
    return MedicationTodaySummaryOut(
        **build_today_summary(
            db,
            user_id=uid,
            subject_user_id=subject,
            local_date=effective_date,
            timezone_offset_minutes=timezone_offset_minutes,
        )
    )


@router.post("/dose-events", response_model=MedicationDoseEventOut)
def record_medication_dose_event(
    payload: MedicationDoseActionIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationDoseEventOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    event = record_dose_action(db, user_id=uid, payload=payload)
    db.commit()
    db.refresh(event)
    return MedicationDoseEventOut(**dose_event_out(event))


@router.get("/reactions", response_model=MedicationReactionListOut)
def get_medication_reactions(
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationReactionListOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    return MedicationReactionListOut(
        subject_user_id=subject,
        items=list_reactions(db, user_id=uid, subject_user_id=subject),
    )


@router.post("/reactions", response_model=MedicationReactionOut)
def record_medication_reaction(
    payload: MedicationReactionCreateIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationReactionOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    event = create_reaction(db, user_id=uid, payload=payload)
    db.commit()
    db.refresh(event)
    return MedicationReactionOut(**reaction_out(event))


@router.post("/reactions/{reaction_key}/correct", response_model=MedicationReactionOut)
def correct_medication_reaction(
    reaction_key: str,
    payload: MedicationReactionCorrectIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationReactionOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    event = correct_reaction(
        db, reaction_key=reaction_key, user_id=uid, payload=payload
    )
    db.commit()
    db.refresh(event)
    return MedicationReactionOut(**reaction_out(event))


@router.post("/reactions/{reaction_key}/retract", response_model=MedicationReactionOut)
def retract_medication_reaction(
    reaction_key: str,
    payload: MedicationReactionRetractIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationReactionOut:
    uid, _subject = _self_subject(user_id, payload.subject_user_id)
    event = retract_reaction(
        db, reaction_key=reaction_key, user_id=uid, payload=payload
    )
    db.commit()
    db.refresh(event)
    return MedicationReactionOut(**reaction_out(event))
