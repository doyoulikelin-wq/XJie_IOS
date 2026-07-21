"""Regression coverage for the trusted report admission boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.db import session as db_session_module
from app.models.health_document import HealthDocument, HealthSummary
from app.models.health_trust import (
    ConfirmedHealthObservation,
    HealthProfileSource,
    HealthReportConfirmationEvent,
    HealthReportFieldCandidate,
    HealthReportWorkflow,
    HealthScoreSnapshot,
)
from app.models.user import User
from app.routers import health_data, health_report_trust
from app.schemas.health_report_trust import HealthReportManualCandidateIn
from app.services import health_report_trust_service
from app.services.context_builder import _get_health_report_text, _get_health_summary_text
from app.services.health_summary_service import run_full_pipeline
from app.services.patient_history_service import build_evidence_overview, build_key_metrics


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[TestClient, sessionmaker, dict[str, str]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add_all(
            [
                User(id=1, phone="18800000101", username="report-owner", password="x"),
                User(id=2, phone="18800000102", username="other-subject", password="x"),
            ]
        )
        db.commit()

    monkeypatch.setattr(health_data.settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(health_data, "_generate_doc_summary", lambda *_args, **_kwargs: ("", ""))

    app = FastAPI()
    app.include_router(health_data.router, prefix="/api/health-data")
    app.include_router(health_report_trust.router, prefix="/api/health-data")

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    token = create_access_token("1")
    return (
        TestClient(app, raise_server_exceptions=False),
        factory,
        {"Authorization": f"Bearer {token}"},
    )


def _upload(client: TestClient, headers: dict[str, str], csv_text: str, *, filename: str = "report.csv"):
    return client.post(
        "/api/health-data/upload",
        headers=headers,
        files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
        data={"doc_type": "exam", "name": "2026-07-15-体检报告"},
    )


def _confirm_payload(review: dict, event_id: str, *, corrections: dict[str, float] | None = None) -> dict:
    corrections = corrections or {}
    decisions = []
    for candidate in review["candidates"]:
        if candidate["review_status"] != "pending_review":
            continue
        if candidate["canonical_name"] in corrections:
            decisions.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                    "action": "correct",
                    "value_numeric": corrections[candidate["canonical_name"]],
                    "unit": candidate["normalized_unit"],
                }
            )
        else:
            decisions.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                    "action": "confirm",
                }
            )
    return {
        "subject_user_id": 1,
        "client_event_id": event_id,
        "workflow_version": review["version"],
        "decisions": decisions,
    }


def test_report_upload_review_and_confirm_requires_subject_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    uploaded = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "空腹血糖,5.6,mmol/L,3.9-6.1,,0.99\n"
        "尿酸,450,umol/L,208-428,异常,0.99\n"
        "谷丙转氨酶,26,U/L,9-50,,\n",
    )
    assert uploaded.status_code == 200, uploaded.text
    upload_body = uploaded.json()
    assert upload_body["extraction_status"] == "done"
    assert upload_body["report_workflow_status"] == "awaiting_confirmation"
    assert upload_body["report_duplicate"] is False
    workflow_id = upload_body["report_workflow_id"]

    forbidden = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 2},
    )
    assert forbidden.status_code == 403

    review_response = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 1},
    )
    assert review_response.status_code == 200
    review = review_response.json()
    by_name = {item["canonical_name"]: item for item in review["candidates"]}
    assert by_name["空腹血糖"]["review_status"] == "auto_accepted"
    assert by_name["空腹血糖"]["low_confidence"] is False
    assert by_name["尿酸"]["review_status"] == "pending_review"
    for field in ("normalized_value", "reference_low", "reference_high", "confidence"):
        assert isinstance(by_name["尿酸"][field], (int, float))
        assert not isinstance(by_name["尿酸"][field], bool)
    assert by_name["谷丙转氨酶"]["low_confidence"] is True
    assert review["requires_report_confirmation"] is True

    unavailable_interpretation = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/interpretation",
        headers=headers,
        params={"subject_user_id": 1},
    )
    assert unavailable_interpretation.status_code == 200
    assert unavailable_interpretation.json()["available"] is False
    assert unavailable_interpretation.json()["candidates"] == []
    assert "确认" in unavailable_interpretation.json()["unavailable_reason"]
    forbidden_interpretation = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/interpretation",
        headers=headers,
        params={"subject_user_id": 2},
    )
    assert forbidden_interpretation.status_code == 403

    payload = _confirm_payload(review, "confirm-report-101", corrections={"尿酸": 430})
    confirmed = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json=payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed_score_pending"
    assert confirmed.json()["admitted_observation_count"] == 3
    assert confirmed.json()["requires_report_confirmation"] is False

    pending_interpretation = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/interpretation",
        headers=headers,
        params={"subject_user_id": 1},
    )
    assert pending_interpretation.status_code == 200, pending_interpretation.text
    interpretation = pending_interpretation.json()
    assert interpretation["available"] is True
    assert interpretation["score_state"] == "pending"
    assert interpretation["score_pending"] is True
    assert interpretation["score_snapshots"] == []
    assert "不构成诊断" in interpretation["non_diagnostic_notice"]
    assert interpretation["follow_up"]["available"] is False
    assert interpretation["follow_up"]["items"] == []
    assert "不会" in interpretation["follow_up"]["unavailable_reason"]
    assert interpretation["document"]["file_url"].endswith(
        f"/documents/{confirmed.json()['legacy_document_id']}/file"
    )
    interpreted_candidates = {
        item["canonical_name"]: item for item in interpretation["candidates"]
    }
    assert interpreted_candidates["尿酸"]["raw_value"] == "450"
    assert interpreted_candidates["尿酸"]["normalized_value"] == 430
    abnormal_names = {
        item["canonical_name"] for item in interpretation["major_abnormalities"]
    }
    assert abnormal_names == {"尿酸"}
    assert len(interpretation["structured_additions"]) == 3
    uric_event = next(
        item
        for item in interpretation["confirmation_events"]
        if item["candidate_id"] == interpreted_candidates["尿酸"]["candidate_id"]
    )
    assert uric_event["event_type"] == "correct"
    assert float(uric_event["before_data"]["value_numeric"]) == 450
    assert float(uric_event["after_data"]["value_numeric"]) == 430

    with factory() as db:
        db.add_all(
            [
                HealthScoreSnapshot(
                    user_id=1,
                    subject_user_id=1,
                    source_report_workflow_id=workflow_id,
                    idempotency_key="score-stress-report-101",
                    score_kind="stress",
                    algorithm_id="trusted-score",
                    algorithm_version="2026.07",
                    before_value=58,
                    after_value=54,
                    before_confidence=0.8,
                    after_confidence=0.85,
                    score_direction="lower_is_better",
                    semantic_outcome="improved",
                    calculation_status="completed",
                    evidence={"observation_ids": [item["observation_id"] for item in interpretation["structured_additions"]]},
                    missing_inputs={},
                    computed_at=datetime.now(timezone.utc),
                ),
                HealthScoreSnapshot(
                    user_id=1,
                    subject_user_id=1,
                    source_report_workflow_id=workflow_id,
                    idempotency_key="score-inflammation-report-101",
                    score_kind="inflammation",
                    algorithm_id="trusted-score",
                    algorithm_version="2026.07",
                    calculation_status="failed",
                    evidence={},
                    missing_inputs={"required": ["hs_crp"]},
                    failure_code="insufficient_evidence",
                    computed_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.commit()

    scored_interpretation = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/interpretation",
        headers=headers,
        params={"subject_user_id": 1},
    ).json()
    assert scored_interpretation["score_state"] == "partial_failed"
    assert scored_interpretation["score_pending"] is True
    scores = {item["score_kind"]: item for item in scored_interpretation["score_snapshots"]}
    assert scores["stress"]["before_value"] == 58
    assert scores["stress"]["after_value"] == 54
    assert scores["stress"]["semantic_outcome"] == "improved"
    assert scores["inflammation"]["after_value"] is None
    assert scores["inflammation"]["failure_code"] == "insufficient_evidence"
    assert scores["inflammation"]["missing_inputs"] == {"required": ["hs_crp"]}

    retry = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json=payload,
    )
    conflict = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json={**payload, "client_event_id": "different-event"},
    )
    assert retry.status_code == 200
    assert retry.json()["admitted_observation_count"] == 3
    assert conflict.status_code == 409

    trend = client.get(
        "/api/health-data/indicators/trend",
        headers=headers,
        params={"names": "尿酸"},
    )
    assert trend.status_code == 200
    assert trend.json()["indicators"][0]["points"][0]["value"] == 430
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ConfirmedHealthObservation)) == 3
        assert db.scalar(select(func.count()).select_from(HealthReportConfirmationEvent)) == 3
        workflow = db.get(HealthReportWorkflow, workflow_id)
        assert workflow.confirmed_by_user_id == 1
        assert workflow.confirmed_at is not None


def test_report_confirmation_failure_is_atomic_and_committing_retry_recovers(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    uploaded = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "总胆固醇,4.2,mmol/L,2.8-5.2,,\n"
        "甘油三酯,1.3,mmol/L,0.3-1.7,,\n",
    ).json()
    workflow_id = uploaded["report_workflow_id"]
    review = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 1},
    ).json()
    payload = _confirm_payload(review, "recoverable-confirmation")

    original = health_report_trust_service._admit_candidate
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected admission failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(health_report_trust_service, "_admit_candidate", fail_second)
    failed = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json=payload,
    )
    assert failed.status_code == 500
    with factory() as db:
        workflow = db.get(HealthReportWorkflow, workflow_id)
        assert workflow.status == "committing"
        assert workflow.confirmation_client_event_id == "recoverable-confirmation"
        assert db.scalar(select(func.count()).select_from(HealthReportConfirmationEvent)) == 0
        assert db.scalar(select(func.count()).select_from(ConfirmedHealthObservation)) == 0

    monkeypatch.setattr(health_report_trust_service, "_admit_candidate", original)
    recovered = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json=payload,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["status"] == "completed_score_pending"
    assert recovered.json()["admitted_observation_count"] == 2


def test_unconfirmed_legacy_done_is_excluded_from_trend_summary_profile_and_ai(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    with factory() as db:
        db.add(
            HealthDocument(
                user_id=1,
                doc_type="exam",
                source_type="csv",
                name="legacy OCR done",
                doc_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
                csv_data={
                    "columns": ["检查项目", "数值", "单位", "参考范围", "异常"],
                    "rows": [["尿酸", "520", "umol/L", "208-428", "异常"]],
                },
                abnormal_flags=[{"field": "尿酸", "value": "520", "is_abnormal": True}],
                extraction_status="done",
            )
        )
        db.add(HealthSummary(user_id=1, summary_text="legacy OCR summary", version=1))
        db.commit()

    trend = client.get(
        "/api/health-data/indicators/trend",
        headers=headers,
        params={"names": "尿酸"},
    )
    summary = client.get("/api/health-data/summary", headers=headers)
    generated_summary = client.post("/api/health-data/summary/generate", headers=headers)
    assert trend.status_code == 200
    assert trend.json() == {"indicators": []}
    assert summary.json() == {"summary_text": "", "updated_at": None}
    assert generated_summary.status_code == 200
    assert "暂无健康数据" in generated_summary.json()["summary_text"]

    with factory() as db:
        assert _get_health_report_text(db, 1) == ""
        assert _get_health_summary_text(db, 1) == ""
        assert build_key_metrics(db, 1) == []
        assert build_evidence_overview(db, 1)["exam_count"] == 0
        assert run_full_pipeline(1, db, stream=False).startswith("暂无健康数据")
        assert db.scalar(select(func.count()).select_from(HealthSummary)) == 0
        assert db.scalar(select(func.count()).select_from(HealthProfileSource)) == 0
        assert db.scalar(select(func.count()).select_from(HealthScoreSnapshot)) == 0


def test_unadmitted_csv_background_and_detail_never_generate_or_expose_ai_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)

    def forbidden_summary(*_args, **_kwargs):
        raise AssertionError("unadmitted OCR must not enter AI summarization")

    monkeypatch.setattr(health_data, "_generate_doc_summary", forbidden_summary)
    csv_upload = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "肌酐,70,umol/L,41-81,,0.99\n",
    )
    assert csv_upload.status_code == 200, csv_upload.text
    assert csv_upload.json()["ai_brief"] is None
    assert csv_upload.json()["ai_summary"] is None

    with factory() as db:
        legacy = HealthDocument(
            user_id=1,
            doc_type="exam",
            source_type="csv",
            name="legacy unverified",
            doc_date=datetime(2026, 7, 11, tzinfo=timezone.utc),
            csv_data={"columns": ["检查项目", "数值"], "rows": [["尿酸", "520"]]},
            ai_brief="危险的旧摘要",
            ai_summary="这是从未确认 OCR 直接生成的旧 AI 内容",
            extraction_status="done",
        )
        db.add(legacy)
        db.commit()
        db.refresh(legacy)
        legacy_id = legacy.id

        photo = HealthDocument(
            user_id=1,
            doc_type="exam",
            source_type="photo",
            name="正在识别-体检报告",
            doc_date=datetime(2026, 7, 12, tzinfo=timezone.utc),
            extraction_status="pending",
        )
        db.add(photo)
        db.flush()
        workflow = health_report_trust_service.create_workflow(
            db,
            doc=photo,
            user_id=1,
            subject_user_id=1,
            fingerprint="b" * 64,
            client_request_id="background-no-ai",
        )
        db.commit()
        photo_id = photo.id
        workflow_id = workflow.id

    detail = client.get(f"/api/health-data/documents/{legacy_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["ai_brief"] is None
    assert detail.json()["ai_summary"] is None

    monkeypatch.setattr(
        health_data,
        "_extract_exam_from_image",
        lambda *_args: (
            {
                "columns": ["检查项目", "数值", "单位", "参考范围", "异常", "置信度"],
                "rows": [["血红蛋白", "135", "g/L", "115-150", "", "0.99"]],
            },
            [],
        ),
    )
    monkeypatch.setattr(health_data, "_extract_name_from_image", lambda *_args: "测试医院-2026-07-12-体检报告")
    monkeypatch.setattr(db_session_module, "SessionLocal", factory)
    health_data._process_document_background(
        photo_id,
        b"fake-image",
        "report.jpg",
        "exam",
        "photo",
    )
    with factory() as db:
        photo = db.get(HealthDocument, photo_id)
        workflow = db.get(HealthReportWorkflow, workflow_id)
        assert photo.extraction_status == "done"
        assert photo.ai_brief is None
        assert photo.ai_summary is None
        assert workflow.status == "awaiting_confirmation"


def test_duplicate_fingerprint_conflicts_and_withdrawal_retract_all_consumers(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    csv_text = (
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "空腹血糖,5.6,mmol/L,3.9-6.1,,0.99\n"
        "空腹血糖,100,mg/dL,70-100,,0.99\n"
    )
    first = _upload(client, headers, csv_text)
    duplicate = _upload(client, headers, csv_text, filename="same-content.csv")
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["report_duplicate"] is True
    assert duplicate.json()["id"] == first.json()["id"]
    assert duplicate.json()["report_workflow_id"] == first.json()["report_workflow_id"]

    workflow_id = first.json()["report_workflow_id"]
    document_id = int(first.json()["id"])
    review = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 1},
    ).json()
    assert review["failure_code"] is None
    assert review["failure_recovery"] is None
    assert review["status"] == "awaiting_confirmation"
    assert all(item["review_status"] == "pending_review" for item in review["candidates"])
    assert all(item["low_confidence"] is False for item in review["candidates"])
    for candidate in review["candidates"]:
        assert set(candidate["conflict_reasons"]) == {
            "unit_conflict",
            "reference_range_conflict",
            "duplicate_value_conflict",
        }
        assert candidate["source_locator"] == {
            "document_id": document_id,
            "source_type": "csv",
            "row_index": candidate["source_locator"]["row_index"],
            "name_column": 0,
            "value_column": 1,
            "unit_column": 2,
            "reference_column": 3,
            "abnormal_column": 4,
            "confidence_column": 5,
        }

    confirmed = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json=_confirm_payload(review, "confirm-conflicted-report"),
    )
    assert confirmed.status_code == 200, confirmed.text
    with factory() as db:
        db.add(HealthSummary(user_id=1, summary_text="trusted summary", version=1))
        db.add(
            HealthScoreSnapshot(
                user_id=1,
                subject_user_id=1,
                source_report_workflow_id=workflow_id,
                idempotency_key="score-before-withdrawal",
                score_kind="stress",
                algorithm_id="test",
                algorithm_version="1",
                calculation_status="pending",
            )
        )
        db.commit()

    deleted = client.delete(f"/api/health-data/documents/{document_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/health-data/documents/{document_id}", headers=headers).status_code == 404
    assert client.get("/api/health-data/documents", headers=headers).json()["total"] == 0
    assert client.get("/api/health-data/summary", headers=headers).json()["summary_text"] == ""
    assert client.get(
        "/api/health-data/indicators/trend",
        headers=headers,
        params={"names": "空腹血糖"},
    ).json() == {"indicators": []}
    assert _upload(client, headers, csv_text).status_code == 409

    with factory() as db:
        observations = db.execute(select(ConfirmedHealthObservation)).scalars().all()
        assert observations and all(item.status == "retracted" for item in observations)
        assert db.get(HealthReportWorkflow, workflow_id).failure_code == "withdrawn"
        score = db.execute(select(HealthScoreSnapshot)).scalars().one()
        assert score.calculation_status == "failed"
        assert score.failure_code == "source_report_withdrawn"

        racing_doc = HealthDocument(
            user_id=1,
            doc_type="exam",
            source_type="photo",
            name="OCR withdrawal race",
            doc_date=datetime(2026, 7, 15, tzinfo=timezone.utc),
            extraction_status="pending",
        )
        db.add(racing_doc)
        db.flush()
        racing_workflow = health_report_trust_service.create_workflow(
            db,
            doc=racing_doc,
            user_id=1,
            subject_user_id=1,
            fingerprint="c" * 64,
            client_request_id="withdraw-during-failed-ocr",
        )
        db.commit()
        racing_doc_id = racing_doc.id
        racing_workflow_id = racing_workflow.id

    def withdraw_then_fail_ocr(*_args):
        with factory() as race_db:
            retained, _ = health_report_trust_service.withdraw_document(
                race_db,
                document_id=racing_doc_id,
                user_id=1,
            )
            assert retained is True
        raise RuntimeError("OCR failed after withdrawal committed")

    monkeypatch.setattr(db_session_module, "SessionLocal", factory)
    monkeypatch.setattr(health_data, "_extract_exam_from_image", withdraw_then_fail_ocr)
    health_data._process_document_background(
        racing_doc_id,
        b"failing-image",
        "failing.jpg",
        "exam",
        "photo",
    )

    with factory() as db:
        racing_doc = db.get(HealthDocument, racing_doc_id)
        racing_workflow = db.get(HealthReportWorkflow, racing_workflow_id)
        assert racing_workflow.status == "failed"
        assert racing_workflow.failure_code == "withdrawn"
        assert racing_doc.extraction_status == "failed"
        assert racing_doc.ai_brief is None
        assert racing_doc.csv_data is None
    assert client.get("/api/health-data/documents", headers=headers).json()["total"] == 0


def test_manual_report_candidate_http_recovers_no_reviewable_failure_and_stays_untrusted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    uploaded = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "体检小结,未见明确结构化指标,,,,\n",
        filename="no-reviewable.csv",
    )
    assert uploaded.status_code == 200, uploaded.text
    workflow_id = uploaded.json()["report_workflow_id"]
    failed = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 1},
    )
    assert failed.status_code == 200, failed.text
    failed_review = failed.json()
    assert failed_review["status"] == "failed"
    assert failed_review["failure_code"] == "no_reviewable_candidates"
    assert failed_review["failure_recovery"] == {
        "failure_code": "no_reviewable_candidates",
        "recovery_action": "manual_entry_or_reupload",
        "retryable": True,
        "allows_manual_candidate": True,
    }
    assert failed_review["can_confirm"] is False

    payload = {
        "subject_user_id": 1,
        "workflow_version": failed_review["version"],
        "client_event_id": "manual-recovery-hscrp-1",
        "canonical_code": "lab.hscrp",
        "canonical_name": "hsCRP",
        "raw_name": "超敏C反应蛋白",
        "value_numeric": 4.8,
        "unit": "mg/L",
        "reference_low": 0,
        "reference_high": 3,
        "reference_text": "0-3",
        "effective_at": "2026-07-15T02:00:00Z",
    }
    forbidden = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json={**payload, "subject_user_id": 2},
    )
    invalid_values = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json={**payload, "client_event_id": "manual-invalid-values", "value_text": "4.8"},
    )
    invalid_reference = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json={
            **payload,
            "client_event_id": "manual-invalid-reference",
            "reference_low": 5,
            "reference_high": 3,
        },
    )
    assert forbidden.status_code == 403
    assert invalid_values.status_code == 422
    assert invalid_reference.status_code == 422

    created = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json=payload,
    )
    assert created.status_code == 200, created.text
    review = created.json()
    assert review["status"] == "awaiting_confirmation"
    assert review["version"] == failed_review["version"] + 1
    assert review["failure_code"] is None
    assert review["failure_detail"] is None
    assert review["failure_recovery"] is None
    assert review["pending_review_count"] == 1
    assert review["can_confirm"] is True
    candidate = review["candidates"][0]
    assert candidate["review_status"] == "pending_review"
    assert candidate["requires_review"] is True
    assert candidate["model_version"] == "manual-entry-v1"
    assert candidate["source_locator"] == {
        "source_type": "manual",
        "entry_method": "report_review",
        "workflow_id": workflow_id,
        "document_id": int(uploaded.json()["id"]),
    }
    assert candidate["normalized_value"] == 4.8
    assert candidate["normalized_text"] is None
    assert candidate["abnormal_state"] == "abnormal"

    retry = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json=payload,
    )
    changed_retry = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json={**payload, "value_numeric": 4.9},
    )
    stale_new_event = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/manual-candidates",
        headers=headers,
        json={**payload, "client_event_id": "manual-stale-event"},
    )
    assert retry.status_code == 200
    assert retry.json()["version"] == review["version"]
    assert retry.json()["candidates"][0]["candidate_id"] == candidate["candidate_id"]
    assert changed_retry.status_code == 409
    assert stale_new_event.status_code == 409

    missing_decision = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "confirm-manual-report-without-field",
            "workflow_version": review["version"],
            "decisions": [],
        },
    )
    assert missing_decision.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ConfirmedHealthObservation)) == 0
        assert db.scalar(select(func.count()).select_from(HealthProfileSource)) == 0
        assert db.scalar(select(func.count()).select_from(HealthScoreSnapshot)) == 0
        assert _get_health_report_text(db, 1) == ""
        events = db.execute(select(HealthReportConfirmationEvent)).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "manual_add"
        assert events[0].actor_user_id == 1
        assert events[0].after_data["candidate_id"] == candidate["candidate_id"]

    confirmed = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "confirm-manual-report-after-field",
            "workflow_version": review["version"],
            "decisions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["version"],
                    "action": "confirm",
                }
            ],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed_score_pending"
    assert confirmed.json()["admitted_observation_count"] == 1


def test_manual_report_candidate_service_enforces_event_scope_and_failure_semantics(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    first_upload = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "空腹血糖,5.6,mmol/L,3.9-6.1,,0.99\n",
        filename="manual-service-first.csv",
    ).json()
    second_upload = _upload(
        client,
        headers,
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        "肌酐,70,umol/L,41-81,,0.99\n",
        filename="manual-service-second.csv",
    ).json()
    first_workflow_id = first_upload["report_workflow_id"]
    second_workflow_id = second_upload["report_workflow_id"]

    with factory() as db:
        first_workflow = db.get(HealthReportWorkflow, first_workflow_id)
        payload = HealthReportManualCandidateIn(
            subject_user_id=1,
            workflow_version=first_workflow.version,
            client_event_id="manual-service-stable-event",
            canonical_name="空腹血糖",
            raw_name="空腹血糖手动补录",
            value_numeric=6.2,
            unit="mmol/L",
            reference_low=3.9,
            reference_high=6.1,
            reference_text="3.9-6.1",
            effective_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        created = health_report_trust_service.add_manual_candidate(
            db,
            workflow_id=first_workflow_id,
            user_id=1,
            payload=payload,
        )
    manual = next(item for item in created["candidates"] if item["raw_name"] == "空腹血糖手动补录")
    assert float(manual["normalized_value"]) == 6.2
    assert manual["normalized_text"] is None
    assert manual["review_status"] == "pending_review"
    glucose_candidates = [item for item in created["candidates"] if item["canonical_name"] == "空腹血糖"]
    assert len(glucose_candidates) == 2
    assert all(item["review_status"] == "pending_review" for item in glucose_candidates)
    assert all("duplicate_value_conflict" in item["conflict_reasons"] for item in glucose_candidates)

    with factory() as db:
        retry = health_report_trust_service.add_manual_candidate(
            db,
            workflow_id=first_workflow_id,
            user_id=1,
            payload=payload,
        )
        assert next(item for item in retry["candidates"] if item["raw_name"] == "空腹血糖手动补录")[
            "candidate_id"
        ] == manual["candidate_id"]
        assert db.scalar(
            select(func.count()).select_from(HealthReportFieldCandidate).where(
                HealthReportFieldCandidate.candidate_key.like("manual:%")
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(HealthReportConfirmationEvent).where(
                HealthReportConfirmationEvent.event_type == "manual_add"
            )
        ) == 1

    with factory() as db:
        second_workflow = db.get(HealthReportWorkflow, second_workflow_id)
        cross_workflow = payload.model_copy(
            update={"workflow_version": second_workflow.version}
        )
        with pytest.raises(HTTPException) as conflict:
            health_report_trust_service.add_manual_candidate(
                db,
                workflow_id=second_workflow_id,
                user_id=1,
                payload=cross_workflow,
            )
        assert conflict.value.status_code == 409

        with pytest.raises(HTTPException) as subject_conflict:
            health_report_trust_service.add_manual_candidate(
                db,
                workflow_id=second_workflow_id,
                user_id=1,
                payload=cross_workflow.model_copy(
                    update={
                        "subject_user_id": 2,
                        "client_event_id": "manual-service-cross-subject",
                    }
                ),
            )
        assert subject_conflict.value.status_code == 403

    with factory() as db:
        stale = payload.model_copy(update={"client_event_id": "manual-service-stale"})
        with pytest.raises(HTTPException) as stale_conflict:
            health_report_trust_service.add_manual_candidate(
                db,
                workflow_id=first_workflow_id,
                user_id=1,
                payload=stale,
            )
        assert stale_conflict.value.status_code == 409

        workflow = db.get(HealthReportWorkflow, first_workflow_id)
        original_status = workflow.status
        with pytest.raises(ValueError, match="Duplicate reports must reuse"):
            health_report_trust_service.mark_workflow_failed(
                db,
                workflow,
                "duplicate",
                "must not become a failure",
            )
        assert workflow.status == original_status

    expected_recovery = {
        "blur": ("retake_image", True, False),
        "missing_page": ("upload_missing_pages", True, False),
        "no_reviewable_candidates": ("manual_entry_or_reupload", True, True),
        "extraction_failed": ("reupload_report", True, False),
        "processing_failed": ("retry_processing", True, False),
        "duplicate": ("open_existing_report", False, False),
    }
    for code, (action, retryable, allows_manual) in expected_recovery.items():
        recovery = health_report_trust_service._failure_recovery_payload(
            HealthReportWorkflow(failure_code=code)
        )
        assert recovery == {
            "failure_code": code,
            "recovery_action": action,
            "retryable": retryable,
            "allows_manual_candidate": allows_manual,
        }
