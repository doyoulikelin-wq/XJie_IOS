"""Authenticated health-profile review and explicit confirmation endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.schemas.health_profile_trust import (
    HealthProfileCandidateReviewIn,
    HealthProfileFactRetractIn,
    HealthProfileFactUpsertIn,
    HealthProfileGoalCreateIn,
    HealthProfileGoalStatusIn,
    HealthProfileGoalUpdateIn,
    HealthProfileOut,
    HealthProfileRevisionListOut,
)
from app.services.health_profile_trust_service import (
    build_profile,
    create_profile_goal,
    list_fact_revisions,
    list_goal_revisions,
    retract_fact,
    review_candidate,
    update_profile_goal,
    update_profile_goal_status,
    upsert_manual_fact,
)


router = APIRouter()


def _require_self_subject(*, user_id: int, subject_user_id: int) -> None:
    # Delegated profile writes require a separate granular family-consent
    # contract. Until then every mutation and read fails closed to self.
    if subject_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Health profile confirmation is limited to the account owner",
        )


@router.get("/profile-trust", response_model=HealthProfileOut)
def get_health_profile(
    subject_user_id: int | None = Query(default=None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    resolved_subject_user_id = user_id if subject_user_id is None else subject_user_id
    _require_self_subject(user_id=user_id, subject_user_id=resolved_subject_user_id)
    return build_profile(db, user_id=user_id, subject_user_id=resolved_subject_user_id)


@router.post(
    "/profile-trust/candidates/{candidate_id}/review",
    response_model=HealthProfileOut,
)
def review_health_profile_candidate(
    candidate_id: int,
    payload: HealthProfileCandidateReviewIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    result = review_candidate(db, candidate_id=candidate_id, user_id=user_id, payload=payload)
    db.commit()
    return result


@router.post("/profile-trust/facts", response_model=HealthProfileOut)
def save_health_profile_fact(
    payload: HealthProfileFactUpsertIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    result = upsert_manual_fact(db, user_id=user_id, payload=payload)
    db.commit()
    return result


@router.post("/profile-trust/facts/{fact_id}/retract", response_model=HealthProfileOut)
def retract_health_profile_fact(
    fact_id: int,
    payload: HealthProfileFactRetractIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    result = retract_fact(db, fact_id=fact_id, user_id=user_id, payload=payload)
    db.commit()
    return result


@router.get(
    "/profile-trust/facts/{fact_id}/revisions",
    response_model=HealthProfileRevisionListOut,
)
def get_health_profile_fact_revisions(
    fact_id: int,
    subject_user_id: int | None = Query(default=None),
    after_revision_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    subject = user_id if subject_user_id is None else subject_user_id
    _require_self_subject(user_id=user_id, subject_user_id=subject)
    return list_fact_revisions(
        db,
        fact_id=fact_id,
        user_id=user_id,
        subject_user_id=subject,
        after_revision_id=after_revision_id,
        limit=limit,
    )


@router.post("/profile-trust/goals", response_model=HealthProfileOut)
def create_health_profile_goal(
    payload: HealthProfileGoalCreateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    create_profile_goal(db, user_id=user_id, payload=payload)
    db.commit()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


@router.patch("/profile-trust/goals/{goal_id}", response_model=HealthProfileOut)
def revise_health_profile_goal(
    goal_id: int,
    payload: HealthProfileGoalUpdateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    update_profile_goal(db, goal_id=goal_id, user_id=user_id, payload=payload)
    db.commit()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


@router.post("/profile-trust/goals/{goal_id}/status", response_model=HealthProfileOut)
def change_health_profile_goal_status(
    goal_id: int,
    payload: HealthProfileGoalStatusIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    update_profile_goal_status(db, goal_id=goal_id, user_id=user_id, payload=payload)
    db.commit()
    return build_profile(db, user_id=user_id, subject_user_id=payload.subject_user_id)


@router.get(
    "/profile-trust/goals/{goal_id}/revisions",
    response_model=HealthProfileRevisionListOut,
)
def get_health_profile_goal_revisions(
    goal_id: int,
    subject_user_id: int | None = Query(default=None),
    after_revision_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    subject = user_id if subject_user_id is None else subject_user_id
    _require_self_subject(user_id=user_id, subject_user_id=subject)
    return list_goal_revisions(
        db,
        goal_id=goal_id,
        user_id=user_id,
        subject_user_id=subject,
        after_revision_id=after_revision_id,
        limit=limit,
    )
