"""Named regressions for RP-01/RP-02/RP-03/RP-06/RP-07."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
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
    HealthReportAssetSetWorkflowLink,
    HealthReportCompletenessAssessment,
    HealthReportFieldLocator,
    HealthReportFollowUpItem,
    HealthReportPage,
    HealthReportScoreJob,
    HealthReportScoreJobItem,
)
from app.models.user import User
from app.services.health_report_trust_service import build_report_runtime
from app.services.report_asset_quality_service import (
    assess_image_quality,
    assess_page_completeness,
    render_pdf_pages,
)
from app.services.report_asset_service import (
    add_asset,
    add_field_locator,
    build_report_trace,
    create_asset_set,
    list_report_history,
    replace_or_add_recovery_asset,
    seal_asset_set,
)
from app.services.report_duplicate_service import (
    ensure_semantic_duplicate_decision,
    ensure_semantic_signature,
    resolve_semantic_duplicate,
)
from app.services.report_follow_up_service import follow_up_presentation, generate_follow_ups
from app.services.report_score_job_service import (
    claim_score_job,
    enqueue_score_job,
    execute_claimed_score_job,
    retry_score_job,
    score_item_presentations,
)
from app.routers import health_reports as legacy_health_reports_router
from app.routers import health_report_trust as health_report_trust_router
from app.services import report_asset_service


def _factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add(User(id=1, phone="18800000401", username="report-completion", password="x"))
        db.commit()
    return factory


def _sharp_report_png(label: str = "CRP") -> bytes:
    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    for y in range(70, 1330, 42):
        draw.text((50, y), f"Health Report {label} {y} 12.5 mg/L range 0-5", fill="black")
        draw.line((45, y + 20, 955, y + 20), fill="gray", width=2)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _candidate(workflow: HealthReportWorkflow, *, name: str, value: str, key: str) -> HealthReportFieldCandidate:
    return HealthReportFieldCandidate(
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        candidate_key=key,
        canonical_code=name.casefold(),
        canonical_name=name,
        raw_name=name,
        raw_value=value,
        normalized_value=Decimal(value) if value.replace(".", "", 1).isdigit() else None,
        normalized_text=None if value.replace(".", "", 1).isdigit() else value,
        normalized_unit="mg/L" if value.replace(".", "", 1).isdigit() else None,
        abnormal_state="abnormal",
        confidence=Decimal("0.9900"),
        effective_at=datetime.now(timezone.utc),
        source_locator={},
        review_status="pending_review",
        requires_review=True,
        version=1,
    )


def test_report_real_image_and_pdf_quality_detects_blur_and_never_truncates_pages():
    sharp = _sharp_report_png()
    sharp_assessment = assess_image_quality(sharp)
    assert sharp_assessment.quality_status == "accepted"

    with Image.open(BytesIO(sharp)) as image:
        blurry = image.filter(ImageFilter.GaussianBlur(radius=6))
        buffer = BytesIO()
        blurry.save(buffer, format="PNG")
    blurry_assessment = assess_image_quality(buffer.getvalue())
    assert blurry_assessment.quality_status == "blurry"
    assert blurry_assessment.failure_code == "blur"

    pages = [Image.new("RGB", (700, 900), color) for color in ("white", "lightgray", "white")]
    pdf = BytesIO()
    pages[0].save(pdf, format="PDF", save_all=True, append_images=pages[1:])
    rendered = render_pdf_pages(pdf.getvalue(), max_pages=3)
    assert [page.page_index for page in rendered] == [1, 2, 3]
    completeness = assess_page_completeness(
        expected_page_count=3, observed_page_indices=[1, 3], basis="user_declared"
    )
    assert completeness.completeness_status == "missing_page"
    assert completeness.missing_page_indices == [2]


def test_report_asset_set_preserves_order_originals_and_field_locator(tmp_path):
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="ordered-assets-1",
            media_kind="photo_library",
            expected_page_count=2,
        )
        for index, label in ((1, "CRP"), (2, "WBC")):
            add_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=index,
                client_asset_id=f"asset-{index}",
                filename=f"page-{index}.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png(label),
                storage_root=str(tmp_path),
            )
        result = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="两页化验报告",
            hospital="测试医院",
            report_date=datetime.now(timezone.utc).date(),
            storage_root=str(tmp_path),
        )
        assert result["workflow_id"] is not None
        workflow = db.get(HealthReportWorkflow, result["workflow_id"])
        pages = list(
            db.execute(
                select(HealthReportPage)
                .where(HealthReportPage.asset_set_id == asset_set.id)
                .order_by(HealthReportPage.page_index)
            ).scalars().all()
        )
        assert [page.page_index for page in pages] == [1, 2]
        assert [row.asset_index for row in db.execute(select(HealthReportAsset).order_by(HealthReportAsset.asset_index)).scalars()] == [1, 2]
        candidate = _candidate(workflow, name="CRP", value="12.5", key="locator-crp")
        db.add(candidate)
        db.flush()
        add_field_locator(
            db,
            workflow_id=workflow.id,
            candidate_id=candidate.id,
            page_id=pages[1].id,
            user_id=1,
            subject_user_id=1,
            region_index=1,
            region_role="value",
            x=Decimal("0.100000"),
            y=Decimal("0.200000"),
            width=Decimal("0.300000"),
            height=Decimal("0.100000"),
            polygon_norm=[],
            provider_id="fixture-ocr",
            model_version="fixture-v1",
            confidence=Decimal("0.9900"),
        )
        db.commit()
        trace = build_report_trace(db, workflow_id=workflow.id, user_id=1, subject_user_id=1)
        assert trace["locators"][0]["page_id"] == pages[1].id
        assert trace["assets"][1]["filename"] == "page-2.png"


def test_rejected_report_replaces_only_bad_page_invalidates_derived_evidence_and_reseals(tmp_path):
    factory = _factory()
    with Image.open(BytesIO(_sharp_report_png("BLUR"))) as image:
        blurry = image.filter(ImageFilter.GaussianBlur(radius=6))
        buffer = BytesIO()
        blurry.save(buffer, format="PNG")
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="recover-bad-page",
            media_kind="photo_library",
            expected_page_count=2,
        )
        first = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="recover-page-1",
            filename="page-1.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("KEEP"),
            storage_root=str(tmp_path),
        )
        rejected = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=2,
            client_asset_id="recover-page-2-old",
            filename="page-2-blurry.png",
            mime_type="image/png",
            file_bytes=buffer.getvalue(),
            storage_root=str(tmp_path),
        )
        result = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="局部重传报告",
            hospital=None,
            report_date=None,
            storage_root=str(tmp_path),
        )
        assert result["failure_code"] == "blur"
        assert result["recovery_action"] == "replace_problem_pages"
        assert result["problem_asset_indices"] == [2]
        assert result["missing_page_indices"] == []
        assert result["asset_set"].status == "rejected"
        assert db.scalar(select(func.count()).select_from(HealthReportPage)) == 2
        assert db.scalar(select(func.count()).select_from(HealthReportAssetQualityResult)) == 2
        assert db.scalar(select(func.count()).select_from(HealthReportCompletenessAssessment)) == 1

        replacement, reopened = replace_or_add_recovery_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=2,
            client_asset_id="recover-page-2-new",
            filename="page-2-clear.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("CLEAR"),
            storage_root=str(tmp_path),
        )
        assert reopened.status == "open"
        assert reopened.sealed_at is None
        assert reopened.aggregate_sha256 is None
        assert replacement.client_asset_id == "recover-page-2-new"
        assert replacement.byte_sha256 != rejected.byte_sha256
        assert db.get(HealthReportAsset, first.id).byte_sha256 == first.byte_sha256
        assert db.scalar(select(func.count()).select_from(HealthReportPage)) == 0
        assert db.scalar(select(func.count()).select_from(HealthReportAssetQualityResult)) == 0
        assert db.scalar(select(func.count()).select_from(HealthReportCompletenessAssessment)) == 0
        audit = reopened.original_summary["replacements"][-1]
        assert audit["old_sha256"] == rejected.byte_sha256
        assert audit["new_sha256"] == replacement.byte_sha256

        resealed = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="局部重传报告",
            hospital=None,
            report_date=None,
            storage_root=str(tmp_path),
        )
        assert resealed["workflow_id"] is not None
        assert resealed["asset_set"].status == "attached"


def test_missing_report_page_can_be_added_without_reuploading_existing_page(tmp_path):
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="recover-missing-page",
            media_kind="photo_library",
            expected_page_count=2,
        )
        first = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="missing-page-1",
            filename="page-1.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("FIRST"),
            storage_root=str(tmp_path),
        )
        rejected = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="缺页报告",
            hospital=None,
            report_date=None,
            storage_root=str(tmp_path),
        )
        assert rejected["failure_code"] == "missing_page"
        assert rejected["recovery_action"] == "upload_missing_pages"
        assert rejected["problem_asset_indices"] == []
        assert rejected["missing_page_indices"] == [2]

        second, reopened = replace_or_add_recovery_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=2,
            client_asset_id="missing-page-2",
            filename="page-2.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("SECOND"),
            storage_root=str(tmp_path),
        )
        assert reopened.received_asset_count == 2
        assert reopened.original_summary["replacements"][-1]["added_missing_page"] is True
        assert db.get(HealthReportAsset, first.id) is not None
        assert second.asset_index == 2


def test_attached_report_asset_set_cannot_be_replaced(tmp_path):
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="attached-no-replace",
            media_kind="photo_library",
            expected_page_count=1,
        )
        add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="attached-page-1",
            filename="page.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png(),
            storage_root=str(tmp_path),
        )
        assert seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="已附加报告",
            hospital=None,
            report_date=None,
            storage_root=str(tmp_path),
        )["workflow_id"] is not None

        with pytest.raises(HTTPException) as error:
            replace_or_add_recovery_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=1,
                client_asset_id="attached-page-new",
                filename="replacement.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png("NEW"),
                storage_root=str(tmp_path),
            )
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "asset_set_not_recoverable"


def test_report_upload_limits_bound_request_read_and_total_asset_set(monkeypatch, tmp_path):
    monkeypatch.setattr(health_report_trust_router, "MAX_REPORT_ASSET_BYTES", 3)
    upload = UploadFile(filename="oversized.bin", file=BytesIO(b"12345"))
    with pytest.raises(HTTPException) as request_error:
        health_report_trust_router._read_bounded_report_upload(upload)
    assert request_error.value.status_code == 413
    assert request_error.value.detail == {"code": "asset_too_large", "max_bytes": 3}
    assert upload.file.tell() == 4

    factory = _factory()
    first_bytes = _sharp_report_png("LIMIT-1")
    second_bytes = _sharp_report_png("LIMIT-2")
    monkeypatch.setattr(
        report_asset_service,
        "MAX_REPORT_ASSET_SET_BYTES",
        len(first_bytes) + len(second_bytes) - 1,
    )
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="asset-set-size-limit",
            media_kind="photo_library",
            expected_page_count=2,
        )
        add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="limit-1",
            filename="limit-1.png",
            mime_type="image/png",
            file_bytes=first_bytes,
            storage_root=str(tmp_path),
        )
        with pytest.raises(HTTPException) as set_error:
            add_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=2,
                client_asset_id="limit-2",
                filename="limit-2.png",
                mime_type="image/png",
                file_bytes=second_bytes,
                storage_root=str(tmp_path),
            )
        assert set_error.value.status_code == 413
        assert set_error.value.detail["code"] == "asset_set_too_large"


def test_semantic_duplicate_requires_explicit_idempotent_choice_before_confirmation():
    factory = _factory()
    now = datetime.now(timezone.utc)
    with factory() as db:
        original = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="semantic-original",
            document_fingerprint="a" * 64,
            report_type="lab",
            status="completed",
            version=2,
            confirmation_client_event_id="confirm-original",
            confirmed_by_user_id=1,
            confirmed_at=now,
            completed_at=now,
            workflow_metadata={},
        )
        db.add(original)
        db.flush()
        first = _candidate(original, name="hsCRP", value="12.5", key="first-hscrp")
        first_wbc = _candidate(original, name="WBC", value="8.1", key="first-wbc")
        db.add_all([first, first_wbc])
        db.flush()
        ensure_semantic_signature(db, workflow=original, candidates=[first, first_wbc])

        incoming = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="semantic-rescan",
            document_fingerprint="b" * 64,
            report_type="lab",
            status="awaiting_confirmation",
            version=1,
            workflow_metadata={},
        )
        db.add(incoming)
        db.flush()
        second = _candidate(incoming, name="hsCRP", value="12.50", key="second-hscrp")
        second_wbc = _candidate(incoming, name="WBC", value="8.10", key="second-wbc")
        db.add_all([second, second_wbc])
        db.flush()
        decision = ensure_semantic_duplicate_decision(
            db, workflow=incoming, candidates=[second, second_wbc]
        )
        assert decision is not None
        assert incoming.status == "recognizing"
        db.commit()
        runtime = build_report_runtime(db, workflow_id=incoming.id, user_id=1, subject_user_id=1)
        assert runtime["state"] == "awaiting_duplicate_decision"
        version = db.get(HealthReportWorkflow, incoming.id).version
        assert runtime["workflow_version"] == version
        resolved = resolve_semantic_duplicate(
            db,
            workflow_id=incoming.id,
            user_id=1,
            subject_user_id=1,
            workflow_version=version,
            action="continue_new",
            client_event_id="continue-semantic-1",
        )
        assert resolved.decision_status == "continue_new"
        retry = resolve_semantic_duplicate(
            db,
            workflow_id=incoming.id,
            user_id=1,
            subject_user_id=1,
            workflow_version=version,
            action="continue_new",
            client_event_id="continue-semantic-1",
        )
        assert retry.id == resolved.id


def _confirmed_inflammation_observation(db: Session, workflow: HealthReportWorkflow) -> None:
    candidate = _candidate(workflow, name="hsCRP", value="12.5", key=f"hscrp-{workflow.id}")
    candidate.review_status = "confirmed"
    candidate.requires_review = False
    db.add(candidate)
    db.flush()
    event = HealthReportConfirmationEvent(
        workflow_id=workflow.id,
        candidate_id=candidate.id,
        user_id=1,
        subject_user_id=1,
        actor_user_id=1,
        client_event_id=f"event-{workflow.id}",
        event_type="confirm",
        candidate_version=1,
        before_data={},
        after_data={},
    )
    db.add(event)
    db.flush()
    db.add(
        ConfirmedHealthObservation(
            workflow_id=workflow.id,
            source_candidate_id=candidate.id,
            confirmation_event_id=event.id,
            user_id=1,
            subject_user_id=1,
            report_confirmation_client_event_id=workflow.confirmation_client_event_id,
            idempotency_key=f"obs-{workflow.id}",
            canonical_code="hscrp",
            canonical_name="超敏C反应蛋白",
            value_numeric=Decimal("12.5"),
            unit="mg/L",
            abnormal_state="abnormal",
            effective_at=workflow.confirmed_at,
            status="active",
            confirmed_by_user_id=1,
            confirmed_at=workflow.confirmed_at,
            version=1,
        )
    )
    db.flush()


def test_report_confirmation_score_job_is_idempotent_and_partial_failure_preserves_report():
    factory = _factory()
    now = datetime.now(timezone.utc)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="score-job-report",
            document_fingerprint="c" * 64,
            report_type="lab",
            status="completed_score_pending",
            version=2,
            confirmation_client_event_id="score-confirmation",
            confirmed_by_user_id=1,
            confirmed_at=now,
            completed_at=now,
            workflow_metadata={},
        )
        db.add(workflow)
        db.flush()
        _confirmed_inflammation_observation(db, workflow)
        first = enqueue_score_job(db, workflow=workflow)
        second = enqueue_score_job(db, workflow=workflow)
        assert first.id == second.id
        db.commit()

        claim = claim_score_job(db)
        assert claim is not None
        job = execute_claimed_score_job(db, job_id=claim[0], lease_token=claim[1])
        assert job.status == "partial_failed"
        assert db.get(HealthReportWorkflow, workflow.id).status == "completed_score_pending"
        assert db.scalar(select(func.count()).select_from(HealthScoreSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(HealthScoreSnapshot).where(HealthScoreSnapshot.score_kind == "x_age")) == 0
        statuses = {
            row.score_kind: row.status
            for row in db.execute(select(HealthReportScoreJobItem).where(HealthReportScoreJobItem.job_id == job.id)).scalars()
        }
        assert statuses == {"stress": "unavailable", "recovery": "unavailable", "inflammation": "completed"}
        presentation = score_item_presentations(db, workflow_id=workflow.id, user_id=1, subject_user_id=1, locale="zh-Hans")
        assert "内部" not in presentation["inflammation"]["method_summary"]["text"]
        assert presentation["stress"]["failure"]["message"]["text"].startswith("缺少")


def test_explicit_score_retry_at_attempt_limit_becomes_claimable_and_only_retries_retryable_items():
    factory = _factory()
    now = datetime.now(timezone.utc)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="score-job-explicit-retry",
            document_fingerprint="e" * 64,
            report_type="lab",
            status="completed_score_pending",
            version=2,
            confirmation_client_event_id="score-retry-confirmation",
            confirmed_by_user_id=1,
            confirmed_at=now,
            completed_at=now,
            workflow_metadata={},
        )
        db.add(workflow)
        db.flush()
        job = enqueue_score_job(db, workflow=workflow)
        items = list(
            db.execute(
                select(HealthReportScoreJobItem)
                .where(HealthReportScoreJobItem.job_id == job.id)
                .order_by(HealthReportScoreJobItem.id)
            ).scalars()
        )
        job.status = "failed"
        job.attempt_count = job.max_attempts
        job.lease_token = "expired-lease"
        job.lease_expires_at = now - timedelta(seconds=1)
        job.finished_at = now
        items[0].status = "failed"
        items[0].retryable = True
        items[1].status = "failed"
        items[1].retryable = False
        items[2].status = "completed"
        db.commit()

        retried = retry_score_job(
            db,
            workflow_id=workflow.id,
            user_id=1,
            subject_user_id=1,
        )
        assert retried.status == "pending"
        assert retried.max_attempts == retried.attempt_count + 1
        assert retried.lease_token is None
        assert retried.lease_expires_at is None
        assert [item.status for item in items] == ["pending", "failed", "completed"]

        claim = claim_score_job(db, now=now + timedelta(seconds=1))
        assert claim is not None
        assert claim[0] == retried.id
        claimed = db.get(HealthReportScoreJob, retried.id)
        assert claimed.status == "running"
        assert claimed.attempt_count == claimed.max_attempts


def test_report_history_includes_null_failure_excludes_withdrawn_and_trace_scopes_every_child_query():
    factory = _factory()
    with factory() as db:
        visible = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="history-visible-null-failure",
            document_fingerprint="f" * 64,
            report_type="lab",
            status="awaiting_confirmation",
            version=1,
            failure_code=None,
            workflow_metadata={},
        )
        withdrawn = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="history-withdrawn",
            document_fingerprint="0" * 64,
            report_type="lab",
            status="failed",
            version=1,
            failure_code="withdrawn",
            workflow_metadata={},
        )
        db.add_all([visible, withdrawn])
        db.commit()

        history = list_report_history(db, user_id=1, subject_user_id=1)
        assert [item["workflow_id"] for item in history] == [visible.id]

        class RecordingSession:
            def __init__(self, delegate: Session):
                self.delegate = delegate
                self.statements = []

            def execute(self, statement, *args, **kwargs):
                self.statements.append(statement)
                return self.delegate.execute(statement, *args, **kwargs)

        recording = RecordingSession(db)
        build_report_trace(
            recording,
            workflow_id=visible.id,
            user_id=1,
            subject_user_id=1,
        )
        compiled = [
            str(statement.compile(compile_kwargs={"literal_binds": True}))
            for statement in recording.statements
        ]
        tenant_tables = (
            HealthReportWorkflow,
            HealthReportAssetSetWorkflowLink,
            HealthReportFieldCandidate,
            HealthReportConfirmationEvent,
            ConfirmedHealthObservation,
            HealthReportFieldLocator,
            HealthReportScoreJob,
            HealthReportScoreJobItem,
            HealthScoreSnapshot,
            HealthReportFollowUpItem,
        )
        for model in tenant_tables:
            table_name = model.__tablename__
            query = next(value for value in compiled if f"FROM {table_name}" in value)
            assert f"{table_name}.user_id = 1" in query
            assert f"{table_name}.subject_user_id = 1" in query


def test_supervised_celery_worker_and_beat_load_generic_app_with_registered_report_sweeps():
    from app.workers.celery_app import celery_app
    from deploy import production_deploy_guard as deploy_guard

    celery_app.loader.import_default_modules()
    assert "process_health_report_score_jobs" in celery_app.tasks
    assert "process_health_report_ocr_workflows" in celery_app.tasks
    assert celery_app.conf.beat_schedule["health-report-score-job-sweep"]["task"] in celery_app.tasks
    assert celery_app.conf.beat_schedule["health-report-ocr-workflow-sweep"]["task"] in celery_app.tasks

    spec_path = Path(__file__).resolve().parents[2] / "deploy" / "production_container.json"
    spec = deploy_guard.load_spec(spec_path)
    assert set(spec["supervised_roles"]) == set(deploy_guard.SUPERVISED_SERVICE_ROLES)
    for role in ("celery-worker", "celery-beat"):
        command = deploy_guard.DEPLOY_ROLE_COMMANDS[role][1]
        assert "app.workers.celery_app:celery_app" in command
        assert "process_health_report_score_jobs" not in command
        assert role in deploy_guard.LONG_RUNNING_ROLES


def test_confirmed_clinician_follow_up_is_traceable_and_localized():
    factory = _factory()
    now = datetime.now(timezone.utc)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id="follow-up-report",
            document_fingerprint="d" * 64,
            report_type="exam",
            status="completed_score_pending",
            version=2,
            confirmation_client_event_id="follow-up-confirm",
            confirmed_by_user_id=1,
            confirmed_at=now,
            completed_at=now,
            workflow_metadata={},
        )
        db.add(workflow)
        db.flush()
        candidate = _candidate(workflow, name="医师建议", value="三个月后复查", key="clinician-follow-up")
        candidate.review_status = "confirmed"
        candidate.requires_review = False
        db.add(candidate)
        db.flush()
        db.add(
            HealthReportConfirmationEvent(
                workflow_id=workflow.id,
                candidate_id=candidate.id,
                user_id=1,
                subject_user_id=1,
                actor_user_id=1,
                client_event_id="follow-up-field-event",
                event_type="confirm",
                candidate_version=1,
                before_data={},
                after_data={},
            )
        )
        db.flush()
        assert len(generate_follow_ups(db, workflow=workflow)) == 1
        db.commit()
        output = follow_up_presentation(db, workflow_id=workflow.id, user_id=1, subject_user_id=1, locale="zh-Hans")
        assert output["available"] is True
        assert "三个月后复查" in output["items"][0]
        assert output["details"][0]["evidence"][0]["confirmation_event_id"] is not None
        assert db.scalar(select(func.count()).select_from(ConfirmedHealthObservation)) == 0


def test_health_ai_summary_uses_only_admitted_observations_even_when_legacy_files_exist(
    monkeypatch,
):
    class _ConsentResult:
        def scalars(self):
            return self

        def first(self):
            return type("ConsentRow", (), {"allow_ai_chat": True})()

    class _DB:
        def execute(self, _statement):
            return _ConsentResult()

    monkeypatch.setattr(
        legacy_health_reports_router,
        "_build_report_data",
        lambda *_args, **_kwargs: pytest.fail(
            "legacy report files must not enter AI summary"
        ),
    )
    from app.services import context_builder

    monkeypatch.setattr(
        context_builder,
        "build_user_context",
        lambda *_args, **_kwargs: {
            "trusted_health_context": {"report_observations": []}
        },
    )

    with pytest.raises(HTTPException) as error:
        legacy_health_reports_router.health_ai_summary(user_id=1, db=_DB())
    assert error.value.status_code == 404
    assert error.value.detail == "No admitted report data to summarize"
