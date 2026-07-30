"""Ordered report assets, page evidence, locators, and history trace."""

from __future__ import annotations

import hashlib
import struct
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
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
    HealthReportExactDuplicateMatch,
    HealthReportFieldLocator,
    HealthReportFollowUpItem,
    HealthReportPage,
    HealthReportScoreJob,
    HealthReportScoreJobItem,
)
from app.services.report_asset_quality_service import (
    IMAGE_DETECTOR_ID,
    IMAGE_DETECTOR_VERSION,
    PDF_MAX_RENDERED_PAGE_BYTES,
    assess_image_quality,
    assess_page_completeness,
    render_pdf_pages,
)
from app.services.report_duplicate_service import (
    find_exact_duplicate_workflow,
    record_exact_duplicate,
)
from app.services.object_storage import (
    ObjectStorageConfigurationError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStorageUnavailableError,
    PrivateObjectStore,
    PrivateObjectWriteLifecycle,
    StoredObjectIdentity,
    StoredObjectMetadata,
)


MAX_REPORT_ASSET_BYTES = 25 * 1024 * 1024
MAX_REPORT_ASSET_SET_BYTES = 250 * 1024 * 1024
MAX_REPORT_RENDERED_PAGE_BYTES = PDF_MAX_RENDERED_PAGE_BYTES
ReportObjectReference = tuple[StoredObjectIdentity, int]
_ACTIVE_OBJECT_LIFECYCLE: ContextVar[PrivateObjectWriteLifecycle | None] = (
    ContextVar("report_object_lifecycle", default=None)
)


def _with_report_object_lifecycle(operation):
    """Wrap every report mutation in the shared object/DB compensation boundary."""

    @wraps(operation)
    def wrapped(db: Session, *args, object_store: PrivateObjectStore, **kwargs):
        lifecycle = PrivateObjectWriteLifecycle(db=db, object_store=object_store)
        token = _ACTIVE_OBJECT_LIFECYCLE.set(lifecycle)
        try:
            with lifecycle:
                return operation(
                    db,
                    *args,
                    object_store=object_store,
                    **kwargs,
                )
        finally:
            _ACTIVE_OBJECT_LIFECYCLE.reset(token)

    return wrapped


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _put_report_object(
    *,
    object_store: PrivateObjectStore,
    key: str,
    digest: str,
    content_type: str,
    user_id: int,
    subject_user_id: int,
    content: bytes,
) -> StoredObjectMetadata:
    metadata = StoredObjectMetadata(
        key=key,
        sha256=digest,
        size_bytes=len(content),
        content_type=content_type,
        owner_user_id=user_id,
        subject_user_id=subject_user_id,
    )
    try:
        lifecycle = _ACTIVE_OBJECT_LIFECYCLE.get()
        if lifecycle is not None and lifecycle.object_store is object_store:
            lifecycle.put(content=content, metadata=metadata)
        else:
            object_store.put(content=content, metadata=metadata)
    except ObjectStorageConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="Report object storage is not configured"
        ) from exc
    except ObjectStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Report object storage is unavailable"
        ) from exc
    except (ObjectStorageIntegrityError, ObjectStorageNotFoundError) as exc:
        raise HTTPException(
            status_code=409, detail="Report object storage rejected the upload"
        ) from exc
    return metadata


def _asset_object_reference(asset: HealthReportAsset) -> ReportObjectReference:
    return (
        StoredObjectIdentity(
            key=asset.storage_key,
            sha256=asset.byte_sha256,
            content_type=asset.mime_type,
            owner_user_id=asset.user_id,
            subject_user_id=asset.subject_user_id,
        ),
        MAX_REPORT_ASSET_BYTES,
    )


def _rendered_page_object_reference(
    page: HealthReportPage,
) -> ReportObjectReference:
    return (
        StoredObjectIdentity(
            key=page.rendered_storage_key,
            sha256=page.rendered_byte_sha256,
            content_type="image/png",
            owner_user_id=page.user_id,
            subject_user_id=page.subject_user_id,
        ),
        MAX_REPORT_RENDERED_PAGE_BYTES,
    )


def _delete_report_objects(
    *,
    object_store: PrivateObjectStore,
    references: list[ReportObjectReference],
) -> None:
    """严格按租户、摘要和类型删除对象；重复引用和不存在对象均幂等。"""

    seen: set[tuple[str, str, str, int, int]] = set()
    failures: list[Exception] = []
    for identity, max_bytes in references:
        dedupe_key = (
            identity.key,
            identity.sha256,
            identity.content_type,
            identity.owner_user_id,
            identity.subject_user_id,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        try:
            object_store.delete(identity=identity, max_bytes=max_bytes)
        except (
            ObjectStorageConfigurationError,
            ObjectStorageUnavailableError,
            ObjectStorageIntegrityError,
            ObjectStorageNotFoundError,
        ) as exc:
            failures.append(exc)
    if not failures:
        return
    first = failures[0]
    if isinstance(first, ObjectStorageConfigurationError):
        raise HTTPException(
            status_code=503, detail="Report object storage is not configured"
        ) from first
    if isinstance(first, ObjectStorageUnavailableError):
        raise HTTPException(
            status_code=503, detail="Report object storage is unavailable"
        ) from first
    raise HTTPException(
        status_code=409, detail="Report object storage cleanup failed validation"
    ) from first


def _reference_payload(reference: ReportObjectReference) -> dict[str, Any]:
    identity, max_bytes = reference
    return {
        "key": identity.key,
        "sha256": identity.sha256,
        "content_type": identity.content_type,
        "owner_user_id": identity.owner_user_id,
        "subject_user_id": identity.subject_user_id,
        "max_bytes": max_bytes,
    }


def _pending_cleanup_references(
    asset_set: HealthReportAssetSet,
) -> list[ReportObjectReference]:
    summary = dict(asset_set.original_summary or {})
    rows = summary.get("pending_object_cleanup") or []
    if not isinstance(rows, list) or len(rows) > 500:
        raise HTTPException(
            status_code=409,
            detail="Report object cleanup state is invalid",
        )
    references: list[ReportObjectReference] = []
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(
                status_code=409,
                detail="Report object cleanup state is invalid",
            )
        try:
            max_bytes = int(row["max_bytes"])
            identity = StoredObjectIdentity(
                key=str(row["key"]),
                sha256=str(row["sha256"]),
                content_type=str(row["content_type"]),
                owner_user_id=int(row["owner_user_id"]),
                subject_user_id=int(row["subject_user_id"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Report object cleanup state is invalid",
            ) from exc
        if max_bytes not in {
            MAX_REPORT_ASSET_BYTES,
            MAX_REPORT_RENDERED_PAGE_BYTES,
        }:
            raise HTTPException(
                status_code=409,
                detail="Report object cleanup state is invalid",
            )
        references.append((identity, max_bytes))
    return references


def _queue_pending_object_cleanup(
    asset_set: HealthReportAssetSet,
    references: list[ReportObjectReference],
) -> None:
    """Persist retirement intent in the same commit that makes old objects unreachable."""

    if not references:
        return
    summary = dict(asset_set.original_summary or {})
    existing = list(summary.get("pending_object_cleanup") or [])
    by_identity: dict[tuple[str, str, str, int, int], dict[str, Any]] = {}
    for payload in [*existing, *(_reference_payload(item) for item in references)]:
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=409,
                detail="Report object cleanup state is invalid",
            )
        key = (
            str(payload.get("key") or ""),
            str(payload.get("sha256") or ""),
            str(payload.get("content_type") or ""),
            int(payload.get("owner_user_id") or 0),
            int(payload.get("subject_user_id") or 0),
        )
        by_identity[key] = payload
    if len(by_identity) > 500:
        raise HTTPException(
            status_code=409,
            detail="Report object cleanup queue is full",
        )
    summary["pending_object_cleanup"] = list(by_identity.values())
    summary["object_cleanup_queued_at"] = _utcnow().isoformat()
    asset_set.original_summary = summary


def _drain_pending_object_cleanup(
    db: Session,
    *,
    asset_set: HealthReportAssetSet,
    object_store: PrivateObjectStore,
) -> bool:
    """Retry durable object retirement; leave the queue intact on any failure."""

    references = _pending_cleanup_references(asset_set)
    if not references:
        return False
    _delete_report_objects(
        object_store=object_store,
        references=references,
    )
    summary = dict(asset_set.original_summary or {})
    summary.pop("pending_object_cleanup", None)
    summary["object_cleanup_completed_at"] = _utcnow().isoformat()
    asset_set.original_summary = summary
    # If this metadata commit fails, the durable queue remains and deletion is
    # safely replayed because exact object deletion is idempotent.
    db.commit()
    return True


def _commit_or_compensate_new_objects(
    db: Session,
    *,
    object_store: PrivateObjectStore,
    new_references: list[ReportObjectReference],
) -> None:
    """DB 提交失败时回滚并删除本次刚写入的对象，避免医疗文件孤儿化。"""

    lifecycle = _ACTIVE_OBJECT_LIFECYCLE.get()
    if lifecycle is not None and lifecycle.object_store is object_store:
        lifecycle.commit()
        return
    try:
        db.commit()
    except Exception:
        db.rollback()
        _delete_report_objects(
            object_store=object_store,
            references=new_references,
        )
        raise


def _write_original_asset(
    *,
    object_store: PrivateObjectStore,
    user_id: int,
    subject_user_id: int,
    asset_set_id: int,
    asset_index: int,
    digest: str,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> StoredObjectMetadata:
    relative = (
        Path("report-assets")
        / str(user_id)
        / str(subject_user_id)
        / str(asset_set_id)
        / f"{asset_index:04d}-{digest}.object"
    )
    key = relative.as_posix()
    return _put_report_object(
        object_store=object_store,
        key=key,
        digest=digest,
        content_type=mime_type,
        user_id=user_id,
        subject_user_id=subject_user_id,
        content=file_bytes,
    )


def _read_original_asset(
    *, object_store: PrivateObjectStore, asset: HealthReportAsset
) -> bytes:
    metadata = StoredObjectMetadata(
        key=asset.storage_key,
        sha256=asset.byte_sha256,
        size_bytes=asset.byte_size,
        content_type=asset.mime_type,
        owner_user_id=asset.user_id,
        subject_user_id=asset.subject_user_id,
    )
    try:
        return object_store.get(metadata=metadata, max_bytes=MAX_REPORT_ASSET_BYTES)
    except ObjectStorageNotFoundError as exc:
        raise HTTPException(
            status_code=409, detail="Report asset content is unavailable"
        ) from exc
    except ObjectStorageUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Report object storage is unavailable"
        ) from exc
    except (ObjectStorageConfigurationError, ObjectStorageIntegrityError) as exc:
        raise HTTPException(
            status_code=409, detail="Report asset content failed integrity validation"
        ) from exc


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


def _upload_session_lifecycle(asset_set: HealthReportAssetSet) -> str | None:
    """Return the server-owned terminal transition recorded for an upload set."""

    value = dict(asset_set.original_summary or {}).get("upload_session_lifecycle")
    return value if isinstance(value, str) else None


def _require_upload_session_mutable(asset_set: HealthReportAssetSet) -> None:
    """Reject replays after an explicit/TTL abandonment started."""

    lifecycle = _upload_session_lifecycle(asset_set)
    if lifecycle in {"abandoning", "abandoned"}:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "report_upload_session_expired",
                "lifecycle": lifecycle,
            },
        )


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
        _require_upload_session_mutable(existing)
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


def _asset_set_object_references(
    db: Session,
    *,
    asset_set: HealthReportAssetSet,
) -> tuple[
    list[HealthReportAsset],
    list[HealthReportPage],
    list[ReportObjectReference],
]:
    """Collect exact private-object identities before DB rows become unreachable."""

    assets = list(
        db.execute(
            select(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == asset_set.id,
                HealthReportAsset.user_id == asset_set.user_id,
                HealthReportAsset.subject_user_id == asset_set.subject_user_id,
            )
        ).scalars()
    )
    pages = list(
        db.execute(
            select(HealthReportPage).where(
                HealthReportPage.asset_set_id == asset_set.id,
                HealthReportPage.user_id == asset_set.user_id,
                HealthReportPage.subject_user_id == asset_set.subject_user_id,
            )
        ).scalars()
    )
    references = [_asset_object_reference(asset) for asset in assets]
    original_keys = {asset.storage_key for asset in assets}
    references.extend(
        _rendered_page_object_reference(page)
        for page in pages
        if page.rendered_storage_key not in original_keys
    )
    return assets, pages, references


def _finalize_abandoned_asset_set(
    db: Session,
    *,
    asset_set: HealthReportAssetSet,
    object_store: PrivateObjectStore,
    now: datetime,
) -> HealthReportAssetSet:
    """Replay exact deletion, then persist a small non-PHI terminal tombstone."""

    _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    )
    summary = dict(asset_set.original_summary or {})
    summary["upload_session_lifecycle"] = "abandoned"
    summary["abandoned_at"] = now.isoformat()
    asset_set.original_summary = summary
    asset_set.status = "retracted"
    db.commit()
    db.refresh(asset_set)
    return asset_set


def abandon_asset_set(
    db: Session,
    *,
    asset_set_id: int,
    user_id: int,
    subject_user_id: int,
    object_store: PrivateObjectStore,
    reason: str = "user_abandoned",
    now: datetime | None = None,
) -> HealthReportAssetSet:
    """Retire one unbound upload session without changing report retention.

    The asset rows and exact object identities become unreachable in the same
    commit that persists ``pending_object_cleanup``. Private-object deletion is
    then replayable and idempotent. A workflow link always wins the race and
    makes the report ineligible for this staging-data lifecycle.
    """

    current = now or _utcnow()
    asset_set = _scoped_set(
        db,
        asset_set_id=asset_set_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        lock=True,
    )
    lifecycle = _upload_session_lifecycle(asset_set)
    if lifecycle == "abandoned":
        return asset_set

    linked = db.execute(
        select(HealthReportAssetSetWorkflowLink.id).where(
            HealthReportAssetSetWorkflowLink.asset_set_id == asset_set.id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalar_one_or_none()
    if linked is not None or asset_set.status == "attached":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "attached_report_cannot_be_abandoned",
                "asset_set_id": asset_set.id,
            },
        )
    if asset_set.status == "retracted" and lifecycle != "abandoning":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "report_upload_session_not_abandonable",
                "status": asset_set.status,
            },
        )
    if lifecycle == "abandoning":
        return _finalize_abandoned_asset_set(
            db,
            asset_set=asset_set,
            object_store=object_store,
            now=current,
        )
    if asset_set.status not in {"open", "rejected", "sealed"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "report_upload_session_not_abandonable",
                "status": asset_set.status,
            },
        )

    assets, pages, references = _asset_set_object_references(
        db,
        asset_set=asset_set,
    )
    page_ids = [page.id for page in pages]
    if page_ids:
        db.execute(
            delete(HealthReportAssetQualityResult).where(
                HealthReportAssetQualityResult.page_id.in_(page_ids),
                HealthReportAssetQualityResult.user_id == user_id,
                HealthReportAssetQualityResult.subject_user_id == subject_user_id,
            )
        )
    db.execute(
        delete(HealthReportCompletenessAssessment).where(
            HealthReportCompletenessAssessment.asset_set_id == asset_set.id,
            HealthReportCompletenessAssessment.user_id == user_id,
            HealthReportCompletenessAssessment.subject_user_id == subject_user_id,
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
        delete(HealthReportExactDuplicateMatch).where(
            HealthReportExactDuplicateMatch.asset_set_id == asset_set.id,
            HealthReportExactDuplicateMatch.user_id == user_id,
            HealthReportExactDuplicateMatch.subject_user_id == subject_user_id,
        )
    )
    if assets:
        db.execute(
            delete(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == asset_set.id,
                HealthReportAsset.user_id == user_id,
                HealthReportAsset.subject_user_id == subject_user_id,
            )
        )

    previous_summary = dict(asset_set.original_summary or {})
    pending = previous_summary.get("pending_object_cleanup")
    summary: dict[str, Any] = {
        "upload_session_lifecycle": "abandoning",
        "abandon_reason": reason[:80],
        "abandon_requested_at": current.isoformat(),
    }
    if isinstance(pending, list):
        summary["pending_object_cleanup"] = pending
    asset_set.original_summary = summary
    _queue_pending_object_cleanup(asset_set, references)
    asset_set.received_asset_count = 0
    asset_set.aggregate_sha256 = None
    asset_set.completeness_basis = None
    # Existing PostgreSQL deployments require a page count for non-open
    # states. This tombstone never represents a report manifest, but retaining
    # a positive sentinel keeps the transition backward compatible with 0024.
    asset_set.expected_page_count = asset_set.expected_page_count or 1
    asset_set.sealed_at = current
    asset_set.status = "rejected"
    db.commit()
    db.refresh(asset_set)
    return _finalize_abandoned_asset_set(
        db,
        asset_set=asset_set,
        object_store=object_store,
        now=current,
    )


def cleanup_expired_asset_sets(
    db: Session,
    *,
    object_store: PrivateObjectStore,
    ttl_hours: int,
    batch_size: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """Expire unbound staging sessions and replay durable object cleanup."""

    if ttl_hours < 1 or ttl_hours > 24 * 365:
        raise ValueError("ttl_hours must be between 1 and 8760")
    if batch_size < 1 or batch_size > 500:
        raise ValueError("batch_size must be between 1 and 500")
    current = now or _utcnow()
    cutoff = current - timedelta(hours=ttl_hours)
    lifecycle = HealthReportAssetSet.original_summary[
        "upload_session_lifecycle"
    ].as_string()
    candidates = list(
        db.execute(
            select(HealthReportAssetSet)
            .outerjoin(
                HealthReportAssetSetWorkflowLink,
                and_(
                    HealthReportAssetSetWorkflowLink.asset_set_id
                    == HealthReportAssetSet.id,
                    HealthReportAssetSetWorkflowLink.user_id
                    == HealthReportAssetSet.user_id,
                    HealthReportAssetSetWorkflowLink.subject_user_id
                    == HealthReportAssetSet.subject_user_id,
                ),
            )
            .where(
                HealthReportAssetSetWorkflowLink.id.is_(None),
                HealthReportAssetSet.status.in_({"open", "rejected", "sealed"}),
                or_(
                    HealthReportAssetSet.created_at < cutoff,
                    lifecycle == "abandoning",
                ),
            )
            .order_by(
                HealthReportAssetSet.created_at,
                HealthReportAssetSet.id,
            )
            .limit(batch_size)
        ).scalars()
    )
    result = {
        "selected": len(candidates),
        "abandoned": 0,
        "cleanup_pending": 0,
        "skipped": 0,
    }
    for candidate in candidates:
        try:
            row = abandon_asset_set(
                db,
                asset_set_id=candidate.id,
                user_id=candidate.user_id,
                subject_user_id=candidate.subject_user_id,
                object_store=object_store,
                reason="ttl_expired",
                now=current,
            )
            if _upload_session_lifecycle(row) == "abandoned":
                result["abandoned"] += 1
            else:
                result["skipped"] += 1
        except HTTPException:
            db.rollback()
            persisted = db.get(HealthReportAssetSet, candidate.id)
            if (
                persisted is not None
                and _upload_session_lifecycle(persisted) == "abandoning"
            ):
                result["cleanup_pending"] += 1
            else:
                result["skipped"] += 1
    return result


@_with_report_object_lifecycle
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
    object_store: PrivateObjectStore,
) -> HealthReportAsset:
    _validate_asset_bytes(file_bytes)
    asset_set = _scoped_set(
        db, asset_set_id=asset_set_id, user_id=user_id, subject_user_id=subject_user_id, lock=True
    )
    _require_upload_session_mutable(asset_set)
    if _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    ):
        asset_set = _scoped_set(
            db,
            asset_set_id=asset_set_id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            lock=True,
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
            # Idempotency is not only a DB shortcut: a prior object write may
            # have been lost independently, so replay must restore and verify it.
            _put_report_object(
                object_store=object_store,
                key=existing.storage_key,
                digest=existing.byte_sha256,
                content_type=existing.mime_type,
                user_id=existing.user_id,
                subject_user_id=existing.subject_user_id,
                content=file_bytes,
            )
            return existing
        raise HTTPException(status_code=409, detail="Asset index or client_asset_id is already bound")
    _validate_asset_set_size(
        db,
        asset_set_id=asset_set.id,
        incoming_size=len(file_bytes),
    )
    stored_object = _write_original_asset(
        object_store=object_store,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_set_id=asset_set.id,
        asset_index=asset_index,
        digest=digest,
        filename=filename,
        mime_type=mime_type,
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
        storage_key=stored_object.key,
        ingest_status="uploaded",
    )
    db.add(row)
    asset_set.received_asset_count += 1
    _commit_or_compensate_new_objects(
        db,
        object_store=object_store,
        new_references=[
            (stored_object.identity(), MAX_REPORT_ASSET_BYTES),
        ],
    )
    db.refresh(row)
    return row


@_with_report_object_lifecycle
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
    object_store: PrivateObjectStore,
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
    _require_upload_session_mutable(asset_set)
    if _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    ):
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
        _put_report_object(
            object_store=object_store,
            key=existing.storage_key,
            digest=existing.byte_sha256,
            content_type=existing.mime_type,
            user_id=existing.user_id,
            subject_user_id=existing.subject_user_id,
            content=file_bytes,
        )
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
    stored_object = _write_original_asset(
        object_store=object_store,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_set_id=asset_set.id,
        asset_index=asset_index,
        digest=digest,
        filename=filename,
        mime_type=mime_type,
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
    current_assets = list(
        db.execute(
            select(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == asset_set.id,
                HealthReportAsset.user_id == user_id,
                HealthReportAsset.subject_user_id == subject_user_id,
            )
        ).scalars()
    )
    original_keys = {asset.storage_key for asset in current_assets}
    retired_references = [
        _rendered_page_object_reference(page)
        for page in pages
        if page.rendered_storage_key not in original_keys
    ]
    if existing:
        retired_references.append(_asset_object_reference(existing))
    page_ids = [page.id for page in pages]
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

    replacement_audit: dict[str, Any] = {
        "asset_index": asset_index,
        "replaced_at": _utcnow().isoformat(),
        "new_sha256": digest,
        "new_filename": filename[:256],
    }
    if existing:
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
        storage_key=stored_object.key,
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
    _queue_pending_object_cleanup(asset_set, retired_references)
    _commit_or_compensate_new_objects(
        db,
        object_store=object_store,
        new_references=[
            (stored_object.identity(), MAX_REPORT_ASSET_BYTES),
        ],
    )
    db.refresh(row)
    db.refresh(asset_set)
    _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    )
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


def _recover_failed_ocr_exact_upload(
    db: Session,
    *,
    workflow: HealthReportWorkflow,
    asset_set: HealthReportAssetSet,
    assets: list[HealthReportAsset],
    title: str,
    hospital: str | None,
    report_date: date | None,
    report_type: str,
    aggregate_sha256: str,
    object_store: PrivateObjectStore,
    new_references: list[ReportObjectReference],
) -> bool:
    """把同字节重传绑定到新的持久对象，允许技术性 OCR 失败真正自愈。"""

    workflow = db.execute(
        select(HealthReportWorkflow)
        .where(
            HealthReportWorkflow.id == workflow.id,
            HealthReportWorkflow.user_id == workflow.user_id,
            HealthReportWorkflow.subject_user_id == workflow.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if (
        workflow is None
        or workflow.status != "failed"
        or workflow.confirmed_at is not None
        or workflow.document_fingerprint != aggregate_sha256
        or workflow.failure_code
        not in {
            "report_ocr_retry_exhausted",
            "report_ocr_storage_unavailable",
            "no_reviewable_candidates",
        }
    ):
        return False
    link = db.execute(
        select(HealthReportAssetSetWorkflowLink)
        .where(
            HealthReportAssetSetWorkflowLink.workflow_id == workflow.id,
            HealthReportAssetSetWorkflowLink.user_id == workflow.user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == workflow.subject_user_id,
        )
        .with_for_update()
    ).scalars().first()
    if not link:
        raise HTTPException(
            status_code=409,
            detail="Failed report workflow has no recoverable asset binding",
        )
    prior_asset_set = _scoped_set(
        db,
        asset_set_id=link.asset_set_id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        lock=True,
    )
    prior_assets = list(
        db.execute(
            select(HealthReportAsset).where(
                HealthReportAsset.asset_set_id == prior_asset_set.id,
                HealthReportAsset.user_id == workflow.user_id,
                HealthReportAsset.subject_user_id == workflow.subject_user_id,
            )
        ).scalars()
    )
    prior_pages = list(
        db.execute(
            select(HealthReportPage).where(
                HealthReportPage.asset_set_id == prior_asset_set.id,
                HealthReportPage.user_id == workflow.user_id,
                HealthReportPage.subject_user_id == workflow.subject_user_id,
            )
        ).scalars()
    )
    prior_references = [_asset_object_reference(asset) for asset in prior_assets]
    prior_original_keys = {asset.storage_key for asset in prior_assets}
    prior_references.extend(
        _rendered_page_object_reference(page)
        for page in prior_pages
        if page.rendered_storage_key not in prior_original_keys
    )
    record_exact_duplicate(
        db,
        asset_set_id=asset_set.id,
        workflow=workflow,
        aggregate_sha256=aggregate_sha256,
    )
    link.asset_set_id = asset_set.id
    prior_asset_set.status = "retracted"
    asset_set.status = "attached"
    asset_set.sealed_at = _utcnow()
    asset_set.aggregate_sha256 = aggregate_sha256
    for asset in assets:
        asset.ingest_status = "accepted"

    metadata = dict(workflow.workflow_metadata or {})
    recovery_count = int(metadata.get("ocr_recovery_count") or 0) + 1
    for key in tuple(metadata):
        if key.startswith("ocr_"):
            metadata.pop(key, None)
    metadata.update(
        {
            "asset_set_id": asset_set.id,
            "ocr_state": "pending",
            "ocr_attempt_count": 0,
            "ocr_recovery_count": recovery_count,
            "ocr_recovered_at": _utcnow().isoformat(),
            "ocr_recovered_from_asset_set_id": prior_asset_set.id,
        }
    )
    workflow.status = "recognizing"
    workflow.report_type = report_type
    workflow.failure_code = None
    workflow.failure_detail = None
    workflow.recognized_at = None
    workflow.version += 1
    workflow.workflow_metadata = metadata
    descriptor = db.execute(
        select(HealthReportDescriptor).where(
            HealthReportDescriptor.workflow_id == workflow.id,
            HealthReportDescriptor.user_id == workflow.user_id,
            HealthReportDescriptor.subject_user_id == workflow.subject_user_id,
        )
    ).scalars().first()
    if descriptor:
        descriptor.title = title[:256]
        descriptor.hospital = hospital[:256] if hospital else None
        descriptor.hospital_normalized = (
            hospital.strip().casefold()[:256] if hospital else None
        )
        descriptor.report_date = report_date
        descriptor.report_type = report_type
    _queue_pending_object_cleanup(asset_set, prior_references)
    _commit_or_compensate_new_objects(
        db,
        object_store=object_store,
        new_references=new_references,
    )
    _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    )
    return True


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


def _write_rendered_page(
    *,
    object_store: PrivateObjectStore,
    relative: Path,
    content: bytes,
    user_id: int,
    subject_user_id: int,
) -> StoredObjectMetadata:
    if not content or len(content) > MAX_REPORT_RENDERED_PAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "rendered_page_too_large",
                "max_bytes": MAX_REPORT_RENDERED_PAGE_BYTES,
            },
        )
    return _put_report_object(
        object_store=object_store,
        key=relative.as_posix(),
        digest=hashlib.sha256(content).hexdigest(),
        content_type="image/png",
        user_id=user_id,
        subject_user_id=subject_user_id,
        content=content,
    )


@_with_report_object_lifecycle
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
    object_store: PrivateObjectStore,
) -> dict[str, Any]:
    asset_set = _scoped_set(
        db, asset_set_id=asset_set_id, user_id=user_id, subject_user_id=subject_user_id, lock=True
    )
    _require_upload_session_mutable(asset_set)
    if _drain_pending_object_cleanup(
        db,
        asset_set=asset_set,
        object_store=object_store,
    ):
        asset_set = _scoped_set(
            db,
            asset_set_id=asset_set_id,
            user_id=user_id,
            subject_user_id=subject_user_id,
            lock=True,
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
    new_rendered_references: list[ReportObjectReference] = []
    if not pages:
        page_index = 1
        for asset in assets:
            original = _read_original_asset(object_store=object_store, asset=asset)
            is_pdf = asset.mime_type == "application/pdf" or asset.original_filename.lower().endswith(".pdf")
            rendered = render_pdf_pages(original) if is_pdf else []
            if is_pdf:
                asset.width_px = max(page.width_px for page in rendered)
                asset.height_px = max(page.height_px for page in rendered)
                for source_page in rendered:
                    relative = (
                        Path("report-pages")
                        / str(user_id)
                        / str(subject_user_id)
                        / str(asset_set.id)
                        / (
                            f"{page_index:04d}-"
                            f"{hashlib.sha256(source_page.png_bytes).hexdigest()[:16]}.png"
                        )
                    )
                    rendered_object = _write_rendered_page(
                        object_store=object_store,
                        relative=relative,
                        content=source_page.png_bytes,
                        user_id=user_id,
                        subject_user_id=subject_user_id,
                    )
                    new_rendered_references.append(
                        (
                            rendered_object.identity(),
                            MAX_REPORT_RENDERED_PAGE_BYTES,
                        )
                    )
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
        _commit_or_compensate_new_objects(
            db,
            object_store=object_store,
            new_references=new_rendered_references,
        )
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
        if _recover_failed_ocr_exact_upload(
            db,
            workflow=exact,
            asset_set=asset_set,
            assets=assets,
            title=title,
            hospital=hospital,
            report_date=report_date,
            report_type=report_type,
            aggregate_sha256=aggregate,
            object_store=object_store,
            new_references=new_rendered_references,
        ):
            return {
                "asset_set": asset_set,
                "workflow_id": exact.id,
                "duplicate": False,
            }
        record_exact_duplicate(db, asset_set_id=asset_set.id, workflow=exact, aggregate_sha256=aggregate)
        asset_set.status = "sealed"
        asset_set.sealed_at = _utcnow()
        _commit_or_compensate_new_objects(
            db,
            object_store=object_store,
            new_references=new_rendered_references,
        )
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
    _commit_or_compensate_new_objects(
        db,
        object_store=object_store,
        new_references=new_rendered_references,
    )
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
    # 报告日期允许缺失；近一年列表此时以任务创建日作为有效日期，避免刚上传的报告消失。
    effective_report_date = func.coalesce(
        HealthReportDescriptor.report_date,
        func.date(HealthReportWorkflow.created_at),
    )
    if date_from:
        query = query.where(effective_report_date >= date_from)
    if date_to:
        query = query.where(effective_report_date <= date_to)
    if hospital:
        query = query.where(HealthReportDescriptor.hospital_normalized.contains(hospital.strip().casefold()))
    if report_type:
        query = query.where(HealthReportWorkflow.report_type == report_type)
    rows = db.execute(
        query.order_by(
            effective_report_date.desc(),
            HealthReportWorkflow.created_at.desc(),
            HealthReportWorkflow.id.desc(),
        )
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


def read_original_asset_content(
    db: Session,
    *,
    workflow_id: int,
    asset_id: int,
    user_id: int,
    subject_user_id: int,
    object_store: PrivateObjectStore,
) -> tuple[bytes, HealthReportAsset]:
    link = db.execute(
        select(HealthReportAssetSetWorkflowLink).where(
            HealthReportAssetSetWorkflowLink.workflow_id == workflow_id,
            HealthReportAssetSetWorkflowLink.user_id == user_id,
            HealthReportAssetSetWorkflowLink.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not link:
        raise HTTPException(status_code=404, detail="Report asset not found")
    asset = db.execute(
        select(HealthReportAsset).where(
            HealthReportAsset.id == asset_id,
            HealthReportAsset.asset_set_id == link.asset_set_id,
            HealthReportAsset.user_id == user_id,
            HealthReportAsset.subject_user_id == subject_user_id,
        )
    ).scalars().first()
    if not asset:
        raise HTTPException(status_code=404, detail="Report asset not found")
    return _read_original_asset(object_store=object_store, asset=asset), asset
