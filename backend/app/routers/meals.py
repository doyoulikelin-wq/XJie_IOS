from datetime import datetime
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.meal import Meal, MealPhoto, MealTsSource
from app.schemas.meal import (
    MealCreate,
    MealOut,
    MealPhotoOut,
    MealUpdate,
    PhotoCompleteRequest,
    PresignRequest,
    PresignResponse,
)
from app.services.meal_service import (
    build_mock_upload_url,
    create_photo_record,
    ensure_local_storage_path,
    generate_object_key,
    process_photo_sync,
)
from app.workers.tasks import process_meal_photo

router = APIRouter()


@router.post("/photo/upload-url", response_model=PresignResponse)
def meal_photo_upload_url(
    payload: PresignRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    功能：生成餐食照片上传所需的“预签名 URL”（当前为 Mock 实现），
          客户端拿到该 URL 后即可将本地图片直传到对象存储。
    入参：
        - payload (PresignRequest): 请求体，包含 filename 等信息（原始文件名）。
        - user_id (str): 从依赖 get_current_user_id 中解析出的当前登录用户 ID。
    返回：
        PresignResponse：包含 upload_url（上传地址）、object_key（对象存储中的唯一键）、
                         expires_in（URL 有效期，秒）。
    """
    object_key = generate_object_key(user_id, payload.filename)
    return PresignResponse(upload_url=build_mock_upload_url(object_key), object_key=object_key, expires_in=900)


@router.put("/photo/mock-upload/{object_key:path}")
async def mock_photo_upload(
    object_key: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """
    功能：Mock 版对象存储上传接口。用于本地/测试环境，将客户端上传的图片
          写入本地磁盘目录，模拟真实的 S3/OSS 直传逻辑；同时校验 object_key
          归属，避免用户越权写入他人目录。
    入参：
        - object_key (str): 由 upload-url 接口生成的对象键（路径式），会写入到该路径。
        - file (UploadFile): 上传的图片文件（multipart/form-data）。
        - user_id (str): 当前登录用户 ID，用于权限校验。
    返回：
        dict：{"ok": True, "object_key": ..., "bytes": 文件大小}
    """
    if f"/{user_id}/" not in f"/{object_key}/":
        raise HTTPException(status_code=403, detail={"error_code": "FORBIDDEN_KEY", "message": "Object key mismatch"})

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail={"error_code": "EMPTY_FILE", "message": "File is empty"})

    local_path = ensure_local_storage_path(object_key)
    with open(local_path, "wb") as f:
        f.write(content)

    return {"ok": True, "object_key": object_key, "bytes": os.path.getsize(local_path)}


@router.post("/photo/complete", response_model=MealPhotoOut)
def meal_photo_complete(
    payload: PhotoCompleteRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：客户端图片上传成功后调用此接口“落库并触发视觉识别”。会先创建
          MealPhoto 记录，随后同步调用 vision 服务进行卡路里估算与拍摄时间
          推断；同时投递 Celery 异步任务作为冗余预热（失败静默忽略）。
    入参：
        - payload (PhotoCompleteRequest): 请求体，包含 object_key（对象键）、
          exif_ts（EXIF 拍摄时间，可选）。
        - user_id (str): 当前登录用户 ID。
        - db (Session): 数据库会话，由依赖注入提供。
    返回：
        MealPhotoOut：图片记录详情，含状态、卡路里估算、置信度、vision_json、
                      以及根据 vision 推断出的 suggested_meal_ts / 置信度。
    """
    photo = create_photo_record(db, user_id, payload.object_key, payload.exif_ts)

    # 始终同步处理，确保客户端立即拿到 vision 结果（用于非食物判定与卡路里展示）。
    # Celery 仅作为冗余预热路径；即便 broker 可用也立即同步执行一次。
    try:
        process_meal_photo.delay(str(photo.id))
    except Exception:  # noqa: BLE001
        pass
    try:
        photo = process_photo_sync(db, photo)
    except Exception:  # noqa: BLE001
        # vision 失败不应阻塞上传；返回 status=uploaded 让前端给出友好提示
        pass

    suggested_ts = None
    suggested_conf = None
    if isinstance(photo.vision_json, dict):
        raw_ts = photo.vision_json.get("inferred_meal_ts")
        if raw_ts:
            suggested_ts = datetime.fromisoformat(raw_ts)
            suggested_conf = photo.vision_json.get("inferred_confidence")

    return MealPhotoOut(
        id=str(photo.id),
        uploaded_at=photo.uploaded_at,
        status=photo.status.value,
        calorie_estimate_kcal=photo.calorie_estimate_kcal,
        confidence=photo.confidence,
        vision_json=photo.vision_json,
        suggested_meal_ts=suggested_ts,
        suggested_confidence=suggested_conf,
    )


@router.get("/photo/{photo_id}", response_model=MealPhotoOut)
def get_photo(
    photo_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：根据 photo_id 查询指定餐食照片的详情（含 vision 识别结果与建议
          就餐时间），仅返回归属于当前用户的记录。
    入参：
        - photo_id (str): 照片记录的主键 ID（路径参数）。
        - user_id (str): 当前登录用户 ID，用于权限过滤。
        - db (Session): 数据库会话。
    返回：
        MealPhotoOut：照片详情。若不存在或不属于当前用户则返回 404。
    """
    photo = db.execute(
        select(MealPhoto).where(MealPhoto.id == photo_id, MealPhoto.user_id == user_id)
    ).scalars().first()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    suggested_ts = None
    suggested_conf = None
    if isinstance(photo.vision_json, dict):
        raw_ts = photo.vision_json.get("inferred_meal_ts")
        if raw_ts:
            suggested_ts = datetime.fromisoformat(raw_ts)
            suggested_conf = photo.vision_json.get("inferred_confidence")

    return MealPhotoOut(
        id=str(photo.id),
        uploaded_at=photo.uploaded_at,
        status=photo.status.value,
        calorie_estimate_kcal=photo.calorie_estimate_kcal,
        confidence=photo.confidence,
        vision_json=photo.vision_json,
        suggested_meal_ts=suggested_ts,
        suggested_confidence=suggested_conf,
    )


@router.post("", response_model=MealOut)
def create_meal(
    payload: MealCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：创建一条正式的餐食（Meal）记录。通常在用户确认照片识别结果或
          手动录入卡路里/标签后调用，将数据写入数据库。
    入参：
        - payload (MealCreate): 请求体，包含 meal_ts（就餐时间）、
          meal_ts_source（时间来源，如 EXIF/手动/推断）、kcal（卡路里）、
          tags（标签列表）、photo_id（关联照片，可选）、notes（备注）。
        - user_id (str): 当前登录用户 ID。
        - db (Session): 数据库会话。
    返回：
        MealOut：创建成功后的餐食记录（含 id）。
    """
    meal = Meal(
        user_id=user_id,
        meal_ts=payload.meal_ts,
        meal_ts_source=MealTsSource(payload.meal_ts_source),
        kcal=payload.kcal,
        tags=payload.tags,
        photo_id=payload.photo_id,
        notes=payload.notes,
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)

    return MealOut(
        id=str(meal.id),
        meal_ts=meal.meal_ts,
        meal_ts_source=meal.meal_ts_source.value,
        kcal=meal.kcal,
        tags=meal.tags,
        notes=meal.notes,
        photo_id=str(meal.photo_id) if meal.photo_id else None,
    )


@router.patch("/{meal_id}", response_model=MealOut)
def update_meal(
    meal_id: str,
    payload: MealUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：局部更新一条餐食记录。仅更新 payload 中显式传入的字段（None 表示
          不修改），常用于用户事后校正就餐时间、卡路里、标签或备注。
    入参：
        - meal_id (str): 要更新的餐食 ID（路径参数）。
        - payload (MealUpdate): 可选字段集合：meal_ts、meal_ts_source、
          kcal、tags、notes。
        - user_id (str): 当前登录用户 ID，用于权限过滤。
        - db (Session): 数据库会话。
    返回：
        MealOut：更新后的餐食记录；若记录不存在或不属于当前用户则返回 404。
    """
    meal = db.execute(select(Meal).where(Meal.id == meal_id, Meal.user_id == user_id)).scalars().first()
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")

    if payload.meal_ts is not None:
        meal.meal_ts = payload.meal_ts
    if payload.meal_ts_source is not None:
        meal.meal_ts_source = MealTsSource(payload.meal_ts_source)
    if payload.kcal is not None:
        meal.kcal = payload.kcal
    if payload.tags is not None:
        meal.tags = payload.tags
    if payload.notes is not None:
        meal.notes = payload.notes

    db.add(meal)
    db.commit()
    db.refresh(meal)

    return MealOut(
        id=str(meal.id),
        meal_ts=meal.meal_ts,
        meal_ts_source=meal.meal_ts_source.value,
        kcal=meal.kcal,
        tags=meal.tags,
        notes=meal.notes,
        photo_id=str(meal.photo_id) if meal.photo_id else None,
    )


@router.delete("/{meal_id}", status_code=204)
def delete_meal(
    meal_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：删除指定的餐食记录（硬删除）。
    入参：
        - meal_id (str): 要删除的餐食 ID（路径参数）。
        - user_id (str): 当前登录用户 ID，用于权限过滤。
        - db (Session): 数据库会话。
    返回：
        无内容响应（HTTP 204）。若记录不存在或不属于当前用户则返回 404。
    """
    meal = db.execute(
        select(Meal).where(Meal.id == meal_id, Meal.user_id == user_id)
    ).scalars().first()
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal not found")
    db.delete(meal)
    db.commit()
    return None


@router.get("", response_model=list[MealOut])
def list_meals(
    from_ts: datetime = Query(alias="from"),
    to_ts: datetime = Query(alias="to"),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    功能：按时间区间查询当前用户的餐食列表，按就餐时间倒序返回。
          区间为左闭右开 [from_ts, to_ts)，常用于日视图/周视图聚合。
    入参：
        - from_ts (datetime): 起始时间（查询参数 from，包含）。
        - to_ts (datetime): 结束时间（查询参数 to，不包含）。
        - user_id (str): 当前登录用户 ID。
        - db (Session): 数据库会话。
    返回：
        list[MealOut]：区间内的餐食记录列表。
    """
    rows = db.execute(
        select(Meal)
        .where(
            Meal.user_id == user_id,
            Meal.meal_ts >= from_ts,
            Meal.meal_ts < to_ts,
        )
        .order_by(Meal.meal_ts.desc())
    ).scalars().all()

    return [
        MealOut(
            id=str(m.id),
            meal_ts=m.meal_ts,
            meal_ts_source=m.meal_ts_source.value,
            kcal=m.kcal,
            tags=m.tags,
            notes=m.notes,
            photo_id=str(m.photo_id) if m.photo_id else None,
        )
        for m in rows
    ]
