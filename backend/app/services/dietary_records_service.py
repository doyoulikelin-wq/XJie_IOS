"""Server-authoritative dietary draft, confirmation, and summary state machine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.dietary_records import (
    DietaryDailySummary,
    DietaryDay,
    DietaryDraft,
    DietaryRecognitionCache,
    DietaryRecord,
    DietaryRecordEvent,
)
from app.providers.base import DailyDietSummaryResult
from app.schemas.dietary_records import (
    DietaryDraftConfirmIn,
    DietaryDraftCreateIn,
    DietaryDraftRetryRecognitionIn,
    DietaryRecordDeleteIn,
    DietaryRecordReuseIn,
    DietaryRecordUpdateIn,
)
from app.services.object_storage import (
    LocalPrivateObjectStore,
    ObjectStorageConfigurationError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageUnavailableError,
    PrivateObjectStore,
    StoredObjectMetadata,
)


RULE_VERSION = "dietary-structure-rules.v1"
TEMPLATE_VERSION = "dietary-summary-zh.v1"
RECOGNITION_VERSION = "meal-vision-normalization.v1"
LOW_CONFIDENCE_THRESHOLD = 0.70
MAX_PERSISTED_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RECOGNITION_RETRY_RECEIPTS = 50
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
SUMMARY_RETRY_DELAYS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
)
NEVER_RECORDED_MESSAGE = "还没有记录过饮食呢，快记录你的第一餐吧"
NO_YESTERDAY_RECORDS_MESSAGE = "昨天忘记记录饮食啦"
RETRYABLE_RECOGNITION_STATUSES = {
    "failed_manual_entry_available",
    "recognition_pending",
    "recognition_incomplete",
}
_HOOK_RECOGNITION_STATUSES = RETRYABLE_RECOGNITION_STATUSES | {"completed"}
_DRAFT_RECOGNITION_FIELDS = (
    "meal_type",
    "food_items",
    "portion_text",
    "structure",
    "estimated_nutrition",
    "field_confidences",
    "recognition_confidence",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return _aware_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dietary_client_event_lock_key(
    *, user_id: int, subject_user_id: int, client_event_id: str
) -> int:
    """Derive one stable signed PostgreSQL advisory-lock key per tenant event."""

    material = (
        f"dietary-client-event.v1\0{user_id}\0{subject_user_id}\0{client_event_id}"
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def _lock_dietary_client_event(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
) -> None:
    """Serialize one tenant/event string until the caller commits or rolls back.

    Unique constraints remain the durable backstop, while this transaction-level
    lock closes the check-then-insert race and lets the waiter re-read the exact
    committed receipt. Receipt identity remains operation-scoped
    (tenant + endpoint + client_event_id); sharing this lock across endpoints is
    deliberate stronger serialization, not a global cross-operation receipt.
    SQLite is used only by deterministic unit tests and has no PostgreSQL
    advisory-lock equivalent.
    """

    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {
            "lock_key": _dietary_client_event_lock_key(
                user_id=user_id,
                subject_user_id=subject_user_id,
                client_event_id=client_event_id,
            )
        },
    )


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Unsupported IANA timezone"
        ) from exc


def derive_diet_date(
    eaten_at: datetime,
    timezone_name: str,
    confirmed_date: date | None = None,
) -> date:
    """Return the local dietary date whose boundary is 04:00.

    An explicit user-confirmed date always wins.  This makes a later timezone
    change unable to silently move an already reviewed meal to another day.
    """

    if confirmed_date is not None:
        return confirmed_date
    if eaten_at.tzinfo is None or eaten_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="eaten_at must include timezone")
    local = eaten_at.astimezone(_timezone(timezone_name))
    return (local - timedelta(hours=4)).date()


def dietary_day_auto_close_at(
    diet_date: date,
    timezone_name: str,
) -> datetime:
    """Return the UTC instant at local 04:00 on the following calendar day."""

    next_date = diet_date + timedelta(days=1)
    local_due_at = datetime(
        next_date.year,
        next_date.month,
        next_date.day,
        4,
        tzinfo=_timezone(timezone_name),
    )
    return local_due_at.astimezone(timezone.utc)


def beijing_target_date(now: datetime | None = None) -> date:
    effective = _aware_utc(now or _now()).astimezone(BEIJING_TIMEZONE)
    return effective.date() - timedelta(days=1)


def _low_confidence_fields(values: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key, value in (values or {}).items()
        if isinstance(value, (int, float)) and float(value) < LOW_CONFIDENCE_THRESHOLD
    )


def draft_out(draft: DietaryDraft, *, cache_reused: bool = False) -> dict[str, Any]:
    return {
        "draft_id": draft.id,
        "subject_user_id": int(draft.subject_user_id),
        "source_type": draft.source_type,
        "source_ref": draft.source_ref,
        "diet_date": draft.diet_date,
        "timezone": draft.timezone,
        "meal_type": draft.meal_type,
        "eaten_at": _aware_utc(draft.eaten_at),
        "food_items": draft.food_items or [],
        "portion_text": draft.portion_text,
        "structure": draft.structure or {},
        "estimated_nutrition": draft.estimated_nutrition or {},
        "field_confidences": {
            key: float(value) for key, value in (draft.field_confidences or {}).items()
        },
        "recognition_confidence": (
            float(draft.recognition_confidence)
            if draft.recognition_confidence is not None
            else None
        ),
        "recognition_status": draft.recognition_status,
        "recognition_cache_reused": cache_reused,
        "low_confidence_fields": _low_confidence_fields(draft.field_confidences or {}),
        "status": draft.status,
        "version": draft.version,
        "requires_user_confirmation": True,
        "formal_record_created": draft.status == "confirmed",
        "created_at": _aware_utc(draft.created_at),
        "updated_at": _aware_utc(draft.updated_at),
    }


def record_out(record: DietaryRecord) -> dict[str, Any]:
    return {
        "record_id": record.id,
        "source_draft_id": record.source_draft_id,
        "subject_user_id": int(record.subject_user_id),
        "diet_date": record.diet_date,
        "timezone": record.timezone,
        "meal_type": record.meal_type,
        "eaten_at": _aware_utc(record.eaten_at),
        "source_type": record.source_type,
        "source_ref": record.source_ref,
        "food_items": record.food_items or [],
        "portion_text": record.portion_text,
        "structure": record.structure or {},
        "estimated_nutrition": record.estimated_nutrition or {},
        "field_confidences": {
            key: float(value) for key, value in (record.field_confidences or {}).items()
        },
        "confidence": float(record.confidence)
        if record.confidence is not None
        else None,
        "status": record.status,
        "version": record.version,
        "trust_state": "user_confirmed",
        "confirmed_at": _aware_utc(record.confirmed_at),
        "created_at": _aware_utc(record.created_at),
        "updated_at": _aware_utc(record.updated_at),
    }


def summary_out(summary: DietaryDailySummary) -> dict[str, Any]:
    return {
        "summary_id": summary.id,
        "subject_user_id": int(summary.subject_user_id),
        "diet_date": summary.diet_date,
        "close_method": summary.close_method,
        "record_complete": summary.record_complete,
        "confirmed_meal_count": summary.confirmed_meal_count,
        "pending_count": summary.pending_count,
        "structure_summary": summary.structure_summary or {},
        "conclusion": summary.conclusion,
        "today_suggestion": summary.today_suggestion,
        "confidence": float(summary.confidence),
        "evidence": summary.evidence or {},
        "rule_version": summary.rule_version,
        "template_version": summary.template_version,
        "record_version": summary.record_version,
        "recalculated_after_edit": summary.recalculated_after_edit,
        "generated_at": _aware_utc(summary.generated_at),
    }


def _get_day(
    db: Session, *, user_id: int, subject_user_id: int, diet_date: date
) -> DietaryDay | None:
    return db.scalar(
        select(DietaryDay).where(
            DietaryDay.user_id == user_id,
            DietaryDay.subject_user_id == subject_user_id,
            DietaryDay.diet_date == diet_date,
        )
    )


def _ensure_day(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    diet_date: date,
    timezone_name: str,
) -> DietaryDay:
    _timezone(timezone_name)
    day = _get_day(
        db, user_id=user_id, subject_user_id=subject_user_id, diet_date=diet_date
    )
    if day is not None:
        return day
    day = DietaryDay(
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=diet_date,
        timezone=timezone_name,
        auto_close_due_at=dietary_day_auto_close_at(diet_date, timezone_name),
        state="open",
        record_version=0,
        record_complete=False,
        confirmed_meal_count=0,
        pending_count=0,
        structure_summary={},
    )
    db.add(day)
    db.flush()
    return day


def _active_records(
    db: Session, *, user_id: int, subject_user_id: int, diet_date: date
) -> list[DietaryRecord]:
    return list(
        db.scalars(
            select(DietaryRecord)
            .where(
                DietaryRecord.user_id == user_id,
                DietaryRecord.subject_user_id == subject_user_id,
                DietaryRecord.diet_date == diet_date,
                DietaryRecord.status != "deleted",
            )
            .order_by(DietaryRecord.eaten_at.asc(), DietaryRecord.id.asc())
        ).all()
    )


def _pending_drafts(
    db: Session, *, user_id: int, subject_user_id: int, diet_date: date
) -> list[DietaryDraft]:
    return list(
        db.scalars(
            select(DietaryDraft)
            .where(
                DietaryDraft.user_id == user_id,
                DietaryDraft.subject_user_id == subject_user_id,
                DietaryDraft.diet_date == diet_date,
                DietaryDraft.status == "pending_confirmation",
            )
            .order_by(DietaryDraft.created_at.asc(), DietaryDraft.id.asc())
        ).all()
    )


def _structure_for(records: list[DietaryRecord]) -> dict[str, str]:
    if not records:
        return {"protein": "unknown", "vegetables": "unknown", "staple": "unknown"}
    threshold = max(1, math.ceil(len(records) / 2))
    output: dict[str, str] = {}
    for key in ("protein", "vegetables", "staple"):
        present = sum(
            1
            for record in records
            if (record.structure or {}).get(key)
            in {"present", "adequate", "balanced", True}
        )
        output[key] = "adequate" if present >= threshold else "low"
    return output


def _refresh_day_counts(
    db: Session, day: DietaryDay
) -> tuple[list[DietaryRecord], list[DietaryDraft]]:
    records = _active_records(
        db,
        user_id=int(day.user_id),
        subject_user_id=int(day.subject_user_id),
        diet_date=day.diet_date,
    )
    pending = _pending_drafts(
        db,
        user_id=int(day.user_id),
        subject_user_id=int(day.subject_user_id),
        diet_date=day.diet_date,
    )
    day.confirmed_meal_count = len({record.meal_type for record in records})
    day.pending_count = len(pending)
    day.structure_summary = _structure_for(records)
    return records, pending


def _mark_day_changed(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    diet_date: date,
    timezone_name: str,
) -> DietaryDay:
    day = _ensure_day(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=diet_date,
        timezone_name=timezone_name,
    )
    day.timezone = timezone_name
    day.auto_close_due_at = dietary_day_auto_close_at(diet_date, timezone_name)
    day.record_version += 1
    day.state = "stale" if day.closed_at is not None else "open"
    _refresh_day_counts(db, day)
    db.add(day)
    return day


def create_draft(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    payload: DietaryDraftCreateIn,
    image_fingerprint: str | None = None,
    recognition_version: str | None = None,
    recognition_status: str = "not_required",
    cache_reused: bool = False,
    input_snapshot_extra: dict[str, Any] | None = None,
    recognition_hook: Callable[[DietaryDraftCreateIn], dict[str, Any]] | None = None,
    event_scope: str = "create",
) -> dict[str, Any]:
    if event_scope not in {"create", "photo", "reuse"}:
        raise ValueError("Unsupported dietary draft event scope")
    resolved_date = derive_diet_date(
        payload.eaten_at, payload.timezone, payload.diet_date
    )
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical["subject_user_id"] = subject_user_id
    canonical["diet_date"] = resolved_date.isoformat()
    canonical["image_fingerprint"] = image_fingerprint
    canonical["recognition_version"] = recognition_version
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    existing = db.scalar(
        select(DietaryDraft)
        .where(
            DietaryDraft.user_id == user_id,
            DietaryDraft.subject_user_id == subject_user_id,
            DietaryDraft.event_scope == event_scope,
            DietaryDraft.client_event_id == payload.client_event_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        replay_cache_reused = bool(
            (existing.input_snapshot or {}).get("recognition_cache_reused", False)
        )
        return draft_out(existing, cache_reused=replay_cache_reused)

    effective_payload = payload
    effective_recognition_version = recognition_version
    effective_recognition_status = recognition_status
    snapshot_extra = dict(input_snapshot_extra or {})
    if recognition_hook is not None:
        try:
            recognized = recognition_hook(payload)
            if not isinstance(recognized, dict):
                raise TypeError("Dietary recognition hook must return a dictionary")
            recognized_fields = {
                name: recognized.get(name)
                for name in _DRAFT_RECOGNITION_FIELDS
                if name in recognized
            }
            effective_payload = DietaryDraftCreateIn.model_validate(
                {
                    **payload.model_dump(mode="python", exclude_none=False),
                    **recognized_fields,
                }
            )
            hook_recognition_status = recognized.get(
                "recognition_status",
                "completed"
                if effective_payload.food_items
                else "recognition_incomplete",
            )
            if hook_recognition_status not in _HOOK_RECOGNITION_STATUSES:
                raise ValueError("Dietary recognition status is invalid")
            effective_recognition_status = hook_recognition_status
            snapshot_extra["recognition_last_error"] = recognized.get(
                "recognition_error"
            )
            hook_recognition_version = recognized.get("recognition_version")
            if hook_recognition_version is not None:
                if (
                    not isinstance(hook_recognition_version, str)
                    or not 1 <= len(hook_recognition_version) <= 80
                    or re.fullmatch(r"[A-Za-z0-9._:-]+", hook_recognition_version)
                    is None
                ):
                    raise ValueError("Dietary recognition version is invalid")
                effective_recognition_version = hook_recognition_version
        except Exception as exc:
            effective_payload = DietaryDraftCreateIn.model_validate(
                {
                    **payload.model_dump(mode="python", exclude_none=False),
                    "food_items": [],
                    "portion_text": None,
                    "structure": {},
                    "estimated_nutrition": {},
                    "field_confidences": {},
                    "recognition_confidence": None,
                }
            )
            effective_recognition_status = "failed_manual_entry_available"
            snapshot_extra["recognition_last_error"] = type(exc).__name__

    input_snapshot = {
        "source_type": effective_payload.source_type,
        "source_ref": effective_payload.source_ref,
        "image_fingerprint": image_fingerprint,
        "recognition_version": effective_recognition_version,
        "raw_input_preserved": effective_payload.raw_input is not None,
        "recognition_cache_reused": cache_reused,
    }
    input_snapshot.update(_jsonable(snapshot_extra))
    draft = DietaryDraft(
        user_id=user_id,
        subject_user_id=subject_user_id,
        event_scope=event_scope,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        source_type=effective_payload.source_type,
        source_ref=effective_payload.source_ref,
        image_fingerprint=image_fingerprint,
        recognition_version=effective_recognition_version,
        recognition_status=effective_recognition_status,
        timezone=effective_payload.timezone,
        diet_date=resolved_date,
        meal_type=effective_payload.meal_type,
        eaten_at=_aware_utc(effective_payload.eaten_at),
        raw_input=effective_payload.raw_input,
        input_snapshot=input_snapshot,
        food_items=[
            item.model_dump(mode="json") for item in effective_payload.food_items
        ],
        portion_text=effective_payload.portion_text,
        structure=effective_payload.structure,
        estimated_nutrition=effective_payload.estimated_nutrition,
        field_confidences=effective_payload.field_confidences,
        recognition_confidence=effective_payload.recognition_confidence,
        status="pending_confirmation",
        version=1,
    )
    db.add(draft)
    db.flush()
    db.refresh(draft)
    _mark_day_changed(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=resolved_date,
        timezone_name=effective_payload.timezone,
    )
    return draft_out(draft, cache_reused=cache_reused)


def confirm_draft(
    db: Session,
    *,
    draft_id: int,
    user_id: int,
    subject_user_id: int,
    payload: DietaryDraftConfirmIn,
) -> dict[str, Any]:
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical.update({"subject_user_id": subject_user_id, "draft_id": draft_id})
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    replay = db.scalar(
        select(DietaryRecord).where(
            DietaryRecord.user_id == user_id,
            DietaryRecord.subject_user_id == subject_user_id,
            DietaryRecord.confirmation_client_event_id == payload.client_event_id,
        )
    )
    if replay is not None:
        if replay.confirmation_request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        return record_out(replay)

    draft = db.scalar(
        select(DietaryDraft)
        .where(
            DietaryDraft.id == draft_id,
            DietaryDraft.user_id == user_id,
            DietaryDraft.subject_user_id == subject_user_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Dietary draft not found")
    replay = db.scalar(
        select(DietaryRecord).where(
            DietaryRecord.user_id == user_id,
            DietaryRecord.subject_user_id == subject_user_id,
            DietaryRecord.confirmation_client_event_id == payload.client_event_id,
        )
    )
    if replay is not None:
        if replay.confirmation_request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        return record_out(replay)
    if draft.status != "pending_confirmation":
        raise HTTPException(status_code=409, detail="Dietary draft is not pending")
    if draft.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Dietary draft version conflict")
    _timezone(payload.timezone)

    record = DietaryRecord(
        source_draft_id=draft.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        confirmation_client_event_id=payload.client_event_id,
        confirmation_request_fingerprint=request_fingerprint,
        diet_date=payload.diet_date,
        timezone=payload.timezone,
        meal_type=payload.meal_type,
        eaten_at=_aware_utc(payload.eaten_at),
        source_type=draft.source_type,
        source_ref=draft.source_ref or f"draft:{draft.id}",
        source_snapshot={
            "draft_id": draft.id,
            "draft_version": draft.version,
            "image_fingerprint": draft.image_fingerprint,
            "recognition_version": draft.recognition_version,
            "original_source_type": draft.source_type,
        },
        food_items=[item.model_dump(mode="json") for item in payload.food_items],
        portion_text=payload.portion_text,
        structure=payload.structure,
        estimated_nutrition=payload.estimated_nutrition,
        field_confidences=payload.field_confidences,
        confidence=payload.recognition_confidence,
        status="user_confirmed",
        version=1,
        confirmed_by_user_id=user_id,
        confirmed_at=_now(),
    )
    db.add(record)
    db.flush()
    db.refresh(record)
    draft.status = "confirmed"
    draft.version += 1
    db.add(draft)
    db.flush()
    result = record_out(record)
    db.add(
        DietaryRecordEvent(
            record_id=record.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="confirm",
            target_version=record.version,
            before_snapshot={
                "draft_id": draft.id,
                "draft_version": payload.expected_version,
            },
            after_snapshot=_jsonable(result),
        )
    )
    if draft.diet_date != payload.diet_date:
        old_day = _mark_day_changed(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=draft.diet_date,
            timezone_name=draft.timezone,
        )
        _recalculate_if_stale(db, old_day)
    new_day = _mark_day_changed(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=payload.diet_date,
        timezone_name=payload.timezone,
    )
    _recalculate_if_stale(db, new_day)
    db.flush()
    return result


def _scoped_record(
    db: Session,
    *,
    record_id: int,
    user_id: int,
    subject_user_id: int,
    for_update: bool = False,
) -> DietaryRecord:
    statement = select(DietaryRecord).where(
        DietaryRecord.id == record_id,
        DietaryRecord.user_id == user_id,
        DietaryRecord.subject_user_id == subject_user_id,
    )
    if for_update:
        statement = statement.execution_options(
            populate_existing=True
        ).with_for_update()
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(status_code=404, detail="Dietary record not found")
    return record


def _event_replay(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
    request_fingerprint: str,
    event_type: str,
) -> dict[str, Any] | None:
    event = db.scalar(
        select(DietaryRecordEvent).where(
            DietaryRecordEvent.user_id == user_id,
            DietaryRecordEvent.subject_user_id == subject_user_id,
            DietaryRecordEvent.event_type == event_type,
            DietaryRecordEvent.client_event_id == client_event_id,
        )
    )
    if event is None:
        return None
    if (
        event.request_fingerprint != request_fingerprint
        or event.event_type != event_type
    ):
        raise HTTPException(status_code=409, detail="client_event_id payload conflict")
    return event.after_snapshot


def update_record(
    db: Session,
    *,
    record_id: int,
    user_id: int,
    subject_user_id: int,
    payload: DietaryRecordUpdateIn,
) -> dict[str, Any]:
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical.update({"subject_user_id": subject_user_id, "record_id": record_id})
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="update",
    )
    if replay is not None:
        return replay
    record = _scoped_record(
        db,
        record_id=record_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        for_update=True,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="update",
    )
    if replay is not None:
        return replay
    if record.status == "deleted":
        raise HTTPException(status_code=409, detail="Dietary record is deleted")
    if record.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Dietary record version conflict")
    before = record_out(record)
    old_date = record.diet_date
    old_timezone = record.timezone
    fields = payload.model_fields_set
    for name in (
        "timezone",
        "diet_date",
        "meal_type",
        "eaten_at",
        "portion_text",
        "structure",
        "estimated_nutrition",
        "field_confidences",
    ):
        if name in fields:
            value = getattr(payload, name)
            if name == "timezone" and value is not None:
                _timezone(value)
            if name == "eaten_at" and value is not None:
                value = _aware_utc(value)
            setattr(record, name, value)
    if "food_items" in fields and payload.food_items is not None:
        record.food_items = [
            item.model_dump(mode="json") for item in payload.food_items
        ]
    if "recognition_confidence" in fields:
        record.confidence = payload.recognition_confidence
    record.status = "modified"
    record.version += 1
    db.add(record)
    db.flush()
    db.refresh(record)
    after = record_out(record)
    db.add(
        DietaryRecordEvent(
            record_id=record.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="update",
            target_version=record.version,
            before_snapshot=_jsonable(before),
            after_snapshot=_jsonable(after),
        )
    )
    old_day_timezone = old_timezone if record.diet_date != old_date else record.timezone
    _mark_day_changed(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=old_date,
        timezone_name=old_day_timezone,
    )
    if record.diet_date != old_date:
        _mark_day_changed(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=record.diet_date,
            timezone_name=record.timezone,
        )
    db.flush()
    return after


def delete_record(
    db: Session,
    *,
    record_id: int,
    user_id: int,
    subject_user_id: int,
    payload: DietaryRecordDeleteIn,
) -> dict[str, Any]:
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical.update({"subject_user_id": subject_user_id, "record_id": record_id})
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="delete",
    )
    if replay is not None:
        return replay
    record = _scoped_record(
        db,
        record_id=record_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        for_update=True,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="delete",
    )
    if replay is not None:
        return replay
    if record.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Dietary record version conflict")
    if record.status == "deleted":
        raise HTTPException(status_code=409, detail="Dietary record is already deleted")
    before = record_out(record)
    record.status = "deleted"
    record.version += 1
    db.add(record)
    db.flush()
    db.refresh(record)
    after = record_out(record)
    db.add(
        DietaryRecordEvent(
            record_id=record.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="delete",
            target_version=record.version,
            before_snapshot=_jsonable(before),
            after_snapshot=_jsonable(after),
        )
    )
    _mark_day_changed(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=record.diet_date,
        timezone_name=record.timezone,
    )
    db.flush()
    return after


def reuse_record(
    db: Session,
    *,
    record_id: int,
    user_id: int,
    subject_user_id: int,
    payload: DietaryRecordReuseIn,
) -> dict[str, Any]:
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical.update({"subject_user_id": subject_user_id, "record_id": record_id})
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="reuse",
    )
    if replay is not None:
        return replay
    record = _scoped_record(
        db,
        record_id=record_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        for_update=True,
    )
    replay = _event_replay(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        request_fingerprint=request_fingerprint,
        event_type="reuse",
    )
    if replay is not None:
        return replay
    if record.status == "deleted":
        raise HTTPException(
            status_code=409, detail="Deleted dietary record cannot be reused"
        )
    if record.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Dietary record version conflict")
    draft_payload = DietaryDraftCreateIn(
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
        source_type="recent",
        source_ref=f"dietary_record:{record.id}:v{record.version}",
        timezone=payload.timezone,
        diet_date=payload.diet_date,
        meal_type=payload.meal_type,
        eaten_at=payload.eaten_at,
        food_items=record.food_items or [],
        portion_text=record.portion_text,
        structure=record.structure or {},
        estimated_nutrition=record.estimated_nutrition or {},
        field_confidences=record.field_confidences or {},
        recognition_confidence=(
            float(record.confidence) if record.confidence is not None else None
        ),
    )
    result = create_draft(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        payload=draft_payload,
        recognition_status="reused_user_confirmed_record",
        event_scope="reuse",
    )
    db.add(
        DietaryRecordEvent(
            record_id=record.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            actor_user_id=user_id,
            client_event_id=payload.client_event_id,
            request_fingerprint=request_fingerprint,
            event_type="reuse",
            target_version=record.version,
            before_snapshot=_jsonable(record_out(record)),
            after_snapshot=_jsonable(result),
        )
    )
    db.flush()
    return result


def _summary_for_day_version(
    db: Session, day: DietaryDay
) -> DietaryDailySummary | None:
    return db.scalar(
        select(DietaryDailySummary).where(
            DietaryDailySummary.user_id == day.user_id,
            DietaryDailySummary.subject_user_id == day.subject_user_id,
            DietaryDailySummary.diet_date == day.diet_date,
            DietaryDailySummary.record_version == day.record_version,
        )
    )


def discover_beijing_summary_candidates(
    db: Session,
    *,
    target_date: date,
    limit: int,
) -> list[tuple[int, int]]:
    """Return only tenants with active confirmed records on the target date."""

    rows = db.execute(
        select(DietaryRecord.user_id, DietaryRecord.subject_user_id)
        .where(
            DietaryRecord.diet_date == target_date,
            DietaryRecord.status != "deleted",
        )
        .distinct()
        .order_by(DietaryRecord.user_id, DietaryRecord.subject_user_id)
        .limit(max(1, min(limit, 500)))
    ).all()
    return [(int(user_id), int(subject_id)) for user_id, subject_id in rows]


def _daily_summary_model_payload(
    *,
    target_date: date,
    records: list[DietaryRecord],
) -> dict[str, Any]:
    return {
        "diet_date": target_date.isoformat(),
        "confirmed_meal_count": len({record.meal_type for record in records}),
        "meals": [
            {
                "meal_type": record.meal_type,
                "food_items": _jsonable(record.food_items or []),
                "portion_text": record.portion_text,
                "structure": _jsonable(record.structure or {}),
                "estimated_nutrition": _jsonable(record.estimated_nutrition or {}),
                "confidence": (
                    float(record.confidence)
                    if record.confidence is not None
                    else None
                ),
            }
            for record in records
        ],
    }


def prepare_daily_summary_attempt(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    target_date: date,
    now: datetime,
) -> dict[str, Any] | None:
    """Commit-ready rule fallback and immutable model input for one tenant."""

    effective_now = _aware_utc(now)
    day = db.scalar(
        select(DietaryDay)
        .where(
            DietaryDay.user_id == user_id,
            DietaryDay.subject_user_id == subject_user_id,
            DietaryDay.diet_date == target_date,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if day is None:
        return None
    records, pending = _refresh_day_counts(db, day)
    if not records:
        return None

    day.close_method = "automatic"
    day.close_client_event_id = (
        f"beijing-daily-summary:{target_date}:{RULE_VERSION}"
    )
    day.close_request_fingerprint = _fingerprint(
        {
            "user_id": user_id,
            "subject_user_id": subject_user_id,
            "target_date": target_date,
            "record_version": day.record_version,
        }
    )
    day.exclude_pending_on_close = True
    day.record_complete = True
    day.closed_at = day.closed_at or effective_now
    day.state = "ready"
    day.structure_summary = _structure_for(records)
    db.add(day)
    db.flush()

    model_payload = _daily_summary_model_payload(
        target_date=target_date,
        records=records,
    )
    model_input_fingerprint = _fingerprint(model_payload)
    summary = _summary_for_day_version(db, day)
    if summary is None:
        conclusion, suggestion = _template_for(day.structure_summary)
        if day.confirmed_meal_count == 1:
            conclusion = "昨天只确认了 1 餐，记录有限，无法完整代表全天饮食。"
            suggestion = "今天继续记录各餐，并尽量包含主食、蛋白质和蔬菜。"
        summary = DietaryDailySummary(
            day_id=day.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=target_date,
            record_version=day.record_version,
            close_method="automatic",
            record_complete=True,
            confirmed_meal_count=day.confirmed_meal_count,
            pending_count=len(pending),
            structure_summary=day.structure_summary,
            conclusion=conclusion,
            today_suggestion=suggestion,
            confidence=_summary_confidence(records, len(pending)),
            evidence={
                "included_record_ids": [record.id for record in records],
                "excluded_pending_draft_ids": [draft.id for draft in pending],
                "pending_records_excluded": bool(pending),
                "natural_language_generated_by_model": False,
                "generation_status": "fallback_retryable",
                "retry_attempt_count": 0,
                "next_retry_at": effective_now.isoformat(),
                "last_error_code": None,
                "model_input_fingerprint": model_input_fingerprint,
            },
            rule_version=RULE_VERSION,
            template_version=TEMPLATE_VERSION,
            recalculated_after_edit=False,
            generated_at=effective_now,
        )
        db.add(summary)
        db.flush()
        db.refresh(summary)

    return {
        "summary": summary_out(summary),
        "record_version": int(day.record_version),
        "model_input_fingerprint": model_input_fingerprint,
        "model_payload": model_payload,
    }


def finalize_daily_summary(
    db: Session,
    *,
    summary_id: int,
    expected_record_version: int,
    expected_input_fingerprint: str,
    result: DailyDietSummaryResult,
    now: datetime,
) -> bool:
    """Write an AI result only while the exact fallback evidence is current."""

    summary = db.scalar(
        select(DietaryDailySummary)
        .where(DietaryDailySummary.id == summary_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if summary is None or summary.record_version != expected_record_version:
        return False
    day = db.scalar(
        select(DietaryDay)
        .where(DietaryDay.id == summary.day_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    evidence = dict(summary.evidence or {})
    if (
        day is None
        or day.record_version != expected_record_version
        or evidence.get("model_input_fingerprint") != expected_input_fingerprint
        or evidence.get("generation_status") != "fallback_retryable"
    ):
        return False

    summary.conclusion = result.conclusion
    summary.today_suggestion = result.today_suggestion
    summary.confidence = result.confidence
    summary.generated_at = _aware_utc(now)
    summary.evidence = {
        **evidence,
        "balance_assessment": result.balance_assessment,
        "generation_status": "ai_completed",
        "natural_language_generated_by_model": True,
        "retry_attempt_count": int(evidence.get("retry_attempt_count") or 0),
        "next_retry_at": None,
        "last_error_code": None,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
    db.add(summary)
    return True


def record_daily_summary_failure(
    db: Session,
    *,
    summary_id: int,
    expected_record_version: int,
    expected_input_fingerprint: str,
    error_code: str,
    now: datetime,
    increment_retry_attempt: bool,
) -> str:
    """Persist bounded retry metadata without storing provider error text."""

    summary = db.scalar(
        select(DietaryDailySummary)
        .where(DietaryDailySummary.id == summary_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if summary is None or summary.record_version != expected_record_version:
        return "stale"
    day = db.scalar(
        select(DietaryDay)
        .where(DietaryDay.id == summary.day_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    evidence = dict(summary.evidence or {})
    if (
        day is None
        or day.record_version != expected_record_version
        or evidence.get("model_input_fingerprint") != expected_input_fingerprint
        or evidence.get("generation_status") != "fallback_retryable"
    ):
        return "stale"

    retry_count = int(evidence.get("retry_attempt_count") or 0)
    if increment_retry_attempt:
        retry_count += 1
    if retry_count >= len(SUMMARY_RETRY_DELAYS):
        generation_status = "fallback_exhausted"
        next_retry_at = None
    else:
        generation_status = "fallback_retryable"
        next_retry_at = (
            _aware_utc(now) + SUMMARY_RETRY_DELAYS[retry_count]
        ).isoformat()
    normalized_error = (
        error_code
        if error_code
        in {"provider_timeout", "provider_invalid_output", "provider_error"}
        else "provider_error"
    )
    summary.evidence = {
        **evidence,
        "generation_status": generation_status,
        "retry_attempt_count": retry_count,
        "next_retry_at": next_retry_at,
        "last_error_code": normalized_error,
    }
    db.add(summary)
    return generation_status


def discover_due_summary_retry_ids(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> list[int]:
    """Return due fallback summary IDs using portable JSON inspection."""

    effective_now = _aware_utc(now)
    bounded_limit = max(1, min(limit, 500))
    summaries = db.scalars(
        select(DietaryDailySummary)
        .order_by(
            DietaryDailySummary.generated_at.asc(),
            DietaryDailySummary.id.asc(),
        )
        .limit(5000)
    ).all()
    due: list[int] = []
    for summary in summaries:
        evidence = summary.evidence or {}
        if evidence.get("generation_status") != "fallback_retryable":
            continue
        raw_next_retry_at = evidence.get("next_retry_at")
        if not isinstance(raw_next_retry_at, str):
            continue
        try:
            next_retry_at = _aware_utc(
                datetime.fromisoformat(raw_next_retry_at.replace("Z", "+00:00"))
            )
        except ValueError:
            continue
        if next_retry_at <= effective_now:
            due.append(int(summary.id))
            if len(due) >= bounded_limit:
                break
    return due


def prepare_daily_summary_retry(
    db: Session,
    *,
    summary_id: int,
    now: datetime,
) -> dict[str, Any] | None:
    """Rebuild the exact current payload for one due fallback summary."""

    effective_now = _aware_utc(now)
    summary = db.get(DietaryDailySummary, summary_id)
    if summary is None:
        return None
    evidence = summary.evidence or {}
    if evidence.get("generation_status") != "fallback_retryable":
        return None
    raw_next_retry_at = evidence.get("next_retry_at")
    if not isinstance(raw_next_retry_at, str):
        return None
    try:
        next_retry_at = _aware_utc(
            datetime.fromisoformat(raw_next_retry_at.replace("Z", "+00:00"))
        )
    except ValueError:
        return None
    if next_retry_at > effective_now:
        return None

    prepared = prepare_daily_summary_attempt(
        db,
        user_id=int(summary.user_id),
        subject_user_id=int(summary.subject_user_id),
        target_date=summary.diet_date,
        now=effective_now,
    )
    if (
        prepared is None
        or int(prepared["summary"]["summary_id"]) != int(summary_id)
        or prepared["model_input_fingerprint"]
        != evidence.get("model_input_fingerprint")
    ):
        return None
    return prepared


def daily_summary_status(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the authenticated tenant's Beijing-yesterday summary state."""

    target_date = beijing_target_date(now)
    tenant_filters = (
        DietaryRecord.user_id == user_id,
        DietaryRecord.subject_user_id == subject_user_id,
        DietaryRecord.status != "deleted",
    )
    any_record_id = db.scalar(
        select(DietaryRecord.id).where(*tenant_filters).limit(1)
    )
    if any_record_id is None:
        return {
            "status": "never_recorded",
            "target_date": target_date,
            "message": NEVER_RECORDED_MESSAGE,
            "summary": None,
        }

    yesterday_record_id = db.scalar(
        select(DietaryRecord.id)
        .where(*tenant_filters, DietaryRecord.diet_date == target_date)
        .limit(1)
    )
    if yesterday_record_id is None:
        return {
            "status": "no_yesterday_records",
            "target_date": target_date,
            "message": NO_YESTERDAY_RECORDS_MESSAGE,
            "summary": None,
        }

    day = _get_day(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=target_date,
    )
    summary = _summary_for_day_version(db, day) if day is not None else None
    if summary is None:
        return {
            "status": "processing",
            "target_date": target_date,
            "message": None,
            "summary": None,
        }

    generation_status = str(
        (summary.evidence or {}).get("generation_status")
        or "fallback_retryable"
    )
    return {
        "status": "available",
        "target_date": target_date,
        "message": None,
        "summary": {
            "conclusion": summary.conclusion,
            "today_suggestion": summary.today_suggestion,
            "confirmed_meal_count": summary.confirmed_meal_count,
            "confidence": float(summary.confidence),
            "generation_source": (
                "ai" if generation_status == "ai_completed" else "rule_fallback"
            ),
            "retry_pending": generation_status == "fallback_retryable",
            "generated_at": _aware_utc(summary.generated_at),
        },
    }


def _template_for(structure: dict[str, str]) -> tuple[str, str]:
    phrases = []
    if structure.get("protein") == "low":
        phrases.append("蛋白质偏少")
    elif structure.get("protein") == "adequate":
        phrases.append("蛋白质来源较充足")
    if structure.get("vegetables") == "low":
        phrases.append("蔬菜记录偏少")
    elif structure.get("vegetables") == "adequate":
        phrases.append("蔬菜较充足")
    if structure.get("staple") == "low":
        phrases.append("主食记录偏少")
    elif structure.get("staple") == "adequate":
        phrases.append("主食结构较均衡")
    conclusion = "，".join(phrases) + "。" if phrases else "已形成本日饮食结构记录。"
    if structure.get("protein") == "low":
        suggestion = "今天午餐或晚餐可以增加一份鱼、肉、蛋或豆制品。"
    elif structure.get("vegetables") == "low":
        suggestion = "今天可以在一餐中增加一份蔬菜。"
    else:
        suggestion = "今天继续按自己的节奏记录餐食即可。"
    return conclusion, suggestion


def _summary_confidence(records: list[DietaryRecord], pending_count: int) -> float:
    values = [
        float(record.confidence) for record in records if record.confidence is not None
    ]
    base = sum(values) / len(values) if values else 0.75
    if pending_count:
        base *= 0.8
    return round(max(0.30, min(0.95, base)), 4)


def day_out(db: Session, day: DietaryDay) -> dict[str, Any]:
    summary = _summary_for_day_version(db, day) if day.state == "ready" else None
    return {
        "subject_user_id": int(day.subject_user_id),
        "diet_date": day.diet_date,
        "state": day.state,
        "record_version": day.record_version,
        "close_method": day.close_method,
        "record_complete": day.record_complete,
        "confirmed_meal_count": day.confirmed_meal_count,
        "pending_count": day.pending_count,
        "summary": summary_out(summary) if summary is not None else None,
    }


def complete_day(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    diet_date: date,
    timezone_name: str,
    method: str,
    client_event_id: str,
    complete_with_confirmed_only: bool,
) -> dict[str, Any]:
    """Close one dietary day using fixed rules and fixed text templates only."""

    if method not in {"automatic", "manual"}:
        raise HTTPException(status_code=422, detail="Unsupported completion method")
    _timezone(timezone_name)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=client_event_id,
    )
    day = db.scalar(
        select(DietaryDay)
        .where(
            DietaryDay.user_id == user_id,
            DietaryDay.subject_user_id == subject_user_id,
            DietaryDay.diet_date == diet_date,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if day is None:
        day = _ensure_day(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=diet_date,
            timezone_name=timezone_name,
        )
    close_fingerprint = _fingerprint(
        {
            "subject_user_id": subject_user_id,
            "diet_date": diet_date,
            "timezone": timezone_name,
            "method": method,
            "complete_with_confirmed_only": complete_with_confirmed_only,
        }
    )
    if day.close_client_event_id == client_event_id:
        if day.close_request_fingerprint != close_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        if day.state != "stale":
            return day_out(db, day)
    if day.closed_at is not None and day.state == "ready":
        return day_out(db, day)

    was_stale = day.state == "stale"
    records, pending = _refresh_day_counts(db, day)
    day.timezone = timezone_name
    day.auto_close_due_at = dietary_day_auto_close_at(diet_date, timezone_name)
    day.close_method = method
    day.close_client_event_id = client_event_id
    day.close_request_fingerprint = close_fingerprint
    day.exclude_pending_on_close = complete_with_confirmed_only
    day.closed_at = day.closed_at or _now()
    day.record_complete = False

    if pending and not complete_with_confirmed_only:
        day.state = "waiting_confirmation"
        db.add(day)
        return day_out(db, day)

    minimum_meals = 2 if method == "automatic" else 1
    if day.confirmed_meal_count < minimum_meals:
        day.state = "incomplete"
        db.add(day)
        return day_out(db, day)

    day.state = "recalculating"
    day.structure_summary = _structure_for(records)
    db.add(day)
    db.flush()
    existing = _summary_for_day_version(db, day)
    if existing is None:
        conclusion, suggestion = _template_for(day.structure_summary)
        existing = DietaryDailySummary(
            day_id=day.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=diet_date,
            record_version=day.record_version,
            close_method=method,
            record_complete=True,
            confirmed_meal_count=day.confirmed_meal_count,
            pending_count=len(pending),
            structure_summary=day.structure_summary,
            conclusion=conclusion,
            today_suggestion=suggestion,
            confidence=_summary_confidence(records, len(pending)),
            evidence={
                "included_record_ids": [record.id for record in records],
                "excluded_pending_draft_ids": [draft.id for draft in pending],
                "pending_records_excluded": bool(pending),
                "natural_language_generated_by_model": False,
            },
            rule_version=RULE_VERSION,
            template_version=TEMPLATE_VERSION,
            recalculated_after_edit=was_stale,
            generated_at=_now(),
        )
        db.add(existing)
        db.flush()
        db.refresh(existing)
    day.state = "ready"
    day.record_complete = True
    db.add(day)
    output = day_out(db, day)
    output["summary"] = summary_out(existing)
    return output


def _recalculate_if_stale(db: Session, day: DietaryDay) -> DietaryDay:
    if day.state != "stale" or day.close_method is None:
        return day
    # Tests and production sessions intentionally disable autoflush.  Persist
    # the stale transition before the locking SELECT refreshes this identity.
    db.flush()
    complete_day(
        db,
        user_id=int(day.user_id),
        subject_user_id=int(day.subject_user_id),
        diet_date=day.diet_date,
        timezone_name=day.timezone,
        method=day.close_method,
        client_event_id=day.close_client_event_id or f"recalculate:{day.diet_date}",
        complete_with_confirmed_only=day.exclude_pending_on_close,
    )
    return day


def auto_complete_due_days(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    timezone_name: str,
    now: datetime | None = None,
) -> None:
    _timezone(timezone_name)
    effective_now = _aware_utc(now or _now())
    days = db.scalars(
        select(DietaryDay).where(
            DietaryDay.user_id == user_id,
            DietaryDay.subject_user_id == subject_user_id,
            DietaryDay.closed_at.is_(None),
            DietaryDay.auto_close_due_at <= effective_now,
        )
    ).all()
    for day in days:
        complete_day(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            diet_date=day.diet_date,
            timezone_name=day.timezone,
            method="automatic",
            client_event_id=f"auto-close:{day.id}:{day.diet_date}:{RULE_VERSION}",
            complete_with_confirmed_only=False,
        )


def discover_due_dietary_day_ids(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> list[int]:
    """Discover due work without claiming it; the claim is DB-authoritative."""

    effective_now = _aware_utc(now)
    bounded_limit = max(1, min(limit, 500))
    return [
        int(day_id)
        for day_id in db.scalars(
            select(DietaryDay.id)
            .where(
                DietaryDay.closed_at.is_(None),
                DietaryDay.auto_close_due_at <= effective_now,
            )
            .order_by(DietaryDay.auto_close_due_at.asc(), DietaryDay.id.asc())
            .limit(bounded_limit)
        ).all()
    ]


def auto_complete_due_day_by_id(
    db: Session,
    *,
    day_id: int,
    now: datetime,
) -> dict[str, Any] | None:
    """Claim and close one due day inside the caller's transaction.

    PostgreSQL ``SKIP LOCKED`` lets overlapping Beat deliveries divide work.
    The closed-at predicate makes a completed claim invisible to later scans.
    """

    effective_now = _aware_utc(now)
    day = db.scalar(
        select(DietaryDay)
        .where(
            DietaryDay.id == day_id,
            DietaryDay.closed_at.is_(None),
            DietaryDay.auto_close_due_at <= effective_now,
        )
        .execution_options(populate_existing=True)
        .with_for_update(skip_locked=True)
    )
    if day is None:
        return None
    # Re-evaluate from the persisted timezone so a corrupt or stale derived
    # timestamp can never close a day before its local 04:00 boundary.
    if derive_diet_date(effective_now, day.timezone) <= day.diet_date:
        return None
    return complete_day(
        db,
        user_id=int(day.user_id),
        subject_user_id=int(day.subject_user_id),
        diet_date=day.diet_date,
        timezone_name=day.timezone,
        method="automatic",
        client_event_id=f"auto-close:{day.id}:{day.diet_date}:{RULE_VERSION}",
        complete_with_confirmed_only=False,
    )


def _weekly_review(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    end_date: date,
) -> dict[str, Any]:
    start_date = end_date - timedelta(days=6)
    days = list(
        db.scalars(
            select(DietaryDay).where(
                DietaryDay.user_id == user_id,
                DietaryDay.subject_user_id == subject_user_id,
                DietaryDay.diet_date >= start_date,
                DietaryDay.diet_date <= end_date,
            )
        ).all()
    )
    summaries = list(
        db.scalars(
            select(DietaryDailySummary).where(
                DietaryDailySummary.user_id == user_id,
                DietaryDailySummary.subject_user_id == subject_user_id,
                DietaryDailySummary.diet_date >= start_date,
                DietaryDailySummary.diet_date <= end_date,
            )
        ).all()
    )
    latest_by_date: dict[date, DietaryDailySummary] = {}
    for summary in summaries:
        current = latest_by_date.get(summary.diet_date)
        if current is None or summary.record_version > current.record_version:
            latest_by_date[summary.diet_date] = summary
    return {
        "window_start": start_date,
        "window_end": end_date,
        "recorded_day_count": sum(day.confirmed_meal_count > 0 for day in days),
        "complete_day_count": sum(day.state == "ready" for day in days),
        "protein_low_days": sum(
            summary.structure_summary.get("protein") == "low"
            for summary in latest_by_date.values()
        ),
        "vegetables_adequate_days": sum(
            summary.structure_summary.get("vegetables") == "adequate"
            for summary in latest_by_date.values()
        ),
        "uses_score": False,
    }


def _streak_days(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    end_date: date,
) -> int:
    recorded_dates = set(
        db.scalars(
            select(DietaryDay.diet_date).where(
                DietaryDay.user_id == user_id,
                DietaryDay.subject_user_id == subject_user_id,
                DietaryDay.diet_date <= end_date,
                DietaryDay.confirmed_meal_count > 0,
            )
        ).all()
    )
    streak = 0
    cursor = end_date
    while cursor in recorded_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def dashboard(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    selected_date: date | None,
    timezone_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or _now()
    today = derive_diet_date(effective_now, timezone_name)
    chosen = selected_date or today
    day = _ensure_day(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=chosen,
        timezone_name=timezone_name,
    )
    _recalculate_if_stale(db, day)
    records, pending = _refresh_day_counts(db, day)
    selected_summary = (
        _summary_for_day_version(db, day) if day.state == "ready" else None
    )

    displayed_date = chosen - timedelta(days=1) if chosen == today else chosen
    displayed_day = _get_day(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        diet_date=displayed_date,
    )
    if displayed_day is not None:
        _recalculate_if_stale(db, displayed_day)
    displayed_summary = (
        _summary_for_day_version(db, displayed_day)
        if displayed_day is not None and displayed_day.state == "ready"
        else None
    )
    return {
        "subject_user_id": subject_user_id,
        "selected_date": chosen,
        "is_today": chosen == today,
        "recorded_meal_count": len(records),
        "pending_count": len(pending),
        "streak_days": _streak_days(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            end_date=chosen,
        ),
        "day_state": day.state,
        "records": [record_out(record) for record in records],
        "pending_drafts": [draft_out(draft) for draft in pending],
        "selected_day_summary": (
            summary_out(selected_summary) if selected_summary is not None else None
        ),
        "displayed_summary": (
            summary_out(displayed_summary) if displayed_summary is not None else None
        ),
        "displayed_summary_date": displayed_date,
        "weekly_review": _weekly_review(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            end_date=chosen,
        ),
    }


def recent_records(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    records = db.scalars(
        select(DietaryRecord)
        .where(
            DietaryRecord.user_id == user_id,
            DietaryRecord.subject_user_id == subject_user_id,
            DietaryRecord.status != "deleted",
        )
        .order_by(DietaryRecord.eaten_at.desc(), DietaryRecord.id.desc())
        .limit(limit)
    ).all()
    return [record_out(record) for record in records]


def recognize_image_bytes(content: bytes, filename: str) -> dict[str, Any]:
    """Recognize one image; callers cache the normalized result by byte digest."""

    from app.providers.factory import get_provider

    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}:
        suffix = ".jpg"
    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            path = handle.name
        result = get_provider().analyze_image(path)
    finally:
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    if not result.is_food or not result.items:
        raise ValueError("Image does not contain a recognizable meal")
    items = [
        {
            "item_id": f"vision-item-{index}",
            "name": item.name,
            "portion_text": item.portion_text or None,
            "categories": [],
            "confidence": float(result.confidence),
            "is_estimated": True,
        }
        for index, item in enumerate(result.items, start=1)
        if item.name
    ]
    kcal = max(0, int(result.total_kcal))
    margin = max(30, int(kcal * 0.15))
    return {
        "food_items": items,
        "structure": {},
        "estimated_nutrition": {
            "energy_kcal_range": [max(0, kcal - margin), kcal + margin],
            "is_estimate": True,
        },
        "field_confidences": {
            "food_items": float(result.confidence),
            "portion_text": float(result.confidence),
        },
        "recognition_confidence": float(result.confidence),
    }


def _safe_image_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    normalized = re.sub(r"[^\w.-]", "_", basename, flags=re.UNICODE)
    return normalized[:256] or "meal-image.jpg"


def persist_dietary_image_object(
    *,
    object_store: PrivateObjectStore,
    user_id: int,
    subject_user_id: int,
    content: bytes,
    filename: str,
    content_type: str,
) -> tuple[str, str, str, int]:
    """Persist a content-addressed, tenant-bound original image."""

    if not content:
        raise HTTPException(status_code=400, detail="Meal image is empty")
    if len(content) > MAX_PERSISTED_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Meal image exceeds 10 MB")
    digest = hashlib.sha256(content).hexdigest()
    original_filename = _safe_image_filename(filename)
    relative = (
        Path("dietary_records")
        / str(user_id)
        / str(subject_user_id)
        / digest[:2]
        / f"{digest}.bin"
    )
    metadata = StoredObjectMetadata(
        key=relative.as_posix(),
        sha256=digest,
        size_bytes=len(content),
        content_type=content_type,
        owner_user_id=user_id,
        subject_user_id=subject_user_id,
    )
    try:
        object_store.put(content=content, metadata=metadata)
    except ObjectStorageConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="Dietary image object storage is not configured"
        ) from exc
    except ObjectStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Dietary image object storage is unavailable"
        ) from exc
    except (ObjectStorageIntegrityError, ObjectStorageNotFoundError) as exc:
        raise HTTPException(
            status_code=409, detail="Dietary image object storage rejected the upload"
        ) from exc
    return digest, relative.as_posix(), original_filename, len(content)


def _read_dietary_image_object(
    draft: DietaryDraft,
    *,
    user_id: int,
    subject_user_id: int,
    object_store: PrivateObjectStore,
) -> tuple[bytes, str]:
    image_object = (draft.input_snapshot or {}).get("image_object")
    if not isinstance(image_object, dict):
        raise HTTPException(
            status_code=409, detail="Dietary image object is unavailable"
        )
    if (
        image_object.get("owner_user_id") != user_id
        or image_object.get("subject_user_id") != subject_user_id
    ):
        raise HTTPException(
            status_code=409, detail="Dietary image object binding mismatch"
        )
    object_key = image_object.get("image_object_key")
    original_filename = image_object.get("original_filename")
    storage_version = image_object.get("storage_version")
    if not isinstance(object_key, str) or not isinstance(original_filename, str):
        raise HTTPException(
            status_code=409, detail="Dietary image object metadata is invalid"
        )
    relative = Path(object_key)
    expected_prefix = ("dietary_records", str(user_id), str(subject_user_id))
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:3] != expected_prefix
    ):
        raise HTTPException(
            status_code=409, detail="Dietary image object key is invalid"
        )
    digest = image_object.get("sha256")
    if storage_version == 1:
        if (
            not isinstance(object_store, LocalPrivateObjectStore)
            or not isinstance(digest, str)
            or digest != draft.image_fingerprint
        ):
            raise HTTPException(
                status_code=409,
                detail="Legacy dietary image object is unavailable",
            )
        try:
            return (
                object_store.get_legacy(
                    key=object_key,
                    sha256=digest,
                    max_bytes=MAX_PERSISTED_IMAGE_BYTES,
                ),
                original_filename,
            )
        except ObjectStorageNotFoundError as exc:
            raise HTTPException(
                status_code=409, detail="Dietary image object is unavailable"
            ) from exc
        except ObjectStorageIntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="Dietary image object digest mismatch"
            ) from exc

    content_type = image_object.get("content_type")
    size_bytes = image_object.get("size_bytes")
    storage_backend = image_object.get("storage_backend")
    if (
        storage_version != 2
        or storage_backend != object_store.backend_name
        or not isinstance(content_type, str)
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or digest != draft.image_fingerprint
        or not isinstance(digest, str)
        or size_bytes <= 0
        or size_bytes > MAX_PERSISTED_IMAGE_BYTES
    ):
        raise HTTPException(
            status_code=409, detail="Dietary image object metadata is invalid"
        )
    metadata = StoredObjectMetadata(
        key=object_key,
        sha256=digest,
        size_bytes=size_bytes,
        content_type=content_type,
        owner_user_id=user_id,
        subject_user_id=subject_user_id,
    )
    try:
        content = object_store.get(
            metadata=metadata,
            max_bytes=MAX_PERSISTED_IMAGE_BYTES,
        )
    except ObjectStorageNotFoundError as exc:
        raise HTTPException(
            status_code=409, detail="Dietary image object is unavailable"
        ) from exc
    except ObjectStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Dietary image object storage is unavailable"
        ) from exc
    except (ObjectStorageConfigurationError, ObjectStorageIntegrityError) as exc:
        raise HTTPException(
            status_code=409, detail="Dietary image object digest mismatch"
        ) from exc
    return content, original_filename


def _recognize_dietary_image(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    content: bytes,
    filename: str,
) -> tuple[dict[str, Any], str, bool]:
    image_fingerprint = hashlib.sha256(content).hexdigest()
    cached = db.scalar(
        select(DietaryRecognitionCache).where(
            DietaryRecognitionCache.user_id == user_id,
            DietaryRecognitionCache.subject_user_id == subject_user_id,
            DietaryRecognitionCache.image_fingerprint == image_fingerprint,
            DietaryRecognitionCache.recognition_version == RECOGNITION_VERSION,
        )
    )
    cache_reused = cached is not None
    recognition_status = "completed"
    if cached is not None:
        result = dict(cached.result_snapshot or {})
        cached.last_used_at = _now()
        db.add(cached)
    else:
        try:
            result = recognize_image_bytes(content, filename)
        except Exception as exc:  # recognition failure must not discard the draft
            recognition_status = "failed_manual_entry_available"
            result = {
                "food_items": [],
                "structure": {},
                "estimated_nutrition": {},
                "field_confidences": {},
                "recognition_confidence": None,
                "recognition_error": type(exc).__name__,
            }
        else:
            cached = DietaryRecognitionCache(
                user_id=user_id,
                subject_user_id=subject_user_id,
                image_fingerprint=image_fingerprint,
                recognition_version=RECOGNITION_VERSION,
                result_snapshot=_jsonable(result),
                last_used_at=_now(),
            )
            db.add(cached)
            db.flush()
    return result, recognition_status, cache_reused


def create_photo_draft(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_event_id: str,
    content: bytes,
    filename: str,
    content_type: str,
    source_type: str,
    diet_date: date | None,
    meal_type: str | None,
    eaten_at: datetime,
    timezone_name: str,
    object_store: PrivateObjectStore,
) -> dict[str, Any]:
    image_fingerprint = hashlib.sha256(content).hexdigest()
    safe_filename = _safe_image_filename(filename)
    upload_fingerprint = _fingerprint(
        {
            "user_id": user_id,
            "subject_user_id": subject_user_id,
            "client_event_id": client_event_id,
            "image_fingerprint": image_fingerprint,
            "filename": safe_filename,
            "content_type": content_type,
            "source_type": source_type,
            "diet_date": diet_date,
            "meal_type": meal_type,
            "eaten_at": eaten_at,
            "timezone": timezone_name,
        }
    )
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=client_event_id,
    )
    existing = db.scalar(
        select(DietaryDraft)
        .where(
            DietaryDraft.user_id == user_id,
            DietaryDraft.subject_user_id == subject_user_id,
            DietaryDraft.event_scope == "photo",
            DietaryDraft.client_event_id == client_event_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if existing is not None:
        stored_fingerprint = (existing.input_snapshot or {}).get(
            "photo_upload_request_fingerprint"
        )
        if stored_fingerprint != upload_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        return draft_out(
            existing,
            cache_reused=bool(
                (existing.input_snapshot or {}).get("recognition_cache_reused", False)
            ),
        )

    (
        persisted_fingerprint,
        image_object_key,
        original_filename,
        size_bytes,
    ) = persist_dietary_image_object(
        object_store=object_store,
        user_id=user_id,
        subject_user_id=subject_user_id,
        content=content,
        filename=safe_filename,
        content_type=content_type,
    )
    if persisted_fingerprint != image_fingerprint:
        raise HTTPException(
            status_code=409, detail="Dietary image object digest mismatch"
        )

    result, recognition_status, cache_reused = _recognize_dietary_image(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        content=content,
        filename=original_filename,
    )
    payload = DietaryDraftCreateIn(
        subject_user_id=subject_user_id,
        client_event_id=client_event_id,
        source_type=source_type,
        source_ref=f"sha256:{image_fingerprint}",
        timezone=timezone_name,
        diet_date=diet_date,
        meal_type=meal_type,
        eaten_at=eaten_at,
        food_items=result.get("food_items") or [],
        structure=result.get("structure") or {},
        estimated_nutrition=result.get("estimated_nutrition") or {},
        field_confidences=result.get("field_confidences") or {},
        recognition_confidence=result.get("recognition_confidence"),
    )
    return create_draft(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        payload=payload,
        image_fingerprint=image_fingerprint,
        recognition_version=RECOGNITION_VERSION,
        recognition_status=recognition_status,
        cache_reused=cache_reused,
        input_snapshot_extra={
            "photo_upload_request_fingerprint": upload_fingerprint,
            "image_object": {
                "storage_version": 2,
                "storage_backend": object_store.backend_name,
                "owner_user_id": user_id,
                "subject_user_id": subject_user_id,
                "image_object_key": image_object_key,
                "original_filename": original_filename,
                "sha256": image_fingerprint,
                "size_bytes": size_bytes,
                "content_type": content_type,
            },
            "recognition_last_error": result.get("recognition_error"),
            "recognition_retry_receipts": {},
        },
        event_scope="photo",
    )


def retry_photo_draft_recognition(
    db: Session,
    *,
    draft_id: int,
    user_id: int,
    subject_user_id: int,
    payload: DietaryDraftRetryRecognitionIn,
    object_store: PrivateObjectStore,
) -> dict[str, Any]:
    canonical = payload.model_dump(mode="json", exclude_none=False)
    canonical.update(
        {
            "draft_id": draft_id,
            "user_id": user_id,
            "subject_user_id": subject_user_id,
        }
    )
    request_fingerprint = _fingerprint(canonical)
    _lock_dietary_client_event(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_event_id=payload.client_event_id,
    )
    draft = db.scalar(
        select(DietaryDraft)
        .where(
            DietaryDraft.id == draft_id,
            DietaryDraft.user_id == user_id,
            DietaryDraft.subject_user_id == subject_user_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Dietary draft not found")
    snapshot = dict(draft.input_snapshot or {})
    receipts = dict(snapshot.get("recognition_retry_receipts") or {})
    receipt = receipts.get(payload.client_event_id)
    if isinstance(receipt, dict):
        if receipt.get("request_fingerprint") != request_fingerprint:
            raise HTTPException(
                status_code=409, detail="client_event_id payload conflict"
            )
        result_snapshot = receipt.get("result")
        if not isinstance(result_snapshot, dict):
            raise HTTPException(
                status_code=409, detail="Recognition retry receipt is invalid"
            )
        return result_snapshot
    if draft.status != "pending_confirmation":
        raise HTTPException(status_code=409, detail="Dietary draft is not pending")
    if draft.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Dietary draft version conflict")
    if (
        draft.source_type not in {"camera", "photo_library"}
        or not draft.image_fingerprint
        or draft.recognition_status not in RETRYABLE_RECOGNITION_STATUSES
    ):
        raise HTTPException(
            status_code=409,
            detail="Dietary draft recognition is not retryable",
        )

    content, original_filename = _read_dietary_image_object(
        draft,
        user_id=user_id,
        subject_user_id=subject_user_id,
        object_store=object_store,
    )
    recognition, recognition_status, cache_reused = _recognize_dietary_image(
        db,
        user_id=user_id,
        subject_user_id=subject_user_id,
        content=content,
        filename=original_filename,
    )
    if recognition_status == "completed":
        draft.food_items = recognition.get("food_items") or []
        draft.structure = recognition.get("structure") or {}
        draft.estimated_nutrition = recognition.get("estimated_nutrition") or {}
        draft.field_confidences = recognition.get("field_confidences") or {}
        draft.recognition_confidence = recognition.get("recognition_confidence")
    snapshot["recognition_last_error"] = recognition.get("recognition_error")
    draft.input_snapshot = snapshot
    draft.recognition_status = recognition_status
    draft.version += 1
    db.add(draft)
    db.flush()
    db.refresh(draft)
    output = draft_out(draft, cache_reused=cache_reused)

    receipts[payload.client_event_id] = {
        "request_fingerprint": request_fingerprint,
        "result": _jsonable(output),
    }
    if len(receipts) > MAX_RECOGNITION_RETRY_RECEIPTS:
        oldest_keys = list(receipts)[: len(receipts) - MAX_RECOGNITION_RETRY_RECEIPTS]
        for key in oldest_keys:
            receipts.pop(key, None)
    snapshot["recognition_retry_receipts"] = receipts
    draft.input_snapshot = snapshot
    db.add(draft)
    db.flush()
    return output
