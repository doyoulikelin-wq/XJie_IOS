from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.user_feedback import UserFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackOut

router = APIRouter()


@router.post("", response_model=FeedbackOut)
@router.post("/", response_model=FeedbackOut)
def create_feedback(
    payload: FeedbackCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    row = UserFeedback(
        user_id=user_id,
        category=payload.category or "general",
        content=payload.content,
        contact=payload.contact,
        app_platform=payload.app_platform,
        app_version=payload.app_version,
        device_info=payload.device_info,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FeedbackOut(
        id=row.id,
        user_id=row.user_id,
        category=row.category,
        content=row.content,
        contact=row.contact,
        app_platform=row.app_platform,
        app_version=row.app_version,
        device_info=row.device_info,
        status=row.status,
        created_at=row.created_at,
    )
