"""Ordered report assets, page evidence, locators, and history trace."""

from __future__ import annotations

import hashlib
import os
import re
import struct
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthReportConfirmationEvent,
    HealthReportFieldCandidate,
    HealthReportWorkflow,
    HealthScoreSnapshot,
)
from app.models.health_trust_expansion import (
    HealthReportAsset,
    HealthReportAssetQualityResult,
    HealthReportAssetSet,
    HealthReportAssetSetWorkflowLink,
    HealthReportCompletenessAssessment,
    HealthReportDescriptor,
    HealthReportFieldLocator,
    HealthReportFollowUpItem,
    HealthReportPage,
    HealthReportScoreJob,
    HealthReportScoreJobItem,
)
from app.services.report_asset_quality_service import (
    IMAGE_DETECTOR_ID,
    IMAGE_DETECTOR_VERSION,
    assess_image_quality,
    assess_page_completeness,
    render_pdf_pages,
)
from app.services.report_duplicate_service import (
    find_exact_duplicate_workflow,
    record_exact_duplicate,
)


MAX_REPORT_ASSET_BYTES = 25 * 1024 * 1024
MAX_REPORT_ASSET_SET_BYTES = 250 * 1024 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w.-]", "_", value, flags=re.UNICODE)[:180] or "report.bin"


def _validate_asset_bytes(file_bytes: bytes) -> None:
    if not file_bytes:
        raise HTTPException(
            status_code=422,
            detail={"code": "empty_asset", "message": "Report asset is empty"},
        )
    if len(file_bytes) > MAX_REPORT_ASSET_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "asset_too_large",
                "max_bytes": MAX_REPORT_ASSET_BYTES,
            },
        )


def _validate_asset_set_size(
    db: Session,
    *,
    asset_set_id: int,
    incoming_size: int,
    replacing_asset_id: int | None = None,
) -> None:
    query = select(func.coalesce(func.sum(HealthReportAsset.byte_size), 0)).where(
        HealthReportAsset.asset_set_id == asset_set_id
    )
    if replacing_asset_id is not None:
        query = query.where(HealthReportAsset.id != replacing_asset_id)
    current = int(db.scalar(query) or 0)
    if current + incoming_size > MAX_REPORT_ASSET_SET_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "asset_set_too_large",
                "max_bytes": MAX_REPORT_ASSET_SET_BYTES,
            },
        )


def _write_original_asset(
    *,
    storage_root: str,
    user_id: int,
    asset_set_id: int,
    asset_index: int,
    digest: str,
    filename: str,
    file_bytes: bytes,
) -> tuple[Path, Path, bool]:
    relative = Path("report-assets") / str(user_id) / str(asset_set_id) / (
        f"{asset_index:04d}-{digest[:16]}-{_safe_name(filename)}"
    )
    target = Path(storage_root) / relative
    target_preexisted = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(file_bytes)
    os.replace(temporary, target)
    return relative, target, target_preexisted


def _scoped_set(db: Session, *, asset_set_id: int, user_id: int, subject_user_id: int, lock: bool = False):
    query = select(HealthReportAssetSet).where(
        HealthReportAssetSet.id == asset_set_id,
        HealthReportAssetSet.user_id == user_id,
        HealthReportAssetSet.subject_user_id == subject_user_id,
    )
    if lock:
        query = query.with_for_update()
    row = db.execute(query).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Report upload session not found")
    return row


def create_asset_set(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    client_request_id: str,
    media_kind: str,
    expected_page_count: int | None,
) -> HealthReportAssetSet:
    if subject_user_id != user_id:
        raise HTTPException(status_code=403, detail="Report upload is limited to the account owner")
    existing = db.execute(
        select(HealthReportAssetSet).where(
            HealthReportAssetSet.user_id == user_id,
            HealthReportAssetSet.subject_user_id == subject_user_id,
            HealthReportAssetSet.client_request_id == client_request_id,
        )
    ).scalars().first()
    if existing:
        if existing.media_kind != media_kind or existing.expected_page_count != expected_page_count:
            raise HTTPException(status_code=409, detail="client_request_id is bound to another manifest")
        return existing
    row = HealthReportAssetSet(
        user_id=user_id,
        subject_user_id=subject_user_id,
        client_request_id=client_request_id,
        media_kind=media_kind,
        status="open",
        expected_page_count=expected_page_count,
        received_asset_count=0,
        completeness_basis="user_declared" if expected_page_count else None,
        original_summary={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_asset(
    db: Session,
    *,
    asset_set_id: int,
    user_id: int,
    subject_user_id: int,
    asset_index: int,
    client_asset_id: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
    storage_root: str,
) -> HealthReportAsset:
    _validate_asset_bytes(file_bytes)
    asset_set = _scoped_set(
        db, asset_set_id=asset_set_id, user_id=user_id, subject_user_id=subject_user_id, lock=True
    )
    if asset_set.status != "open":
        raise HTTPException(status_code=409, detail="Report upload session is sealed")
    digest = hashlib.sha256(file_bytes).hexdigest()
    existing = db.execute(
        select(HealthReportAsset).where(
            HealthReportAsset.asset_set_id == asset_set.id,
            HealthReportAsset.user_id == user_id,
            HealthReportAsset.subject_user_id == subject_user_id,
            (HealthReportAsset.asset_index == asset_index)
            | (HealthReportAsset.client_asset_id == client_asset_id),
        )
    ).scalars().first()
    if existing:
        if (
            existing.asset_index == asset_index
            and existing.client_asset_id == client_asset_id
            and existing.byte_sha256 == digest
        ):
            return existing
        raise HTTPException(status_code=409, detail="Asset index or client_asset_id is already bound")
    _validate_asset_set_size(
        db,
        asset_set_id=asset_set.id,
        incoming_size=len(file_bytes),
    )
    relative, target, target_preexisted = _write_original_asset(
        storage_root=storage_root,
        user_id=user_id,
        asset_set_id=asset_set.id,
        asset_index=asset_index,
        digest=digest,
        filename=filename,
        file_bytes=file_bytes,
    )
    row = HealthReportAsset(
        asset_set_id=asset_set.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_index=asset_index,
        client_asset_id=client_asset_id,
        original_filename=filename[:256],
        mime_type=mime_type[:128],
        byte_size=len(file_bytes),
        byte_sha256=digest,
        storage_key=str(relative),
        ingest_status="uploaded",
    )
    db.add(row)
    asset_set.received_asset_count += 1
    try:
        db.commit()
    except Exception:
        if not target_preexisted:
            target.unlink(missing_ok=True)
        raise
    db.refresh(row)
    return row


def replace_or_add_recovery_asset(
    db: Session,
    *,
    asset_set_id: int,
    user_id: int,
    subject_user_id: int,
    asset_index: int,
    client_asset_id: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
    storage_root: str,
) -> tuple[HealthReportAsset, HealthReportAssetSet]:
    """Replace one rejected page (or add a missing page) without reuploading the set.

    Accepted originals remain immutable. Recovery is allowed only before an
    asset set is attached to a workflow. The prior row is removed and a new
    immutable asset row is created; the replacement audit keeps the old hash
    and filename without keeping rejected medical bytes reachable by an API.
    All derived pages/quality/completeness evidence is invalidated and rebuilt
    on the next seal.
    """

    _validate_asset_bytes(file_bytes)
    if asset_index < 1:
        raise HTTPException(status_code=422, detail={"code": "invalid_asset_index"})
    asset_set = _scoped_set(
        db,
        asset_set_id=asset_set_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        lock=True,
    )
    if asset_set.status not in {"open", "rejected"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "asset_set_not_recoverable", "status": asset_set.status},
        )
    linked = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.asset_set_id == asset_set.id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if linked:
        raise HTTPException(status_code=409, detail={"code": "asset_set_already_attached"})

    existing = db.execute(
        select(HealthReportAsset).where(
            HealthReportAsset.asset_set_id == asset_set.id,
            HealthReportAsset.user_id == user_id,
            HealthReportAsset.subject_user_id == subject_user_id,
            HealthReportAsset.asset_index == asset_index,
        )
    ).scalars().first()
    digest = hashlib.sha256(file_bytes).hexdigest()
    if existing and existing.client_asset_id == client_asset_id and existing.byte_sha256 == digest:
        return existing, asset_set

    client_conflict = db.execute(
        select(HealthReportAsset).where(
            HealthReportAsset.asset_set_id == asset_set.id,
            HealthReportAsset.user_id == user_id,
            HealthReportAsset.subject_user_id == subject_user_id,
            HealthReportAsset.client_asset_id == client_asset_id,
            HealthReportAsset.asset_index != asset_index,
        )
    ).scalars().first()
    if client_conflict:
        raise HTTPException(
            status_code=409,
            detail={"code": "client_asset_id_already_bound"},
        )

    _validate_asset_set_size(
        db,
        asset_set_id=asset_set.id,
        incoming_size=len(file_bytes),
        replacing_asset_id=existing.id if existing else None,
    )
    relative, target, target_preexisted = _write_original_asset(
        storage_root=storage_root,
        user_id=user_id,
        asset_set_id=asset_set.id,
        asset_index=asset_index,
        digest=digest,
        filename=filename,
        file_bytes=file_bytes,
    )

    pages = list(
        db.execute(
            select(HealthReportPage).where(
                HealthReportPage.asset_set_id == asset_set.id,
                HealthReportPage.user_id == user_id,
                HealthReportPage.subject_user_id == subject_user_id,
            )
        ).scalars().all()
    )
    page_ids = [page.id for page in pages]
    rendered_paths = {
        (Path(storage_root) / page.rendered_storage_key).resolve()
        for page in pages
        if page.rendered_storage_key
    }
    if page_ids:
        db.execute(
            delete(HealthReportAssetQualityResult).where(
                HealthReportAssetQualityResult.page_id.in_(page_ids),
                HealthReportAssetQualityResult.user_id == user_id,
                HealthReportAssetQualityResult.subject_user_id == subject_user_id,
            )
        )
    db.execute(
        delete(HealthReportPage).where(
            HealthReportPage.asset_set_id == asset_set.id,
            HealthReportPage.user_id == user_id,
            HealthReportPage.subject_user_id == subject_user_id,
        )
    )
    db.execute(
        delete(HealthReportCompletenessAssessment).where(
            HealthReportCompletenessAssessment.asset_set_id == asset_set.id,
            HealthReportCompletenessAssessment.user_id == user_id,
            HealthReportCompletenessAssessment.subject_user_id == subject_user_id,
        )
    )

    old_path: Path | None = None
    replacement_audit: dict[str, Any] = {
        "asset_index": asset_index,
        "replaced_at": _utcnow().isoformat(),
        "new_sha256": digest,
        "new_filename": filename[:256],
    }
    if existing:
        old_path = (Path(storage_root) / existing.storage_key).resolve()
        replacement_audit.update(
            {
                "old_asset_id": existing.id,
                "old_sha256": existing.byte_sha256,
                "old_filename": existing.original_filename,
            }
        )
        db.delete(existing)
        db.flush()
    else:
        replacement_audit["added_missing_page"] = True

    row = HealthReportAsset(
        asset_set_id=asset_set.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_index=asset_index,
        client_asset_id=client_asset_id,
        original_filename=filename[:256],
        mime_type=mime_type[:128],
        byte_size=len(file_bytes),
        byte_sha256=digest,
        storage_key=str(relative),
        ingest_status="uploaded",
    )
    db.add(row)
    db.flush()
    asset_set.received_asset_count = int(
        db.scalar(
            select(func.count()).select_from(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == asset_set.id,
                HealthReportAsset.user_id == user_id,
                HealthReportAsset.subject_user_id == subject_user_id,
            )
        )
        or 0
    )
    asset_set.status = "open"
    asset_set.aggregate_sha256 = None
    asset_set.sealed_at = None
    summary = dict(asset_set.original_summary or {})
    replacements = list(summary.get("replacements") or [])
    replacements.append(replacement_audit)
    summary["replacements"] = replacements[-100:]
    asset_set.original_summary = summary
    try:
        db.commit()
    except Exception:
        if not target_preexisted:
            target.unlink(missing_ok=True)
        raise
    db.refresh(row)
    db.refresh(asset_set)

    storage_root_path = Path(storage_root).resolve()
    protected_paths = {
        (Path(storage_root) / asset.storage_key).resolve()
        for asset in db.execute(
            select(HealthReportAsset).where(HealthReportAsset.asset_set_id == asset_set.id)
        ).scalars().all()
    }
    for stale in rendered_paths | ({old_path} if old_path else set()):
        if stale in protected_paths:
            continue
        if storage_root_path in stale.parents:
            stale.unlink(missing_ok=True)
    return row, asset_set


def aggregate_asset_digest(assets: list[HealthReportAsset]) -> str:
    if len(assets) == 1:
        return assets[0].byte_sha256
    digest = hashlib.sha256(b"xjie-report-asset-set-v1\0")
    for asset in sorted(assets, key=lambda item: item.asset_index):
        mime = asset.mime_type.encode("utf-8")
        digest.update(struct.pack(">IQH", asset.asset_index, asset.byte_size, len(mime)))
        digest.update(mime)
        digest.update(bytes.fromhex(asset.byte_sha256))
    return digest.hexdigest()


def _persist_page_quality(
    db: Session, *, page: HealthReportPage, image_bytes: bytes
) -> HealthReportAssetQualityResult:
    existing = db.execute(
        select(HealthReportAssetQualityResult).where(
            HealthReportAssetQualityResult.page_id == page.id,
            HealthReportAssetQualityResult.user_id == page.user_id,
            HealthReportAssetQualityResult.subject_user_id == page.subject_user_id,
            HealthReportAssetQualityResult.detector_id == IMAGE_DETECTOR_ID,
            HealthReportAssetQualityResult.detector_version == IMAGE_DETECTOR_VERSION,
        )
    ).scalars().first()
    if existing:
        return existing
    assessment = assess_image_quality(image_bytes)
    row = HealthReportAssetQualityResult(
        page_id=page.id,
        user_id=page.user_id,
        subject_user_id=page.subject_user_id,
        detector_id=assessment.detector_id,
        detector_version=assessment.detector_version,
        quality_status=assessment.quality_status,
        blur_score=Decimal(str(assessment.blur_score)) if assessment.blur_score is not None else None,
        quality_metrics=assessment.metrics,
        missing_page_evidence={},
        failure_code=assessment.failure_code,
    )
    db.add(row)
    return row


def _write_rendered_page(storage_root: str, relative: Path, content: bytes) -> None:
    target = Path(storage_root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def seal_asset_set(
    db: Session,
    *,
    asset_set_id: int,
    user_id: int,
    subject_user_id: int,
    report_type: str,
    title: str,
    hospital: str | None,
    report_date: date | None,
    storage_root: str,
) -> dict[str, Any]:
    asset_set = _scoped_set(
        db, asset_set_id=asset_set_id, user_id=user_id, subject_user_id=subject_user_id, lock=True
    )
    linked = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.asset_set_id == asset_set.id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if linked:
        return {"asset_set": asset_set, "workflow_id": linked.workflow_id, "duplicate": False}
    assets = list(
        db.execute(
            select(HealthReportAsset)
            .where(
                HealthReportAsset.asset_set_id == asset_set.id,
                HealthReportAsset.user_id == user_id,
                HealthReportAsset.subject_user_id == subject_user_id,
            )
            .order_by(HealthReportAsset.asset_index)
        ).scalars().all()
    )
    if not assets:
        raise HTTPException(status_code=422, detail="At least one report asset is required")
    if [item.asset_index for item in assets] != list(range(1, len(assets) + 1)):
        upper_bound = max(asset_set.expected_page_count or 0, assets[-1].asset_index)
        received = {item.asset_index for item in assets}
        missing = [index for index in range(1, upper_bound + 1) if index not in received]
        asset_set.status = "rejected"
        asset_set.sealed_at = _utcnow()
        db.commit()
        return {
            "asset_set": asset_set,
            "workflow_id": None,
            "duplicate": False,
            "failure_code": "missing_page",
            "recovery_action": "upload_missing_pages",
            "problem_asset_indices": [],
            "missing_page_indices": missing,
        }
    existing_pages = list(
        db.execute(
            select(HealthReportPage)
            .where(
                HealthReportPage.asset_set_id == asset_set.id,
                HealthReportPage.user_id == user_id,
                HealthReportPage.subject_user_id == subject_user_id,
            )
            .order_by(HealthReportPage.page_index)
        ).scalars().all()
    )
    pages = existing_pages
    if not pages:
        page_index = 1
        for asset in assets:
            original = (Path(storage_root) / asset.storage_key).read_bytes()
            is_pdf = asset.mime_type == "application/pdf" or asset.original_filename.lower().endswith(".pdf")
            rendered = render_pdf_pages(original) if is_pdf else []
            if is_pdf:
                asset.width_px = max(page.width_px for page in rendered)
                asset.height_px = max(page.height_px for page in rendered)
                for source_page in rendered:
                    relative = Path("report-pages") / str(user_id) / str(asset_set.id) / (
                        f"{page_index:04d}-{hashlib.sha256(source_page.png_bytes).hexdigest()[:16]}.png"
                    )
                    _write_rendered_page(storage_root, relative, source_page.png_bytes)
                    page = HealthReportPage(
                        asset_set_id=asset_set.id,
                        source_asset_id=asset.id,
                        user_id=user_id,
                        subject_user_id=subject_user_id,
                        page_index=page_index,
                        source_page_index=source_page.page_index,
                        rendered_byte_sha256=hashlib.sha256(source_page.png_bytes).hexdigest(),
                        rendered_storage_key=str(relative),
                        width_px=source_page.width_px,
                        height_px=source_page.height_px,
                    )
                    db.add(page)
                    db.flush()
                    _persist_page_quality(db, page=page, image_bytes=source_page.png_bytes)
                    pages.append(page)
                    page_index += 1
            else:
                assessment = assess_image_quality(original)
                if assessment.width_px is None or assessment.height_px is None:
                    raise HTTPException(status_code=422, detail={"code": assessment.failure_code or "unreadable_image"})
                asset.width_px = assessment.width_px
                asset.height_px = assessment.height_px
                page = HealthReportPage(
                    asset_set_id=asset_set.id,
                    source_asset_id=asset.id,
                    user_id=user_id,
                    subject_user_id=subject_user_id,
                    page_index=page_index,
                    source_page_index=1,
                    rendered_byte_sha256=asset.byte_sha256,
                    rendered_storage_key=asset.storage_key,
                    width_px=assessment.width_px,
                    height_px=assessment.height_px,
                )
                db.add(page)
                db.flush()
                _persist_page_quality(db, page=page, image_bytes=original)
                pages.append(page)
                page_index += 1
        db.flush()
    expected = asset_set.expected_page_count or len(pages)
    if asset_set.media_kind == "pdf":
        expected = len(pages)
        asset_set.completeness_basis = "pdf_page_count"
    else:
        asset_set.completeness_basis = asset_set.completeness_basis or "user_declared"
    asset_set.expected_page_count = expected
    completeness = assess_page_completeness(
        expected_page_count=expected,
        observed_page_indices=[page.page_index for page in pages],
        basis=asset_set.completeness_basis,
    )
    existing_completeness = db.execute(
        select(HealthReportCompletenessAssessment).where(
            HealthReportCompletenessAssessment.asset_set_id == asset_set.id,
            HealthReportCompletenessAssessment.user_id == user_id,
            HealthReportCompletenessAssessment.subject_user_id == subject_user_id,
            HealthReportCompletenessAssessment.detector_id == completeness.detector_id,
            HealthReportCompletenessAssessment.detector_version == completeness.detector_version,
        )
    ).scalars().first()
    if not existing_completeness:
        db.add(
            HealthReportCompletenessAssessment(
                asset_set_id=asset_set.id,
                user_id=user_id,
                subject_user_id=subject_user_id,
                detector_id=completeness.detector_id,
                detector_version=completeness.detector_version,
                completeness_status=completeness.completeness_status,
                basis=asset_set.completeness_basis,
                expected_page_count=expected,
                observed_page_count=completeness.observed_page_count,
                missing_page_indices=completeness.missing_page_indices,
                evidence=completeness.evidence,
                failure_code=completeness.failure_code,
            )
        )
    quality_rows = list(
        db.execute(
            select(HealthReportAssetQualityResult)
            .join(HealthReportPage, HealthReportPage.id == HealthReportAssetQualityResult.page_id)
            .where(HealthReportPage.asset_set_id == asset_set.id)
        ).scalars().all()
    )
    failures = [row for row in quality_rows if row.quality_status != "accepted"]
    if completeness.failure_code or failures:
        pages_by_id = {page.id: page for page in pages}
        assets_by_id = {asset.id: asset for asset in assets}
        problem_asset_indices = sorted(
            {
                assets_by_id[pages_by_id[row.page_id].source_asset_id].asset_index
                for row in failures
                if row.page_id in pages_by_id
                and pages_by_id[row.page_id].source_asset_id in assets_by_id
            }
        )
        for asset in assets:
            if asset.asset_index in problem_asset_indices:
                asset.ingest_status = "rejected"
        asset_set.status = "rejected"
        asset_set.sealed_at = _utcnow()
        db.commit()
        code = completeness.failure_code or failures[0].failure_code or "unreadable_image"
        missing_page_indices = list(completeness.missing_page_indices or [])
        return {
            "asset_set": asset_set,
            "workflow_id": None,
            "duplicate": False,
            "failure_code": code,
            "recovery_action": (
                "upload_missing_pages" if missing_page_indices else "replace_problem_pages"
            ),
            "problem_asset_indices": problem_asset_indices,
            "missing_page_indices": missing_page_indices,
        }
    aggregate = aggregate_asset_digest(assets)
    asset_set.aggregate_sha256 = aggregate
    exact = find_exact_duplicate_workflow(
        db, user_id=user_id, subject_user_id=subject_user_id, aggregate_sha256=aggregate
    )
    if exact:
        record_exact_duplicate(db, asset_set_id=asset_set.id, workflow=exact, aggregate_sha256=aggregate)
        asset_set.status = "sealed"
        asset_set.sealed_at = _utcnow()
        db.commit()
        return {"asset_set": asset_set, "workflow_id": exact.id, "duplicate": True}
    workflow = HealthReportWorkflow(
        user_id=user_id,
        subject_user_id=subject_user_id,
        legacy_document_id=None,
        client_request_id=asset_set.client_request_id,
        document_fingerprint=aggregate,
        report_type=report_type,
        status="recognizing",
        version=1,
        workflow_metadata={"asset_set_id": asset_set.id},
    )
    db.add(workflow)
    db.flush()
    db.add(
        HealthReportAssetSetWorkflowLink(
            asset_set_id=asset_set.id,
            workflow_id=workflow.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
        )
    )
    db.add(
        HealthReportDescriptor(
            workflow_id=workflow.id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            title=title[:256],
            hospital=hospital[:256] if hospital else None,
            hospital_normalized=hospital.strip().casefold()[:256] if hospital else None,
            report_date=report_date,
            report_type=report_type,
        )
    )
    asset_set.status = "attached"
    asset_set.sealed_at = _utcnow()
    for asset in assets:
        asset.ingest_status = "accepted"
    db.commit()
    db.refresh(workflow)
    return {"asset_set": asset_set, "workflow_id": workflow.id, "duplicate": False}


def add_field_locator(
    db: Session,
    *,
    workflow_id: int,
    candidate_id: int,
    page_id: int,
    user_id: int,
    subject_user_id: int,
    region_index: int,
    region_role: str,
    x: Decimal,
    y: Decimal,
    width: Decimal,
    height: Decimal,
    polygon_norm: list,
    provider_id: str | None,
    model_version: str | None,
    confidence: Decimal | None,
) -> HealthReportFieldLocator:
    link = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.workflow_id == workflow_id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    page = db.execute(
        select(HealthReportPage).where(
            HealthReportPage.id == page_id,
            HealthReportPage.user_id == user_id,
            HealthReportPage.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not link or not page or page.asset_set_id != link.asset_set_id:
        raise HTTPException(status_code=422, detail="Locator page does not belong to report workflow")
    row = HealthReportFieldLocator(
        candidate_id=candidate_id,
        workflow_id=workflow_id,
        asset_set_id=link.asset_set_id,
        page_id=page_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        x=x,
        y=y,
        width=width,
        height=height,
        region_index=region_index,
        region_role=region_role,
        polygon_norm=polygon_norm,
        provider_id=provider_id,
        model_version=model_version,
        confidence=confidence,
        locator_version="normalized-region-v1",
    )
    db.add(row)
    db.flush()
    return row


def list_report_history(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    hospital: str | None = None,
    report_type: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(HealthReportWorkflow, HealthReportDescriptor)
        .outerjoin(
            HealthReportDescriptor,
            and_(
                HealthReportDescriptor.workflow_id == HealthReportWorkflow.id,
                HealthReportDescriptor.user_id == HealthReportWorkflow.user_id,
                HealthReportDescriptor.subject_user_id == HealthReportWorkflow.subject_user_id,
            ),
        )
        .where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
            or_(
                HealthReportWorkflow.failure_code.is_(None),
                HealthReportWorkflow.failure_code != "withdrawn",
            ),
        )
    )
    if date_from:
        query = query.where(HealthReportDescriptor.report_date >= date_from)
    if date_to:
        query = query.where(HealthReportDescriptor.report_date <= date_to)
    if hospital:
        query = query.where(HealthReportDescriptor.hospital_normalized.contains(hospital.strip().casefold()))
    if report_type:
        query = query.where(HealthReportWorkflow.report_type == report_type)
    rows = db.execute(
        query.order_by(HealthReportDescriptor.report_date.desc(), HealthReportWorkflow.id.desc())
    ).all()
    return [
        {
            "workflow_id": workflow.id,
            "status": workflow.status,
            "report_type": workflow.report_type,
            "title": descriptor.title if descriptor else f"报告 {workflow.id}",
            "hospital": descriptor.hospital if descriptor else None,
            "report_date": descriptor.report_date if descriptor else None,
            "created_at": workflow.created_at,
        }
        for workflow, descriptor in rows
    ]


def build_report_trace(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int
) -> dict[str, Any]:
    workflow = db.execute(
        select(HealthReportWorkflow).where(
            HealthReportWorkflow.id == workflow_id,
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Report workflow not found")
    link = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.workflow_id == workflow_id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    assets = []
    pages = []
    if link:
        assets = list(
            db.execute(
                select(HealthReportAsset)
                .where(
                    HealthReportAsset.asset_set_id == link.asset_set_id,
                    HealthReportAsset.user_id == user_id,
                    HealthReportAsset.subject_user_id == subject_user_id,
                )
                .order_by(HealthReportAsset.asset_index)
            ).scalars()
        )
        pages = list(
            db.execute(
                select(HealthReportPage)
                .where(
                    HealthReportPage.asset_set_id == link.asset_set_id,
                    HealthReportPage.user_id == user_id,
                    HealthReportPage.subject_user_id == subject_user_id,
                )
                .order_by(HealthReportPage.page_index)
            ).scalars()
        )

    def scoped_rows(model, *criteria, order_by):
        return list(
            db.execute(
                select(model)
                .where(
                    *criteria,
                    model.user_id == user_id,
                    model.subject_user_id == subject_user_id,
                )
                .order_by(*order_by)
            ).scalars()
        )

    candidates = scoped_rows(
        HealthReportFieldCandidate,
        HealthReportFieldCandidate.workflow_id == workflow_id,
        order_by=(HealthReportFieldCandidate.id,),
    )
    events = scoped_rows(
        HealthReportConfirmationEvent,
        HealthReportConfirmationEvent.workflow_id == workflow_id,
        order_by=(HealthReportConfirmationEvent.id,),
    )
    observations = scoped_rows(
        ConfirmedHealthObservation,
        ConfirmedHealthObservation.workflow_id == workflow_id,
        order_by=(ConfirmedHealthObservation.id,),
    )
    locators = scoped_rows(
        HealthReportFieldLocator,
        HealthReportFieldLocator.workflow_id == workflow_id,
        order_by=(HealthReportFieldLocator.candidate_id, HealthReportFieldLocator.region_index),
    )
    score_jobs = scoped_rows(
        HealthReportScoreJob,
        HealthReportScoreJob.workflow_id == workflow_id,
        order_by=(HealthReportScoreJob.id,),
    )
    score_items = scoped_rows(
        HealthReportScoreJobItem,
        HealthReportScoreJobItem.workflow_id == workflow_id,
        order_by=(HealthReportScoreJobItem.id,),
    )
    snapshots = scoped_rows(
        HealthScoreSnapshot,
        HealthScoreSnapshot.source_report_workflow_id == workflow_id,
        order_by=(HealthScoreSnapshot.id,),
    )
    follow_ups = scoped_rows(
        HealthReportFollowUpItem,
        HealthReportFollowUpItem.workflow_id == workflow_id,
        order_by=(HealthReportFollowUpItem.id,),
    )
    return {
        "workflow": {"id": workflow.id, "status": workflow.status, "version": workflow.version},
        "assets": [{"id": row.id, "index": row.asset_index, "filename": row.original_filename, "sha256": row.byte_sha256} for row in assets],
        "pages": [{"id": row.id, "page_index": row.page_index, "asset_id": row.source_asset_id} for row in pages],
        "locators": [{"candidate_id": row.candidate_id, "page_id": row.page_id, "role": row.region_role, "bbox": [float(row.x), float(row.y), float(row.width), float(row.height)]} for row in locators],
        "candidates": [{"id": row.id, "name": row.canonical_name, "status": row.review_status, "version": row.version} for row in candidates],
        "confirmation_events": [{"id": row.id, "candidate_id": row.candidate_id, "event_type": row.event_type} for row in events],
        "observations": [{"id": row.id, "candidate_id": row.source_candidate_id, "name": row.canonical_name, "status": row.status} for row in observations],
        "score_jobs": [{"id": row.id, "status": row.status, "input_revision": row.input_revision, "manifest_digest": row.input_manifest_digest} for row in score_jobs],
        "score_items": [{"id": row.id, "job_id": row.job_id, "kind": row.score_kind, "status": row.status} for row in score_items],
        "score_snapshots": [{"id": row.id, "kind": row.score_kind, "algorithm_version": row.algorithm_version, "status": row.calculation_status} for row in snapshots],
        "follow_ups": [{"id": row.id, "code": row.item_code, "rule_version": row.rule_version, "status": row.status} for row in follow_ups],
    }


def resolve_original_asset_path(
    db: Session, *, workflow_id: int, asset_id: int, user_id: int, subject_user_id: int, storage_root: str
) -> tuple[Path, HealthReportAsset]:
    link = db.execute(select(HealthReportAssetSetWorkflowLink).where(HealthReportAssetSetWorkflowLink.workflow_id == workflow_id, HealthReportAssetSetWorkflowLink.user_id == user_id, HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id)).scalars().first()
    if not link:
        raise HTTPException(status_code=404, detail="Report asset not found")
    asset = db.execute(select(HealthReportAsset).where(HealthReportAsset.id == asset_id, HealthReportAsset.asset_set_id == link.asset_set_id, HealthReportAsset.user_id == user_id, HealthReportAsset.subject_user_id == subject_user_id)).scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Report asset not found")
    root = Path(storage_root).resolve()
    path = (root / asset.storage_key).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Report asset content not found")
    return path, asset
