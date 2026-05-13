from __future__ import annotations

from datetime import datetime
import os
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import LLMAuditLog
from app.models.meal import Meal, MealPhoto, MealTsSource, PhotoStatus
from app.providers.base import MealVisionResult
from app.providers.factory import get_provider
from app.services.inference_service import infer_meal_time_from_glucose
from app.utils.hash import context_hash


def generate_object_key(user_id: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    return f"meals/{user_id}/{uuid.uuid4().hex}{ext}"


def build_mock_upload_url(object_key: str) -> str:
    return f"/api/meals/photo/mock-upload/{object_key}"


def ensure_local_storage_path(object_key: str) -> str:
    path = os.path.join(settings.LOCAL_STORAGE_DIR, object_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def create_photo_record(db: Session, user_id: str, object_key: str, exif_ts: datetime | None) -> MealPhoto:
    photo = MealPhoto(user_id=user_id, image_object_key=object_key, exif_ts=exif_ts)
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def process_photo_sync(db: Session, photo: MealPhoto) -> MealPhoto:
    provider = get_provider()
    # 直接传本地路径（provider 会读盘并转为 base64 data URL），避免依赖外网可达 S3。
    image_url = ensure_local_storage_path(photo.image_object_key)
    t0 = time.perf_counter()
    result = provider.analyze_image(image_url)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Record audit for vision call
    audit = LLMAuditLog(
        user_id=int(photo.user_id),
        provider=provider.provider_name,
        model=provider.vision_model,
        feature="meal_vision",
        latency_ms=latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        context_hash=context_hash({"image_key": photo.image_object_key}),
        meta={"photo_id": photo.id, "total_kcal": result.total_kcal},
    )
    db.add(audit)

    # 先尝试推断餐点时间，再写入 vision 结果。这样即便 inference 失败也不会
    # 触发 db.rollback() 把 photo.vision_json 在 SQLAlchemy 会话中回滚成空。
    inferred_ts: datetime | None = None
    inferred_conf: float | None = None
    try:
        inferred_ts, inferred_conf = infer_meal_time_from_glucose(
            db, str(photo.user_id), photo.uploaded_at
        )
    except Exception:  # noqa: BLE001
        db.rollback()
        # rollback 把 audit 也丢了，重新 add
        db.add(audit)
        inferred_ts = None
        inferred_conf = None

    _update_photo_from_vision(photo, result)
    if inferred_ts is not None:
        photo.vision_json = {
            **(photo.vision_json or {}),
            "inferred_meal_ts": inferred_ts.isoformat(),
            "inferred_confidence": inferred_conf,
        }

    db.add(photo)

    # 识别为食物 → 自动写入一条 meals 记录，UI 直接展示。
    if result.is_food and result.total_kcal > 0 and result.items:
        first = result.items[0]
        meal_ts = inferred_ts or photo.uploaded_at or datetime.utcnow()
        meal_ts_source = (
            MealTsSource.inferred_from_glucose if inferred_ts else MealTsSource.uploaded_at
        )
        meal = Meal(
            user_id=int(photo.user_id),
            meal_ts=meal_ts,
            meal_ts_source=meal_ts_source,
            kcal=int(result.total_kcal),
            tags=[first.name] if first.name else [],
            notes=None,
            photo_id=photo.id,
        )
        db.add(meal)

    db.commit()
    db.refresh(photo)
    return photo


def _update_photo_from_vision(photo: MealPhoto, result: MealVisionResult) -> None:
    # \u975e\u98df\u7269\u6216\u9519\u8bef\u4e00\u5f8b\u6807\u8bb0\u4e3a failed\uff0c\u907f\u514d\u524d\u7aef\u663e\u793a "\u5904\u7406\u4e2d"\u3002
    photo.status = PhotoStatus.processed if result.is_food else PhotoStatus.failed
    photo.vision_json = result.model_dump()
    photo.calorie_estimate_kcal = result.total_kcal if result.is_food else None
    photo.confidence = result.confidence if result.is_food else None
