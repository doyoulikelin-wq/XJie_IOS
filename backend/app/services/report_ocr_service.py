"""Durable, review-first OCR for ordered health-report pages.

The vision provider must return a real normalized bounding box for every
candidate. Items without a valid provider-supplied box are dropped; this
service never invents page coordinates or admits extracted values directly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Protocol

from openai import OpenAI
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.health_trust import HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import (
    HealthReportAsset,
    HealthReportAssetSetWorkflowLink,
    HealthReportDescriptor,
    HealthReportPage,
)
from app.services.object_storage import (
    ObjectStorageConfigurationError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageUnavailableError,
    PrivateObjectStore,
    StoredObjectIdentity,
    StoredObjectMetadata,
)
from app.services.report_asset_service import (
    MAX_REPORT_ASSET_BYTES,
    MAX_REPORT_RENDERED_PAGE_BYTES,
    add_field_locator,
    queue_attached_report_object_retirement,
    retire_attached_report_objects,
)
from app.services.report_asset_quality_service import (
    is_heif_container,
    render_image_page,
)
from app.services.report_duplicate_service import ensure_semantic_duplicate_decision
from app.services.report_ocr_recovery_policy import (
    REPORT_OCR_PROVIDER_UNAVAILABLE_FAILURE_CODE,
    fresh_report_ocr_pending_metadata,
)


logger = logging.getLogger(__name__)

OCR_PROVIDER_ID = "openai-compatible-vision"
OCR_LOCATOR_VERSION = "provider-normalized-region-v1"
OCR_LEASE_SECONDS = 15 * 60
OCR_PROVIDER_TIMEOUT_SECONDS = 2 * 60
OCR_STALE_SECONDS = 2 * OCR_LEASE_SECONDS
OCR_MAX_ATTEMPTS = 3
OCR_INFRASTRUCTURE_RETRY_DELAY_SECONDS = 60
OCR_MAX_INFRASTRUCTURE_ATTEMPTS = 5


class ReportOCRProviderInitializationError(RuntimeError):
    """The configured OCR provider could not be constructed safely."""


REPORT_OCR_INFRASTRUCTURE_ERRORS = (
    ReportOCRProviderInitializationError,
    ObjectStorageConfigurationError,
    ObjectStorageUnavailableError,
    ObjectStorageNotFoundError,
    ObjectStorageIntegrityError,
)
_COORDINATE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class ExtractedReportField:
    raw_name: str
    raw_value: str
    normalized_value: Decimal | None
    normalized_text: str | None
    unit: str | None
    reference_low: Decimal | None
    reference_high: Decimal | None
    reference_text: str | None
    abnormal_state: str
    confidence: Decimal | None
    bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    provider_item_index: int


class ReportPageExtractor(Protocol):
    provider_id: str
    model_version: str

    def extract_page(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        page_index: int,
    ) -> list[dict[str, Any]]: ...


class OpenAIReportPageExtractor:
    """Vision extractor using the configured OpenAI-compatible endpoint."""

    provider_id = OCR_PROVIDER_ID

    def __init__(self) -> None:
        # worker 进程不经过 FastAPI startup，因此在真正创建客户端前再次失败关闭。
        try:
            settings.validate_report_vision_configuration(require_credentials=True)
        except Exception as exc:
            # 配置校验消息不含用户数据；保留原消息便于启动检查定位具体字段。
            raise ReportOCRProviderInitializationError(str(exc)) from exc
        kwargs: dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        try:
            self._client = OpenAI(**kwargs)
        except Exception as exc:
            # SDK 构造异常可能带环境细节，持久状态与外层消息只使用稳定分类。
            raise ReportOCRProviderInitializationError(
                "Report OCR provider initialization failed."
            ) from exc
        self.model_version = settings.OPENAI_MODEL_VISION
        self.provider_family = settings.report_vision_provider_family()

    def extract_page(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        page_index: int,
    ) -> list[dict[str, Any]]:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        provider_options: dict[str, Any] = {}
        if self.provider_family == "moonshot":
            provider_options["extra_body"] = {"thinking": {"type": "disabled"}}
        response = self._client.chat.completions.create(
            model=self.model_version,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是医疗报告逐页转录器。只转录图片中真实可见的检查项目，不做诊断、推断或补全。"
                        "只返回严格 JSON 对象。每个项目必须包含该项目整行在原图中的真实位置 bbox，"
                        "采用左上角原点的归一化 [x,y,width,height]，每项保留最多六位小数。"
                        "看不清数值或无法确定真实 bbox 时必须省略该项目，禁止用 [0,0,1,1] 等占位坐标。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": (
                                f"转录第 {page_index} 页。返回格式："
                                '{"items":[{"name":"项目名","value":"原始结果",'
                                '"unit":"单位或null","reference_low":数字或null,'
                                '"reference_high":数字或null,"reference_text":"原文或null",'
                                '"abnormal_state":"normal|abnormal|unknown",'
                                '"confidence":0到1,"bbox":[x,y,width,height]}]}'
                            ),
                        },
                    ],
                },
            ],
            max_tokens=4096,
            # 单页调用必须在 DB 租约内确定结束；下一页开始前会续租。
            timeout=OCR_PROVIDER_TIMEOUT_SECONDS,
            **settings.llm_temperature_kwargs(settings.OPENAI_MODEL_VISION),
            **provider_options,
        )
        raw = response.choices[0].message.content or ""
        payload = _parse_json_object(raw)
        items = payload.get("items")
        return items[:200] if isinstance(items, list) else []


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if "```" in text:
        blocks = text.split("```")
        text = next(
            (block.removeprefix("json").strip() for block in blocks if block.strip().startswith(("json", "{"))),
            text,
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _bounded_text(value: Any, limit: int) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    normalized = str(value).strip()
    return normalized[:limit] if normalized else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _confidence(value: Any) -> Decimal | None:
    parsed = _decimal(value)
    if parsed is None or parsed < 0 or parsed > 1:
        return None
    return parsed.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _field_decimal(value: Any) -> Decimal | None:
    parsed = _decimal(value)
    if parsed is None or abs(parsed) >= Decimal("10000000000000000"):
        return None
    try:
        return parsed.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _provider_bbox(value: Any) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    parsed = [_decimal(item) for item in value]
    if any(item is None for item in parsed):
        return None
    x, y, width, height = (
        item.quantize(_COORDINATE_QUANTUM, rounding=ROUND_HALF_UP) for item in parsed if item is not None
    )
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    if x > 1 or y > 1 or width > 1 or height > 1:
        return None
    if x + width > 1 or y + height > 1:
        return None
    if (x, y, width, height) == (Decimal("0"), Decimal("0"), Decimal("1"), Decimal("1")):
        return None
    return x, y, width, height


def normalize_provider_items(items: list[Any]) -> list[ExtractedReportField]:
    """Validate provider rows; invalid or locator-less rows are fail-closed."""

    normalized: list[ExtractedReportField] = []
    for index, raw in enumerate(items[:200], start=1):
        if not isinstance(raw, dict):
            continue
        name = _bounded_text(raw.get("name"), 160)
        value = _bounded_text(raw.get("value"), 2000)
        bbox = _provider_bbox(raw.get("bbox"))
        if not name or not value or bbox is None:
            continue
        numeric_value = _field_decimal(value)
        text_value = None if numeric_value is not None else value
        reference_low = _field_decimal(raw.get("reference_low"))
        reference_high = _field_decimal(raw.get("reference_high"))
        if (
            reference_low is not None
            and reference_high is not None
            and reference_low > reference_high
        ):
            reference_low = None
            reference_high = None
        abnormal_state = str(raw.get("abnormal_state") or "unknown").strip().casefold()
        if abnormal_state not in {"normal", "abnormal", "unknown"}:
            abnormal_state = "unknown"
        normalized.append(
            ExtractedReportField(
                raw_name=name,
                raw_value=value,
                normalized_value=numeric_value,
                normalized_text=text_value,
                unit=_bounded_text(raw.get("unit"), 64),
                reference_low=reference_low,
                reference_high=reference_high,
                reference_text=_bounded_text(raw.get("reference_text"), 256),
                abnormal_state=abnormal_state,
                confidence=_confidence(raw.get("confidence")),
                bbox=bbox,
                provider_item_index=index,
            )
        )
    return normalized


def _lease_expiry(metadata: dict[str, Any]) -> datetime | None:
    raw = metadata.get("ocr_lease_expires_at")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _metadata_datetime(metadata: dict[str, Any], key: str) -> datetime | None:
    raw = metadata.get(key)
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def report_ocr_infrastructure_reason(exc: BaseException) -> str:
    """Return a stable non-PHI classification for storage infrastructure failures."""

    if isinstance(exc, ReportOCRProviderInitializationError):
        return "provider_initialization"
    if isinstance(exc, ObjectStorageConfigurationError):
        return "object_storage_configuration"
    if isinstance(exc, ObjectStorageUnavailableError):
        return "object_storage_unavailable"
    if isinstance(exc, ObjectStorageNotFoundError):
        return "object_storage_not_found"
    if isinstance(exc, ObjectStorageIntegrityError):
        return "object_storage_integrity"
    raise TypeError("error is not a report OCR infrastructure failure")


def reconcile_stale_report_ocr_workflow(
    db: Session,
    *,
    workflow_id: int,
    now: datetime | None = None,
    stale_seconds: int = OCR_STALE_SECONDS,
) -> bool:
    """把超时未认领或租约停滞的任务收敛为可重新上传的终态。"""

    effective_now = now or _utcnow()
    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.legacy_document_id.is_(None),
        )
        .with_for_update()
    ).scalars().first()
    if not workflow or workflow.status != "recognizing":
        return False
    metadata = dict(workflow.workflow_metadata or {})
    state = metadata.get("ocr_state")
    if state in {None, "pending"}:
        pending_deadline = _metadata_datetime(
            metadata,
            "ocr_pending_deadline_at",
        )
        if pending_deadline is None:
            # 升级前的 pending 行没有持久时限。首次观察只补写窗口，避免按
            # 数据库 created_at 猜测并误杀仍可能被旧 worker 处理的任务。
            metadata.update(fresh_report_ocr_pending_metadata(now=effective_now))
            workflow.workflow_metadata = metadata
            db.commit()
            return False
        if pending_deadline > effective_now:
            return False
        metadata.update(
            {
                "ocr_state": "failed",
                "ocr_failed_at": effective_now.isoformat(),
                "ocr_pending_timeout_reconciled_at": effective_now.isoformat(),
            }
        )
        metadata.pop("ocr_claim_token", None)
        metadata.pop("ocr_lease_expires_at", None)
        metadata.pop("ocr_next_infrastructure_attempt_at", None)
        workflow.status = "failed"
        workflow.failure_code = "report_ocr_stalled"
        workflow.failure_detail = (
            "Report recognition was not claimed before its bounded deadline."
        )
        workflow.version += 1
        workflow.workflow_metadata = metadata
        db.commit()
        queue_attached_report_object_retirement(db, workflow_id=workflow.id)
        return True
    lease_expiry = _lease_expiry(metadata)
    # running 分支只收敛曾被 worker 认领且租约已长期过期的任务；
    # pending/unclaimed 已由上方持久 deadline 独立约束。
    if (
        state != "running"
        or lease_expiry is None
        or lease_expiry > effective_now
    ):
        return False
    # claimed/failed 时间不能代表长任务是否仍活着；只信 worker heartbeat，
    # 旧数据没有 heartbeat 时才以最后一个租约截止点作为保守兼容基准。
    last_progress = _metadata_datetime(metadata, "ocr_heartbeat_at") or lease_expiry
    if (effective_now - last_progress).total_seconds() < max(60, stale_seconds):
        return False
    metadata.update(
        {
            "ocr_state": "failed",
            "ocr_failed_at": effective_now.isoformat(),
            "ocr_stalled_reconciled_at": effective_now.isoformat(),
        }
    )
    metadata.pop("ocr_claim_token", None)
    metadata.pop("ocr_lease_expires_at", None)
    metadata.pop("ocr_next_infrastructure_attempt_at", None)
    workflow.status = "failed"
    workflow.failure_code = "report_ocr_stalled"
    workflow.failure_detail = "Report recognition did not make progress before its bounded deadline."
    workflow.version += 1
    workflow.workflow_metadata = metadata
    db.commit()
    # 失败终态也不再需要服务端原件；先持久记录删除意图，由清理 sweep 重放。
    queue_attached_report_object_retirement(db, workflow_id=workflow.id)
    return True


def reconcile_stale_report_ocr_workflows(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = 50,
) -> int:
    """扫描 pending deadline 与长期过期的 running lease。"""

    if batch_size < 1 or batch_size > 500:
        raise ValueError("batch_size must be between 1 and 500")
    workflow_ids = list(
        db.scalars(
            select(HealthReportWorkflow.id)
            .where(
                HealthReportWorkflow.legacy_document_id.is_(None),
                HealthReportWorkflow.status == "recognizing",
            )
            .order_by(HealthReportWorkflow.id)
            .limit(batch_size)
        )
    )
    return sum(
        reconcile_stale_report_ocr_workflow(
            db,
            workflow_id=workflow_id,
            now=now,
        )
        for workflow_id in workflow_ids
    )


def _best_effort_retire_terminal_source(
    db: Session,
    *,
    workflow_id: int,
    object_store: PrivateObjectStore,
) -> None:
    """OCR 结果先提交；原件清理失败只保留重放队列，不能推翻结果。"""

    try:
        retire_attached_report_objects(
            db,
            workflow_id=workflow_id,
            object_store=object_store,
        )
    except Exception:
        db.rollback()
        logger.warning(
            "health report terminal source retirement deferred workflow_id=%s",
            workflow_id,
        )


def claim_report_ocr_workflow(
    db: Session,
    *,
    now: datetime | None = None,
    lease_seconds: int = OCR_LEASE_SECONDS,
    exclude_workflow_ids: set[int] | None = None,
) -> tuple[int, str] | None:
    """Claim one DB-authoritative workflow; broker delivery is only a wake-up."""

    now = now or _utcnow()
    query = select(HealthReportWorkflow).where(
        HealthReportWorkflow.legacy_document_id.is_(None),
        HealthReportWorkflow.status == "recognizing",
    )
    excluded = {value for value in (exclude_workflow_ids or set()) if value > 0}
    if excluded:
        query = query.where(HealthReportWorkflow.id.not_in(excluded))
    changed = False
    cursor_id = 0
    while True:
        page_query = query
        if cursor_id:
            page_query = page_query.where(HealthReportWorkflow.id > cursor_id)
        rows = list(
            db.execute(
                # 自增主键既保持创建顺序，又避免时间戳精度在 SQLite/Postgres
                # 间不同导致 keyset 边界遗漏。
                page_query.order_by(HealthReportWorkflow.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        if not rows:
            break
        cursor_id = rows[-1].id
        for workflow in rows:
            metadata = dict(workflow.workflow_metadata or {})
            if metadata.get("ocr_state") == "completed":
                continue
            infrastructure_retry_at = _metadata_datetime(
                metadata,
                "ocr_next_infrastructure_attempt_at",
            )
            if infrastructure_retry_at and infrastructure_retry_at > now:
                continue
            expiry = _lease_expiry(metadata)
            if metadata.get("ocr_state") == "running" and expiry and expiry > now:
                continue
            attempts = int(metadata.get("ocr_attempt_count") or 0)
            if attempts >= OCR_MAX_ATTEMPTS:
                workflow.status = "failed"
                workflow.failure_code = "report_ocr_retry_exhausted"
                workflow.failure_detail = "Report recognition could not be completed after bounded retries."
                workflow.version += 1
                metadata.update(
                    {"ocr_state": "failed", "ocr_failed_at": now.isoformat()}
                )
                metadata.pop("ocr_claim_token", None)
                metadata.pop("ocr_lease_expires_at", None)
                workflow.workflow_metadata = metadata
                changed = True
                continue
            token = uuid.uuid4().hex
            metadata.update(
                {
                    "ocr_state": "running",
                    "ocr_attempt_count": attempts + 1,
                    "ocr_claim_token": token,
                    "ocr_claimed_at": now.isoformat(),
                    "ocr_heartbeat_at": now.isoformat(),
                    "ocr_heartbeat_count": 0,
                    "ocr_lease_expires_at": (
                        now + timedelta(seconds=max(60, lease_seconds))
                    ).isoformat(),
                }
            )
            metadata.pop("ocr_pending_since", None)
            metadata.pop("ocr_pending_deadline_at", None)
            metadata.pop("ocr_next_infrastructure_attempt_at", None)
            metadata.pop("ocr_infrastructure_state", None)
            workflow.workflow_metadata = metadata
            workflow.failure_code = None
            workflow.failure_detail = None
            db.commit()
            return workflow.id, token
        if len(rows) < 50:
            break
    if changed:
        db.commit()
    return None


def heartbeat_report_ocr_claim(
    db: Session,
    *,
    workflow_id: int,
    claim_token: str,
    now: datetime | None = None,
    lease_seconds: int = OCR_LEASE_SECONDS,
) -> bool:
    """按 claim token 原子续租；被新 worker 接管后旧 worker 必须失败。"""

    effective_now = now or _utcnow()
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.legacy_document_id.is_(None),
        )
    ).scalars().first()
    metadata = dict(workflow.workflow_metadata or {}) if workflow else {}
    if (
        not workflow
        or workflow.status != "recognizing"
        or metadata.get("ocr_state") != "running"
        or metadata.get("ocr_claim_token") != claim_token
    ):
        db.rollback()
        raise RuntimeError("report OCR claim is stale")
    metadata.update(
        {
            "ocr_heartbeat_at": effective_now.isoformat(),
            "ocr_heartbeat_count": int(metadata.get("ocr_heartbeat_count") or 0)
            + 1,
            "ocr_lease_expires_at": (
                effective_now + timedelta(seconds=max(60, lease_seconds))
            ).isoformat(),
        }
    )
    result = db.execute(
        update(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.status == "recognizing",
            HealthReportWorkflow.workflow_metadata["ocr_state"].as_string()
            == "running",
            HealthReportWorkflow.workflow_metadata[
                "ocr_claim_token"
            ].as_string()
            == claim_token,
        )
        .values(workflow_metadata=metadata)
    )
    if result.rowcount != 1:
        db.rollback()
        raise RuntimeError("report OCR claim is stale")
    db.commit()
    return True


def _scoped_ocr_workflow(
    db: Session,
    *,
    workflow_id: int,
    claim_token: str,
    lock: bool = False,
) -> HealthReportWorkflow:
    query = select(HealthReportWorkflow).where(
        HealthReportWorkflow.id == workflow_id,
        HealthReportWorkflow.legacy_document_id.is_(None),
    )
    if lock:
        query = query.with_for_update()
    workflow = db.execute(query).scalars().first()
    metadata = dict(workflow.workflow_metadata or {}) if workflow else {}
    if (
        not workflow
        or workflow.status != "recognizing"
        or metadata.get("ocr_claim_token") != claim_token
        or metadata.get("ocr_state") != "running"
    ):
        raise RuntimeError("report OCR claim is stale")
    return workflow


def _page_content(
    object_store: PrivateObjectStore,
    page: HealthReportPage,
    source_asset: HealthReportAsset,
) -> tuple[bytes, str]:
    """读取经租户和摘要绑定的 OCR 页面；原图与 PDF 渲染页使用各自元数据。"""

    if page.rendered_storage_key == source_asset.storage_key:
        if not source_asset.mime_type.startswith("image/"):
            raise RuntimeError("report OCR page is not an image")
        metadata = StoredObjectMetadata(
            key=source_asset.storage_key,
            sha256=source_asset.byte_sha256,
            size_bytes=source_asset.byte_size,
            content_type=source_asset.mime_type,
            owner_user_id=source_asset.user_id,
            subject_user_id=source_asset.subject_user_id,
        )
        source_bytes = object_store.get(
            metadata=metadata,
            max_bytes=MAX_REPORT_ASSET_BYTES,
        )
        # 兼容修复前已经封存的任务：现场数据的名称/MIME 是 PNG，
        # 但原始字节是 HEIC。旧页不会重走 seal，因此 OCR 边界必须
        # 按真实签名即时生成兼容 PNG，且绝不改写原件。
        if is_heif_container(source_bytes):
            return render_image_page(source_bytes).png_bytes, "image/png"
        return source_bytes, source_asset.mime_type
    identity = StoredObjectIdentity(
        key=page.rendered_storage_key,
        sha256=page.rendered_byte_sha256,
        content_type="image/png",
        owner_user_id=page.user_id,
        subject_user_id=page.subject_user_id,
    )
    return (
        object_store.get_bounded(
            identity=identity,
            max_bytes=MAX_REPORT_RENDERED_PAGE_BYTES,
        ),
        "image/png",
    )


def _effective_at(db: Session, workflow: HealthReportWorkflow) -> datetime:
    descriptor = db.execute(
        select(HealthReportDescriptor).where(
            HealthReportDescriptor.workflow_id == workflow.id,
            HealthReportDescriptor.user_id == workflow.user_id,
            HealthReportDescriptor.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().first()
    if descriptor and descriptor.report_date:
        return datetime.combine(descriptor.report_date, time.min, tzinfo=timezone.utc)
    created = workflow.created_at or _utcnow()
    return created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created


def execute_report_ocr_workflow(
    db: Session,
    *,
    workflow_id: int,
    claim_token: str,
    extractor: ReportPageExtractor,
    object_store: PrivateObjectStore,
) -> int:
    """Extract all pages, then atomically persist candidates and real locators."""

    workflow = _scoped_ocr_workflow(db, workflow_id=workflow_id, claim_token=claim_token)
    link = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.workflow_id == workflow.id,
            HealthReportAssetSetWorkflowLink.user_id == workflow.user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().first()
    if not link:
        raise RuntimeError("report OCR asset set is unavailable")
    pages = list(
        db.execute(
            select(HealthReportPage)
            .where(
                HealthReportPage.asset_set_id == link.asset_set_id,
                HealthReportPage.user_id == workflow.user_id,
                HealthReportPage.subject_user_id == workflow.subject_user_id,
            )
            .order_by(HealthReportPage.page_index)
        ).scalars()
    )
    if not pages:
        raise RuntimeError("report OCR has no rendered pages")
    assets = {
        asset.id: asset
        for asset in db.execute(
            select(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == link.asset_set_id,
                HealthReportAsset.user_id == workflow.user_id,
                HealthReportAsset.subject_user_id == workflow.subject_user_id,
            )
        ).scalars()
    }
    if any(page.source_asset_id not in assets for page in pages):
        raise RuntimeError("report OCR source asset is unavailable")

    extracted: list[tuple[HealthReportPage, ExtractedReportField]] = []
    for page in pages:
        image_bytes, mime_type = _page_content(
            object_store,
            page,
            assets[page.source_asset_id],
        )
        provider_items = extractor.extract_page(
            image_bytes=image_bytes,
            mime_type=mime_type,
            page_index=page.page_index,
        )
        extracted.extend((page, field) for field in normalize_provider_items(provider_items))
        # 每页 provider 调用完成后立即续租；下一页只能由仍持有 token 的 worker 继续。
        heartbeat_report_ocr_claim(
            db,
            workflow_id=workflow_id,
            claim_token=claim_token,
        )

    workflow = _scoped_ocr_workflow(
        db,
        workflow_id=workflow_id,
        claim_token=claim_token,
        lock=True,
    )
    existing = list(
        db.execute(
            select(HealthReportFieldCandidate).where(
                HealthReportFieldCandidate.workflow_id == workflow.id,
                HealthReportFieldCandidate.user_id == workflow.user_id,
                HealthReportFieldCandidate.subject_user_id == workflow.subject_user_id,
            )
        ).scalars()
    )
    if existing:
        raise RuntimeError("report OCR workflow already contains candidates")
    metadata = dict(workflow.workflow_metadata or {})
    metadata.pop("ocr_claim_token", None)
    metadata.pop("ocr_lease_expires_at", None)
    metadata["ocr_provider_id"] = extractor.provider_id[:80]
    metadata["ocr_model_version"] = extractor.model_version[:80]

    if not extracted:
        workflow.status = "failed"
        workflow.failure_code = "no_reviewable_candidates"
        workflow.failure_detail = "Recognition returned no fields with verifiable page coordinates."
        workflow.version += 1
        metadata.update({"ocr_state": "failed", "ocr_failed_at": _utcnow().isoformat()})
        workflow.workflow_metadata = metadata
        db.commit()
        _best_effort_retire_terminal_source(
            db,
            workflow_id=workflow_id,
            object_store=object_store,
        )
        return 0

    effective_at = _effective_at(db, workflow)
    candidates: list[HealthReportFieldCandidate] = []
    for page, field in extracted:
        bbox_text = ",".join(str(value) for value in field.bbox)
        key_material = (
            f"{workflow.id}:{page.id}:{field.provider_item_index}:"
            f"{field.raw_name}:{field.raw_value}:{field.unit or ''}:{bbox_text}"
        )
        candidate = HealthReportFieldCandidate(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            subject_user_id=workflow.subject_user_id,
            candidate_key=f"vision:{hashlib.sha256(key_material.encode('utf-8')).hexdigest()}",
            canonical_code=None,
            canonical_name=field.raw_name,
            raw_name=field.raw_name,
            raw_value=field.raw_value,
            raw_unit=field.unit,
            normalized_value=field.normalized_value,
            normalized_text=field.normalized_text,
            normalized_unit=field.unit,
            reference_low=field.reference_low,
            reference_high=field.reference_high,
            reference_text=field.reference_text,
            abnormal_state=field.abnormal_state,
            confidence=field.confidence,
            effective_at=effective_at,
            source_locator={
                "asset_set_id": link.asset_set_id,
                "page_id": page.id,
                "page_index": page.page_index,
                "provider_id": extractor.provider_id[:80],
                "model_version": extractor.model_version[:80],
                "coordinate_space": "normalized_top_left",
                "bbox_source": "provider_output",
                "bbox": [str(value) for value in field.bbox],
            },
            review_status="pending_review",
            requires_review=True,
            model_version=extractor.model_version[:80],
            version=1,
        )
        db.add(candidate)
        db.flush()
        x, y, width, height = field.bbox
        locator = add_field_locator(
            db,
            workflow_id=workflow.id,
            candidate_id=candidate.id,
            page_id=page.id,
            user_id=workflow.user_id,
            subject_user_id=workflow.subject_user_id,
            region_index=1,
            region_role="row",
            x=x,
            y=y,
            width=width,
            height=height,
            polygon_norm=[],
            provider_id=extractor.provider_id[:80],
            model_version=extractor.model_version[:80],
            confidence=field.confidence,
        )
        locator.locator_version = OCR_LOCATOR_VERSION
        candidates.append(candidate)

    now = _utcnow()
    workflow.status = "awaiting_confirmation"
    workflow.failure_code = None
    workflow.failure_detail = None
    workflow.recognized_at = now
    workflow.version += 1
    metadata.update(
        {
            "ocr_state": "completed",
            "ocr_completed_at": now.isoformat(),
            "ocr_candidate_count": len(candidates),
        }
    )
    workflow.workflow_metadata = metadata
    ensure_semantic_duplicate_decision(db, workflow=workflow, candidates=candidates)
    db.commit()
    _best_effort_retire_terminal_source(
        db,
        workflow_id=workflow_id,
        object_store=object_store,
    )
    return len(candidates)


def fail_report_ocr_claim(
    db: Session,
    *,
    workflow_id: int,
    claim_token: str,
) -> None:
    """Release a failed claim without storing provider output or PHI in errors."""

    try:
        workflow = _scoped_ocr_workflow(
            db,
            workflow_id=workflow_id,
            claim_token=claim_token,
            lock=True,
        )
    except RuntimeError:
        db.rollback()
        return
    metadata = dict(workflow.workflow_metadata or {})
    attempts = int(metadata.get("ocr_attempt_count") or 0)
    metadata.pop("ocr_claim_token", None)
    metadata.pop("ocr_lease_expires_at", None)
    metadata["ocr_last_failed_at"] = _utcnow().isoformat()
    if attempts >= OCR_MAX_ATTEMPTS:
        workflow.status = "failed"
        workflow.failure_code = "report_ocr_retry_exhausted"
        workflow.failure_detail = "Report recognition could not be completed after bounded retries."
        workflow.version += 1
        metadata["ocr_state"] = "failed"
    else:
        metadata.update(fresh_report_ocr_pending_metadata(now=_utcnow()))
    workflow.workflow_metadata = metadata
    db.commit()


def defer_report_ocr_infrastructure_claim(
    db: Session,
    *,
    workflow_id: int,
    claim_token: str,
    reason_code: str,
    now: datetime | None = None,
    retry_delay_seconds: int = OCR_INFRASTRUCTURE_RETRY_DELAY_SECONDS,
) -> None:
    """Release an infrastructure-failed claim without consuming a content retry.

    Provider initialization and object-storage failures use their own bounded
    counter. Persistent infrastructure faults therefore become an explicit
    re-upload state instead of leaving the user in “recognizing” forever.
    """

    effective_now = now or _utcnow()
    try:
        workflow = _scoped_ocr_workflow(
            db,
            workflow_id=workflow_id,
            claim_token=claim_token,
            lock=True,
        )
    except RuntimeError:
        db.rollback()
        return
    metadata = dict(workflow.workflow_metadata or {})
    attempts = int(metadata.get("ocr_attempt_count") or 0)
    infrastructure_attempts = int(
        metadata.get("ocr_infrastructure_attempt_count") or 0
    ) + 1
    metadata["ocr_attempt_count"] = max(0, attempts - 1)
    metadata["ocr_infrastructure_attempt_count"] = infrastructure_attempts
    metadata.pop("ocr_claim_token", None)
    metadata.pop("ocr_lease_expires_at", None)
    metadata["ocr_infrastructure_reason"] = reason_code[:80]
    metadata["ocr_infrastructure_failed_at"] = effective_now.isoformat()
    if infrastructure_attempts >= OCR_MAX_INFRASTRUCTURE_ATTEMPTS:
        metadata["ocr_state"] = "failed"
        metadata["ocr_infrastructure_state"] = "failed"
        metadata.pop("ocr_next_infrastructure_attempt_at", None)
        workflow.status = "failed"
        if reason_code == "provider_initialization":
            workflow.failure_code = REPORT_OCR_PROVIDER_UNAVAILABLE_FAILURE_CODE
            workflow.failure_detail = (
                "Report recognition provider remained unavailable after bounded retries."
            )
        else:
            workflow.failure_code = "report_ocr_storage_unavailable"
            workflow.failure_detail = (
                "Report source storage remained unavailable after bounded retries."
            )
        workflow.version += 1
    else:
        metadata.update(
            {
                "ocr_infrastructure_state": "delayed",
                "ocr_next_infrastructure_attempt_at": (
                    effective_now
                    + timedelta(seconds=max(1, retry_delay_seconds))
                ).isoformat(),
            }
        )
        metadata.update(fresh_report_ocr_pending_metadata(now=effective_now))
        workflow.failure_code = None
        workflow.failure_detail = None
    workflow.workflow_metadata = metadata
    db.commit()
