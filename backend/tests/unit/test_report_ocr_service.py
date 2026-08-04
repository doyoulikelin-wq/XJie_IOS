"""Named regressions for durable report OCR and real page locators."""

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.models.health_trust import HealthReportFieldCandidate, HealthReportWorkflow
from app.models.health_trust_expansion import (
    HealthReportAsset,
    HealthReportAssetQualityResult,
    HealthReportAssetSet,
    HealthReportAssetSetWorkflowLink,
    HealthReportFieldLocator,
    HealthReportPage,
)
from app.models.user import User
from app.services import report_ocr_service
from app.services.health_report_trust_service import build_report_runtime
from app.services.report_asset_quality_service import (
    assess_image_quality,
    render_image_page,
)
from app.services.report_asset_service import (
    acknowledge_local_original_binding,
    add_asset,
    cleanup_pending_attached_report_objects,
    create_asset_set,
    queue_terminal_report_object_retirements,
    read_original_asset_content,
    replace_or_add_recovery_asset,
    retire_attached_report_objects,
    seal_asset_set,
)
from app.services.object_storage import (
    LocalPrivateObjectStore,
    ObjectStorageConfigurationError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    StoredObjectIdentity,
    StoredObjectMetadata,
    configured_report_object_store,
    validate_report_object_storage_configuration,
)
from app.services.report_ocr_service import (
    claim_report_ocr_workflow,
    defer_report_ocr_infrastructure_claim,
    execute_report_ocr_workflow,
    fail_report_ocr_claim,
    normalize_provider_items,
    report_ocr_infrastructure_reason,
)
from app.workers import report_ocr_tasks


_SYNTHETIC_HEIC_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "synthetic_health_report.heic"
)
_SYNTHETIC_HEIC_SHA256 = (
    "993305a3a04704faab5a9714d4804d0a3cab795f1a26c68256abacec211370b5"
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


def _sharp_report_jpeg() -> bytes:
    image = Image.open(BytesIO(_sharp_report_png())).convert("RGB")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
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


def _ack_local_original(db, workflow: HealthReportWorkflow) -> None:
    """模拟新版 iOS 在本地 workflow 绑定成功后提交的删除授权证明。"""

    asset_set = db.scalar(select(HealthReportAssetSet))
    assert acknowledge_local_original_binding(
        db,
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        client_request_id=workflow.client_request_id,
        contract_version=1,
        asset_count=asset_set.received_asset_count,
        aggregate_sha256=asset_set.aggregate_sha256,
    )


@pytest.mark.parametrize(
    ("mismatch", "expected_status"),
    [
        ("user", 404),
        ("subject", 404),
        ("request", 409),
        ("asset_count", 409),
        ("digest", 409),
        ("contract", 422),
    ],
)
def test_local_original_ack_rejects_every_tenant_and_manifest_mismatch(
    tmp_path,
    mismatch,
    expected_status,
):
    """账号、主体、request、数量、摘要或协议任一错配都不能产生删除授权。"""

    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(
            db,
            tmp_path,
            f"ack-mismatch-{mismatch}",
        )
        workflow.status = "failed"
        db.commit()
        asset = db.scalar(select(HealthReportAsset))
        asset_set = db.scalar(select(HealthReportAssetSet))
        values = {
            "workflow_id": workflow.id,
            "user_id": workflow.user_id,
            "subject_user_id": workflow.subject_user_id,
            "client_request_id": workflow.client_request_id,
            "contract_version": 1,
            "asset_count": asset_set.received_asset_count,
            "aggregate_sha256": asset_set.aggregate_sha256,
        }
        if mismatch == "user":
            values["user_id"] = 2
        elif mismatch == "subject":
            values["subject_user_id"] = 2
        elif mismatch == "request":
            values["client_request_id"] = "wrong-request"
        elif mismatch == "asset_count":
            values["asset_count"] += 1
        elif mismatch == "digest":
            values["aggregate_sha256"] = "0" * 64
        else:
            values["contract_version"] = 2

        with pytest.raises(HTTPException) as exc_info:
            acknowledge_local_original_binding(db, **values)

        assert exc_info.value.status_code == expected_status
        db.refresh(asset_set)
        assert "client_local_original" not in asset_set.original_summary
        assert "server_original_state" not in asset_set.original_summary
        assert (tmp_path / asset.storage_key).is_file()


def test_local_original_ack_replay_is_idempotent_and_does_not_duplicate_cleanup_refs(
    tmp_path,
):
    """相同 ACK 可安全重放，首次审计时间与精确删除对象集合保持不变。"""

    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ack-idempotent-replay")
        workflow.status = "failed"
        db.commit()
        asset_set = db.scalar(select(HealthReportAssetSet))

        _ack_local_original(db, workflow)
        db.refresh(asset_set)
        first_proof = dict(asset_set.original_summary["client_local_original"])
        first_cleanup = list(asset_set.original_summary["pending_object_cleanup"])
        _ack_local_original(db, workflow)
        db.refresh(asset_set)

        assert asset_set.original_summary["client_local_original"] == first_proof
        assert asset_set.original_summary["pending_object_cleanup"] == first_cleanup
        assert len(first_cleanup) == len(
            {
                (
                    row["key"],
                    row["sha256"],
                    row["content_type"],
                    row["owner_user_id"],
                    row["subject_user_id"],
                )
                for row in first_cleanup
            }
        )


def test_report_object_store_selection_is_independent_and_production_local_fails_closed(
    tmp_path,
):
    configured = Settings(
        _env_file=None,
        APP_ENV="test",
        DIETARY_IMAGE_STORAGE_BACKEND="s3",
        REPORT_OBJECT_STORAGE_BACKEND="local",
        LOCAL_STORAGE_DIR=str(tmp_path),
    )
    assert isinstance(configured_report_object_store(configured), LocalPrivateObjectStore)

    production = configured.model_copy(update={"APP_ENV": "production"})
    with pytest.raises(ObjectStorageConfigurationError):
        validate_report_object_storage_configuration(production)


def test_real_heic_original_is_preserved_while_quality_and_ocr_use_rendered_png(
    tmp_path,
):
    """即使 HEIC 被误标成 PNG 也按签名解码，原件不变且 vision 只收派生 PNG。"""

    class CapturingExtractor:
        provider_id = "fixture-heic-rendered-png"
        model_version = "fixture-vision-v1"

        def __init__(self):
            self.calls = []

        def extract_page(self, *, image_bytes: bytes, mime_type: str, page_index: int):
            self.calls.append((image_bytes, mime_type, page_index))
            assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
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

    original = _SYNTHETIC_HEIC_FIXTURE.read_bytes()
    assert hashlib.sha256(original).hexdigest() == _SYNTHETIC_HEIC_SHA256
    direct_assessment = assess_image_quality(original)
    assert direct_assessment.quality_status == "accepted"
    assert (direct_assessment.width_px, direct_assessment.height_px) == (720, 960)
    rendered = render_image_page(original)
    assert rendered.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert (rendered.width_px, rendered.height_px) == (720, 960)

    store = LocalPrivateObjectStore(str(tmp_path))
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="real-heic-report",
            media_kind="photo_library",
            expected_page_count=1,
        )
        asset = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="real-heic-report-asset",
            # 现场故障中客户端文件名/MIME 是 PNG，但实际字节是 HEIC。
            # 回归必须覆盖这一路径，不能仅验证正确声明的 HEIC。
            filename="synthetic-health-report.png",
            mime_type="image/png",
            file_bytes=original,
            object_store=store,
        )
        original_key = asset.storage_key
        original_path = tmp_path / original_key
        assert original_path.read_bytes() == original
        assert asset.byte_sha256 == _SYNTHETIC_HEIC_SHA256

        sealed = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="合成 HEIC 体检报告",
            hospital="测试医院",
            report_date=datetime.now(timezone.utc).date(),
            object_store=store,
        )

        assert sealed.get("failure_code") is None
        workflow = db.get(HealthReportWorkflow, sealed["workflow_id"])
        db.refresh(asset)
        db.refresh(asset_set)
        page = db.scalar(select(HealthReportPage))
        quality = db.scalar(select(HealthReportAssetQualityResult))
        assert asset.storage_key == original_key
        assert asset.byte_sha256 == _SYNTHETIC_HEIC_SHA256
        assert asset_set.aggregate_sha256 == _SYNTHETIC_HEIC_SHA256
        assert original_path.read_bytes() == original
        assert page.source_asset_id == asset.id
        assert page.rendered_storage_key != asset.storage_key
        assert page.rendered_storage_key.endswith(".png")
        rendered_bytes = (tmp_path / page.rendered_storage_key).read_bytes()
        assert rendered_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(rendered_bytes).hexdigest() == page.rendered_byte_sha256
        assert quality.quality_status == "accepted"
        assert quality.failure_code is None
        downloaded_original, downloaded_asset = read_original_asset_content(
            db,
            workflow_id=workflow.id,
            asset_id=asset.id,
            user_id=1,
            subject_user_id=1,
            object_store=store,
        )
        assert downloaded_original == original
        assert downloaded_asset.byte_sha256 == _SYNTHETIC_HEIC_SHA256

        claim = claim_report_ocr_workflow(db)
        assert claim
        assert claim[0] == workflow.id
        extractor = CapturingExtractor()
        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=extractor,
            object_store=store,
        ) == 1
        assert len(extractor.calls) == 1
        assert original_path.read_bytes() == original


def test_existing_mislabeled_heic_page_is_normalized_at_ocr_read_boundary(tmp_path):
    """修复前已封存的 HEIC 页不重走 seal，OCR 读取时也必须即时转为 PNG。"""

    original = _SYNTHETIC_HEIC_FIXTURE.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    metadata = StoredObjectMetadata(
        key="report-assets/1/1/legacy/mislabeled-png.object",
        sha256=digest,
        size_bytes=len(original),
        content_type="image/png",
        owner_user_id=1,
        subject_user_id=1,
    )
    store = LocalPrivateObjectStore(str(tmp_path))
    store.put(content=original, metadata=metadata)
    source_asset = SimpleNamespace(
        storage_key=metadata.key,
        byte_sha256=digest,
        byte_size=len(original),
        mime_type="image/png",
        user_id=1,
        subject_user_id=1,
    )
    page = SimpleNamespace(rendered_storage_key=metadata.key)

    provider_bytes, provider_mime = report_ocr_service._page_content(
        store,
        page,
        source_asset,
    )

    assert provider_mime == "image/png"
    assert provider_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert store.get(metadata=metadata, max_bytes=len(original)) == original


def test_jpeg_adjacent_path_remains_direct_and_provider_compatible(tmp_path):
    """JPEG 仍复用原始对象并以 image/jpeg 交给 provider，不受 HEIF 分支影响。"""

    class JPEGExtractor:
        provider_id = "fixture-jpeg-direct"
        model_version = "fixture-vision-v1"

        def extract_page(self, *, image_bytes: bytes, mime_type: str, page_index: int):
            assert image_bytes.startswith(b"\xff\xd8\xff")
            assert mime_type == "image/jpeg"
            assert page_index == 1
            return [
                {
                    "name": "CRP",
                    "value": "12.5",
                    "unit": "mg/L",
                    "bbox": [0.1, 0.2, 0.3, 0.1],
                }
            ]

    original = _sharp_report_jpeg()
    store = LocalPrivateObjectStore(str(tmp_path))
    factory = _factory()
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="jpeg-adjacent-path",
            media_kind="photo_library",
            expected_page_count=1,
        )
        asset = add_asset(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            asset_index=1,
            client_asset_id="jpeg-adjacent-path-asset",
            filename="report.jpg",
            mime_type="image/jpeg",
            file_bytes=original,
            object_store=store,
        )
        sealed = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="JPEG 相邻路径",
            hospital=None,
            report_date=None,
            object_store=store,
        )
        page = db.scalar(select(HealthReportPage))
        assert page.rendered_storage_key == asset.storage_key
        assert page.rendered_byte_sha256 == asset.byte_sha256

        claim = claim_report_ocr_workflow(db)
        assert claim and claim[0] == sealed["workflow_id"]
        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=JPEGExtractor(),
            object_store=store,
        ) == 1


def test_report_ocr_task_records_storage_builder_failure_after_claim(monkeypatch):
    factory = _factory()
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-store-builder-failure",
            document_fingerprint="7" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={},
        )
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id

    monkeypatch.setattr(report_ocr_tasks, "SessionLocal", factory)
    monkeypatch.setattr(report_ocr_tasks, "OpenAIReportPageExtractor", lambda: object())

    def unavailable_store(_settings):
        raise ObjectStorageConfigurationError("missing report storage")

    monkeypatch.setattr(
        report_ocr_tasks,
        "configured_report_object_store",
        unavailable_store,
    )
    outcome = report_ocr_tasks.process_health_report_ocr_workflows.run(max_workflows=1)

    assert outcome["infrastructure_deferred"] == 1
    with factory() as db:
        persisted = db.get(HealthReportWorkflow, workflow_id)
        assert persisted.status == "recognizing"
        assert persisted.workflow_metadata["ocr_state"] == "pending"
        assert persisted.workflow_metadata["ocr_infrastructure_attempt_count"] == 1


def test_report_ocr_task_queues_cleanup_when_claim_discovers_exhausted_attempts(
    monkeypatch,
    tmp_path,
):
    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-preclaim-exhausted")
        metadata = dict(workflow.workflow_metadata or {})
        metadata.update({"ocr_state": "pending", "ocr_attempt_count": 3})
        workflow.workflow_metadata = metadata
        db.commit()
        workflow_id = workflow.id
        asset_set_id = db.scalar(select(HealthReportAssetSet.id))

    monkeypatch.setattr(report_ocr_tasks, "SessionLocal", factory)
    monkeypatch.setattr(report_ocr_tasks, "OpenAIReportPageExtractor", lambda: object())
    outcome = report_ocr_tasks.process_health_report_ocr_workflows.run(max_workflows=1)

    assert outcome["processed"] == 0
    assert outcome["terminal_retirements_queued"] == 0
    with factory() as db:
        persisted = db.get(HealthReportWorkflow, workflow_id)
        asset_set = db.get(HealthReportAssetSet, asset_set_id)
        assert persisted.status == "failed"
        assert persisted.failure_code == "report_ocr_retry_exhausted"
        assert "server_original_state" not in asset_set.original_summary
        assert "pending_object_cleanup" not in asset_set.original_summary


def test_stale_recognizing_workflow_reconciles_to_reupload_action():
    factory = _factory()
    now = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-stale-runtime",
            document_fingerprint="6" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={
                "ocr_state": "running",
                "ocr_claimed_at": (now - timedelta(hours=2)).isoformat(),
                "ocr_lease_expires_at": (now - timedelta(hours=1)).isoformat(),
                "ocr_claim_token": "expired",
            },
        )
        db.add(workflow)
        db.commit()

        changed = report_ocr_service.reconcile_stale_report_ocr_workflow(
            db,
            workflow_id=workflow.id,
            now=now,
        )

        assert changed is True
        persisted = db.get(HealthReportWorkflow, workflow.id)
        assert persisted.status == "failed"
        assert persisted.failure_code == "report_ocr_stalled"
        assert "ocr_claim_token" not in persisted.workflow_metadata
        runtime = build_report_runtime(
            db,
            workflow_id=workflow.id,
            user_id=1,
            subject_user_id=1,
        )
        assert runtime["primary_action"] == {
            "code": "reupload_report",
            "enabled": True,
            "pending_count": 0,
        }


def test_unclaimed_report_ocr_persistent_deadline_reconciles_without_worker(
    tmp_path,
):
    """worker/beat 全部缺席时，读取边界也必须按持久 deadline 结束识别中。"""

    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(
            db,
            tmp_path,
            "ocr-unclaimed-persistent-deadline",
        )
        metadata = dict(workflow.workflow_metadata or {})
        assert metadata["ocr_state"] == "pending"
        pending_since = datetime.fromisoformat(metadata["ocr_pending_since"])
        pending_deadline = datetime.fromisoformat(metadata["ocr_pending_deadline_at"])
        assert pending_deadline > pending_since

        metadata["ocr_pending_deadline_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        workflow.workflow_metadata = metadata
        db.commit()

        runtime = build_report_runtime(
            db,
            workflow_id=workflow.id,
            user_id=1,
            subject_user_id=1,
        )

        db.refresh(workflow)
        assert workflow.status == "failed"
        assert workflow.failure_code == "report_ocr_stalled"
        assert workflow.workflow_metadata["ocr_state"] == "failed"
        assert workflow.workflow_metadata["ocr_pending_timeout_reconciled_at"]
        assert runtime["primary_action"] == {
            "code": "reupload_report",
            "enabled": True,
            "pending_count": 0,
        }


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


def test_report_ocr_terminal_retires_server_bytes_but_keeps_trace_metadata(tmp_path):
    class FixtureExtractor:
        provider_id = "fixture-terminal-retirement"
        model_version = "fixture-vision-v1"

        def extract_page(self, **_kwargs):
            return [
                {
                    "name": "CRP",
                    "value": "12.5",
                    "unit": "mg/L",
                    "bbox": [0.1, 0.2, 0.3, 0.1],
                }
            ]

    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-retire-original")
        _ack_local_original(db, workflow)
        asset = db.scalar(select(HealthReportAsset))
        original_path = tmp_path / asset.storage_key
        assert original_path.is_file()
        claim = claim_report_ocr_workflow(db)
        assert claim

        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=FixtureExtractor(),
            object_store=store,
        ) == 1

        assert not original_path.exists()
        assert db.get(HealthReportAsset, asset.id) is not None
        assert db.scalar(select(HealthReportFieldCandidate)) is not None
        assert db.scalar(select(HealthReportFieldLocator)) is not None
        asset_set = db.scalar(select(HealthReportAssetSet))
        assert asset_set.original_summary["server_original_state"] == "purged"
        with pytest.raises(HTTPException) as exc_info:
            read_original_asset_content(
                db,
                workflow_id=workflow.id,
                asset_id=asset.id,
                user_id=1,
                subject_user_id=1,
                object_store=store,
            )
        assert getattr(exc_info.value, "status_code", None) == 410


def test_report_ocr_cleanup_failure_stays_pending_until_sweep_replays(tmp_path):
    class FixtureExtractor:
        provider_id = "fixture-cleanup-replay"
        model_version = "fixture-vision-v1"

        def extract_page(self, **_kwargs):
            return [
                {
                    "name": "CRP",
                    "value": "12.5",
                    "bbox": [0.1, 0.2, 0.3, 0.1],
                }
            ]

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
    durable_store = LocalPrivateObjectStore(str(tmp_path))
    flaky_store = FailFirstDeleteStore(durable_store)
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-cleanup-replay")
        _ack_local_original(db, workflow)
        asset = db.scalar(select(HealthReportAsset))
        original_path = tmp_path / asset.storage_key
        claim = claim_report_ocr_workflow(db)
        assert claim

        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=FixtureExtractor(),
            object_store=flaky_store,
        ) == 1

        asset_set = db.scalar(select(HealthReportAssetSet))
        db.refresh(asset_set)
        assert asset_set.original_summary["server_original_state"] == "purge_pending"
        assert asset_set.original_summary["pending_object_cleanup"]
        assert original_path.is_file()

        outcome = cleanup_pending_attached_report_objects(
            db,
            object_store=durable_store,
            batch_size=10,
        )

        assert outcome == {
            "selected": 1,
            "purged": 1,
            "cleanup_pending": 0,
            "protected": 0,
        }
        db.refresh(asset_set)
        assert asset_set.original_summary["server_original_state"] == "purged"
        assert "pending_object_cleanup" not in asset_set.original_summary
        assert not original_path.exists()


def test_legacy_terminal_report_without_local_ack_keeps_original_readable(tmp_path):
    """旧版/未 ACK 客户端的终态报告不得被补扫或 OCR 终态路径删除。"""

    class FixtureExtractor:
        provider_id = "fixture-legacy-retention"
        model_version = "fixture-vision-v1"

        def extract_page(self, **_kwargs):
            return [{"name": "CRP", "value": "12.5", "bbox": [0.1, 0.2, 0.3, 0.1]}]

    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-legacy-retained")
        asset = db.scalar(select(HealthReportAsset))
        original_path = tmp_path / asset.storage_key
        claim = claim_report_ocr_workflow(db)
        assert claim

        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=FixtureExtractor(),
            object_store=store,
        ) == 1

        asset_set = db.scalar(select(HealthReportAssetSet))
        assert original_path.is_file()
        assert "server_original_state" not in asset_set.original_summary
        content, persisted_asset = read_original_asset_content(
            db,
            workflow_id=workflow.id,
            asset_id=asset.id,
            user_id=1,
            subject_user_id=1,
            object_store=store,
        )
        assert content == _sharp_report_png()
        assert persisted_asset.id == asset.id


def test_cleanup_sweep_cancels_unacknowledged_legacy_purge_pending(tmp_path):
    """升级前误入 purge_pending 的历史行也必须恢复保留，不能被 sweep 删除。"""

    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-protect-old-pending")
        workflow.status = "failed"
        asset = db.scalar(select(HealthReportAsset))
        asset_set = db.scalar(select(HealthReportAssetSet))
        original_path = tmp_path / asset.storage_key
        asset_set.original_summary = {
            "server_original_state": "purge_pending",
            "pending_object_cleanup": [
                {
                    "key": asset.storage_key,
                    "sha256": asset.byte_sha256,
                    "content_type": asset.mime_type,
                    "owner_user_id": asset.user_id,
                    "subject_user_id": asset.subject_user_id,
                    "max_bytes": 25 * 1024 * 1024,
                }
            ],
        }
        db.commit()

        outcome = cleanup_pending_attached_report_objects(
            db,
            object_store=store,
            batch_size=10,
        )

        assert outcome == {
            "selected": 1,
            "purged": 0,
            "cleanup_pending": 0,
            "protected": 1,
        }
        db.refresh(asset_set)
        assert asset_set.original_summary["server_original_state"] == "retained"
        assert "pending_object_cleanup" not in asset_set.original_summary
        assert original_path.is_file()
        content, _ = read_original_asset_content(
            db,
            workflow_id=workflow.id,
            asset_id=asset.id,
            user_id=1,
            subject_user_id=1,
            object_store=store,
        )
        assert content


@pytest.mark.parametrize("has_local_ack", [False, True], ids=["unacknowledged", "acknowledged"])
@pytest.mark.parametrize("replay_entry", ["add", "replace", "seal"])
def test_generic_upload_replays_never_bypass_local_original_retirement_guard(
    tmp_path,
    replay_entry,
    has_local_ack,
):
    """add/replace/seal 重放都不能替代显式清理器删除已绑定报告原件。"""

    storage_root = tmp_path / f"{replay_entry}-{has_local_ack}"
    storage_root.mkdir()
    store = LocalPrivateObjectStore(str(storage_root))
    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(
            db,
            storage_root,
            f"ocr-replay-retirement-{replay_entry}-{has_local_ack}",
        )
        asset = db.scalar(select(HealthReportAsset))
        asset_set = db.scalar(select(HealthReportAssetSet))
        original_path = storage_root / asset.storage_key
        assert original_path.is_file()

        if has_local_ack:
            workflow.status = "failed"
            db.commit()
            _ack_local_original(db, workflow)
        else:
            asset_set.original_summary = {
                "server_original_state": "purge_pending",
                "pending_object_cleanup": [
                    {
                        "key": asset.storage_key,
                        "sha256": asset.byte_sha256,
                        "content_type": asset.mime_type,
                        "owner_user_id": asset.user_id,
                        "subject_user_id": asset.subject_user_id,
                        "max_bytes": 25 * 1024 * 1024,
                    }
                ],
            }
            db.commit()

        if replay_entry == "add":
            with pytest.raises(HTTPException) as exc_info:
                add_asset(
                    db,
                    asset_set_id=asset_set.id,
                    user_id=1,
                    subject_user_id=1,
                    asset_index=2,
                    client_asset_id=f"{asset_set.client_request_id}-replay-add",
                    filename="replay-add.png",
                    mime_type="image/png",
                    file_bytes=_sharp_report_png(),
                    object_store=store,
                )
            assert exc_info.value.status_code == 409
        elif replay_entry == "replace":
            with pytest.raises(HTTPException) as exc_info:
                replace_or_add_recovery_asset(
                    db,
                    asset_set_id=asset_set.id,
                    user_id=1,
                    subject_user_id=1,
                    asset_index=1,
                    client_asset_id=f"{asset_set.client_request_id}-replay-replace",
                    filename="replay-replace.png",
                    mime_type="image/png",
                    file_bytes=_sharp_report_png(),
                    object_store=store,
                )
            assert exc_info.value.status_code == 409
        else:
            result = seal_asset_set(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                report_type="lab",
                title="重放不得删除原件",
                hospital="测试医院",
                report_date=datetime.now(timezone.utc).date(),
                object_store=store,
            )
            assert result["workflow_id"] == workflow.id

        db.refresh(asset_set)
        assert original_path.is_file()
        if has_local_ack:
            assert asset_set.original_summary["server_original_state"] == "purge_pending"
            assert asset_set.original_summary["pending_object_cleanup"]
            outcome = cleanup_pending_attached_report_objects(
                db,
                object_store=store,
                batch_size=10,
            )
            assert outcome["purged"] == 1
            assert not original_path.exists()
        else:
            assert asset_set.original_summary["server_original_state"] == "retained"
            assert "pending_object_cleanup" not in asset_set.original_summary
            content, _ = read_original_asset_content(
                db,
                workflow_id=workflow.id,
                asset_id=asset.id,
                user_id=1,
                subject_user_id=1,
                object_store=store,
            )
            assert content == _sharp_report_png()


def test_terminal_retirement_json_query_compiles_for_sqlite_and_postgresql():
    """ACK/状态 JSON 条件必须同时可由 SQLite 回归库和 PostgreSQL 生产库编译。"""

    class CapturingSession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return ()

    capture = CapturingSession()
    assert queue_terminal_report_object_retirements(capture, batch_size=7) == 0
    assert capture.statement is not None

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        compiled = str(
            capture.statement.compile(
                dialect=dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        assert "client_local_original" in compiled
        assert "contract_version" in compiled
        assert "client_request_id" in compiled
        assert "asset_count" in compiled
        assert "aggregate_sha256" in compiled
        assert "server_original_state" in compiled
        if dialect.name == "sqlite":
            assert "JSON_EXTRACT" in compiled
        else:
            assert "->>" in compiled


def test_terminal_retirement_scan_skips_fifty_invalid_proofs_without_starving_valid_ack():
    """坏 proof 即使排在前 50 行，也不能占满 batch 饿死后续有效 ACK。"""

    factory = _factory()
    with factory() as db:
        valid_asset_set_id = None
        for offset in range(51):
            request_id = f"terminal-proof-{offset:02d}"
            digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
            proof_digest = digest if offset == 50 else "0" * 64
            asset_set = HealthReportAssetSet(
                user_id=1,
                subject_user_id=1,
                client_request_id=request_id,
                media_kind="photo_library",
                status="attached",
                expected_page_count=1,
                received_asset_count=1,
                completeness_basis="user_declared",
                aggregate_sha256=digest,
                original_summary={
                    "client_local_original": {
                        "contract_version": 1,
                        "client_request_id": request_id,
                        "asset_count": 1,
                        "aggregate_sha256": proof_digest,
                        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            workflow = HealthReportWorkflow(
                user_id=1,
                subject_user_id=1,
                legacy_document_id=None,
                client_request_id=request_id,
                document_fingerprint=digest,
                report_type="lab",
                status="failed",
                version=1,
                workflow_metadata={},
            )
            db.add_all([asset_set, workflow])
            db.flush()
            db.add(
                HealthReportAssetSetWorkflowLink(
                    asset_set_id=asset_set.id,
                    workflow_id=workflow.id,
                    user_id=1,
                    subject_user_id=1,
                )
            )
            if offset == 50:
                valid_asset_set_id = asset_set.id
        db.commit()

        assert queue_terminal_report_object_retirements(db, batch_size=50) == 1

        valid_asset_set = db.get(HealthReportAssetSet, valid_asset_set_id)
        assert valid_asset_set.original_summary["server_original_state"] == "purge_pending"
        invalid_states = list(
            db.scalars(
                select(HealthReportAssetSet.original_summary).where(
                    HealthReportAssetSet.id != valid_asset_set_id
                )
            )
        )
        assert all("server_original_state" not in summary for summary in invalid_states)


def test_explicit_server_original_retirement_requires_attached_asset_set(tmp_path):
    """即使 ACK 正确且显式 allow，异常的非 attached 状态也必须失败关闭。"""

    store = LocalPrivateObjectStore(str(tmp_path))
    factory = _factory()
    with factory() as db:
        workflow = _create_sealed_workflow(db, tmp_path, "ocr-retirement-status-guard")
        workflow.status = "failed"
        db.commit()
        _ack_local_original(db, workflow)
        asset = db.scalar(select(HealthReportAsset))
        asset_set = db.scalar(select(HealthReportAssetSet))
        original_path = tmp_path / asset.storage_key
        asset_set.status = "sealed"
        db.commit()

        assert not retire_attached_report_objects(
            db,
            workflow_id=workflow.id,
            object_store=store,
        )

        db.refresh(asset_set)
        assert asset_set.original_summary["server_original_state"] == "purge_pending"
        assert asset_set.original_summary["pending_object_cleanup"]
        assert original_path.is_file()


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


def test_openai_report_page_request_timeout_is_shorter_than_claim_lease(monkeypatch):
    from types import SimpleNamespace

    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"items":[]}'))]
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(report_ocr_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(report_ocr_service.settings, "OPENAI_MODEL_VISION", "kimi-k2.5")
    monkeypatch.setattr(
        report_ocr_service,
        "OpenAI",
        lambda **_kwargs: fake_client,
    )

    extractor = report_ocr_service.OpenAIReportPageExtractor()
    assert extractor.extract_page(
        image_bytes=b"image",
        mime_type="image/png",
        page_index=1,
    ) == []

    assert 0 < captured["timeout"] < report_ocr_service.OCR_LEASE_SECONDS
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_report_vision_model_fails_closed_before_text_only_provider_call(monkeypatch):
    """普通 moonshot-v1 文本模型不得进入图片 OCR 请求或消耗重试次数。"""

    client_created = False

    def unexpected_client(**_kwargs):
        nonlocal client_created
        client_created = True
        raise AssertionError("text-only model must be rejected before client creation")

    monkeypatch.setattr(report_ocr_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        report_ocr_service.settings,
        "OPENAI_MODEL_VISION",
        "moonshot-v1-8k",
    )
    monkeypatch.setattr(report_ocr_service, "OpenAI", unexpected_client)

    with pytest.raises(RuntimeError, match="explicitly image-capable"):
        report_ocr_service.OpenAIReportPageExtractor()

    assert client_created is False


def test_report_vision_configuration_keeps_reviewed_openai_image_endpoint():
    """公开支持的 OpenAI endpoint 仍可使用经过审核的图像输入模型。"""

    configured = Settings(
        _env_file=None,
        APP_ENV="production",
        OPENAI_API_KEY="test-key",
        OPENAI_BASE_URL="https://api.openai.com/v1",
        OPENAI_MODEL_VISION="gpt-4o",
    )
    configured.validate_report_vision_configuration(require_credentials=True)
    assert configured.report_vision_provider_family() == "openai"
    defaults = Settings(_env_file=None)
    defaults.validate_report_vision_configuration()
    assert defaults.report_vision_provider_family() == "moonshot"


def test_openai_report_page_request_omits_kimi_only_options(monkeypatch):
    """OpenAI 视觉请求不得携带 Moonshot 专属 thinking 扩展字段。"""

    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"items":[]}'))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(report_ocr_service.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        report_ocr_service.settings,
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    )
    monkeypatch.setattr(report_ocr_service.settings, "OPENAI_MODEL_VISION", "gpt-4o")
    monkeypatch.setattr(report_ocr_service, "OpenAI", lambda **_kwargs: fake_client)

    extractor = report_ocr_service.OpenAIReportPageExtractor()
    assert extractor.extract_page(
        image_bytes=b"image",
        mime_type="image/png",
        page_index=1,
    ) == []
    assert "extra_body" not in captured


def test_fastapi_startup_rejects_text_only_report_vision_model(monkeypatch, tmp_path):
    """API 必须在接受上传前拒绝无法读取图片的模型，而不是留下永久 pending。"""

    from app import main as app_main

    monkeypatch.setattr(app_main.settings, "APP_ENV", "test")
    monkeypatch.setattr(app_main.settings, "DIETARY_IMAGE_STORAGE_BACKEND", "local")
    monkeypatch.setattr(app_main.settings, "REPORT_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setattr(app_main.settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(app_main.settings, "OPENAI_MODEL_VISION", "moonshot-v1-8k")

    startup = app_main.create_app().router.on_startup[0]
    with pytest.raises(RuntimeError, match="explicitly image-capable"):
        startup()


def test_report_ocr_task_rejects_invalid_vision_provider_before_claim(
    monkeypatch,
):
    """保留历史 ID：Provider 构造失败必须持久化、有界且不消耗内容重试。"""

    factory = _factory()
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-invalid-provider-preclaim",
            document_fingerprint="9" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={},
        )
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id

    monkeypatch.setattr(report_ocr_tasks, "SessionLocal", factory)
    def provider_initialization_fails():
        raise RuntimeError("synthetic invalid report vision provider")

    monkeypatch.setattr(
        report_ocr_tasks,
        "OpenAIReportPageExtractor",
        provider_initialization_fails,
    )

    for attempt in range(1, report_ocr_service.OCR_MAX_INFRASTRUCTURE_ATTEMPTS + 1):
        outcome = report_ocr_tasks.process_health_report_ocr_workflows.run(
            max_workflows=1
        )
        assert outcome["processed"] == 0
        assert outcome["infrastructure_deferred"] == 1

        with factory() as db:
            persisted = db.get(HealthReportWorkflow, workflow_id)
            metadata = dict(persisted.workflow_metadata or {})
            assert metadata["ocr_attempt_count"] == 0
            assert metadata["ocr_infrastructure_attempt_count"] == attempt
            assert "ocr_claim_token" not in metadata
            assert "ocr_lease_expires_at" not in metadata
            if attempt < report_ocr_service.OCR_MAX_INFRASTRUCTURE_ATTEMPTS:
                assert persisted.status == "recognizing"
                assert persisted.failure_code is None
                assert metadata["ocr_state"] == "pending"
                metadata["ocr_next_infrastructure_attempt_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
                persisted.workflow_metadata = metadata
                db.commit()
            else:
                assert persisted.status == "failed"
                assert persisted.failure_code == "report_ocr_provider_unavailable"
                assert persisted.version == 2
                assert metadata["ocr_state"] == "failed"
                runtime = build_report_runtime(
                    db,
                    workflow_id=workflow_id,
                    user_id=1,
                    subject_user_id=1,
                )
                assert runtime["primary_action"] == {
                    "code": "reupload_report",
                    "enabled": True,
                    "pending_count": 0,
                }


def test_report_ocr_heartbeat_renews_only_owned_claim_and_blocks_stale_reconciler():
    factory = _factory()
    claimed_at = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    heartbeat_at = claimed_at + timedelta(hours=2)
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-heartbeat-owned-claim",
            document_fingerprint="5" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={},
        )
        db.add(workflow)
        db.commit()
        claim = claim_report_ocr_workflow(db, now=claimed_at, lease_seconds=60)
        assert claim

        assert report_ocr_service.heartbeat_report_ocr_claim(
            db,
            workflow_id=workflow.id,
            claim_token=claim[1],
            now=heartbeat_at,
            lease_seconds=120,
        ) is True
        db.refresh(workflow)
        metadata = dict(workflow.workflow_metadata or {})
        assert metadata["ocr_heartbeat_at"] == heartbeat_at.isoformat()
        assert metadata["ocr_lease_expires_at"] == (
            heartbeat_at + timedelta(seconds=120)
        ).isoformat()

        # claimed_at 与其他旧失败时间不再决定 stale；新 heartbeat/lease 胜出。
        assert report_ocr_service.reconcile_stale_report_ocr_workflow(
            db,
            workflow_id=workflow.id,
            now=heartbeat_at + timedelta(seconds=30),
            stale_seconds=1,
        ) is False
        with pytest.raises(RuntimeError, match="stale"):
            report_ocr_service.heartbeat_report_ocr_claim(
                db,
                workflow_id=workflow.id,
                claim_token="wrong-token",
                now=heartbeat_at + timedelta(seconds=31),
                lease_seconds=120,
            )


def test_report_ocr_execution_heartbeats_after_every_page(monkeypatch, tmp_path):
    class FixtureExtractor:
        provider_id = "fixture-heartbeat-pages"
        model_version = "fixture-vision-v1"

        def extract_page(self, **_kwargs):
            return [
                {
                    "name": "CRP",
                    "value": "12.5",
                    "bbox": [0.1, 0.2, 0.3, 0.1],
                }
            ]

    factory = _factory()
    store = LocalPrivateObjectStore(str(tmp_path))
    with factory() as db:
        asset_set = create_asset_set(
            db,
            user_id=1,
            subject_user_id=1,
            client_request_id="ocr-two-page-heartbeat",
            media_kind="photo_library",
            expected_page_count=2,
        )
        for asset_index in (1, 2):
            add_asset(
                db,
                asset_set_id=asset_set.id,
                user_id=1,
                subject_user_id=1,
                asset_index=asset_index,
                client_asset_id=f"heartbeat-page-{asset_index}",
                filename=f"page-{asset_index}.png",
                mime_type="image/png",
                file_bytes=_sharp_report_png(),
                object_store=store,
            )
        result = seal_asset_set(
            db,
            asset_set_id=asset_set.id,
            user_id=1,
            subject_user_id=1,
            report_type="lab",
            title="两页报告",
            hospital="测试医院",
            report_date=datetime.now(timezone.utc).date(),
            object_store=store,
        )
        claim = claim_report_ocr_workflow(db)
        assert claim and claim[0] == result["workflow_id"]
        heartbeat_calls: list[tuple[int, str]] = []
        real_heartbeat = report_ocr_service.heartbeat_report_ocr_claim

        def recording_heartbeat(session, *, workflow_id, claim_token, **kwargs):
            heartbeat_calls.append((workflow_id, claim_token))
            return real_heartbeat(
                session,
                workflow_id=workflow_id,
                claim_token=claim_token,
                **kwargs,
            )

        monkeypatch.setattr(
            report_ocr_service,
            "heartbeat_report_ocr_claim",
            recording_heartbeat,
        )
        assert execute_report_ocr_workflow(
            db,
            workflow_id=claim[0],
            claim_token=claim[1],
            extractor=FixtureExtractor(),
            object_store=store,
        ) == 2
        assert heartbeat_calls == [claim, claim]
        persisted = db.get(HealthReportWorkflow, claim[0])
        assert persisted.workflow_metadata["ocr_heartbeat_count"] == 2


def test_report_ocr_reconciler_winner_invalidates_concurrent_worker_heartbeat():
    factory = _factory()
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    claim_token = "worker-that-lost-race"
    with factory() as db:
        workflow = HealthReportWorkflow(
            user_id=1,
            subject_user_id=1,
            legacy_document_id=None,
            client_request_id="ocr-reconciler-wins",
            document_fingerprint="4" * 64,
            report_type="lab",
            status="recognizing",
            version=1,
            workflow_metadata={
                "ocr_state": "running",
                "ocr_claim_token": claim_token,
                "ocr_heartbeat_at": (now - timedelta(hours=2)).isoformat(),
                "ocr_lease_expires_at": (now - timedelta(hours=1)).isoformat(),
            },
        )
        db.add(workflow)
        db.commit()

        assert report_ocr_service.reconcile_stale_report_ocr_workflow(
            db,
            workflow_id=workflow.id,
            now=now,
        ) is True
        with pytest.raises(RuntimeError, match="stale"):
            report_ocr_service.heartbeat_report_ocr_claim(
                db,
                workflow_id=workflow.id,
                claim_token=claim_token,
                now=now + timedelta(seconds=1),
            )

        db.refresh(workflow)
        assert workflow.status == "failed"
        assert workflow.failure_code == "report_ocr_stalled"


def test_report_ocr_claim_paginates_past_fifty_temporarily_ineligible_rows():
    factory = _factory()
    now = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    with factory() as db:
        rows: list[HealthReportWorkflow] = []
        for index in range(51):
            if index < 25:
                metadata = {
                    "ocr_state": "pending",
                    "ocr_next_infrastructure_attempt_at": (
                        now + timedelta(hours=1)
                    ).isoformat(),
                }
            elif index < 50:
                metadata = {
                    "ocr_state": "running",
                    "ocr_claim_token": f"active-{index}",
                    "ocr_heartbeat_at": now.isoformat(),
                    "ocr_lease_expires_at": (now + timedelta(hours=1)).isoformat(),
                }
            else:
                metadata = {"ocr_state": "pending"}
            rows.append(
                HealthReportWorkflow(
                    user_id=1,
                    subject_user_id=1,
                    legacy_document_id=None,
                    client_request_id=f"ocr-page-claim-{index:02d}",
                    document_fingerprint=f"{index + 100:064x}",
                    report_type="lab",
                    status="recognizing",
                    version=1,
                    workflow_metadata=metadata,
                )
            )
        db.add_all(rows)
        db.commit()

        claim = claim_report_ocr_workflow(db, now=now)

        assert claim is not None
        assert claim[0] == rows[50].id
