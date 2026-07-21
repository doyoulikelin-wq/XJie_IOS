"""Authenticated routes for trusted dietary drafts, records, and summaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user_id, get_db
from app.schemas.dietary_records import (
    DietaryDailySummaryStatusOut,
    DietaryDashboardOut,
    DietaryDayCompleteIn,
    DietaryDayOut,
    DietaryDraftConfirmIn,
    DietaryDraftCreateIn,
    DietaryDraftOut,
    DietaryDraftRetryRecognitionIn,
    DietaryRecentOut,
    DietaryRecordDeleteIn,
    DietaryRecordOut,
    DietaryRecordReuseIn,
    DietaryRecordUpdateIn,
)
from app.services import dietary_records_service as dietary_service
from app.services.dietary_text_extraction import (
    TEXT_RECOGNITION_CONTRACT_VERSION,
    extract_dietary_text_candidate,
)
from app.services.object_storage import (
    ObjectStorageConfigurationError,
    configured_private_object_store,
)


router = APIRouter()
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
    "image/webp",
}
TEXT_RECOGNITION_SOURCES = {"text", "voice", "chat"}


def _extract_text_draft(payload: DietaryDraftCreateIn) -> dict:
    """Called by the service only after its tenant/event replay lock is held."""

    return extract_dietary_text_candidate(payload.raw_input or "")


def _self_subject(user_id: int, requested: int | None) -> tuple[int, int]:
    uid = int(user_id)
    subject_user_id = requested if requested is not None else uid
    if subject_user_id != uid:
        raise HTTPException(
            status_code=403,
            detail="Dietary subject access requires explicit delegated authorization",
        )
    return uid, subject_user_id


def _dietary_image_object_store():
    try:
        return configured_private_object_store(settings)
    except ObjectStorageConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Dietary image object storage is not configured",
        ) from exc


@router.get("/daily-summary", response_model=DietaryDailySummaryStatusOut)
def get_daily_dietary_summary(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDailySummaryStatusOut:
    uid = int(user_id)
    return DietaryDailySummaryStatusOut(
        **dietary_service.daily_summary_status(
            db,
            user_id=uid,
            subject_user_id=uid,
        )
    )


@router.get("/dashboard", response_model=DietaryDashboardOut)
def get_dietary_dashboard(
    diet_date: date | None = Query(default=None),
    timezone_name: str = Query(default="Asia/Shanghai", alias="timezone"),
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDashboardOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    result = dietary_service.dashboard(
        db,
        user_id=uid,
        subject_user_id=subject,
        selected_date=diet_date,
        timezone_name=timezone_name,
    )
    db.commit()
    return DietaryDashboardOut(**result)


@router.post("/drafts", response_model=DietaryDraftOut)
def create_dietary_draft(
    payload: DietaryDraftCreateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDraftOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    should_extract_text = (
        payload.source_type in TEXT_RECOGNITION_SOURCES
        and bool((payload.raw_input or "").strip())
        and not payload.food_items
    )
    result = dietary_service.create_draft(
        db,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
        recognition_version=(
            TEXT_RECOGNITION_CONTRACT_VERSION if should_extract_text else None
        ),
        recognition_hook=_extract_text_draft if should_extract_text else None,
    )
    db.commit()
    return DietaryDraftOut(**result)


@router.put("/drafts/photo", response_model=DietaryDraftOut)
@router.post("/drafts/photo", response_model=DietaryDraftOut, include_in_schema=False)
def create_dietary_photo_draft(
    file: UploadFile = File(...),
    client_event_id: str = Form(..., min_length=1, max_length=80),
    diet_date: date | None = Form(default=None),
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = Form(
        default=None
    ),
    eaten_at: datetime = Form(...),
    source: Literal["camera", "photo_library"] = Form(...),
    timezone_name: str = Form(default="Asia/Shanghai", alias="timezone"),
    subject_user_id: int | None = Form(default=None, gt=0),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDraftOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported meal image type")
    content = file.file.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Meal image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Meal image exceeds 10 MB")
    result = dietary_service.create_photo_draft(
        db,
        user_id=uid,
        subject_user_id=subject,
        client_event_id=client_event_id,
        content=content,
        filename=file.filename or "meal.jpg",
        content_type=file.content_type,
        source_type=source,
        diet_date=diet_date,
        meal_type=meal_type,
        eaten_at=eaten_at,
        timezone_name=timezone_name,
        object_store=_dietary_image_object_store(),
    )
    db.commit()
    return DietaryDraftOut(**result)


@router.post("/drafts/{draft_id}/retry-recognition", response_model=DietaryDraftOut)
def retry_dietary_photo_recognition(
    draft_id: int,
    payload: DietaryDraftRetryRecognitionIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDraftOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.retry_photo_draft_recognition(
        db,
        draft_id=draft_id,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
        object_store=_dietary_image_object_store(),
    )
    db.commit()
    return DietaryDraftOut(**result)


@router.post("/drafts/{draft_id}/confirm", response_model=DietaryRecordOut)
def confirm_dietary_draft(
    draft_id: int,
    payload: DietaryDraftConfirmIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryRecordOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.confirm_draft(
        db,
        draft_id=draft_id,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
    )
    db.commit()
    return DietaryRecordOut(**result)


@router.patch("/records/{record_id}", response_model=DietaryRecordOut)
def update_dietary_record(
    record_id: int,
    payload: DietaryRecordUpdateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryRecordOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.update_record(
        db,
        record_id=record_id,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
    )
    db.commit()
    return DietaryRecordOut(**result)


@router.delete("/records/{record_id}", response_model=DietaryRecordOut)
def delete_dietary_record(
    record_id: int,
    payload: DietaryRecordDeleteIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryRecordOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.delete_record(
        db,
        record_id=record_id,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
    )
    db.commit()
    return DietaryRecordOut(**result)


@router.post("/records/{record_id}/reuse", response_model=DietaryDraftOut)
def reuse_dietary_record(
    record_id: int,
    payload: DietaryRecordReuseIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDraftOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.reuse_record(
        db,
        record_id=record_id,
        user_id=uid,
        subject_user_id=subject,
        payload=payload,
    )
    db.commit()
    return DietaryDraftOut(**result)


@router.get("/recent", response_model=DietaryRecentOut)
def get_recent_dietary_records(
    limit: int = Query(default=10, ge=1, le=30),
    subject_user_id: int | None = Query(default=None, gt=0),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryRecentOut:
    uid, subject = _self_subject(user_id, subject_user_id)
    return DietaryRecentOut(
        subject_user_id=subject,
        items=dietary_service.recent_records(
            db, user_id=uid, subject_user_id=subject, limit=limit
        ),
    )


@router.post("/days/{diet_date}/complete", response_model=DietaryDayOut)
def complete_dietary_day(
    diet_date: date,
    payload: DietaryDayCompleteIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DietaryDayOut:
    uid, subject = _self_subject(user_id, payload.subject_user_id)
    result = dietary_service.complete_day(
        db,
        user_id=uid,
        subject_user_id=subject,
        diet_date=diet_date,
        timezone_name=payload.timezone,
        method="manual",
        client_event_id=payload.client_event_id,
        complete_with_confirmed_only=payload.complete_with_confirmed_only,
    )
    db.commit()
    return DietaryDayOut(**result)
