"""Named regressions for RP-01/RP-02/RP-03/RP-06/RP-07."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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
from app.models.user import User
from app.services.health_report_trust_service import (
    build_interpretation,
    build_report_runtime,
)
from app.services.report_asset_quality_service import (
    ReportAssetQualityError,
    assess_image_quality,
    assess_page_completeness,
    render_pdf_pages,
)
from app.services.report_asset_service import (
    add_asset,
    add_field_locator,
    abandon_asset_set,
    build_report_trace,
    cleanup_expired_asset_sets,
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
from app.services.object_storage import (
    LocalPrivateObjectStore,
    ObjectStorageIntegrityError,
    ObjectStorageUnavailableError,
    PrivateObjectWriteLifecycle,
    StoredObjectIdentity,
    StoredObjectMetadata,
)
from app.services.report_follow_up_service import follow_up_presentation, generate_follow_ups
from app.services.report_score_job_service import (
    claim_score_job,
    enqueue_score_job,
    execute_claimed_score_job,
    fail_score_job_claim,
    reconcile_exhausted_score_jobs,
    retry_score_job,
    score_item_presentations,
)
from app.services.report_ocr_service import claim_report_ocr_workflow
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


def test_report_pdf_render_limits_each_page_and_total_bytes_before_persistence():
    image = Image.new("RGB", (700, 900), "white")
    pdf = BytesIO()
    image.save(pdf, format="PDF")
    with pytest.raises(ReportAssetQualityError) as page_error:
        render_pdf_pages(pdf.getvalue(), max_page_bytes=1)
    assert page_error.value.code == "rendered_page_too_large"
    with pytest.raises(ReportAssetQualityError) as total_error:
        render_pdf_pages(
            pdf.getvalue(),
            max_page_bytes=10 * 1024 * 1024,
            max_total_bytes=1,
        )
    assert total_error.value.code == "rendered_pdf_too_large"


def test_report_pdf_seal_post_render_failure_compensates_all_pages_and_db_rows(
    monkeypatch,
    tmp_path,
):
    with Image.open(BytesIO(_sharp_report_png("PDF-COMPENSATE"))) as image:
        pdf = BytesIO()
        image.convert("RGB").save(pdf, format="PDF")
    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="pdf-render-compensation",
            media_kind="pdf",
            expected_page_count=None,
        )
        add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="pdf-render-compensation-asset",
            filename="report.pdf",
            mime_type="application/pdf",
            file_bytes=pdf.getvalue(),
            object_store=store,
        )

        monkeypatch.setattr(
            report_asset_service,
            "_persist_page_quality",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("synthetic quality persistence failure")
            ),
        )
        with pytest.raises(
            RuntimeError,
            match="synthetic quality persistence failure",
        ):
            seal_asset_set(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                report_type="lab",
                title="PDF 渲染补偿",
                hospital=None,
                report_date=None,
                object_store=store,
            )

        assert (
            db.scalar(
                select(func.count()).select_from(HealthReportPage)
            )
            == 0
        )
        rendered_root = tmp_path / "report-pages"
        assert not rendered_root.exists() or not any(
            path.is_file() for path in rendered_root.rglob("*")
        )


def test_private_object_delete_requires_exact_tenant_digest_and_is_idempotent(tmp_path):
    store = LocalPrivateObjectStore(str(tmp_path))
    content = b"tenant-bound-report"
    digest = hashlib.sha256(content).hexdigest()
    metadata = StoredObjectMetadata(
        key="reports/1/1/exact.bin",
        sha256=digest,
        size_bytes=len(content),
        content_type="application/octet-stream",
        owner_user_id=1,
        subject_user_id=1,
    )
    store.put(content=content, metadata=metadata)
    sidecar = tmp_path / "reports/1/1/.exact.bin.xjie-metadata.json"
    sidecar.unlink()
    store.put(content=content, metadata=metadata)
    assert sidecar.is_file(), "精确重放必须为升级前本地对象补齐租户元数据"
    wrong_tenant = StoredObjectIdentity(
        key=metadata.key,
        sha256=metadata.sha256,
        content_type=metadata.content_type,
        owner_user_id=2,
        subject_user_id=2,
    )
    with pytest.raises(ObjectStorageIntegrityError):
        store.delete(identity=wrong_tenant, max_bytes=1024)
    assert store.delete(identity=metadata.identity(), max_bytes=1024) is True
    assert store.delete(identity=metadata.identity(), max_bytes=1024) is False


def test_write_lifecycle_never_compensates_existing_object_when_put_probe_fails():
    class ExistingObjectProbeFailureStore:
        backend_name = "existing-probe-failure"

        def __init__(self):
            self.delete_count = 0

        def put(self, **_kwargs):
            # Models an existing S3 object whose HEAD/get probe times out
            # before the store can return created=False.
            raise ObjectStorageUnavailableError("synthetic existing read timeout")

        def delete(self, **_kwargs):
            self.delete_count += 1
            return True

    class FakeDB:
        def rollback(self):
            return None

    store = ExistingObjectProbeFailureStore()
    lifecycle = PrivateObjectWriteLifecycle(db=FakeDB(), object_store=store)
    metadata = StoredObjectMetadata(
        key="report-assets/1/1/7/existing.object",
        sha256=hashlib.sha256(b"existing").hexdigest(),
        size_bytes=len(b"existing"),
        content_type="image/png",
        owner_user_id=1,
        subject_user_id=1,
    )
    with pytest.raises(ObjectStorageUnavailableError):
        with lifecycle:
            lifecycle.put(content=b"existing", metadata=metadata)
    assert store.delete_count == 0


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
                object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
        stored_assets = list(
            db.execute(
                select(HealthReportAsset).order_by(
                    HealthReportAsset.asset_index
                )
            ).scalars()
        )
        assert [row.asset_index for row in stored_assets] == [1, 2]
        assert all(row.storage_key.endswith(".object") for row in stored_assets)
        assert all(
            row.original_filename not in row.storage_key for row in stored_assets
        )
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


def test_report_asset_idempotent_replay_restores_a_missing_private_object(tmp_path):
    factory = _factory()
    content = _sharp_report_png("RESTORE")
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="restore-idempotent-object",
            media_kind="photo_library",
            expected_page_count=1,
        )
        first = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="restore-idempotent-asset",
            filename="report.png",
            mime_type="image/png",
            file_bytes=content,
            object_store=store,
        )
        object_path = tmp_path / first.storage_key
        object_path.unlink()

        replay = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="restore-idempotent-asset",
            filename="report.png",
            mime_type="image/png",
            file_bytes=content,
            object_store=store,
        )

        assert replay.id == first.id
        assert object_path.read_bytes() == content


def test_report_asset_db_commit_failure_compensates_new_private_object(
    monkeypatch, tmp_path
):
    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="commit-compensation",
            media_kind="photo_library",
            expected_page_count=1,
        )
        monkeypatch.setattr(
            db,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("synthetic commit failure")),
        )
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            add_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=1,
                client_asset_id="commit-compensation-asset",
                filename="report.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png("COMPENSATE"),
                object_store=store,
            )
    assert not any(path.is_file() for path in tmp_path.rglob("*"))

    arbitrary_failure_root = tmp_path / "after-put-failure"
    second_factory = _factory()
    with second_factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="after-put-compensation",
            media_kind="photo_library",
            expected_page_count=1,
        )
        real_add = db.add

        def fail_asset_add(row):
            if isinstance(row, HealthReportAsset):
                raise RuntimeError("synthetic post-put ORM failure")
            return real_add(row)

        monkeypatch.setattr(db, "add", fail_asset_add)
        with pytest.raises(RuntimeError, match="synthetic post-put ORM failure"):
            add_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=1,
                client_asset_id="after-put-asset",
                filename="report.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png("AFTER-PUT"),
                object_store=LocalPrivateObjectStore(
                    str(arbitrary_failure_root)
                ),
            )
    assert not any(
        path.is_file() for path in arbitrary_failure_root.rglob("*")
    )


def test_report_replacement_delete_failure_keeps_durable_cleanup_queue_for_replay(
    tmp_path,
):
    class FailFirstDeleteStore:
        backend_name = "fail-first-delete"

        def __init__(self, delegate):
            self.delegate = delegate
            self.remaining_failures = 1

        def put(self, **kwargs):
            return self.delegate.put(**kwargs)

        def get(self, **kwargs):
            return self.delegate.get(**kwargs)

        def get_bounded(self, **kwargs):
            return self.delegate.get_bounded(**kwargs)

        def delete(self, **kwargs):
            if self.remaining_failures:
                self.remaining_failures -= 1
                from app.services.object_storage import ObjectStorageUnavailableError

                raise ObjectStorageUnavailableError("synthetic unavailable")
            return self.delegate.delete(**kwargs)

    factory = _factory()
    store = FailFirstDeleteStore(LocalPrivateObjectStore(str(tmp_path)))
    old_content = _sharp_report_png("OLD-CLEANUP")
    new_content = _sharp_report_png("NEW-CLEANUP")
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="durable-cleanup-replay",
            media_kind="photo_library",
            expected_page_count=1,
        )
        original = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="durable-cleanup-old",
            filename="old.png",
            mime_type="image/png",
            file_bytes=old_content,
            object_store=store,
        )
        old_path = tmp_path / original.storage_key
        asset_set.status = "rejected"
        db.commit()

        with pytest.raises(HTTPException) as first_attempt:
            replace_or_add_recovery_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=1,
                client_asset_id="durable-cleanup-new",
                filename="new.png",
                mime_type="image/png",
                file_bytes=new_content,
                object_store=store,
            )
        assert first_attempt.value.status_code == 503
        db.expire_all()
        persisted_set = db.get(type(asset_set), asset_set.id)
        assert persisted_set.original_summary["pending_object_cleanup"]
        assert old_path.is_file()

        replay, _ = replace_or_add_recovery_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="durable-cleanup-new",
            filename="new.png",
            mime_type="image/png",
            file_bytes=new_content,
            object_store=store,
        )

        db.refresh(persisted_set)
        assert replay.client_asset_id == "durable-cleanup-new"
        assert "pending_object_cleanup" not in persisted_set.original_summary
        assert not old_path.exists()


def test_report_upload_abandon_is_tenant_bound_idempotent_and_preserves_attached_report(
    tmp_path,
):
    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        db.add(
            User(
                id=2,
                phone="18800000402",
                username="other-report-owner",
                password="x",
            )
        )
        db.commit()
        abandoned_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="explicit-abandon",
            media_kind="photo_library",
            expected_page_count=1,
        )
        abandoned_asset = add_asset(
            db,
            asset_set_id=abandoned_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="explicit-abandon-asset",
            filename="private-report.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("ABANDON"),
            object_store=store,
        )
        abandoned_path = tmp_path / abandoned_asset.storage_key

        with pytest.raises(HTTPException) as wrong_tenant:
            abandon_asset_set(
                db,
                asset_set_id=abandoned_set.id,
                user_id=2,
                subject_user_id=2,
                object_store=store,
            )
        assert wrong_tenant.value.status_code == 404
        assert abandoned_path.is_file()

        terminal = abandon_asset_set(
            db,
            asset_set_id=abandoned_set.id,
            user_id=1,
            subject_user_id=1,
            object_store=store,
        )
        assert terminal.status == "retracted"
        assert terminal.original_summary["upload_session_lifecycle"] == "abandoned"
        assert "pending_object_cleanup" not in terminal.original_summary
        assert not abandoned_path.exists()
        assert db.scalar(select(func.count()).select_from(HealthReportAsset)) == 0
        assert (
            abandon_asset_set(
                db,
                asset_set_id=abandoned_set.id,
                user_id=1,
                subject_user_id=1,
                object_store=store,
            ).id
            == terminal.id
        )
        with pytest.raises(HTTPException) as expired_replay:
            add_asset(
                db,
                asset_set_id=abandoned_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=1,
                client_asset_id="expired-replay",
                filename="replay.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png("REPLAY"),
                object_store=store,
            )
        assert expired_replay.value.status_code == 410

        attached_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="attached-must-survive",
            media_kind="photo_library",
            expected_page_count=1,
        )
        attached_asset = add_asset(
            db,
            asset_set_id=attached_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="attached-must-survive-asset",
            filename="attached.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("ATTACHED"),
            object_store=store,
        )
        attached_path = tmp_path / attached_asset.storage_key
        sealed = seal_asset_set(
            db,
            asset_set_id=attached_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="已绑定报告",
            hospital=None,
            report_date=None,
            object_store=store,
        )
        assert sealed["asset_set"].status == "attached"
        with pytest.raises(HTTPException) as attached_error:
            abandon_asset_set(
                db,
                asset_set_id=attached_set.id,
                user_id=1,
                subject_user_id=1,
                object_store=store,
            )
        assert attached_error.value.status_code == 409
        assert attached_path.is_file()
        assert db.get(HealthReportAsset, attached_asset.id) is not None

    delete_routes = [
        route
        for route in health_report_trust_router.router.routes
        if route.path == "/report-upload-sessions/{asset_set_id}"
        and "DELETE" in route.methods
    ]
    assert len(delete_routes) == 1


def test_expired_report_upload_sweep_replays_durable_cleanup_and_skips_linked_reports(
    tmp_path,
):
    class FailFirstDeleteStore:
        backend_name = "fail-first-expired-delete"

        def __init__(self, delegate):
            self.delegate = delegate
            self.remaining_failures = 1

        def put(self, **kwargs):
            return self.delegate.put(**kwargs)

        def get(self, **kwargs):
            return self.delegate.get(**kwargs)

        def get_bounded(self, **kwargs):
            return self.delegate.get_bounded(**kwargs)

        def delete(self, **kwargs):
            if self.remaining_failures:
                self.remaining_failures -= 1
                raise ObjectStorageUnavailableError("synthetic unavailable")
            return self.delegate.delete(**kwargs)

    factory = _factory()
    store = FailFirstDeleteStore(LocalPrivateObjectStore(str(tmp_path)))
    now = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
    with factory() as db:
        expired_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="ttl-expired",
            media_kind="photo_library",
            expected_page_count=1,
        )
        expired_asset = add_asset(
            db,
            asset_set_id=expired_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="ttl-expired-asset",
            filename="expired.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("EXPIRED"),
            object_store=store,
        )
        expired_set.created_at = now - timedelta(hours=73)

        fresh_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="ttl-fresh",
            media_kind="photo_library",
            expected_page_count=1,
        )
        fresh_asset = add_asset(
            db,
            asset_set_id=fresh_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="ttl-fresh-asset",
            filename="fresh.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("FRESH"),
            object_store=store,
        )
        fresh_set.created_at = now - timedelta(hours=71)

        linked_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="ttl-linked",
            media_kind="photo_library",
            expected_page_count=1,
        )
        linked_asset = add_asset(
            db,
            asset_set_id=linked_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="ttl-linked-asset",
            filename="linked.png",
            mime_type="image/png",
            file_bytes=_sharp_report_png("LINKED"),
            object_store=store,
        )
        assert seal_asset_set(
            db,
            asset_set_id=linked_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="TTL 不得删除",
            hospital=None,
            report_date=None,
            object_store=store,
        )["asset_set"].status == "attached"
        linked_set.created_at = now - timedelta(hours=100)
        db.commit()

        first = cleanup_expired_asset_sets(
            db,
            object_store=store,
            ttl_hours=72,
            batch_size=10,
            now=now,
        )
        assert first == {
            "selected": 1,
            "abandoned": 0,
            "cleanup_pending": 1,
            "skipped": 0,
        }
        db.expire_all()
        pending = db.get(HealthReportAssetSet, expired_set.id)
        assert pending.status == "rejected"
        assert pending.original_summary["upload_session_lifecycle"] == "abandoning"
        assert pending.original_summary["pending_object_cleanup"]
        assert (tmp_path / expired_asset.storage_key).is_file()

        replay = cleanup_expired_asset_sets(
            db,
            object_store=store,
            ttl_hours=72,
            batch_size=10,
            now=now,
        )
        assert replay == {
            "selected": 1,
            "abandoned": 1,
            "cleanup_pending": 0,
            "skipped": 0,
        }
        db.expire_all()
        assert db.get(HealthReportAssetSet, expired_set.id).status == "retracted"
        assert not (tmp_path / expired_asset.storage_key).exists()
        assert db.get(HealthReportAsset, fresh_asset.id) is not None
        assert (tmp_path / fresh_asset.storage_key).is_file()
        assert db.get(HealthReportAsset, linked_asset.id) is not None
        assert (tmp_path / linked_asset.storage_key).is_file()

        with pytest.raises(ValueError):
            cleanup_expired_asset_sets(
                db,
                object_store=store,
                ttl_hours=0,
                batch_size=10,
                now=now,
            )


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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
        )
        assert result["failure_code"] == "blur"
        assert result["recovery_action"] == "replace_problem_pages"
        assert result["problem_asset_indices"] == [2]
        assert result["missing_page_indices"] == []
        assert result["asset_set"].status == "rejected"
        assert db.scalar(select(func.count()).select_from(HealthReportPage)) == 2
        assert db.scalar(select(func.count()).select_from(HealthReportAssetQualityResult)) == 2
        assert db.scalar(select(func.count()).select_from(HealthReportCompletenessAssessment)) == 1
        rejected_object_path = tmp_path / rejected.storage_key
        assert rejected_object_path.is_file()

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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
        assert not rejected_object_path.exists()

        resealed = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="局部重传报告",
            hospital=None,
            report_date=None,
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
                object_store=LocalPrivateObjectStore(str(tmp_path)),
            )
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "asset_set_not_recoverable"


def test_failed_ocr_exact_reupload_rebinds_durable_asset_set_and_restarts_same_workflow(
    tmp_path,
):
    """保留历史回归 ID，并验证内容重试耗尽后的精确重传。"""

    _assert_failed_ocr_exact_reupload_rebinds_and_restarts(
        tmp_path,
        "report_ocr_retry_exhausted",
    )


@pytest.mark.parametrize(
    "failure_code",
    ["report_ocr_stalled", "report_ocr_provider_unavailable"],
    ids=["stalled", "provider-unavailable"],
)
def test_failed_ocr_exact_reupload_additional_technical_failures_rebind_and_restart(
    tmp_path,
    failure_code,
):
    """所有声明可重传的新增技术失败都必须真正恢复同一 workflow。"""

    _assert_failed_ocr_exact_reupload_rebinds_and_restarts(
        tmp_path,
        failure_code,
    )


def _assert_failed_ocr_exact_reupload_rebinds_and_restarts(
    tmp_path,
    failure_code,
):
    factory = _factory()
    content = _sharp_report_png("RETRY")
    durable_store = LocalPrivateObjectStore(str(tmp_path / "durable-store"))
    with factory() as db:
        first_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="failed-ocr-original",
            media_kind="photo_library",
            expected_page_count=1,
        )
        original_asset = add_asset(
            db,
            asset_set_id=first_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="failed-ocr-original-asset",
            filename="report.png",
            mime_type="image/png",
            file_bytes=content,
            object_store=durable_store,
        )
        first_result = seal_asset_set(
            db,
            asset_set_id=first_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="旧失败任务",
            hospital=None,
            report_date=None,
            object_store=durable_store,
        )
        workflow = db.get(HealthReportWorkflow, first_result["workflow_id"])
        workflow.status = "failed"
        workflow.failure_code = failure_code
        workflow.failure_detail = "bounded retry exhausted"
        workflow.workflow_metadata = {
            "asset_set_id": first_set.id,
            "ocr_state": "failed",
            "ocr_attempt_count": 3,
        }
        db.commit()
        original_object_path = (
            tmp_path / "durable-store" / original_asset.storage_key
        )
        assert original_object_path.is_file()

        replacement_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="failed-ocr-reupload",
            media_kind="photo_library",
            expected_page_count=1,
        )
        add_asset(
            db,
            asset_set_id=replacement_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="failed-ocr-reupload-asset",
            filename="report.png",
            mime_type="image/png",
            file_bytes=content,
            object_store=durable_store,
        )
        recovered = seal_asset_set(
            db,
            asset_set_id=replacement_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="exam",
            title="重新上传任务",
            hospital=None,
            report_date=None,
            object_store=durable_store,
        )

        db.refresh(workflow)
        db.refresh(first_set)
        link = db.scalar(
            select(HealthReportAssetSetWorkflowLink).where(
                HealthReportAssetSetWorkflowLink.workflow_id == workflow.id
            )
        )
        assert recovered["workflow_id"] == workflow.id
        assert recovered["duplicate"] is False
        assert workflow.status == "recognizing"
        assert workflow.report_type == "exam"
        assert db.scalar(
            select(HealthReportDescriptor.report_type).where(
                HealthReportDescriptor.workflow_id == workflow.id
            )
        ) == "exam"
        assert workflow.failure_code is None
        assert workflow.workflow_metadata["ocr_state"] == "pending"
        assert workflow.workflow_metadata["ocr_attempt_count"] == 0
        assert workflow.workflow_metadata["ocr_recovered_from_asset_set_id"] == first_set.id
        assert (
            workflow.workflow_metadata["ocr_recovered_from_client_request_id"]
            == "failed-ocr-original"
        )
        assert workflow.client_request_id == "failed-ocr-reupload"
        assert link.asset_set_id == replacement_set.id
        assert first_set.status == "retracted"
        assert recovered["asset_set"].status == "attached"
        assert not original_object_path.exists()
        claim = claim_report_ocr_workflow(db)
        assert claim is not None
        assert claim[0] == workflow.id


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
            object_store=LocalPrivateObjectStore(str(tmp_path)),
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
                object_store=LocalPrivateObjectStore(str(tmp_path)),
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
        assert db.get(HealthReportWorkflow, workflow.id).status == "completed"
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
        interpretation = build_interpretation(
            db,
            workflow_id=workflow.id,
            user_id=1,
            subject_user_id=1,
            locale="zh-Hans",
        )
        assert interpretation["score_state"] == "partial_failed"
        assert interpretation["score_pending"] is False


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


def test_score_worker_three_crashes_and_expired_final_lease_atomically_end_report(
    monkeypatch,
):
    from app.workers import health_score_tasks

    factory = _factory()
    now = datetime.now(timezone.utc)

    def add_score_workflow(db: Session, *, suffix: str) -> tuple[int, int]:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            client_request_id=f"score-crash-{suffix}",
            document_fingerprint=("8" if suffix == "caught" else "9") * 64,
            report_type="lab",
            status="completed_score_pending",
            version=2,
            confirmation_client_event_id=f"score-crash-confirmation-{suffix}",
            confirmed_by_user_id=1,
            confirmed_at=now,
            completed_at=now,
            workflow_metadata={},
        )
        db.add(workflow)
        db.flush()
        job = enqueue_score_job(db, workflow=workflow)
        db.commit()
        return workflow.id, job.id

    with factory() as db:
        caught_workflow_id, caught_job_id = add_score_workflow(
            db,
            suffix="caught",
        )

    monkeypatch.setattr(health_score_tasks, "SessionLocal", factory)

    def crash_score_execution(*_args, **_kwargs):
        raise RuntimeError("synthetic score worker crash")

    monkeypatch.setattr(
        health_score_tasks,
        "execute_claimed_score_job",
        crash_score_execution,
    )

    for attempt in range(1, 4):
        outcome = health_score_tasks.process_health_report_score_jobs.run(
            max_jobs=1
        )
        assert outcome["failed"] == 1
        with factory() as db:
            job = db.get(HealthReportScoreJob, caught_job_id)
            workflow = db.get(HealthReportWorkflow, caught_workflow_id)
            assert job.attempt_count == attempt
            if attempt < 3:
                assert job.status == "pending"
                assert job.lease_token is None
                assert job.lease_expires_at is None
                assert workflow.status == "completed_score_pending"
                assert workflow.version == 2
                job.next_attempt_at = datetime.now(timezone.utc) - timedelta(
                    seconds=1
                )
                db.commit()
            else:
                assert job.status == "failed"
                assert job.last_failure_code == "score_worker_execution_failed"
                assert job.finished_at is not None
                assert job.next_attempt_at is None
                assert job.lease_token is None
                assert job.lease_expires_at is None
                assert workflow.status == "completed"
                assert workflow.version == 3
                items = list(
                    db.scalars(
                        select(HealthReportScoreJobItem).where(
                            HealthReportScoreJobItem.job_id == caught_job_id
                        )
                    )
                )
                assert {item.status for item in items} == {"failed"}
                assert all(item.retryable for item in items)

    with factory() as db:
        assert (
            fail_score_job_claim(
                db,
                job_id=caught_job_id,
                lease_token="stale-worker-token",
            )
            is False
        )
        assert db.get(HealthReportWorkflow, caught_workflow_id).version == 3

    with factory() as db:
        expired_workflow_id, expired_job_id = add_score_workflow(
            db,
            suffix="expired",
        )
        expired_job = db.get(HealthReportScoreJob, expired_job_id)
        expired_job.status = "running"
        expired_job.attempt_count = expired_job.max_attempts
        expired_job.lease_token = "dead-worker-token"
        expired_job.lease_expires_at = now - timedelta(seconds=1)
        db.commit()

    outcome = health_score_tasks.process_health_report_score_jobs.run(max_jobs=1)
    assert outcome == {
        "processed": 0,
        "failed": 0,
        "exhausted_reconciled": 1,
    }
    with factory() as db:
        expired_job = db.get(HealthReportScoreJob, expired_job_id)
        expired_workflow = db.get(HealthReportWorkflow, expired_workflow_id)
        assert expired_job.status == "failed"
        assert expired_job.last_failure_code == "score_worker_attempts_exhausted"
        assert expired_job.lease_token is None
        assert expired_job.lease_expires_at is None
        assert expired_workflow.status == "completed"
        assert expired_workflow.version == 3
        assert reconcile_exhausted_score_jobs(db, now=now) == 0


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


def test_report_history_date_range_uses_created_at_for_undated_reports_and_orders_by_effective_date():
    factory = _factory()
    with factory() as db:
        def add_workflow(
            request_id: str,
            created_at: datetime,
            *,
            report_date: date | None,
            add_descriptor: bool = True,
        ) -> HealthReportWorkflow:
            workflow = HealthReportWorkflow(
                user_id=1,
                subject_user_id=1,
                client_request_id=request_id,
                document_fingerprint=request_id.encode().hex().ljust(64, "0")[:64],
                report_type="lab",
                status="recognizing",
                version=1,
                failure_code=None,
                workflow_metadata={},
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(workflow)
            db.flush()
            if add_descriptor:
                db.add(
                    HealthReportDescriptor(
                        workflow_id=workflow.id,
                        user_id=1,
                        subject_user_id=1,
                        title=request_id,
                        hospital=None,
                        hospital_normalized=None,
                        report_date=report_date,
                        report_type="lab",
                    )
                )
            return workflow

        newest_undated = add_workflow(
            "history-undated-new",
            datetime(2026, 7, 30, 8, tzinfo=timezone.utc),
            report_date=None,
        )
        dated = add_workflow(
            "history-explicit-date",
            datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
            report_date=date(2026, 7, 29),
        )
        descriptor_missing = add_workflow(
            "history-no-descriptor",
            datetime(2026, 7, 28, 8, tzinfo=timezone.utc),
            report_date=None,
            add_descriptor=False,
        )
        old_undated = add_workflow(
            "history-undated-old",
            datetime(2025, 7, 29, 8, tzinfo=timezone.utc),
            report_date=None,
        )
        db.commit()

        history = list_report_history(
            db,
            user_id=1,
            subject_user_id=1,
            date_from=date(2025, 7, 30),
            date_to=date(2026, 7, 30),
        )

        assert [item["workflow_id"] for item in history] == [
            newest_undated.id,
            dated.id,
            descriptor_missing.id,
        ]
        assert history[0]["report_date"] is None
        assert history[1]["report_date"] == date(2026, 7, 29)
        assert history[2]["title"] == f"报告 {descriptor_missing.id}"
        assert old_undated.id not in {item["workflow_id"] for item in history}


def test_supervised_celery_worker_and_beat_load_generic_app_with_registered_report_sweeps():
    from app.workers.celery_app import celery_app
    from deploy import production_deploy_guard as deploy_guard

    celery_app.loader.import_default_modules()
    assert "cleanup_expired_health_report_upload_sessions" in celery_app.tasks
    assert "cleanup_terminal_health_report_originals" in celery_app.tasks
    assert "process_health_report_score_jobs" in celery_app.tasks
    assert "process_health_report_ocr_workflows" in celery_app.tasks
    assert celery_app.conf.beat_schedule["health-report-score-job-sweep"]["task"] in celery_app.tasks
    assert celery_app.conf.beat_schedule["health-report-ocr-workflow-sweep"]["task"] in celery_app.tasks
    assert (
        celery_app.conf.beat_schedule["health-report-upload-session-cleanup"][
            "task"
        ]
        in celery_app.tasks
    )
    assert (
        celery_app.conf.beat_schedule["health-report-terminal-original-cleanup"][
            "task"
        ]
        in celery_app.tasks
    )

    spec_path = Path(__file__).resolve().parents[2] / "deploy" / "production_container.json"
    spec = deploy_guard.load_spec(spec_path)
    assert set(spec["supervised_roles"]) == set(deploy_guard.SUPERVISED_SERVICE_ROLES)
    for role in ("celery-worker", "celery-beat"):
        command = deploy_guard.DEPLOY_ROLE_COMMANDS[role][1]
        assert "app.workers.celery_app:celery_app" in command
        assert "process_health_report_score_jobs" not in command
        assert role in deploy_guard.LONG_RUNNING_ROLES

    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    services_text = (
        compose_path.read_text(encoding="utf-8")
        .split("services:\n", 1)[1]
        .split("\nvolumes:\n", 1)[0]
    )
    service_blocks: dict[str, list[str]] = {}
    current_service: str | None = None
    for line in services_text.splitlines():
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current_service = line.strip()[:-1]
            service_blocks[current_service] = []
        elif current_service:
            service_blocks[current_service].append(line)

    assert {"backend", "worker", "beat"} <= service_blocks.keys()
    shared_runtime_lines = {
        "    build:",
        "      context: ./backend",
        "    env_file:",
        "      - ./backend/.env.example",
        "    volumes:",
        "      - ./backend:/app",
        "      - /tmp/metabodash_uploads:/tmp/metabodash_uploads",
        "    depends_on:",
        "      - db",
        "      - redis",
    }
    for role in ("backend", "worker", "beat"):
        assert shared_runtime_lines <= set(service_blocks[role])
    assert (
        "    command: celery -A app.workers.celery_app.celery_app worker --loglevel=info"
        in service_blocks["worker"]
    )
    assert (
        "    command: celery -A app.workers.celery_app.celery_app beat --loglevel=info"
        in service_blocks["beat"]
    )


def test_report_seal_best_effort_wakes_ocr_without_rolling_back_on_broker_failure(
    monkeypatch,
):
    wakeups: list[int] = []

    monkeypatch.setattr(
        health_report_trust_router,
        "seal_asset_set",
        lambda *_args, **_kwargs: {
            "asset_set": SimpleNamespace(id=19, status="attached"),
            "workflow_id": 42,
            "duplicate": False,
        },
    )
    monkeypatch.setattr(
        health_report_trust_router,
        "_report_object_store",
        lambda: object(),
    )
    monkeypatch.setattr(
        health_report_trust_router,
        "_best_effort_wake_report_ocr",
        lambda workflow_id: wakeups.append(workflow_id) or False,
    )
    result = health_report_trust_router.seal_report_upload_session(
        19,
        SimpleNamespace(
            subject_user_id=1,
            report_type="lab",
            title="报告",
            hospital=None,
            report_date=None,
        ),
        user_id=1,
        db=object(),
    )

    assert result["workflow_id"] == 42
    assert result["status"] == "attached"
    assert wakeups == [42]


def test_report_ocr_broker_wakeup_failure_is_absorbed_by_sweep_fallback(monkeypatch):
    def broker_down():
        raise RuntimeError("synthetic broker outage")

    monkeypatch.setattr(
        health_report_trust_router,
        "_dispatch_report_ocr_wakeup",
        broker_down,
    )

    assert health_report_trust_router._best_effort_wake_report_ocr(42) is False


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
