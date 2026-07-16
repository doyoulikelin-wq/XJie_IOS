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
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.health_trust import HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import (
    HealthReportAssetSetWorkflowLink,
    HealthReportDescriptor,
    HealthReportPage,
)
from app.services.report_asset_service import add_field_locator
from app.services.report_duplicate_service import ensure_semantic_duplicate_decision


logger = logging.getLogger(__name__)

OCR_PROVIDER_ID = "openai-compatible-vision"
OCR_LOCATOR_VERSION = "provider-normalized-region-v1"
OCR_LEASE_SECONDS = 15 * 60
OCR_MAX_ATTEMPTS = 3
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
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("report OCR provider is not configured")
        kwargs: dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)
        self.model_version = settings.OPENAI_MODEL_VISION

    def extract_page(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        page_index: int,
    ) -> list[dict[str, Any]]:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
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
            extra_body={"thinking": {"type": "disabled"}},
            **settings.llm_temperature_kwargs(settings.OPENAI_MODEL_VISION),
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


def claim_report_ocr_workflow(
    db: Session,
    *,
    now: datetime | None = None,
    lease_seconds: int = OCR_LEASE_SECONDS,
) -> tuple[int, str] | None:
    """Claim one DB-authoritative workflow; broker delivery is only a wake-up."""

    now = now or _utcnow()
    rows = list(
        db.execute(
            select(HealthReportWorkflow)
            .where(
                HealthReportWorkflow.legacy_document_id.is_(None),
                HealthReportWorkflow.status == "recognizing",
            )
            .order_by(HealthReportWorkflow.created_at, HealthReportWorkflow.id)
            .limit(50)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    changed = False
    for workflow in rows:
        metadata = dict(workflow.workflow_metadata or {})
        if metadata.get("ocr_state") == "completed":
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
            metadata.update({"ocr_state": "failed", "ocr_failed_at": now.isoformat()})
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
                "ocr_lease_expires_at": (now + timedelta(seconds=max(60, lease_seconds))).isoformat(),
            }
        )
        workflow.workflow_metadata = metadata
        workflow.failure_code = None
        workflow.failure_detail = None
        db.commit()
        return workflow.id, token
    if changed:
        db.commit()
    return None


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


def _page_content(storage_root: str, page: HealthReportPage) -> tuple[bytes, str]:
    root = Path(storage_root).resolve()
    path = (root / page.rendered_storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise RuntimeError("report OCR page is unavailable")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime_type.startswith("image/"):
        raise RuntimeError("report OCR page is not an image")
    return path.read_bytes(), mime_type


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
    storage_root: str,
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

    extracted: list[tuple[HealthReportPage, ExtractedReportField]] = []
    for page in pages:
        image_bytes, mime_type = _page_content(storage_root, page)
        provider_items = extractor.extract_page(
            image_bytes=image_bytes,
            mime_type=mime_type,
            page_index=page.page_index,
        )
        extracted.extend((page, field) for field in normalize_provider_items(provider_items))

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
        metadata["ocr_state"] = "pending"
    workflow.workflow_metadata = metadata
    db.commit()
