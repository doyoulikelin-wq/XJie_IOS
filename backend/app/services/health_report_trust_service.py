"""Trusted report ingestion, review, admission, and withdrawal.

The legacy ``HealthDocument.extraction_status`` describes OCR only.  This
service is the single admission boundary that can create observations consumed
by trends, summaries, AI context, profile facts, and score calculations.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.health_document import (
    HealthDocument,
    HealthDocumentSummary,
    HealthSummary,
    SummaryTask,
)
from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthProfileCandidate,
    HealthProfileSource,
    HealthReportConfirmationEvent,
    HealthReportFieldCandidate,
    HealthReportWorkflow,
    REPORT_ADMISSION_SCORE_KINDS,
    HealthScoreSnapshot,
)
from app.schemas.health_document import HealthDocumentOut
from app.schemas.health_report_trust import HealthReportConfirmIn, HealthReportManualCandidateIn


AUTO_ACCEPT_CONFIDENCE = Decimal("0.9500")
_FINAL_WORKFLOW_STATUSES = {"completed", "completed_score_pending"}
_SKIP_CANDIDATE_NAMES = {"提取失败", "备注"}
_SUMMARY_CANDIDATE_NAMES = {"体检小结", "小结"}
_FOLLOW_UP_TEXT_RE = re.compile(r"建议|复查|随访|复诊|观察")
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_RANGE_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[-~～至]\s*([+-]?\d+(?:\.\d+)?)\s*$")
_UPPER_RE = re.compile(r"^\s*[<≤]\s*([+-]?\d+(?:\.\d+)?)\s*$")
_LOWER_RE = re.compile(r"^\s*[>≥]\s*([+-]?\d+(?:\.\d+)?)\s*$")

_FAILURE_RECOVERY: dict[str, dict[str, Any]] = {
    "blur": {
        "recovery_action": "retake_image",
        "retryable": True,
        "allows_manual_candidate": False,
    },
    "blurry_image": {
        "recovery_action": "retake_image",
        "retryable": True,
        "allows_manual_candidate": False,
    },
    "missing_page": {
        "recovery_action": "upload_missing_pages",
        "retryable": True,
        "allows_manual_candidate": False,
    },
    "no_reviewable_candidates": {
        "recovery_action": "manual_entry_or_reupload",
        "retryable": True,
        "allows_manual_candidate": True,
    },
    "extraction_failed": {
        "recovery_action": "reupload_report",
        "retryable": True,
        "allows_manual_candidate": False,
    },
    "processing_failed": {
        "recovery_action": "retry_processing",
        "retryable": True,
        "allows_manual_candidate": False,
    },
    # Duplicates are represented by HealthDocumentOut.report_duplicate and
    # reuse the existing workflow. This defensive mapping exists only for
    # legacy/imported rows and must never be used to mark a new upload failed.
    "duplicate": {
        "recovery_action": "open_existing_report",
        "retryable": False,
        "allows_manual_candidate": False,
    },
    "withdrawn": {
        "recovery_action": "none",
        "retryable": False,
        "allows_manual_candidate": False,
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def document_fingerprint(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _bounded_hash(prefix: str, value: str, *, limit: int = 80) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"[:limit]


def _norm_column(value: Any) -> str:
    return re.sub(r"[\s_\-/（）()]+", "", str(value or "")).lower()


def _column_index(columns: list[Any], aliases: set[str], fallback: int | None = None) -> int | None:
    normalized_aliases = {_norm_column(alias) for alias in aliases}
    for idx, column in enumerate(columns):
        if _norm_column(column) in normalized_aliases:
            return idx
    return fallback if fallback is not None and fallback < len(columns) else None


def _cell(row: list[Any], index: int | None) -> str:
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _decimal(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace(",", "").replace("↑", "").replace("↓", "")
    if not text or not _NUMBER_RE.fullmatch(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _confidence(value: Any) -> Decimal | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    if parsed > 1 and parsed <= 100:
        parsed /= 100
    if Decimal("0") <= parsed <= Decimal("1"):
        return parsed.quantize(Decimal("0.0001"))
    return None


def _reference_bounds(value: str) -> tuple[Decimal | None, Decimal | None]:
    match = _RANGE_RE.match(value or "")
    if match:
        low, high = Decimal(match.group(1)), Decimal(match.group(2))
        if low <= high:
            return low, high
        return None, None
    match = _UPPER_RE.match(value or "")
    if match:
        return None, Decimal(match.group(1))
    match = _LOWER_RE.match(value or "")
    if match:
        return Decimal(match.group(1)), None
    return None, None


def _abnormal_state(value: str, *, column_present: bool, flagged: bool) -> str:
    if flagged:
        return "abnormal"
    normalized = _norm_column(value)
    if any(token in normalized for token in ("异常", "偏高", "偏低", "↑", "↓", "true", "yes")):
        return "abnormal"
    if normalized in {"1", "是"}:
        return "abnormal"
    if column_present and (not normalized or normalized in {"0", "否", "正常", "false", "no"}):
        return "normal"
    return "unknown"


def _effective_at(doc: HealthDocument) -> datetime:
    value = doc.doc_date or doc.created_at or _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_workflow(
    db: Session,
    *,
    doc: HealthDocument,
    user_id: int,
    subject_user_id: int,
    fingerprint: str,
    client_request_id: str,
) -> HealthReportWorkflow:
    """Attach a tenant-bound recognition workflow to a newly flushed document."""
    workflow = HealthReportWorkflow(
        user_id=user_id,
        subject_user_id=subject_user_id,
        legacy_document_id=doc.id,
        client_request_id=client_request_id,
        document_fingerprint=fingerprint,
        report_type="exam" if doc.doc_type == "exam" else "medical_record",
        status="recognizing",
        version=1,
        workflow_metadata={"admission_contract": "report-trust-v1"},
    )
    db.add(workflow)
    db.flush()
    return workflow


def find_duplicate_workflow(
    db: Session, *, user_id: int, subject_user_id: int, fingerprint: str
) -> HealthReportWorkflow | None:
    return db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
            HealthReportWorkflow.document_fingerprint == fingerprint,
        )
    ).scalars().first()


def find_request_workflow(
    db: Session, *, user_id: int, subject_user_id: int, client_request_id: str
) -> HealthReportWorkflow | None:
    return db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
            HealthReportWorkflow.client_request_id == client_request_id,
        )
    ).scalars().first()


def workflow_for_document(
    db: Session, *, user_id: int, document_id: int
) -> HealthReportWorkflow | None:
    return db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.legacy_document_id == document_id,
        )
    ).scalars().first()


def is_withdrawn(workflow: HealthReportWorkflow | None) -> bool:
    return bool(workflow and workflow.status == "failed" and workflow.failure_code == "withdrawn")


def document_out(
    doc: HealthDocument,
    workflow: HealthReportWorkflow | None = None,
    *,
    duplicate: bool = False,
) -> HealthDocumentOut:
    file_url = None
    if doc.original_file_path and not doc.original_file_path.startswith("data:"):
        file_url = f"/api/health-data/documents/{doc.id}/file"
    trusted = bool(workflow and workflow.status in _FINAL_WORKFLOW_STATUSES)
    return HealthDocumentOut(
        id=str(doc.id),
        doc_type=doc.doc_type,
        source_type=doc.source_type,
        name=doc.name,
        hospital=doc.hospital,
        doc_date=doc.doc_date.isoformat() if doc.doc_date else None,
        csv_data=doc.csv_data,
        abnormal_flags=doc.abnormal_flags,
        ai_brief=doc.ai_brief if trusted else None,
        ai_summary=doc.ai_summary if trusted else None,
        extraction_status=doc.extraction_status,
        created_at=doc.created_at,
        file_url=file_url,
        report_workflow_id=workflow.id if workflow else None,
        report_workflow_status=workflow.status if workflow else None,
        report_subject_user_id=workflow.subject_user_id if workflow else None,
        report_duplicate=duplicate,
    )


def sync_extracted_candidates(db: Session, workflow: HealthReportWorkflow) -> list[HealthReportFieldCandidate]:
    """Normalize OCR rows into review candidates without admitting any fact."""
    if workflow.status not in {"recognizing", "awaiting_confirmation"}:
        return []
    existing = db.execute(
        select(HealthReportFieldCandidate).where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == workflow.user_id,
            HealthReportFieldCandidate.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().all()
    if existing:
        return list(existing)

    doc = db.get(HealthDocument, workflow.legacy_document_id)
    if not doc or doc.user_id != workflow.user_id:
        raise RuntimeError("workflow document is missing or belongs to another tenant")
    csv_data = doc.csv_data if isinstance(doc.csv_data, dict) else {}
    columns = csv_data.get("columns") if isinstance(csv_data.get("columns"), list) else []
    rows = csv_data.get("rows") if isinstance(csv_data.get("rows"), list) else []

    name_idx = _column_index(columns, {"检查项目", "项目", "指标", "名称", "field"}, 0)
    value_idx = _column_index(columns, {"数值", "结果", "内容", "value", "content"}, 1)
    unit_idx = _column_index(columns, {"单位", "unit"})
    reference_idx = _column_index(columns, {"参考范围", "参考值", "ref_range", "reference"})
    abnormal_idx = _column_index(columns, {"异常", "异常标记", "is_abnormal"})
    page_idx = _column_index(columns, {"页码", "页", "page"})
    confidence_idx = _column_index(columns, {"置信度", "confidence"})
    abnormal_names = {
        str(item.get("field") or item.get("name") or "").strip()
        for item in (doc.abnormal_flags or [])
        if isinstance(item, dict)
    }

    candidates: list[HealthReportFieldCandidate] = []
    for row_index, raw_row in enumerate(rows):
        if not isinstance(raw_row, list):
            continue
        name = _cell(raw_row, name_idx)
        raw_value = _cell(raw_row, value_idx)
        if not name or not raw_value or name in _SKIP_CANDIDATE_NAMES or raw_value == "未提及":
            continue
        if name in _SUMMARY_CANDIDATE_NAMES:
            if not _FOLLOW_UP_TEXT_RE.search(raw_value):
                continue
            name = "医师建议"
        numeric_value = _decimal(raw_value)
        normalized_text = None if numeric_value is not None else raw_value
        raw_unit = _cell(raw_row, unit_idx)
        reference_text = _cell(raw_row, reference_idx)
        reference_low, reference_high = _reference_bounds(reference_text)
        confidence = _confidence(_cell(raw_row, confidence_idx))
        abnormal = _abnormal_state(
            _cell(raw_row, abnormal_idx),
            column_present=abnormal_idx is not None,
            flagged=name in abnormal_names,
        )
        auto_accepted = (
            doc.doc_type == "exam"
            and numeric_value is not None
            and confidence is not None
            and confidence >= AUTO_ACCEPT_CONFIDENCE
            and abnormal == "normal"
        )
        locator: dict[str, Any] = {
            "document_id": doc.id,
            "source_type": doc.source_type,
            "row_index": row_index,
            "name_column": name_idx,
            "value_column": value_idx,
        }
        for key, index in (
            ("unit_column", unit_idx),
            ("reference_column", reference_idx),
            ("abnormal_column", abnormal_idx),
            ("confidence_column", confidence_idx),
        ):
            if index is not None:
                locator[key] = index
        page_text = _cell(raw_row, page_idx)
        page_match = re.search(r"\d+", page_text)
        if page_match:
            locator["page"] = int(page_match.group())

        candidate_key = _bounded_hash(
            "row:", f"{workflow.id}:{row_index}:{name}:{raw_value}:{raw_unit}", limit=128
        )
        candidate = HealthReportFieldCandidate(
            workflow_id=workflow.id,
            user_id=workflow.user_id,
            subject_user_id=workflow.subject_user_id,
            candidate_key=candidate_key,
            canonical_code=None,
            canonical_name=name,
            raw_name=name,
            raw_value=raw_value,
            raw_unit=raw_unit or None,
            normalized_value=numeric_value,
            normalized_text=normalized_text,
            normalized_unit=raw_unit or None,
            reference_low=reference_low,
            reference_high=reference_high,
            reference_text=reference_text or None,
            abnormal_state=abnormal,
            confidence=confidence,
            effective_at=_effective_at(doc),
            source_locator=locator,
            review_status="auto_accepted" if auto_accepted else "pending_review",
            requires_review=not auto_accepted,
            model_version="legacy-ocr-adapter-v1",
            version=1,
        )
        db.add(candidate)
        candidates.append(candidate)

    if not candidates:
        workflow.status = "failed"
        workflow.failure_code = "no_reviewable_candidates"
        workflow.failure_detail = "OCR completed but produced no reviewable report fields."
        workflow.version += 1
        db.flush()
        return []

    db.flush()
    # Individually high-confidence rows may still contradict one another. Such
    # conflicts are server-owned review conditions and must never auto-admit.
    conflicts = _candidate_conflicts(candidates)
    for candidate in candidates:
        if conflicts.get(candidate.id):
            candidate.review_status = "pending_review"
            candidate.requires_review = True

    workflow.status = "awaiting_confirmation"
    workflow.recognized_at = _utcnow()
    workflow.failure_code = None
    workflow.failure_detail = None
    workflow.version += 1
    db.flush()
    # Semantic duplicates are proposals only. A pending decision keeps the
    # legacy workflow in its legal ``recognizing`` state and blocks admission.
    from app.services.report_duplicate_service import ensure_semantic_duplicate_decision

    ensure_semantic_duplicate_decision(db, workflow=workflow, candidates=candidates)
    return candidates


def mark_workflow_failed(db: Session, workflow: HealthReportWorkflow, code: str, detail: str) -> None:
    if code == "duplicate":
        raise ValueError("Duplicate reports must reuse the existing workflow, not become failures")
    if workflow.status in _FINAL_WORKFLOW_STATUSES or workflow.status == "committing":
        return
    workflow.status = "failed"
    workflow.failure_code = code[:80]
    workflow.failure_detail = detail[:2000]
    workflow.version += 1


def _candidate_conflicts(candidates: list[HealthReportFieldCandidate]) -> dict[int, list[str]]:
    groups: dict[str, list[HealthReportFieldCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.canonical_name.strip().casefold(), []).append(candidate)
    result: dict[int, list[str]] = {candidate.id: [] for candidate in candidates}
    for group in groups.values():
        units = {str(item.normalized_unit).strip().casefold() for item in group if item.normalized_unit}
        references = {str(item.reference_text).strip().casefold() for item in group if item.reference_text}
        values = {
            (str(item.normalized_value) if item.normalized_value is not None else item.normalized_text or "")
            for item in group
        }
        for candidate in group:
            reasons = result[candidate.id]
            if len(units) > 1:
                reasons.append("unit_conflict")
            elif units and not candidate.normalized_unit:
                reasons.append("unit_missing")
            if len(references) > 1:
                reasons.append("reference_range_conflict")
            if len(group) > 1 and len(values) > 1:
                reasons.append("duplicate_value_conflict")
            if candidate.reference_text and _RANGE_RE.match(candidate.reference_text):
                match = _RANGE_RE.match(candidate.reference_text)
                if match and Decimal(match.group(1)) > Decimal(match.group(2)):
                    reasons.append("invalid_reference_range")
    return result


def _candidate_payload(
    candidate: HealthReportFieldCandidate, conflicts: dict[int, list[str]]
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "candidate_key": candidate.candidate_key,
        "version": candidate.version,
        "canonical_code": candidate.canonical_code,
        "canonical_name": candidate.canonical_name,
        "raw_name": candidate.raw_name,
        "raw_value": candidate.raw_value,
        "raw_unit": candidate.raw_unit,
        "normalized_value": candidate.normalized_value,
        "normalized_text": candidate.normalized_text,
        "normalized_unit": candidate.normalized_unit,
        "reference_low": candidate.reference_low,
        "reference_high": candidate.reference_high,
        "reference_text": candidate.reference_text,
        "abnormal_state": candidate.abnormal_state,
        "confidence": candidate.confidence,
        "effective_at": candidate.effective_at,
        "source_locator": candidate.source_locator or {},
        "model_version": candidate.model_version,
        "review_status": candidate.review_status,
        "requires_review": candidate.requires_review,
        "low_confidence": (
            candidate.confidence is None or candidate.confidence < AUTO_ACCEPT_CONFIDENCE
        ),
        "conflict_reasons": conflicts.get(candidate.id, []),
    }


def _failure_recovery_payload(workflow: HealthReportWorkflow) -> dict[str, Any] | None:
    code = workflow.failure_code
    if not code:
        return None
    policy = _FAILURE_RECOVERY.get(
        code,
        {
            "recovery_action": "contact_support",
            "retryable": False,
            "allows_manual_candidate": False,
        },
    )
    return {"failure_code": code, **policy}


def build_review(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int
) -> dict[str, Any]:
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not workflow or is_withdrawn(workflow):
        raise HTTPException(status_code=404, detail="Report workflow not found")
    candidates = db.execute(
        select(HealthReportFieldCandidate)
        .where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == user_id,
            HealthReportFieldCandidate.subject_user_id == subject_user_id,
        )
        .order_by(HealthReportFieldCandidate.id)
    ).scalars().all()
    admitted_count = db.scalar(
        select(func.count()).select_from(ConfirmedHealthObservation).where(
            ConfirmedHealthObservation.workflow_id == workflow.id,
            ConfirmedHealthObservation.user_id == user_id,
            ConfirmedHealthObservation.subject_user_id == subject_user_id,
            ConfirmedHealthObservation.status == "active",
        )
    ) or 0
    doc = db.get(HealthDocument, workflow.legacy_document_id) if workflow.legacy_document_id else None
    conflicts = _candidate_conflicts(list(candidates))
    return {
        "workflow_id": workflow.id,
        "legacy_document_id": workflow.legacy_document_id,
        "subject_user_id": workflow.subject_user_id,
        "status": workflow.status,
        "version": workflow.version,
        "report_type": workflow.report_type,
        "document_fingerprint": workflow.document_fingerprint,
        "recognized_at": workflow.recognized_at,
        "confirmed_at": workflow.confirmed_at,
        "completed_at": workflow.completed_at,
        "confirmation_client_event_id": workflow.confirmation_client_event_id,
        "failure_code": workflow.failure_code,
        "failure_detail": workflow.failure_detail,
        "failure_recovery": _failure_recovery_payload(workflow),
        "pending_review_count": sum(item.review_status == "pending_review" for item in candidates),
        "auto_accepted_count": sum(item.review_status == "auto_accepted" for item in candidates),
        "admitted_observation_count": int(admitted_count),
        "requires_report_confirmation": workflow.status not in _FINAL_WORKFLOW_STATUSES,
        "can_confirm": workflow.status in {"awaiting_confirmation", "committing"},
        "document": document_out(doc, workflow) if doc else None,
        "candidates": [_candidate_payload(item, conflicts) for item in candidates],
    }


def derive_report_runtime_state(
    db: Session, *, workflow: HealthReportWorkflow, pending_review_count: int
) -> dict[str, Any]:
    """Return the one server-owned state/action mapping used by every client."""

    from app.services.report_duplicate_service import pending_semantic_decision

    duplicate = pending_semantic_decision(
        db,
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
    )
    if duplicate:
        state = "awaiting_duplicate_decision"
        action = {
            "code": "resolve_duplicate",
            "enabled": True,
            "pending_count": 1,
            "target_workflow_id": duplicate.matched_workflow_id,
        }
    elif workflow.status in {"draft", "uploading"}:
        state = "uploading"
        action = {"code": "uploading", "enabled": False, "pending_count": 0}
    elif workflow.status == "recognizing":
        state = "recognizing"
        action = {"code": "recognizing", "enabled": False, "pending_count": 0}
    elif workflow.status == "awaiting_confirmation" and pending_review_count:
        state = "awaiting_confirmation"
        action = {
            "code": "review_fields",
            "enabled": True,
            "pending_count": pending_review_count,
        }
    elif workflow.status == "awaiting_confirmation":
        state = "ready_for_report_confirmation"
        action = {"code": "confirm_and_update_scores", "enabled": True, "pending_count": 0}
    elif workflow.status == "committing":
        state = "committing"
        action = {"code": "committing", "enabled": False, "pending_count": 0}
    elif workflow.status == "completed_score_pending":
        state = "completed_score_pending"
        action = {"code": "view_interpretation", "enabled": True, "pending_count": 0}
    elif workflow.status == "completed":
        state = "completed"
        action = {"code": "view_interpretation", "enabled": True, "pending_count": 0}
    elif workflow.failure_code == "semantic_duplicate_use_existing":
        state = "duplicate_reused"
        action = {"code": "open_existing_report", "enabled": True, "pending_count": 0}
    else:
        state = "failed"
        recovery = _failure_recovery_payload(workflow)
        action = {
            "code": (recovery or {}).get("recovery_action", "contact_support"),
            "enabled": bool((recovery or {}).get("retryable")),
            "pending_count": 0,
        }
    return {
        "workflow_id": workflow.id,
        "workflow_version": workflow.version,
        "subject_user_id": workflow.subject_user_id,
        "state": state,
        "workflow_status": workflow.status,
        "failure_code": workflow.failure_code,
        "primary_action": action,
    }


def build_report_runtime(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int
) -> dict[str, Any]:
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not workflow or is_withdrawn(workflow):
        raise HTTPException(status_code=404, detail="Report workflow not found")
    pending = int(
        db.scalar(
            select(func.count()).select_from(HealthReportFieldCandidate).where(
                HealthReportFieldCandidate.workflow_id == workflow.id,
                HealthReportFieldCandidate.user_id == user_id,
                HealthReportFieldCandidate.subject_user_id == subject_user_id,
                HealthReportFieldCandidate.review_status == "pending_review",
            )
        )
        or 0
    )
    return derive_report_runtime_state(db, workflow=workflow, pending_review_count=pending)


_NON_DIAGNOSTIC_NOTICE = (
    "本解读仅依据已确认的报告字段与服务端实际评分快照整理，"
    "不构成诊断或治疗建议。"
)
_FOLLOW_UP_UNAVAILABLE = (
    "当前没有经过确认的随访或复查建议数据；系统不会根据异常值自行推断。"
)


def _interpretation_unavailable_reason(workflow: HealthReportWorkflow) -> str | None:
    if workflow.status in _FINAL_WORKFLOW_STATUSES:
        return None
    if workflow.status in {"draft", "uploading"}:
        return "报告仍在上传，完成识别与字段确认后才可查看本次解读。"
    if workflow.status == "recognizing":
        return "报告仍在识别，完成字段确认后才可查看本次解读。"
    if workflow.status == "awaiting_confirmation":
        return "请先检查待确认字段并确认入库，之后才可查看本次解读。"
    if workflow.status == "committing":
        return "报告正在入库，完成后即可查看本次解读。"
    if workflow.status == "failed":
        return "报告处理未完成，请按失败原因重新上传或恢复后再查看本次解读。"
    return "报告尚未完成确认，暂不能查看本次解读。"


def _observation_payload(observation: ConfirmedHealthObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.id,
        "source_candidate_id": observation.source_candidate_id,
        "confirmation_event_id": observation.confirmation_event_id,
        "canonical_code": observation.canonical_code,
        "canonical_name": observation.canonical_name,
        "value_numeric": observation.value_numeric,
        "value_text": observation.value_text,
        "unit": observation.unit,
        "reference_low": observation.reference_low,
        "reference_high": observation.reference_high,
        "reference_text": observation.reference_text,
        "abnormal_state": observation.abnormal_state,
        "effective_at": observation.effective_at,
        "confirmed_at": observation.confirmed_at,
    }


def _score_interpretation_state(
    workflow: HealthReportWorkflow, snapshots: list[HealthScoreSnapshot]
) -> tuple[str, bool]:
    statuses = {snapshot.calculation_status for snapshot in snapshots}
    score_pending = workflow.status == "completed_score_pending" or "pending" in statuses
    if not statuses:
        return ("pending", True) if score_pending else ("unavailable", False)
    if "pending" in statuses:
        return "pending", True
    if statuses == {"completed"}:
        return "completed", score_pending
    if "completed" in statuses and "failed" in statuses:
        return "partial_failed", score_pending
    if statuses == {"failed"}:
        return "failed", score_pending
    return "unavailable", score_pending


def build_interpretation(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int, locale: str = "zh-Hans"
) -> dict[str, Any]:
    """Return only durable post-confirmation evidence; never invent clinical meaning."""
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not workflow or is_withdrawn(workflow):
        raise HTTPException(status_code=404, detail="Report workflow not found")

    doc = db.get(HealthDocument, workflow.legacy_document_id) if workflow.legacy_document_id else None
    unavailable_reason = _interpretation_unavailable_reason(workflow)
    if unavailable_reason is not None:
        return {
            "workflow_id": workflow.id,
            "subject_user_id": workflow.subject_user_id,
            "status": workflow.status,
            "available": False,
            "unavailable_reason": unavailable_reason,
            "non_diagnostic_notice": _NON_DIAGNOSTIC_NOTICE,
            "document": document_out(doc, workflow) if doc else None,
            "candidates": [],
            "confirmation_events": [],
            "structured_additions": [],
            "major_abnormalities": [],
            "follow_up": {
                "available": False,
                "items": [],
                "unavailable_reason": _FOLLOW_UP_UNAVAILABLE,
            },
            "profile_impacts": [],
            "score_state": "unavailable",
            "score_pending": False,
            "score_snapshots": [],
            "score_details": {},
        }

    candidates = db.execute(
        select(HealthReportFieldCandidate)
        .where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == user_id,
            HealthReportFieldCandidate.subject_user_id == subject_user_id,
        )
        .order_by(HealthReportFieldCandidate.id)
    ).scalars().all()
    conflicts = _candidate_conflicts(list(candidates))
    events = db.execute(
        select(HealthReportConfirmationEvent)
        .where(
            HealthReportConfirmationEvent.workflow_id == workflow.id,
            HealthReportConfirmationEvent.user_id == user_id,
            HealthReportConfirmationEvent.subject_user_id == subject_user_id,
        )
        .order_by(HealthReportConfirmationEvent.id)
    ).scalars().all()
    observations = db.execute(
        select(ConfirmedHealthObservation)
        .where(
            ConfirmedHealthObservation.workflow_id == workflow.id,
            ConfirmedHealthObservation.user_id == user_id,
            ConfirmedHealthObservation.subject_user_id == subject_user_id,
            ConfirmedHealthObservation.status == "active",
        )
        .order_by(ConfirmedHealthObservation.id)
    ).scalars().all()
    observation_payloads = [_observation_payload(item) for item in observations]

    profile_rows = db.execute(
        select(HealthProfileCandidate, HealthProfileSource)
        .join(
            HealthProfileSource,
            and_(
                HealthProfileSource.candidate_id == HealthProfileCandidate.id,
                HealthProfileSource.user_id == HealthProfileCandidate.user_id,
                HealthProfileSource.subject_user_id == HealthProfileCandidate.subject_user_id,
            ),
        )
        .join(
            ConfirmedHealthObservation,
            and_(
                ConfirmedHealthObservation.id == HealthProfileSource.source_observation_id,
                ConfirmedHealthObservation.user_id == HealthProfileSource.user_id,
                ConfirmedHealthObservation.subject_user_id == HealthProfileSource.subject_user_id,
            ),
        )
        .where(
            ConfirmedHealthObservation.workflow_id == workflow.id,
            ConfirmedHealthObservation.status == "active",
            HealthProfileCandidate.user_id == user_id,
            HealthProfileCandidate.subject_user_id == subject_user_id,
            HealthProfileSource.source_type == "report_observation",
        )
        .order_by(HealthProfileCandidate.id, HealthProfileSource.id)
    ).all()
    snapshots = list(
        db.execute(
            select(HealthScoreSnapshot)
            .where(
                HealthScoreSnapshot.source_report_workflow_id == workflow.id,
                HealthScoreSnapshot.user_id == user_id,
                HealthScoreSnapshot.subject_user_id == subject_user_id,
                HealthScoreSnapshot.score_kind.in_(REPORT_ADMISSION_SCORE_KINDS),
            )
            .order_by(HealthScoreSnapshot.score_kind, HealthScoreSnapshot.id)
        ).scalars().all()
    )
    score_state, score_pending = _score_interpretation_state(workflow, snapshots)
    from app.services.report_follow_up_service import follow_up_presentation
    from app.services.report_score_job_service import score_item_presentations

    follow_up = follow_up_presentation(
        db,
        workflow_id=workflow.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        locale=locale,
    )
    score_presentations = score_item_presentations(
        db,
        workflow_id=workflow.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        locale=locale,
    )
    from app.models.health_trust_expansion import HealthReportScoreJob

    latest_score_job = db.execute(
        select(HealthReportScoreJob)
        .where(
            HealthReportScoreJob.workflow_id == workflow.id,
            HealthReportScoreJob.user_id == user_id,
            HealthReportScoreJob.subject_user_id == subject_user_id,
        )
        .order_by(HealthReportScoreJob.input_revision.desc())
    ).scalars().first()
    if latest_score_job and latest_score_job.status in {"partial_failed", "failed", "completed"}:
        score_state = latest_score_job.status
    return {
        "workflow_id": workflow.id,
        "subject_user_id": workflow.subject_user_id,
        "status": workflow.status,
        "available": True,
        "unavailable_reason": None,
        "non_diagnostic_notice": _NON_DIAGNOSTIC_NOTICE,
        "document": document_out(doc, workflow) if doc else None,
        "candidates": [_candidate_payload(item, conflicts) for item in candidates],
        "confirmation_events": [
            {
                "event_id": event.id,
                "candidate_id": event.candidate_id,
                "event_type": event.event_type,
                "candidate_version": event.candidate_version,
                "before_data": event.before_data or {},
                "after_data": event.after_data or {},
                "created_at": event.created_at,
            }
            for event in events
        ],
        "structured_additions": observation_payloads,
        "major_abnormalities": [
            payload
            for payload in observation_payloads
            if payload["abnormal_state"] == "abnormal"
        ],
        "follow_up": follow_up,
        "profile_impacts": [
            {
                "profile_candidate_id": candidate.id,
                "source_id": source.id,
                "source_observation_id": source.source_observation_id,
                "fact_key": candidate.fact_key,
                "category": candidate.category,
                "proposed_value": candidate.proposed_value or {},
                "review_status": candidate.review_status,
                "confidence": candidate.confidence,
            }
            for candidate, source in profile_rows
        ],
        "score_state": score_state,
        "score_pending": score_pending,
        "score_details": score_presentations,
        "score_snapshots": [
            {
                "snapshot_id": snapshot.id,
                "score_kind": snapshot.score_kind,
                "algorithm_id": snapshot.algorithm_id,
                "algorithm_version": snapshot.algorithm_version,
                "before_value": snapshot.before_value,
                "after_value": snapshot.after_value,
                "before_confidence": snapshot.before_confidence,
                "after_confidence": snapshot.after_confidence,
                "score_direction": snapshot.score_direction,
                "semantic_outcome": snapshot.semantic_outcome,
                "calculation_status": snapshot.calculation_status,
                "evidence": snapshot.evidence or {},
                "missing_inputs": snapshot.missing_inputs or {},
                "failure_code": snapshot.failure_code,
                "computed_at": snapshot.computed_at,
                **score_presentations.get(snapshot.score_kind, {}),
            }
            for snapshot in snapshots
        ],
    }


def _decimal_snapshot(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _datetime_snapshot(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _manual_request_snapshot(payload: HealthReportManualCandidateIn) -> dict[str, Any]:
    return {
        "workflow_version": payload.workflow_version,
        "canonical_code": payload.canonical_code,
        "canonical_name": payload.canonical_name,
        "raw_name": payload.raw_name,
        "value_numeric": _decimal_snapshot(payload.value_numeric),
        "value_text": payload.value_text,
        "unit": payload.unit,
        "reference_low": _decimal_snapshot(payload.reference_low),
        "reference_high": _decimal_snapshot(payload.reference_high),
        "reference_text": payload.reference_text,
        "effective_at": _datetime_snapshot(payload.effective_at),
    }


def _existing_manual_event_review(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    payload: HealthReportManualCandidateIn,
    request_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    event = db.execute(
        select(HealthReportConfirmationEvent).where(
            HealthReportConfirmationEvent.user_id == user_id,
            HealthReportConfirmationEvent.subject_user_id == payload.subject_user_id,
            HealthReportConfirmationEvent.client_event_id == payload.client_event_id,
        )
    ).scalars().first()
    if not event:
        return None
    if event.event_type != "manual_add":
        raise HTTPException(status_code=409, detail="client_event_id is already bound to another event")
    if event.workflow_id != workflow_id:
        raise HTTPException(status_code=409, detail="client_event_id is already bound to another report")
    if (event.after_data or {}).get("request") != request_snapshot:
        raise HTTPException(status_code=409, detail="client_event_id payload does not match the original request")
    candidate = db.execute(
        select(HealthReportFieldCandidate.id).where(
            HealthReportFieldCandidate.id == event.candidate_id,
            HealthReportFieldCandidate.workflow_id == workflow_id,
            HealthReportFieldCandidate.user_id == user_id,
            HealthReportFieldCandidate.subject_user_id == payload.subject_user_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=409, detail="Manual candidate event has no matching candidate")
    return build_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    )


def _manual_abnormal_state(payload: HealthReportManualCandidateIn) -> str:
    value = payload.value_numeric
    if value is None:
        return "unknown"
    if payload.reference_low is not None and value < payload.reference_low:
        return "abnormal"
    if payload.reference_high is not None and value > payload.reference_high:
        return "abnormal"
    if payload.reference_low is not None or payload.reference_high is not None:
        return "normal"
    return "unknown"


def add_manual_candidate(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    payload: HealthReportManualCandidateIn,
) -> dict[str, Any]:
    """Create an auditable proposal without admitting it to any consumer."""
    if payload.subject_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="Manual report candidates are limited to the account owner",
        )
    request_snapshot = _manual_request_snapshot(payload)
    existing = _existing_manual_event_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        payload=payload,
        request_snapshot=request_snapshot,
    )
    if existing is not None:
        return existing

    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not workflow or is_withdrawn(workflow):
        raise HTTPException(status_code=404, detail="Report workflow not found")

    # Recheck after the workflow lock so same-workflow concurrent retries see
    # the event created by the request that acquired the lock first.
    existing = _existing_manual_event_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        payload=payload,
        request_snapshot=request_snapshot,
    )
    if existing is not None:
        return existing

    recoverable_failure = (
        workflow.status == "failed" and workflow.failure_code == "no_reviewable_candidates"
    )
    if workflow.status != "awaiting_confirmation" and not recoverable_failure:
        raise HTTPException(
            status_code=409,
            detail=f"Manual candidates cannot be added from {workflow.status}",
        )
    if workflow.version != payload.workflow_version:
        raise HTTPException(status_code=409, detail="Report workflow version is stale")

    now = _utcnow()
    effective_at = payload.effective_at
    if effective_at is None:
        doc = db.get(HealthDocument, workflow.legacy_document_id) if workflow.legacy_document_id else None
        effective_at = _effective_at(doc) if doc else now
    elif effective_at.tzinfo is None:
        effective_at = effective_at.replace(tzinfo=timezone.utc)
    else:
        effective_at = effective_at.astimezone(timezone.utc)

    numeric_text = _decimal_snapshot(payload.value_numeric)
    raw_value = numeric_text if numeric_text is not None else payload.value_text
    candidate_key = _bounded_hash(
        "manual:",
        f"{user_id}:{payload.subject_user_id}:{payload.client_event_id}",
        limit=128,
    )
    source_locator: dict[str, Any] = {
        "source_type": "manual",
        "entry_method": "report_review",
        "workflow_id": workflow.id,
    }
    if workflow.legacy_document_id is not None:
        source_locator["document_id"] = workflow.legacy_document_id
    candidate = HealthReportFieldCandidate(
        workflow_id=workflow.id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        candidate_key=candidate_key,
        canonical_code=payload.canonical_code,
        canonical_name=payload.canonical_name,
        raw_name=payload.raw_name,
        raw_value=raw_value,
        raw_unit=payload.unit,
        normalized_value=payload.value_numeric,
        normalized_text=payload.value_text,
        normalized_unit=payload.unit,
        reference_low=payload.reference_low,
        reference_high=payload.reference_high,
        reference_text=payload.reference_text,
        abnormal_state=_manual_abnormal_state(payload),
        confidence=None,
        effective_at=effective_at,
        source_locator=source_locator,
        review_status="pending_review",
        requires_review=True,
        model_version="manual-entry-v1",
        version=1,
    )
    db.add(candidate)
    db.flush()

    # A manual proposal can reveal a conflict with a row that was previously
    # safe to auto-accept. Once that conflict exists, both values must be
    # presented for review; the older row cannot remain an implicit decision.
    workflow_candidates = db.execute(
        select(HealthReportFieldCandidate).where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == user_id,
            HealthReportFieldCandidate.subject_user_id == payload.subject_user_id,
        )
    ).scalars().all()
    conflicts = _candidate_conflicts(list(workflow_candidates))
    for workflow_candidate in workflow_candidates:
        if conflicts.get(workflow_candidate.id) and workflow_candidate.review_status == "auto_accepted":
            workflow_candidate.review_status = "pending_review"
            workflow_candidate.requires_review = True

    event = HealthReportConfirmationEvent(
        workflow_id=workflow.id,
        candidate_id=candidate.id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        actor_user_id=user_id,
        client_event_id=payload.client_event_id,
        event_type="manual_add",
        candidate_version=candidate.version,
        before_data={},
        after_data={
            "request": request_snapshot,
            "candidate_id": candidate.id,
            "candidate_key": candidate.candidate_key,
            "candidate_version": candidate.version,
            "review_status": candidate.review_status,
            "requires_review": candidate.requires_review,
        },
    )
    db.add(event)
    workflow.status = "awaiting_confirmation"
    workflow.recognized_at = workflow.recognized_at or now
    workflow.failure_code = None
    workflow.failure_detail = None
    workflow.version += 1
    try:
        db.commit()
    except IntegrityError:
        # The event uniqueness constraint is the final cross-workflow race
        # boundary. Recover an identical retry; reject any different owner.
        db.rollback()
        recovered = _existing_manual_event_review(
            db,
            workflow_id=workflow_id,
            user_id=user_id,
            payload=payload,
            request_snapshot=request_snapshot,
        )
        if recovered is not None:
            return recovered
        raise

    return build_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    )


def _decision_dict(payload: HealthReportConfirmIn) -> dict[int, dict[str, Any]]:
    decisions: dict[int, dict[str, Any]] = {}
    for item in payload.decisions:
        if item.candidate_id in decisions:
            raise HTTPException(status_code=422, detail="Duplicate candidate decision")
        numeric = item.value_numeric
        text = item.value_text.strip() if item.value_text else None
        if item.action == "correct" and ((numeric is None) == (text is None)):
            raise HTTPException(
                status_code=422,
                detail="Correction requires exactly one of value_numeric or value_text",
            )
        if item.action != "correct" and (numeric is not None or text is not None):
            raise HTTPException(status_code=422, detail="Only correction may replace a value")
        decisions[item.candidate_id] = {
            "candidate_id": item.candidate_id,
            "candidate_version": item.candidate_version,
            "action": item.action,
            "value_numeric": str(numeric) if numeric is not None else None,
            "value_text": text,
            "unit": item.unit.strip() if item.unit else None,
        }
    return decisions


def _prepare_confirmation(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    payload: HealthReportConfirmIn,
) -> HealthReportWorkflow:
    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == payload.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not workflow or is_withdrawn(workflow):
        raise HTTPException(status_code=404, detail="Report workflow not found")
    if workflow.status in _FINAL_WORKFLOW_STATUSES:
        if workflow.confirmation_client_event_id == payload.client_event_id:
            return workflow
        raise HTTPException(status_code=409, detail="Report is already confirmed")
    if workflow.status == "committing":
        if workflow.confirmation_client_event_id != payload.client_event_id:
            raise HTTPException(status_code=409, detail="Another confirmation is committing")
        return workflow
    if workflow.status != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail=f"Report cannot be confirmed from {workflow.status}")
    from app.services.report_duplicate_service import pending_semantic_decision

    if pending_semantic_decision(
        db,
        workflow_id=workflow.id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    ):
        raise HTTPException(status_code=409, detail="Semantic duplicate decision is required")
    if workflow.version != payload.workflow_version:
        raise HTTPException(status_code=409, detail="Report workflow version is stale")
    event_owner = db.execute(
        select(HealthReportWorkflow.id).where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == payload.subject_user_id,
            HealthReportWorkflow.confirmation_client_event_id == payload.client_event_id,
            HealthReportWorkflow.id != workflow.id,
        )
    ).scalar_one_or_none()
    if event_owner is not None:
        raise HTTPException(status_code=409, detail="client_event_id is already bound to another report")

    candidates = db.execute(
        select(HealthReportFieldCandidate).where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == user_id,
            HealthReportFieldCandidate.subject_user_id == payload.subject_user_id,
        )
    ).scalars().all()
    by_id = {item.id: item for item in candidates}
    decisions = _decision_dict(payload)
    if set(decisions) - set(by_id):
        raise HTTPException(status_code=422, detail="Decision references an unknown candidate")
    missing = [
        item.id
        for item in candidates
        if item.review_status == "pending_review" and item.id not in decisions
    ]
    if missing:
        raise HTTPException(status_code=422, detail={"code": "pending_decisions_required", "candidate_ids": missing})
    for candidate_id, decision in decisions.items():
        candidate = by_id[candidate_id]
        if candidate.version != decision["candidate_version"]:
            raise HTTPException(status_code=409, detail=f"Candidate {candidate_id} version is stale")

    now = _utcnow()
    metadata = dict(workflow.workflow_metadata or {})
    metadata["confirmation_decisions"] = list(decisions.values())
    metadata["confirmation_workflow_version"] = payload.workflow_version
    workflow.workflow_metadata = metadata
    workflow.confirmed_at = now
    workflow.confirmed_by_user_id = user_id
    workflow.confirmation_client_event_id = payload.client_event_id
    workflow.status = "committing"
    workflow.version += 1
    db.commit()
    db.refresh(workflow)
    return workflow


def _event_snapshot(candidate: HealthReportFieldCandidate) -> dict[str, Any]:
    return {
        "value_numeric": str(candidate.normalized_value) if candidate.normalized_value is not None else None,
        "value_text": candidate.normalized_text,
        "unit": candidate.normalized_unit,
        "abnormal_state": candidate.abnormal_state,
        "review_status": candidate.review_status,
        "version": candidate.version,
    }


def _admit_candidate(
    db: Session,
    *,
    workflow: HealthReportWorkflow,
    candidate: HealthReportFieldCandidate,
    decision: dict[str, Any],
) -> None:
    before = _event_snapshot(candidate)
    action = decision["action"]
    numeric = candidate.normalized_value
    text = candidate.normalized_text
    unit = candidate.normalized_unit
    if action == "correct":
        numeric = Decimal(decision["value_numeric"]) if decision.get("value_numeric") is not None else None
        text = decision.get("value_text")
        unit = decision.get("unit") if decision.get("unit") is not None else unit
        candidate.normalized_value = numeric
        candidate.normalized_text = text
        candidate.normalized_unit = unit
        if numeric is not None:
            if candidate.reference_low is not None and numeric < candidate.reference_low:
                candidate.abnormal_state = "abnormal"
            elif candidate.reference_high is not None and numeric > candidate.reference_high:
                candidate.abnormal_state = "abnormal"
            elif candidate.reference_low is not None or candidate.reference_high is not None:
                candidate.abnormal_state = "normal"
            else:
                candidate.abnormal_state = "unknown"
        else:
            candidate.abnormal_state = "unknown"
        candidate.review_status = "corrected"
    elif action == "reject":
        candidate.review_status = "rejected"
    else:
        candidate.review_status = "confirmed"
    candidate.requires_review = False
    candidate.version += 1

    event = HealthReportConfirmationEvent(
        workflow_id=workflow.id,
        candidate_id=candidate.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        actor_user_id=workflow.confirmed_by_user_id,
        client_event_id=_bounded_hash(
            "field:", f"{workflow.confirmation_client_event_id}:{candidate.id}"
        ),
        event_type=action,
        candidate_version=decision["candidate_version"],
        before_data=before,
        after_data={
            "value_numeric": str(numeric) if numeric is not None else None,
            "value_text": text,
            "unit": unit,
            "abnormal_state": candidate.abnormal_state,
            "review_status": candidate.review_status,
            "version": candidate.version,
        },
    )
    db.add(event)
    db.flush()
    if action == "reject":
        return
    from app.services.report_follow_up_service import is_clinician_follow_up_candidate

    # Confirmed clinician statements are follow-up evidence, not physiological
    # observations. Keeping them out of observation consumers prevents advice
    # text from entering trends, profile facts, AI metrics, or score inputs.
    if is_clinician_follow_up_candidate(candidate):
        return
    if (numeric is None) == (text is None):
        raise RuntimeError(f"Candidate {candidate.id} does not have exactly one normalized value")
    now = workflow.confirmed_at or _utcnow()
    observation = ConfirmedHealthObservation(
        workflow_id=workflow.id,
        source_candidate_id=candidate.id,
        confirmation_event_id=event.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        report_confirmation_client_event_id=workflow.confirmation_client_event_id,
        idempotency_key=_bounded_hash(
            "obs:", f"{workflow.confirmation_client_event_id}:{candidate.id}", limit=96
        ),
        canonical_code=candidate.canonical_code,
        canonical_name=candidate.canonical_name,
        value_numeric=numeric,
        value_text=text,
        unit=unit,
        reference_low=candidate.reference_low,
        reference_high=candidate.reference_high,
        reference_text=candidate.reference_text,
        abnormal_state=candidate.abnormal_state,
        effective_at=candidate.effective_at or now,
        status="active",
        confirmed_by_user_id=workflow.confirmed_by_user_id,
        confirmed_at=now,
        version=1,
    )
    db.add(observation)


def invalidate_trusted_report_consumers(db: Session, *, user_id: int) -> None:
    db.execute(delete(HealthDocumentSummary).where(HealthDocumentSummary.user_id == user_id))
    db.execute(delete(HealthSummary).where(HealthSummary.user_id == user_id))


def _complete_confirmation(
    db: Session, *, workflow_id: int, user_id: int, client_event_id: str
) -> None:
    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
        )
        .with_for_update()
    ).scalars().one()
    if workflow.status in _FINAL_WORKFLOW_STATUSES:
        return
    if workflow.status != "committing" or workflow.confirmation_client_event_id != client_event_id:
        raise HTTPException(status_code=409, detail="Confirmation recovery token does not match")
    candidates = db.execute(
        select(HealthReportFieldCandidate)
        .where(
            HealthReportFieldCandidate.workflow_id == workflow.id,
            HealthReportFieldCandidate.user_id == workflow.user_id,
            HealthReportFieldCandidate.subject_user_id == workflow.subject_user_id,
        )
        .order_by(HealthReportFieldCandidate.id)
    ).scalars().all()
    decision_rows = (workflow.workflow_metadata or {}).get("confirmation_decisions") or []
    decisions = {int(item["candidate_id"]): item for item in decision_rows}
    for candidate in candidates:
        decision = decisions.get(candidate.id)
        if decision is None:
            if candidate.review_status != "auto_accepted":
                raise RuntimeError(f"Pending candidate {candidate.id} has no persisted decision")
            decision = {
                "candidate_id": candidate.id,
                "candidate_version": candidate.version,
                "action": "confirm",
                "value_numeric": None,
                "value_text": None,
                "unit": None,
            }
        _admit_candidate(db, workflow=workflow, candidate=candidate, decision=decision)

    db.flush()
    from app.services.report_follow_up_service import generate_follow_ups
    from app.services.report_score_job_service import enqueue_score_job

    generate_follow_ups(db, workflow=workflow)
    enqueue_score_job(db, workflow=workflow)
    workflow.status = "completed_score_pending"
    workflow.completed_at = _utcnow()
    workflow.version += 1
    db.flush()
    # A confirmed report may propose a profile update, but it can never write a
    # profile fact. Candidate acceptance is a separate user confirmation event.
    from app.services.health_profile_trust_service import (
        generate_candidates_from_admitted_observations,
    )

    generate_candidates_from_admitted_observations(
        db,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
    )
    invalidate_trusted_report_consumers(db, user_id=user_id)
    db.commit()


def confirm_workflow(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    payload: HealthReportConfirmIn,
) -> dict[str, Any]:
    """Persist a recoverable committing boundary, then atomically admit fields."""
    workflow = _prepare_confirmation(db, workflow_id=workflow_id, user_id=user_id, payload=payload)
    if workflow.status == "committing":
        try:
            _complete_confirmation(
                db,
                workflow_id=workflow.id,
                user_id=user_id,
                client_event_id=payload.client_event_id,
            )
        except Exception:
            db.rollback()
            raise
    return build_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
    )


def active_observations(db: Session, *, user_id: int) -> list[ConfirmedHealthObservation]:
    return list(
        db.execute(
            select(ConfirmedHealthObservation)
            .join(
                HealthReportWorkflow,
                HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
            )
            .where(
                ConfirmedHealthObservation.user_id == user_id,
                ConfirmedHealthObservation.subject_user_id == user_id,
                ConfirmedHealthObservation.status == "active",
                HealthReportWorkflow.user_id == user_id,
                HealthReportWorkflow.subject_user_id == user_id,
                HealthReportWorkflow.status.in_(tuple(_FINAL_WORKFLOW_STATUSES)),
            )
            .order_by(ConfirmedHealthObservation.effective_at, ConfirmedHealthObservation.id)
        ).scalars().all()
    )


def has_active_observations(db: Session, *, user_id: int) -> bool:
    return bool(
        db.scalar(
            select(func.count()).select_from(ConfirmedHealthObservation).join(
                HealthReportWorkflow,
                HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
            ).where(
                ConfirmedHealthObservation.user_id == user_id,
                ConfirmedHealthObservation.subject_user_id == user_id,
                ConfirmedHealthObservation.status == "active",
                HealthReportWorkflow.status.in_(tuple(_FINAL_WORKFLOW_STATUSES)),
            )
        )
    )


def observation_indicator_map(db: Session, *, user_id: int) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for observation in active_observations(db, user_id=user_id):
        if observation.value_numeric is None:
            continue
        date_value = observation.effective_at.date().isoformat()
        result.setdefault(observation.canonical_name, []).append(
            {
                "date": date_value,
                "value": float(observation.value_numeric),
                "unit": observation.unit or "",
                "ref_range": observation.reference_text or "",
                "abnormal": observation.abnormal_state == "abnormal",
                "source": "document",
                "measured_at": observation.effective_at.isoformat(),
                "source_id": f"report-observation:{observation.id}",
                "record_id": observation.id,
            }
        )
    return result


def withdraw_document(
    db: Session, *, document_id: int, user_id: int
) -> tuple[bool, str | None]:
    """Retract trusted effects while retaining the immutable report audit chain."""
    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.legacy_document_id == document_id,
        )
        .with_for_update()
    ).scalars().first()
    if not workflow:
        return False, None
    if is_withdrawn(workflow):
        return True, None
    doc = db.get(HealthDocument, document_id)
    old_path = doc.original_file_path if doc else None
    now = _utcnow()
    db.execute(
        update(ConfirmedHealthObservation)
        .where(
            ConfirmedHealthObservation.workflow_id == workflow.id,
            ConfirmedHealthObservation.user_id == user_id,
            ConfirmedHealthObservation.status == "active",
        )
        .values(status="retracted", version=ConfirmedHealthObservation.version + 1)
    )
    db.execute(
        update(HealthScoreSnapshot)
        .where(
            HealthScoreSnapshot.source_report_workflow_id == workflow.id,
            HealthScoreSnapshot.user_id == user_id,
        )
        .values(
            calculation_status="failed",
            failure_code="source_report_withdrawn",
            computed_at=now,
        )
    )
    db.execute(
        update(SummaryTask)
        .where(
            SummaryTask.user_id == user_id,
            SummaryTask.status.in_(["pending", "running"]),
        )
        .values(status="failed", error_message="Trusted report source was withdrawn.")
    )
    workflow.status = "failed"
    workflow.failure_code = "withdrawn"
    workflow.failure_detail = "The user withdrew this report; admitted observations were retracted."
    workflow.version += 1
    if doc:
        doc.csv_data = None
        doc.abnormal_flags = None
        doc.ai_brief = None
        doc.ai_summary = None
        doc.original_file_path = None
        doc.extraction_status = "failed"
    db.flush()
    from app.services.health_profile_trust_service import (
        refresh_candidates_after_observation_retraction,
    )

    refresh_candidates_after_observation_retraction(
        db,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        workflow_id=workflow.id,
    )
    invalidate_trusted_report_consumers(db, user_id=user_id)
    db.commit()

    if old_path and not old_path.startswith("data:"):
        full_path = Path(settings.LOCAL_STORAGE_DIR) / old_path
        try:
            full_path.unlink(missing_ok=True)
        except OSError:
            # Data withdrawal is already enforced in the database. A failed
            # best-effort file cleanup must not resurrect trusted consumption.
            pass
    return True, old_path
