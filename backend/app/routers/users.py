from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.core.intervention import InterventionLevel, get_strategy
from app.models.consent import Consent
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.user_settings import UserSettings
from app.schemas.settings import InterventionStrategyOut, UserSettingsOut, UserSettingsUpdate
from app.schemas.user import (
    ConsentOut,
    ConsentUpdateRequest,
    UserMeOut,
    UserProfileOut,
    UserProfileUpdate,
)

router = APIRouter()


@router.get("/me", response_model=UserMeOut)
def me(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.id == user_id)).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    consent = db.execute(select(Consent).where(Consent.user_id == user.id)).scalars().first()
    if consent is None:
        consent = Consent(user_id=user.id)
        db.add(consent)
        db.commit()
        db.refresh(consent)

    settings_row = _get_or_create_settings(db, user.id)

    profile = db.execute(select(UserProfile).where(UserProfile.user_id == user.id)).scalars().first()
    profile_out = (
        UserProfileOut(
            sex=profile.sex,
            age=profile.age,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            display_name=profile.display_name,
        )
        if profile is not None
        else None
    )

    return UserMeOut(
        id=str(user.id),
        phone=user.phone,
        username=user.username,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
        consent={
            "allow_ai_chat": consent.allow_ai_chat,
            "allow_data_upload": consent.allow_data_upload,
            "version": consent.version,
            "updated_at": consent.updated_at,
        },
        settings={
            "intervention_level": settings_row.intervention_level,
            "daily_reminder_limit": settings_row.daily_reminder_limit,
            "allow_auto_escalation": settings_row.allow_auto_escalation,
        },
        profile=profile_out,
    )


@router.patch("/consent", response_model=ConsentOut)
def update_consent(
    payload: ConsentUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    consent = db.execute(select(Consent).where(Consent.user_id == user_id)).scalars().first()
    if consent is None:
        consent = Consent(user_id=user_id)

    if payload.allow_ai_chat is not None:
        consent.allow_ai_chat = payload.allow_ai_chat
    if payload.allow_data_upload is not None:
        consent.allow_data_upload = payload.allow_data_upload

    db.add(consent)
    db.commit()
    db.refresh(consent)

    return ConsentOut(
        allow_ai_chat=consent.allow_ai_chat,
        allow_data_upload=consent.allow_data_upload,
        version=consent.version,
        updated_at=consent.updated_at,
    )


# ---------------------------------------------------------------------------
# Profile (性别/年龄/身高/体重) endpoints
# ---------------------------------------------------------------------------


def _get_or_create_profile(db: Session, user_id) -> UserProfile:
    profile = db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    ).scalars().first()
    if profile is None:
        profile = UserProfile(
            user_id=int(user_id),
            subject_id=f"phone_{user_id}",
            cohort="phone",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.get("/profile", response_model=UserProfileOut)
def get_profile(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserProfileOut:
    profile = _get_or_create_profile(db, user_id)
    return UserProfileOut(
        sex=profile.sex,
        age=profile.age,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        display_name=profile.display_name,
    )


@router.patch("/profile", response_model=UserProfileOut)
def update_profile(
    payload: UserProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserProfileOut:
    profile = _get_or_create_profile(db, user_id)
    data = payload.model_dump(exclude_unset=True)
    for field in ("sex", "age", "height_cm", "weight_kg", "display_name"):
        if field in data:
            value = data[field]
            # 空字符串视为清空
            if isinstance(value, str) and value.strip() == "":
                value = None
            setattr(profile, field, value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return UserProfileOut(
        sex=profile.sex,
        age=profile.age,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        display_name=profile.display_name,
    )


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


def _get_or_create_settings(db: Session, user_id) -> UserSettings:
    """Retrieve or lazily create default UserSettings row."""
    settings = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _build_settings_out(settings: UserSettings) -> UserSettingsOut:
    """Build response with resolved strategy parameters."""
    level = InterventionLevel(settings.intervention_level)
    strat = get_strategy(level)
    return UserSettingsOut(
        intervention_level=settings.intervention_level,
        daily_reminder_limit=settings.daily_reminder_limit,
        allow_auto_escalation=settings.allow_auto_escalation,
        glucose_unit=settings.glucose_unit,
        updated_at=settings.updated_at,
        strategy=InterventionStrategyOut(
            trigger_min_risk=strat.trigger_min_risk.value,
            daily_reminder_limit=strat.daily_reminder_limit,
            per_meal_reminder_limit=strat.per_meal_reminder_limit,
            suggestion_count_min=strat.suggestion_count_min,
            suggestion_count_max=strat.suggestion_count_max,
            review_required=strat.review_required,
            escalation_consecutive_days=strat.escalation_consecutive_days,
        ),
    )


@router.get("/settings", response_model=UserSettingsOut)
def get_settings(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserSettingsOut:
    """Return current user settings (creates defaults if not yet set)."""
    settings = _get_or_create_settings(db, user_id)
    return _build_settings_out(settings)


@router.patch("/settings", response_model=UserSettingsOut)
def update_settings(
    payload: UserSettingsUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> UserSettingsOut:
    """Update user settings (partial update)."""
    settings = _get_or_create_settings(db, user_id)

    if payload.intervention_level is not None:
        # Validate it's a real level
        try:
            InterventionLevel(payload.intervention_level)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid intervention level")
        settings.intervention_level = payload.intervention_level

    if payload.daily_reminder_limit is not None:
        # Enforce it doesn't exceed level max
        level = InterventionLevel(settings.intervention_level)
        strat = get_strategy(level)
        if payload.daily_reminder_limit > strat.daily_reminder_limit:
            raise HTTPException(
                status_code=422,
                detail=f"daily_reminder_limit cannot exceed {strat.daily_reminder_limit} for level {level.value}",
            )
        settings.daily_reminder_limit = payload.daily_reminder_limit

    if payload.allow_auto_escalation is not None:
        settings.allow_auto_escalation = payload.allow_auto_escalation

    if payload.glucose_unit is not None:
        settings.glucose_unit = payload.glucose_unit

    db.add(settings)
    db.commit()
    db.refresh(settings)
    return _build_settings_out(settings)
