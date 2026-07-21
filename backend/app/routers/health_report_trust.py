"""Authenticated review, report assets, and trusted admission endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user_id, get_db
from app.models.health_trust import HealthReportWorkflow
from app.schemas.health_report_trust import (
    HealthReportAssetOut,
    HealthReportAssetRecoveryOut,
    HealthReportConfirmIn,
    HealthReportDuplicateDecisionIn,
    HealthReportDuplicateDecisionOut,
    HealthReportHistoryOut,
    HealthReportInterpretationOut,
    HealthReportManualCandidateIn,
    HealthReportReviewOut,
    HealthReportRuntimeOut,
    HealthReportScoreRetryOut,
    HealthReportSealIn,
    HealthReportSealOut,
    HealthReportTraceOut,
    HealthReportUploadSessionIn,
    HealthReportUploadSessionOut,
)
from app.services.report_asset_service import (
    MAX_REPORT_ASSET_BYTES,
    add_asset,
    build_report_trace,
    create_asset_set,
    list_report_history,
    replace_or_add_recovery_asset,
    resolve_original_asset_path,
    seal_asset_set,
)
from app.services.report_duplicate_service import resolve_semantic_duplicate
from app.services.report_score_job_service import retry_score_job
from app.services.health_report_trust_service import (
    add_manual_candidate,
    build_interpretation,
    build_review,
    build_report_runtime,
    confirm_workflow,
)


router = APIRouter()


def _read_bounded_report_upload(file: UploadFile) -> bytes:
    """Read at most one byte beyond the contract so request memory is bounded."""

    content = file.file.read(MAX_REPORT_ASSET_BYTES + 1)
    if len(content) > MAX_REPORT_ASSET_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "asset_too_large",
                "max_bytes": MAX_REPORT_ASSET_BYTES,
            },
        )
    return content


def _require_self_subject(*, user_id: int, subject_user_id: int) -> None:
    # Family permissions are currently view-only. Report writes and medical
    # confirmation fail closed until a separate delegated-consent contract is
    # introduced.
    if subject_user_id != user_id:
        raise HTTPException(status_code=403, detail="Report confirmation is limited to the account owner")


@router.get("/report-workflows/{workflow_id}/review", response_model=HealthReportReviewOut)
def get_report_review(
    workflow_id: int,
    subject_user_id: int = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    return build_review(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
    )


@router.get(
    "/report-workflows/{workflow_id}/interpretation",
    response_model=HealthReportInterpretationOut,
)
def get_report_interpretation(
    workflow_id: int,
    subject_user_id: int = Query(...),
    locale: str = Query(default="zh-Hans", max_length=32),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    return build_interpretation(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        locale=locale,
    )


@router.post("/report-workflows/{workflow_id}/confirm", response_model=HealthReportReviewOut)
def confirm_report_review(
    workflow_id: int,
    payload: HealthReportConfirmIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    return confirm_workflow(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        payload=payload,
    )


@router.post(
    "/report-workflows/{workflow_id}/manual-candidates",
    response_model=HealthReportReviewOut,
)
def create_manual_report_candidate(
    workflow_id: int,
    payload: HealthReportManualCandidateIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    return add_manual_candidate(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        payload=payload,
    )


@router.get("/report-workflows/{workflow_id}/runtime", response_model=HealthReportRuntimeOut)
def get_report_runtime(
    workflow_id: int,
    subject_user_id: int = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    return build_report_runtime(
        db, workflow_id=workflow_id, user_id=user_id, subject_user_id=subject_user_id
    )


@router.post(
    "/report-workflows/{workflow_id}/duplicate-decision",
    response_model=HealthReportDuplicateDecisionOut,
)
def decide_report_duplicate(
    workflow_id: int,
    payload: HealthReportDuplicateDecisionIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    decision = resolve_semantic_duplicate(
        db,
        workflow_id=workflow_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        workflow_version=payload.workflow_version,
        action=payload.action,
        client_event_id=payload.client_event_id,
    )
    workflow = db.get(HealthReportWorkflow, workflow_id)
    return {
        "workflow_id": workflow_id,
        "matched_workflow_id": decision.matched_workflow_id,
        "decision_status": decision.decision_status,
        "similarity": decision.similarity,
        "workflow_version": workflow.version if workflow else payload.workflow_version,
    }


@router.post("/report-upload-sessions", response_model=HealthReportUploadSessionOut)
def start_report_upload_session(
    payload: HealthReportUploadSessionIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    row = create_asset_set(
        db,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        client_request_id=payload.client_request_id,
        media_kind=payload.media_kind,
        expected_page_count=payload.expected_page_count,
    )
    return {
        "asset_set_id": row.id,
        "subject_user_id": row.subject_user_id,
        "status": row.status,
        "media_kind": row.media_kind,
        "expected_page_count": row.expected_page_count,
        "received_asset_count": row.received_asset_count,
        "aggregate_sha256": row.aggregate_sha256,
    }


@router.put(
    "/report-upload-sessions/{asset_set_id}/assets/{asset_index}",
    response_model=HealthReportAssetOut,
)
def upload_report_asset(
    asset_set_id: int,
    asset_index: int,
    file: UploadFile = File(...),
    subject_user_id: int = Form(...),
    client_asset_id: str = Form(..., min_length=1, max_length=80),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    row = add_asset(
        db,
        asset_set_id=asset_set_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_index=asset_index,
        client_asset_id=client_asset_id,
        filename=file.filename or "report.bin",
        mime_type=file.content_type or "application/octet-stream",
        file_bytes=_read_bounded_report_upload(file),
        storage_root=settings.LOCAL_STORAGE_DIR,
    )
    return {
        "asset_id": row.id,
        "asset_index": row.asset_index,
        "client_asset_id": row.client_asset_id,
        "filename": row.original_filename,
        "mime_type": row.mime_type,
        "byte_size": row.byte_size,
        "sha256": row.byte_sha256,
    }


@router.put(
    "/report-upload-sessions/{asset_set_id}/assets/{asset_index}/replacement",
    response_model=HealthReportAssetRecoveryOut,
)
def recover_report_asset(
    asset_set_id: int,
    asset_index: int,
    file: UploadFile = File(...),
    subject_user_id: int = Form(...),
    client_asset_id: str = Form(..., min_length=1, max_length=80),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Replace one rejected page, or add one missing page, before attachment."""

    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    row, asset_set = replace_or_add_recovery_asset(
        db,
        asset_set_id=asset_set_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        asset_index=asset_index,
        client_asset_id=client_asset_id,
        filename=file.filename or "report.bin",
        mime_type=file.content_type or "application/octet-stream",
        file_bytes=_read_bounded_report_upload(file),
        storage_root=settings.LOCAL_STORAGE_DIR,
    )
    return {
        "asset_id": row.id,
        "asset_index": row.asset_index,
        "client_asset_id": row.client_asset_id,
        "filename": row.original_filename,
        "mime_type": row.mime_type,
        "byte_size": row.byte_size,
        "sha256": row.byte_sha256,
        "asset_set_id": asset_set.id,
        "session_status": asset_set.status,
        "received_asset_count": asset_set.received_asset_count,
    }


@router.post("/report-upload-sessions/{asset_set_id}/seal", response_model=HealthReportSealOut)
def seal_report_upload_session(
    asset_set_id: int,
    payload: HealthReportSealIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=payload.subject_user_id)
    result = seal_asset_set(
        db,
        asset_set_id=asset_set_id,
        user_id=user_id,
        subject_user_id=payload.subject_user_id,
        report_type=payload.report_type,
        title=payload.title,
        hospital=payload.hospital,
        report_date=payload.report_date,
        storage_root=settings.LOCAL_STORAGE_DIR,
    )
    row = result["asset_set"]
    return {
        "asset_set_id": row.id,
        "status": row.status,
        "workflow_id": result.get("workflow_id"),
        "duplicate": result.get("duplicate", False),
        "failure_code": result.get("failure_code"),
        "recovery_action": result.get("recovery_action"),
        "problem_asset_indices": result.get("problem_asset_indices", []),
        "missing_page_indices": result.get("missing_page_indices", []),
    }


@router.get("/report-workflows", response_model=HealthReportHistoryOut)
def get_report_history(
    subject_user_id: int = Query(...),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    hospital: str | None = Query(default=None, max_length=256),
    report_type: str | None = Query(default=None, max_length=24),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    return {
        "items": list_report_history(
            db,
            user_id=user_id,
            subject_user_id=subject_user_id,
            date_from=date_from,
            date_to=date_to,
            hospital=hospital,
            report_type=report_type,
        )
    }


@router.get("/report-workflows/{workflow_id}/trace", response_model=HealthReportTraceOut)
def get_report_trace(
    workflow_id: int,
    subject_user_id: int = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    return build_report_trace(
        db, workflow_id=workflow_id, user_id=user_id, subject_user_id=subject_user_id
    )


@router.get("/report-workflows/{workflow_id}/assets/{asset_id}/content")
def get_report_original_asset(
    workflow_id: int,
    asset_id: int,
    subject_user_id: int = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    path, asset = resolve_original_asset_path(
        db,
        workflow_id=workflow_id,
        asset_id=asset_id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        storage_root=settings.LOCAL_STORAGE_DIR,
    )
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_filename)


@router.post(
    "/report-workflows/{workflow_id}/score-jobs/retry",
    response_model=HealthReportScoreRetryOut,
)
def retry_report_scores(
    workflow_id: int,
    subject_user_id: int = Query(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _require_self_subject(user_id=user_id, subject_user_id=subject_user_id)
    job = retry_score_job(
        db, workflow_id=workflow_id, user_id=user_id, subject_user_id=subject_user_id
    )
    return {"job_id": job.id, "status": job.status}
