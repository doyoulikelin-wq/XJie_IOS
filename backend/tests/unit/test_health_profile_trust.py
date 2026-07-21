"""Regression coverage for the confirmed health-profile trust boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models.health_trust import (
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileRevision,
    HealthProfileSource,
    HealthReportWorkflow,
)
from app.models.user import User
from app.routers import health_data, health_profile_trust, health_report_trust
from app.services.context_builder import _get_patient_history_context
from app.services.health_profile_trust_service import confirmed_profile_context


def _client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> tuple[TestClient, sessionmaker, dict[str, str]]:
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
                User(id=1, phone="18800000201", username="profile-owner", password="x"),
                User(id=2, phone="18800000202", username="other-owner", password="x"),
            ]
        )
        db.commit()

    monkeypatch.setattr(health_data.settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(health_data, "_generate_doc_summary", lambda *_args, **_kwargs: ("", ""))

    app = FastAPI()
    app.include_router(health_data.router, prefix="/api/health-data")
    app.include_router(health_report_trust.router, prefix="/api/health-data")
    app.include_router(health_profile_trust.router, prefix="/api/health-data")

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


def _save_fact(
    client: TestClient,
    headers: dict[str, str],
    *,
    event_id: str,
    fact_key: str,
    category: str,
    response_state: str,
    value=None,
    safety: bool = False,
    expected_version: int | None = None,
):
    payload = {
        "subject_user_id": 1,
        "client_event_id": event_id,
        "fact_key": fact_key,
        "category": category,
        "response_state": response_state,
        "is_safety_critical": safety,
    }
    if value is not None:
        payload["value"] = value
    if expected_version is not None:
        payload["expected_version"] = expected_version
    return client.post("/api/health-data/profile-trust/facts", headers=headers, json=payload)


def _admit_abnormal_report(
    client: TestClient,
    headers: dict[str, str],
    *,
    value: int,
    suffix: str,
) -> int:
    csv_text = (
        "检查项目,数值,单位,参考范围,异常,置信度\n"
        f"尿酸,{value},umol/L,208-428,异常,0.99\n"
    )
    uploaded = client.post(
        "/api/health-data/upload",
        headers=headers,
        files={"file": (f"uric-acid-{suffix}.csv", csv_text.encode("utf-8"), "text/csv")},
        data={"doc_type": "exam", "name": f"体检报告-{suffix}"},
    )
    assert uploaded.status_code == 200, uploaded.text
    workflow_id = int(uploaded.json()["report_workflow_id"])
    review_response = client.get(
        f"/api/health-data/report-workflows/{workflow_id}/review",
        headers=headers,
        params={"subject_user_id": 1},
    )
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    decisions = [
        {
            "candidate_id": candidate["candidate_id"],
            "candidate_version": candidate["version"],
            "action": "confirm",
        }
        for candidate in review["candidates"]
        if candidate["review_status"] == "pending_review"
    ]
    confirmed = client.post(
        f"/api/health-data/report-workflows/{workflow_id}/confirm",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": f"confirm-{suffix}",
            "workflow_version": review["version"],
            "decisions": decisions,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed_score_pending"
    return workflow_id


def test_profile_get_defaults_to_authenticated_subject_and_rejects_other_subject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client, _factory, headers = _client(monkeypatch, tmp_path)

    default_subject = client.get("/api/health-data/profile-trust", headers=headers)
    explicit_self = client.get(
        "/api/health-data/profile-trust",
        headers=headers,
        params={"subject_user_id": 1},
    )
    forbidden_read = client.get(
        "/api/health-data/profile-trust",
        headers=headers,
        params={"subject_user_id": 2},
    )
    forbidden_write = client.post(
        "/api/health-data/profile-trust/facts",
        headers=headers,
        json={
            "subject_user_id": 2,
            "client_event_id": "cross-subject-write",
            "fact_key": "basic.birth_date",
            "category": "basic",
            "response_state": "value",
            "value": "1980-01-01",
        },
    )

    assert default_subject.status_code == 200
    assert default_subject.json()["subject_user_id"] == 1
    assert default_subject.json() == explicit_self.json()
    assert forbidden_read.status_code == 403
    assert forbidden_write.status_code == 403


def test_manual_profile_states_versions_idempotency_sources_and_retraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client, factory, headers = _client(monkeypatch, tmp_path)

    created = _save_fact(
        client,
        headers,
        event_id="birth-create",
        fact_key="basic.birth_date",
        category="basic",
        response_state="value",
        value="1980-01-01",
    )
    assert created.status_code == 200, created.text
    replay = _save_fact(
        client,
        headers,
        event_id="birth-create",
        fact_key="basic.birth_date",
        category="basic",
        response_state="value",
        value="1980-01-01",
    )
    assert replay.status_code == 200
    reused_event = _save_fact(
        client,
        headers,
        event_id="birth-create",
        fact_key="basic.birth_date",
        category="basic",
        response_state="value",
        value="1981-01-01",
    )
    assert reused_event.status_code == 409

    safety_none = _save_fact(
        client,
        headers,
        event_id="allergy-none",
        fact_key="safety.medication_allergy",
        category="safety",
        response_state="none",
        safety=True,
    )
    goal_na = _save_fact(
        client,
        headers,
        event_id="goal-na",
        fact_key="goal.primary",
        category="goal",
        response_state="not_applicable",
    )
    sex_private = _save_fact(
        client,
        headers,
        event_id="sex-private",
        fact_key="basic.sex",
        category="basic",
        response_state="prefer_not_to_answer",
    )
    assert safety_none.status_code == 200
    assert goal_na.status_code == 200
    assert sex_private.status_code == 200
    profile = sex_private.json()
    assert profile["overview"]["resolved_required_weight"] == 4
    assert profile["overview"]["completeness_percent"] == 27
    assert profile["overview"]["independent_source_count"] == 4
    by_key = {fact["fact_key"]: fact for fact in profile["facts"]}
    assert by_key["safety.medication_allergy"]["value_data"] == {"response_state": "none"}
    assert by_key["safety.medication_allergy"]["is_safety_critical"] is True

    bad_safety_category = _save_fact(
        client,
        headers,
        event_id="unsafe-category",
        fact_key="safety.other_allergy",
        category="safety",
        response_state="none",
        safety=False,
    )
    bad_safety_flag = _save_fact(
        client,
        headers,
        event_id="unsafe-flag",
        fact_key="basic.height",
        category="basic",
        response_state="value",
        value=170,
        safety=True,
    )
    disguised_safety_key = _save_fact(
        client,
        headers,
        event_id="disguised-safety-key",
        fact_key="safety.contraindication",
        category="basic",
        response_state="none",
        safety=False,
    )
    mismatched_safety_category = _save_fact(
        client,
        headers,
        event_id="mismatched-safety-category",
        fact_key="basic.height",
        category="safety",
        response_state="none",
        safety=True,
    )
    value_on_none = _save_fact(
        client,
        headers,
        event_id="none-with-value",
        fact_key="basic.blood_type",
        category="basic",
        response_state="none",
        value="A",
    )
    assert bad_safety_category.status_code == 422
    assert bad_safety_flag.status_code == 422
    assert disguised_safety_key.status_code == 422
    assert mismatched_safety_category.status_code == 422
    assert value_on_none.status_code == 422

    stale_update = _save_fact(
        client,
        headers,
        event_id="birth-stale",
        fact_key="basic.birth_date",
        category="basic",
        response_state="value",
        value="1982-01-01",
    )
    assert stale_update.status_code == 409
    updated = _save_fact(
        client,
        headers,
        event_id="birth-update",
        fact_key="basic.birth_date",
        category="basic",
        response_state="value",
        value="1982-01-01",
        expected_version=1,
    )
    assert updated.status_code == 200, updated.text
    birth = next(
        fact for fact in updated.json()["facts"] if fact["fact_key"] == "basic.birth_date"
    )
    assert birth["version"] == 2
    assert len(birth["sources"]) == 1
    assert updated.json()["overview"]["independent_source_count"] == 4

    fact_id = int(birth["fact_id"])
    stale_retract = client.post(
        f"/api/health-data/profile-trust/facts/{fact_id}/retract",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "birth-retract-stale",
            "expected_version": 1,
        },
    )
    assert stale_retract.status_code == 409
    retract_payload = {
        "subject_user_id": 1,
        "client_event_id": "birth-retract",
        "expected_version": 2,
    }
    retracted = client.post(
        f"/api/health-data/profile-trust/facts/{fact_id}/retract",
        headers=headers,
        json=retract_payload,
    )
    retract_replay = client.post(
        f"/api/health-data/profile-trust/facts/{fact_id}/retract",
        headers=headers,
        json=retract_payload,
    )
    assert retracted.status_code == 200
    assert retract_replay.status_code == 200
    assert all(fact["fact_id"] != fact_id for fact in retracted.json()["facts"])
    assert retracted.json()["overview"]["resolved_required_weight"] == 3

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(HealthProfileFact)) == 4
        assert db.scalar(select(func.count()).select_from(HealthProfileSource)) == 4
        assert db.scalar(select(func.count()).select_from(HealthProfileRevision)) == 6


def test_repeated_admitted_reports_require_explicit_profile_acceptance_and_conflict_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client, factory, headers = _client(monkeypatch, tmp_path)

    _admit_abnormal_report(client, headers, value=450, suffix="one")
    first_profile = client.get("/api/health-data/profile-trust", headers=headers).json()
    assert first_profile["facts"] == []
    assert first_profile["candidates"] == []

    _admit_abnormal_report(client, headers, value=460, suffix="two")
    proposed = client.get("/api/health-data/profile-trust", headers=headers).json()
    assert proposed["facts"] == []
    assert len(proposed["candidates"]) == 1
    candidate = proposed["candidates"][0]
    assert candidate["review_status"] == "pending_review"
    assert candidate["is_safety_critical"] is False
    assert isinstance(candidate["confidence"], (int, float))
    assert not isinstance(candidate["confidence"], bool)
    assert candidate["proposed_value"]["occurrence_count"] == 2
    assert len(candidate["sources"]) == 2
    assert all(
        isinstance(source["confidence"], (int, float))
        and not isinstance(source["confidence"], bool)
        for source in candidate["sources"]
    )
    with factory() as db:
        assert confirmed_profile_context(db, user_id=1) == {}
        assert _get_patient_history_context(db, "1") == {}

    accept_payload = {
        "subject_user_id": 1,
        "client_event_id": "accept-repeated-uric-acid",
        "candidate_version": candidate["version"],
        "action": "accept",
    }
    accepted = client.post(
        f"/api/health-data/profile-trust/candidates/{candidate['candidate_id']}/review",
        headers=headers,
        json=accept_payload,
    )
    replay = client.post(
        f"/api/health-data/profile-trust/candidates/{candidate['candidate_id']}/review",
        headers=headers,
        json=accept_payload,
    )
    assert accepted.status_code == 200, accepted.text
    assert replay.status_code == 200
    trusted_fact = accepted.json()["facts"][0]
    assert trusted_fact["confirmation_method"] == "user"
    assert trusted_fact["value_data"]["occurrence_count"] == 2
    assert len(trusted_fact["sources"]) == 2
    assert all(
        isinstance(source["confidence"], (int, float))
        and not isinstance(source["confidence"], bool)
        for source in trusted_fact["sources"]
    )
    assert accepted.json()["overview"]["independent_source_count"] == 2
    with factory() as db:
        context = _get_patient_history_context(db, "1")
        assert context["confirmed_facts"]["long_term_health"][0]["fact_key"] == trusted_fact[
            "fact_key"
        ]
        assert db.scalar(select(func.count()).select_from(HealthProfileFact)) == 1
        assert db.scalar(
            select(func.count()).select_from(HealthProfileSource).where(
                HealthProfileSource.fact_id == trusted_fact["fact_id"]
            )
        ) == 2
        assert db.scalar(select(func.count()).select_from(HealthProfileRevision)) == 2

    _admit_abnormal_report(client, headers, value=470, suffix="three")
    conflicted = client.get("/api/health-data/profile-trust", headers=headers).json()
    assert len(conflicted["facts"]) == 1
    assert conflicted["facts"][0]["value_data"] == trusted_fact["value_data"]
    assert len(conflicted["candidates"]) == 1
    conflict = conflicted["candidates"][0]
    assert conflict["review_status"] == "conflict"
    assert conflict["conflict_with_fact_id"] == trusted_fact["fact_id"]
    assert conflict["proposed_value"]["latest_value_numeric"] == "470.00000000"

    rejected = client.post(
        f"/api/health-data/profile-trust/candidates/{conflict['candidate_id']}/review",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "reject-conflicting-uric-acid",
            "candidate_version": conflict["version"],
            "action": "reject",
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["candidates"] == []
    assert rejected.json()["facts"][0]["value_data"] == trusted_fact["value_data"]
    with factory() as db:
        context = _get_patient_history_context(db, "1")
        assert context["confirmed_facts"]["long_term_health"][0]["value"] == trusted_fact[
            "value_data"
        ]


def test_report_withdrawal_supersedes_unaccepted_profile_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    _admit_abnormal_report(client, headers, value=450, suffix="withdraw-one")
    second_workflow_id = _admit_abnormal_report(
        client,
        headers,
        value=460,
        suffix="withdraw-two",
    )
    proposed = client.get("/api/health-data/profile-trust", headers=headers).json()
    candidate = proposed["candidates"][0]

    with factory() as db:
        document_id = db.get(HealthReportWorkflow, second_workflow_id).legacy_document_id
    withdrawn = client.delete(f"/api/health-data/documents/{document_id}", headers=headers)
    assert withdrawn.status_code == 200, withdrawn.text

    profile = client.get("/api/health-data/profile-trust", headers=headers).json()
    assert profile["facts"] == []
    assert profile["candidates"] == []
    stale_acceptance = client.post(
        f"/api/health-data/profile-trust/candidates/{candidate['candidate_id']}/review",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "accept-withdrawn-source",
            "candidate_version": candidate["version"],
            "action": "accept",
        },
    )
    assert stale_acceptance.status_code == 409
    with factory() as db:
        stored_candidate = db.get(HealthProfileCandidate, candidate["candidate_id"])
        assert stored_candidate.review_status == "superseded"
        assert db.scalar(select(func.count()).select_from(HealthProfileFact)) == 0
        assert _get_patient_history_context(db, "1") == {}


def test_legacy_profile_import_requires_user_verification_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    client, factory, headers = _client(monkeypatch, tmp_path)
    unverified_sections = {
        "diagnoses": {
            "value": "高血压",
            "status": "documented",
            "source_type": "document",
            "verified_by_user": False,
        },
        "allergies": {
            "value": "青霉素过敏",
            "status": "documented",
            "source_type": "document",
            "verified_by_user": False,
        },
    }
    unverified = client.put(
        "/api/health-data/patient-history",
        headers=headers,
        json={"doctor_summary": "未确认的生成摘要", "sections": unverified_sections},
    )
    assert unverified.status_code == 200, unverified.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(HealthProfileFact)) == 0
        assert _get_patient_history_context(db, "1") == {}

    verified_sections = {
        key: {**value, "verified_by_user": True}
        for key, value in unverified_sections.items()
    }
    verified_payload = {
        "doctor_summary": "未确认的生成摘要",
        "sections": verified_sections,
        "verified_at": "2026-07-15T10:00:00Z",
    }
    verified = client.put(
        "/api/health-data/patient-history",
        headers=headers,
        json=verified_payload,
    )
    replay = client.put(
        "/api/health-data/patient-history",
        headers=headers,
        json=verified_payload,
    )
    assert verified.status_code == 200, verified.text
    assert replay.status_code == 200, replay.text

    with factory() as db:
        facts = db.execute(select(HealthProfileFact).order_by(HealthProfileFact.fact_key)).scalars().all()
        assert len(facts) == 2
        safety_fact = next(fact for fact in facts if fact.category == "safety")
        assert safety_fact.is_safety_critical is True
        assert safety_fact.confirmation_method == "user"
        assert all(fact.version == 1 for fact in facts)
        assert db.scalar(select(func.count()).select_from(HealthProfileSource)) == 2
        assert db.scalar(select(func.count()).select_from(HealthProfileRevision)) == 2
        context = _get_patient_history_context(db, "1")
        assert "未确认的生成摘要" not in str(context)
        assert context["confirmed_facts"]["safety"][0]["value"]["value"] == "青霉素过敏"


def test_automatic_profile_facts_never_enter_ai_and_safety_cannot_be_automatic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _client_instance, factory, _headers = _client(monkeypatch, tmp_path)
    now = datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc)
    with factory() as db:
        db.add(
            HealthProfileFact(
                user_id=1,
                subject_user_id=1,
                fact_key="basic.automatic-suggestion",
                category="basic",
                value_data={"response_state": "value", "value": "untrusted"},
                is_safety_critical=False,
                confirmation_method="automatic",
                status="active",
                version=1,
                confirmed_by_user_id=None,
                confirmed_at=None,
                updated_at=now,
            )
        )
        db.commit()
        assert confirmed_profile_context(db, user_id=1) == {}
        assert _get_patient_history_context(db, "1") == {}

    with factory() as db:
        db.add(
            HealthProfileFact(
                user_id=1,
                subject_user_id=1,
                fact_key="safety.automatic-allergy",
                category="safety",
                value_data={"response_state": "value", "value": "青霉素过敏"},
                is_safety_critical=True,
                confirmation_method="automatic",
                status="active",
                version=1,
                confirmed_by_user_id=1,
                confirmed_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(
            select(func.count()).select_from(HealthProfileCandidate).where(
                HealthProfileCandidate.category == "safety"
            )
        ) == 0
