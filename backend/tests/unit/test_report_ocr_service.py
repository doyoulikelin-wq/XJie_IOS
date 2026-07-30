"""Named regressions for durable report OCR and real page locators."""

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.health_trust import HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import HealthReportFieldLocator
from app.models.user import User
from app.services.report_asset_service import add_asset, create_asset_set, seal_asset_set
from app.services.object_storage import (
    LocalPrivateObjectStore,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    StoredObjectIdentity,
    StoredObjectMetadata,
)
from app.services.report_ocr_service import (
    claim_report_ocr_workflow,
    defer_report_ocr_infrastructure_claim,
    execute_report_ocr_workflow,
    fail_report_ocr_claim,
    normalize_provider_items,
    report_ocr_infrastructure_reason,
)


def _factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add(User(id=1, phone="18800000402", username="report-ocr", password="x"))
        db.commit()
    return factory


def _sharp_report_png() -> bytes:
    image = Image.new("RGB", (1000, 1400), "white")
    draw = ImageDraw.Draw(image)
    for y in range(70, 1330, 42):
        draw.text((50, y), f"Health Report CRP {y} 12.5 mg/L range 0-5", fill="black")
        draw.line((45, y + 20, 955, y + 20), fill="gray", width=2)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _sharp_report_pdf() -> bytes:
    image = Image.open(BytesIO(_sharp_report_png())).convert("RGB")
    output = BytesIO()
    image.save(output, format="PDF")
    return output.getvalue()


class _SharedPrivateObjectStore:
    """模拟两个容器分别构造客户端、共同访问同一私有对象桶。"""

    backend_name = "shared-test"

    def __init__(self, objects: dict[str, tuple[bytes, StoredObjectMetadata]]) -> None:
        self.objects = objects
        self.read_keys: list[str] = []

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> bool:
        if hashlib.sha256(content).hexdigest() != metadata.sha256:
            raise ObjectStorageIntegrityError("test object digest mismatch")
        existing = self.objects.get(metadata.key)
        if existing is not None and existing != (content, metadata):
            raise ObjectStorageIntegrityError("test object collision")
        if existing is not None:
            return False
        self.objects[metadata.key] = (content, metadata)
        return True

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes:
        stored = self.objects.get(metadata.key)
        if stored is None:
            raise ObjectStorageNotFoundError("test object missing")
        content, stored_metadata = stored
        if (
            stored_metadata != metadata
            or len(content) > max_bytes
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            raise ObjectStorageIntegrityError("test object identity mismatch")
        self.read_keys.append(metadata.key)
        return content

    def get_bounded(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bytes:
        stored = self.objects.get(identity.key)
        if stored is None:
            raise ObjectStorageNotFoundError("test object missing")
        content, metadata = stored
        if (
            metadata.identity() != identity
            or len(content) > max_bytes
            or hashlib.sha256(content).hexdigest() != identity.sha256
        ):
            raise ObjectStorageIntegrityError("test object identity mismatch")
        self.read_keys.append(identity.key)
        return content


def _create_sealed_workflow(db, tmp_path, request_id: str) -> HealthReportWorkflow:
    asset_set = create_asset_set(
        db,
        user_id=1,
        subject_user_id=1,
        client_request_id=request_id,
        media_kind="photo_library",
        expected_page_count=1,
    )
    add_asset(
        db,
        asset_set_id=asset_set.id,
        user_id=1,
        subject_user_id=1,
        asset_index=1,
        client_asset_id=f"{request_id}-asset",
        filename="report.png",
        mime_type="image/png",
        file_bytes=_sharp_report_png(),
        object_store=LocalPrivateObjectStore(str(tmp_path)),
    )
    result = seal_asset_set(
        db,
        asset_set_id=asset_set.id,
        user_id=1,
        subject_user_id=1,
        report_type="lab",
        title="带坐标的报告",
        hospital="测试医院",
        report_date=datetime.now(timezone.utc).date(),
        object_store=LocalPrivateObjectStore(str(tmp_path)),
    )
    return db.get(HealthReportWorkflow, result["workflow_id"])


def test_report_ocr_drops_missing_placeholder_and_out_of_bounds_provider_boxes():
    items = normalize_provider_items(
        [
            {"name": "无坐标", "value": "1"},
            {"name": "占位", "value": "2", "bbox": [0, 0, 1, 1]},
            {"name": "越界", "value": "3", "bbox": [0.8, 0.2, 0.3, 0.1]},
            {
                "name": "CRP",
                "value": "12.5",
                "unit": "mg/L",
                "confidence": 0.99,
                "bbox": [0.123456, 0.234567, 0.345678, 0.045678],
            },
        ]
    )
    assert [item.raw_name for item in items] == ["CRP"]
    assert items[0].bbox == (
        Decimal("0.123456"),
        Decimal("0.234567"),
        Decimal("0.345678"),
        Decimal("0.045678"),
    )


def test_report_ocr_claim_is_durable_and_persists_exact_provider_locator(tmp_path):
    class FixtureExtractor:
        provider_id = "fixture-real-locator"
        model_version = "fixture-vision-v1"

        def extract_page(self, *, image_bytes: bytes, mime_type: str, page_index: int):
            assert image_bytes
            assert mime_type == "image/png"
            assert page_index == 1
            return [
                {"name": "missing-box", "value": "99"},
                {
                    "name": "CRP",
                    "value": "12.5",
                    "unit": "mg/L",
                    "reference_low": 0,
                    "reference_high": 5,
                    "reference_text": "0-5",
                    "abnormal_state": "abnormal",
                    "confidence": 0.9876,
                    "bbox": [0.123456, 0.234567, 0.345678, 0.045678],
                },
            ]

    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "durable-ocr")
        claim = claim_report_ocr_workflow(db)
        assert claim and claim[0] == workflow.id
        assert claim_report_ocr_workflow(db) is None

        count = execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=FixtureExtractor(),
            object_store=LocalPrivateObjectStore(str(tmp_path)),
        )
        assert count == 1
        workflow = db.get(HealthReportWorkflow, workflow.id)
        assert workflow.status == "awaiting_confirmation"
        assert workflow.workflow_metadata["ocr_state"] == "completed"
        assert "ocr_claim_token" not in workflow.workflow_metadata
        candidate = db.scalar(select(HealthReportFieldCandidate))
        assert candidate.review_status == "pending_review"
        assert candidate.requires_review is True
        assert candidate.source_locator["bbox_source"] == "provider_output"
        assert candidate.source_locator["bbox"] == [
            "0.123456",
            "0.234567",
            "0.345678",
            "0.045678",
        ]
        locator = db.scalar(select(HealthReportFieldLocator))
        assert (locator.x, locator.y, locator.width, locator.height) == (
            Decimal("0.123456"),
            Decimal("0.234567"),
            Decimal("0.345678"),
            Decimal("0.045678"),
        )
        assert locator.provider_id == "fixture-real-locator"
        assert locator.locator_version == "provider-normalized-region-v1"


def test_report_ocr_reads_pdf_page_written_by_api_from_separate_worker_store_instance():
    class FixtureExtractor:
        provider_id = "fixture-shared-object-store"
        model_version = "fixture-vision-v1"

        def __init__(self) -> None:
            self.call_count = 0

        def extract_page(self, *, image_bytes: bytes, mime_type: str, page_index: int):
            self.call_count += 1
            assert image_bytes.startswith(b"\x89PNG")
            assert mime_type == "image/png"
            assert page_index == 1
            return [
                {
                    "name": "CRP",
                    "value": "12.5",
                    "unit": "mg/L",
                    "bbox": [0.1, 0.2, 0.3, 0.1],
                }
            ]

    shared_objects: dict[str, tuple[bytes, StoredObjectMetadata]] = {}
    api_store = _SharedPrivateObjectStore(shared_objects)
    worker_store = _SharedPrivateObjectStore(shared_objects)
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="cross-container-pdf",
            media_kind="pdf",
            expected_page_count=None,
        )
        add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="cross-container-pdf-asset",
            filename="report.pdf",
            mime_type="application/pdf",
            file_bytes=_sharp_report_pdf(),
            object_store=api_store,
        )
        result = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="跨容器 PDF",
            hospital="测试医院",
            report_date=datetime.now(timezone.utc).date(),
            object_store=api_store,
        )
        claim = claim_report_ocr_workflow(db)
        assert claim and claim[0] == result["workflow_id"]
        rendered_key = next(
            key for key in shared_objects if key.startswith("report-pages/")
        )
        rendered_object = shared_objects[rendered_key]
        shared_objects[rendered_key] = (b"tampered-page", rendered_object[1])
        extractor = FixtureExtractor()
        with pytest.raises(ObjectStorageIntegrityError):
            execute_report_ocr_workflow(
                db,
                workflow_id=claim[0],
                claim_token=claim[1],
                extractor=extractor,
                object_store=worker_store,
            )
        assert extractor.call_count == 0
        shared_objects[rendered_key] = rendered_object

        count = execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=extractor,
            object_store=worker_store,
        )

        assert count == 1
        assert extractor.call_count == 1
        assert api_store is not worker_store
        assert any(key.startswith("report-pages/") for key in worker_store.read_keys)
        workflow = db.get(HealthReportWorkflow, claim[0])
        assert workflow.status == "awaiting_confirmation"
        assert workflow.workflow_metadata["ocr_state"] == "completed"


def test_report_ocr_without_any_real_locator_fails_without_candidates(tmp_path):
    class NoLocatorExtractor:
        provider_id = "fixture-no-locator"
        model_version = "fixture-vision-v1"

        def extract_page(self, **_kwargs):
            return [{"name": "CRP", "value": "12.5"}]

    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-no-locator")
        claim = claim_report_ocr_workflow(db)
        assert claim
        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=NoLocatorExtractor(),
            object_store=LocalPrivateObjectStore(str(tmp_path)),
        ) == 0
        workflow = db.get(HealthReportWorkflow, workflow.id)
        assert workflow.status == "failed"
        assert workflow.failure_code == "no_reviewable_candidates"
        assert db.scalar(select(func.count()).select_from(HealthReportFieldCandidate)) == 0
        assert db.scalar(select(func.count()).select_from(HealthReportFieldLocator)) == 0


def test_report_ocr_failed_claim_retries_are_bounded_and_terminal():
    factory = _factory()
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-bounded-retry",
            document_fingerprint="9" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={},
        )
        db.add(workflow)
        db.commit()
        first_claim = claim_report_ocr_workflow(db)
        assert first_claim and first_claim[0] == workflow.id
        fail_report_ocr_claim(
            db,
            workflow_id=first_claim[0],
            claim_token=first_claim[1],
        )
        assert (
            claim_report_ocr_workflow(
                db,
                exclude_workflow_ids={workflow.id},
            )
            is None
        )
        for _ in range(2):
            claim = claim_report_ocr_workflow(db)
            assert claim and claim[0] == workflow.id
            fail_report_ocr_claim(db, workflow_id=claim[0], claim_token=claim[1])
        workflow = db.get(HealthReportWorkflow, workflow.id)
        assert workflow.status == "failed"
        assert workflow.failure_code == "report_ocr_retry_exhausted"
        assert workflow.workflow_metadata["ocr_attempt_count"] == 3
        assert claim_report_ocr_workflow(db) is None


def test_report_ocr_storage_failure_is_delayed_without_consuming_content_retry():
    factory = _factory()
    now = datetime(2026, 7, 30, 8, tzinfo=timezone.utc)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-storage-delay",
            document_fingerprint="8" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={},
        )
        db.add(workflow)
        db.commit()
        claim = claim_report_ocr_workflow(db, now=now)
        assert claim and claim[0] == workflow.id
        reason = report_ocr_infrastructure_reason(
            ObjectStorageNotFoundError("missing")
        )
        defer_report_ocr_infrastructure_claim(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            reason_code=reason,
            now=now,
            retry_delay_seconds=120,
        )
        db.refresh(workflow)
        assert workflow.workflow_metadata["ocr_attempt_count"] == 0
        assert workflow.workflow_metadata["ocr_infrastructure_state"] == "delayed"
        assert workflow.workflow_metadata["ocr_infrastructure_reason"] == (
            "object_storage_not_found"
        )
        assert workflow.workflow_metadata["ocr_infrastructure_attempt_count"] == 1
        assert claim_report_ocr_workflow(
            db,
            now=now + timedelta(seconds=119),
        ) is None
        retried = claim_report_ocr_workflow(
            db,
            now=now + timedelta(seconds=121),
        )
        assert retried and retried[0] == workflow.id
        db.refresh(workflow)
        assert workflow.workflow_metadata["ocr_attempt_count"] == 1
        for infrastructure_attempt in range(2, 6):
            deferred_at = now + timedelta(seconds=121 * infrastructure_attempt)
            defer_report_ocr_infrastructure_claim(
                db,
                workflow_id=retried[0],
                claim_token=retried[1],
                reason_code=reason,
                now=deferred_at,
                retry_delay_seconds=120,
            )
            db.refresh(workflow)
            assert workflow.workflow_metadata["ocr_attempt_count"] == 0
            assert (
                workflow.workflow_metadata["ocr_infrastructure_attempt_count"]
                == infrastructure_attempt
            )
            if infrastructure_attempt < 5:
                retried = claim_report_ocr_workflow(
                    db,
                    now=deferred_at + timedelta(seconds=121),
                )
                assert retried and retried[0] == workflow.id
        assert workflow.status == "failed"
        assert workflow.failure_code == "report_ocr_storage_unavailable"
        assert workflow.workflow_metadata["ocr_infrastructure_state"] == "failed"
        assert claim_report_ocr_workflow(
            db,
            now=now + timedelta(days=1),
        ) is None
