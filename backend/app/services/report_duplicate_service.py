"""Byte-identical reuse and explicit semantic duplicate decisions."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health_document import HealthDocument
from app.models.health_trust import HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import (
    HealthReportDescriptor,
    HealthReportDuplicateDecision,
    HealthReportExactDuplicateMatch,
    HealthReportSemanticSignature,
)


SEMANTIC_ALGORITHM_VERSION = "report-semantic-token-jaccard-v1"
SEMANTIC_THRESHOLD_VERSION = "report-semantic-threshold-v1"
SEMANTIC_DUPLICATE_THRESHOLD = Decimal("0.8600")
_ACTIVE_MATCH_STATUSES = {
    "recognizing",
    "awaiting_confirmation",
    "committing",
    "completed",
    "completed_score_pending",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[^0-9a-z\u3400-\u9fff.+-]+", "", text)


def _normalized_number(value: Decimal | None, text: str | None) -> str:
    numeric = value
    if numeric is None and text:
        try:
            numeric = Decimal(str(text).strip())
        except (InvalidOperation, ValueError):
            numeric = None
    if numeric is None:
        return _normalized_text(text)
    if not numeric.is_finite():
        return ""
    normalized = format(numeric.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def candidate_token_manifest(candidates: Iterable[HealthReportFieldCandidate]) -> dict:
    tokens: list[str] = []
    fields: list[dict[str, str]] = []
    for candidate in candidates:
        if candidate.review_status == "rejected":
            continue
        name = _normalized_text(candidate.canonical_code or candidate.canonical_name)
        value = _normalized_number(candidate.normalized_value, candidate.normalized_text or candidate.raw_value)
        unit = _normalized_text(candidate.normalized_unit or candidate.raw_unit)
        if not name or not value:
            continue
        token = f"{name}|{value}|{unit}"
        tokens.append(token)
        fields.append({"name": name, "value": value, "unit": unit})
    return {"tokens": sorted(set(tokens)), "fields": sorted(fields, key=lambda row: tuple(row.values()))}


def _descriptor_metadata(db: Session, workflow: HealthReportWorkflow) -> dict:
    descriptor = db.execute(
        select(HealthReportDescriptor).where(
            HealthReportDescriptor.workflow_id == workflow.id,
            HealthReportDescriptor.user_id == workflow.user_id,
            HealthReportDescriptor.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().first()
    if descriptor:
        report_date = descriptor.report_date.isoformat() if descriptor.report_date else None
        return {
            "title": _normalized_text(descriptor.title),
            "hospital": _normalized_text(descriptor.hospital_normalized or descriptor.hospital),
            "report_date": report_date,
            "report_type": descriptor.report_type,
        }
    document = db.get(HealthDocument, workflow.legacy_document_id) if workflow.legacy_document_id else None
    report_date: str | None = None
    if document and document.doc_date:
        report_date = document.doc_date.date().isoformat()
    return {
        "title": _normalized_text(document.name if document else ""),
        "hospital": _normalized_text(document.hospital if document else ""),
        "report_date": report_date,
        "report_type": workflow.report_type,
    }


def _metadata_keys(metadata: dict) -> tuple[str | None, str | None]:
    return metadata.get("report_date"), metadata.get("hospital") or None


def _similarity(left: HealthReportSemanticSignature, right_manifest: dict, right_metadata: dict) -> Decimal:
    left_tokens = set((left.field_token_manifest or {}).get("tokens") or [])
    right_tokens = set(right_manifest.get("tokens") or [])
    if not left_tokens or not right_tokens:
        return Decimal("0")
    shared = left_tokens & right_tokens
    left_metadata = left.normalized_metadata or {}
    strong_metadata_match = bool(
        left_metadata.get("report_date")
        and right_metadata.get("report_date")
        and left_metadata.get("hospital")
        and right_metadata.get("hospital")
        and left_metadata["report_date"] == right_metadata["report_date"]
        and left_metadata["hospital"] == right_metadata["hospital"]
    )
    # One common laboratory value is not enough to call two reports the same.
    # A single-token match is considered only when both date and hospital also
    # match; otherwise at least two independent normalized fields are required.
    if len(shared) < 2 and not strong_metadata_match:
        return Decimal("0")
    token_score = Decimal(len(left_tokens & right_tokens)) / Decimal(len(left_tokens | right_tokens))
    comparable: list[bool] = []
    for key in ("report_type", "report_date", "hospital"):
        left_value = left_metadata.get(key)
        right_value = right_metadata.get(key)
        if left_value and right_value:
            comparable.append(left_value == right_value)
    if not comparable:
        return token_score.quantize(Decimal("0.0001"))
    metadata_score = Decimal(sum(comparable)) / Decimal(len(comparable))
    return ((token_score * Decimal("0.85")) + (metadata_score * Decimal("0.15"))).quantize(
        Decimal("0.0001")
    )


def ensure_semantic_signature(
    db: Session,
    *,
    workflow: HealthReportWorkflow,
    candidates: list[HealthReportFieldCandidate],
) -> HealthReportSemanticSignature:
    existing = db.execute(
        select(HealthReportSemanticSignature).where(
            HealthReportSemanticSignature.workflow_id == workflow.id,
            HealthReportSemanticSignature.user_id == workflow.user_id,
            HealthReportSemanticSignature.subject_user_id == workflow.subject_user_id,
            HealthReportSemanticSignature.algorithm_version == SEMANTIC_ALGORITHM_VERSION,
        )
    ).scalars().first()
    if existing:
        return existing
    metadata = _descriptor_metadata(db, workflow)
    manifest = candidate_token_manifest(candidates)
    date_key, hospital_key = _metadata_keys(metadata)
    signature = HealthReportSemanticSignature(
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        algorithm_version=SEMANTIC_ALGORITHM_VERSION,
        threshold_version=SEMANTIC_THRESHOLD_VERSION,
        report_type=workflow.report_type,
        report_date_key=date_key,
        hospital_key=hospital_key,
        normalized_metadata=metadata,
        field_token_manifest=manifest,
        signature_hash=_stable_hash({"metadata": metadata, "manifest": manifest}),
    )
    db.add(signature)
    db.flush()
    return signature


def ensure_semantic_duplicate_decision(
    db: Session,
    *,
    workflow: HealthReportWorkflow,
    candidates: list[HealthReportFieldCandidate],
) -> HealthReportDuplicateDecision | None:
    """Persist at most one deterministic top semantic match for a workflow."""

    current = ensure_semantic_signature(db, workflow=workflow, candidates=candidates)
    existing_decision = db.execute(
        select(HealthReportDuplicateDecision).where(
            HealthReportDuplicateDecision.workflow_id == workflow.id,
            HealthReportDuplicateDecision.user_id == workflow.user_id,
            HealthReportDuplicateDecision.subject_user_id == workflow.subject_user_id,
            HealthReportDuplicateDecision.semantic_algorithm_version == SEMANTIC_ALGORITHM_VERSION,
        )
    ).scalars().first()
    if existing_decision:
        return existing_decision

    candidates_rows = db.execute(
        select(HealthReportSemanticSignature, HealthReportWorkflow)
        .join(
            HealthReportWorkflow,
            HealthReportWorkflow.id == HealthReportSemanticSignature.workflow_id,
        )
        .where(
            HealthReportSemanticSignature.user_id == workflow.user_id,
            HealthReportSemanticSignature.subject_user_id == workflow.subject_user_id,
            HealthReportSemanticSignature.workflow_id != workflow.id,
            HealthReportSemanticSignature.algorithm_version == SEMANTIC_ALGORITHM_VERSION,
            HealthReportSemanticSignature.report_type == workflow.report_type,
            HealthReportWorkflow.status.in_(tuple(_ACTIVE_MATCH_STATUSES)),
        )
    ).all()
    scored: list[tuple[Decimal, HealthReportSemanticSignature, HealthReportWorkflow]] = []
    for signature, matched_workflow in candidates_rows:
        score = _similarity(signature, current.field_token_manifest or {}, current.normalized_metadata or {})
        if score >= SEMANTIC_DUPLICATE_THRESHOLD:
            scored.append((score, signature, matched_workflow))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[2].created_at or _utcnow(), row[2].id), reverse=True)
    similarity, matched_signature, matched_workflow = scored[0]
    detection_key = _stable_hash(
        {
            "workflow_id": workflow.id,
            "matched_workflow_id": matched_workflow.id,
            "algorithm_version": SEMANTIC_ALGORITHM_VERSION,
            "current_signature": current.signature_hash,
            "matched_signature": matched_signature.signature_hash,
        }
    )[:96]
    decision = HealthReportDuplicateDecision(
        workflow_id=workflow.id,
        matched_workflow_id=matched_workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        duplicate_kind="semantic",
        semantic_algorithm_version=SEMANTIC_ALGORITHM_VERSION,
        similarity=similarity,
        decision_status="awaiting_user_choice",
        detection_key=detection_key,
        evidence={
            "threshold": str(SEMANTIC_DUPLICATE_THRESHOLD),
            "threshold_version": SEMANTIC_THRESHOLD_VERSION,
            "current_signature_hash": current.signature_hash,
            "matched_signature_hash": matched_signature.signature_hash,
            "shared_tokens": sorted(
                set((current.field_token_manifest or {}).get("tokens") or [])
                & set((matched_signature.field_token_manifest or {}).get("tokens") or [])
            ),
        },
    )
    db.add(decision)
    # The legacy status check does not include a duplicate-decision state.  Keep
    # the legal recognizing status and expose the composite state at the API.
    workflow.status = "recognizing"
    workflow.version += 1
    db.flush()
    return decision


def pending_semantic_decision(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int
) -> HealthReportDuplicateDecision | None:
    return db.execute(
        select(HealthReportDuplicateDecision).where(
            HealthReportDuplicateDecision.workflow_id == workflow_id,
            HealthReportDuplicateDecision.user_id == user_id,
            HealthReportDuplicateDecision.subject_user_id == subject_user_id,
            HealthReportDuplicateDecision.decision_status == "awaiting_user_choice",
        )
    ).scalars().first()


def resolve_semantic_duplicate(
    db: Session,
    *,
    workflow_id: int,
    user_id: int,
    subject_user_id: int,
    workflow_version: int,
    action: str,
    client_event_id: str,
) -> HealthReportDuplicateDecision:
    if action not in {"use_existing", "continue_new"}:
        raise HTTPException(status_code=422, detail="Unsupported duplicate decision")
    decision = db.execute(
        select(HealthReportDuplicateDecision)
        .where(
            HealthReportDuplicateDecision.workflow_id == workflow_id,
            HealthReportDuplicateDecision.user_id == user_id,
            HealthReportDuplicateDecision.subject_user_id == subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not decision or not workflow:
        raise HTTPException(status_code=404, detail="Semantic duplicate decision not found")
    if decision.decision_status != "awaiting_user_choice":
        if decision.decision_status == action and decision.decision_client_event_id == client_event_id:
            return decision
        raise HTTPException(status_code=409, detail="Semantic duplicate was already resolved")
    if workflow.version != workflow_version:
        raise HTTPException(status_code=409, detail="Report workflow version is stale")
    decision.decision_status = action
    decision.decision_client_event_id = client_event_id
    decision.decided_by_user_id = user_id
    decision.decided_at = _utcnow()
    workflow.version += 1
    if action == "continue_new":
        workflow.status = "awaiting_confirmation"
        workflow.failure_code = None
        workflow.failure_detail = None
    else:
        workflow.status = "failed"
        workflow.failure_code = "semantic_duplicate_use_existing"
        workflow.failure_detail = f"User selected existing workflow {decision.matched_workflow_id}."
    db.commit()
    db.refresh(decision)
    return decision


def find_exact_duplicate_workflow(
    db: Session, *, user_id: int, subject_user_id: int, aggregate_sha256: str
) -> HealthReportWorkflow | None:
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
            HealthReportWorkflow.document_fingerprint == aggregate_sha256,
        )
    ).scalars().first()
    if workflow and workflow.failure_code != "withdrawn":
        return workflow
    return None


def record_exact_duplicate(
    db: Session,
    *,
    asset_set_id: int,
    workflow: HealthReportWorkflow,
    aggregate_sha256: str,
) -> HealthReportExactDuplicateMatch:
    existing = db.execute(
        select(HealthReportExactDuplicateMatch).where(
            HealthReportExactDuplicateMatch.asset_set_id == asset_set_id,
            HealthReportExactDuplicateMatch.user_id == workflow.user_id,
            HealthReportExactDuplicateMatch.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().first()
    if existing:
        return existing
    row = HealthReportExactDuplicateMatch(
        asset_set_id=asset_set_id,
        matched_workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        aggregate_sha256=aggregate_sha256,
        matched_document_fingerprint=workflow.document_fingerprint or aggregate_sha256,
    )
    db.add(row)
    db.flush()
    return row
