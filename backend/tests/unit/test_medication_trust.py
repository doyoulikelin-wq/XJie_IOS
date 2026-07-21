"""Regression coverage for the trusted medication execution loop."""

from __future__ import annotations

import inspect
import importlib
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.deps import get_db
from app.core.security import create_access_token
from app.db.base import Base
from app.models.health_trust import (
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileSource,
)
from app.models.medication import Medication
from app.models.medication_trust import (
    MedicationAdverseReactionEvent,
    MedicationDoseEvent,
    MedicationPrefillCandidate,
    TrustedMedicationPlan,
)
from app.models.user import User
from app.routers import medication_trust, medications
from app.services.context_builder import _get_current_medications
from app.services.medication_trust_service import build_today_summary


migration_0023 = importlib.import_module(
    "app.db.migrations.versions.0023_trusted_medication_loop"
)


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, sessionmaker, dict[str, str]]:
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
                User(id=1, phone="18800000301", username="med-owner", password="x"),
                User(id=2, phone="18800000302", username="other-owner", password="x"),
            ]
        )
        db.commit()

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    app = FastAPI()
    app.include_router(medications.router, prefix="/api/medications")
    app.include_router(medication_trust.router, prefix="/api/medications")

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    token = create_access_token("1")
    return TestClient(app, raise_server_exceptions=False), factory, {
        "Authorization": f"Bearer {token}"
    }


def _confirm_payload(
    *,
    event_id: str,
    request_id: str,
    name: str = "二甲双胍",
    candidate: dict | None = None,
    initial_quantity: float | None = 10,
    dose_quantity: float | None = 1,
    is_long_term: bool = False,
) -> dict:
    payload = {
        "subject_user_id": 1,
        "client_request_id": request_id,
        "client_event_id": event_id,
        "generic_name": name,
        "brand_name": None,
        "strength": "500mg",
        "dose_text": "1片",
        "dose_quantity": dose_quantity,
        "frequency": "每日一次",
        "schedule_times": ["08:00"],
        "meal_relation": "after_meal",
        "instructions": "按确认计划服用",
        "course_start": None,
        "course_end": None,
        "prescriber": None,
        "initial_quantity": initial_quantity,
        "inventory_unit": "片" if initial_quantity is not None else None,
        "is_long_term": is_long_term,
        "source_type": "ocr" if candidate else "manual",
        "source_ref": None,
    }
    if candidate:
        payload.update(
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_version": candidate["candidate_version"],
            }
        )
    return payload


def _confirm_plan(client: TestClient, headers: dict[str, str], **kwargs) -> dict:
    payload = _confirm_payload(**kwargs)
    response = client.post(
        "/api/medications/trust/plans/confirm", headers=headers, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def _dose_payload(
    plan: dict,
    *,
    event_id: str,
    local_date: date,
    expected_occurrence_version: int,
    action: str,
    **extra,
) -> dict:
    return {
        "subject_user_id": 1,
        "plan_id": plan["plan_id"],
        "expected_plan_version": plan["version"],
        "client_event_id": event_id,
        "scheduled_local_date": local_date.isoformat(),
        "scheduled_time": "08:00",
        "expected_occurrence_version": expected_occurrence_version,
        "action": action,
        **extra,
    }


def test_0023_migration_is_additive_and_enforces_confirmed_tenant_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    _client_instance, factory, _headers = _client(monkeypatch)
    source = inspect.getsource(migration_0023.upgrade)
    assert migration_0023.revision == "0023_trusted_medication_loop"
    assert migration_0023.down_revision == "0022_health_trust_contracts"
    assert "alter_column" not in source
    assert "drop_table" not in source
    assert "execute(" not in source
    assert source.count("op.create_table(") == 5

    plan_table = TrustedMedicationPlan.__table__
    assert list(plan_table.columns) == [
        plan_table.c.id,
        plan_table.c.user_id,
        plan_table.c.subject_user_id,
        plan_table.c.client_request_id,
        plan_table.c.generic_name,
        plan_table.c.brand_name,
        plan_table.c.strength,
        plan_table.c.dose_text,
        plan_table.c.dose_quantity,
        plan_table.c.frequency,
        plan_table.c.schedule_times,
        plan_table.c.meal_relation,
        plan_table.c.instructions,
        plan_table.c.course_start,
        plan_table.c.course_end,
        plan_table.c.prescriber,
        plan_table.c.initial_quantity,
        plan_table.c.inventory_unit,
        plan_table.c.is_long_term,
        plan_table.c.source_type,
        plan_table.c.source_ref,
        plan_table.c.source_snapshot,
        plan_table.c.status,
        plan_table.c.version,
        plan_table.c.confirmed_by_user_id,
        plan_table.c.confirmed_at,
        plan_table.c.created_at,
        plan_table.c.updated_at,
        plan_table.c.purpose,
    ]
    assert str(MedicationPrefillCandidate.__table__.c.source_type.server_default.arg) == "ocr"
    assert (
        str(MedicationAdverseReactionEvent.__table__.c.status.server_default.arg)
        == "active"
    )
    assert {constraint.name for constraint in plan_table.constraints} >= {
        "uq_trusted_med_plan_tenant_request",
        "uq_trusted_med_plan_tenant_id",
        "ck_trusted_med_plan_user_confirmed",
    }

    with factory() as db:
        plan = TrustedMedicationPlan(
            user_id=1,
            subject_user_id=1,
            client_request_id="tenant-plan",
            generic_name="阿司匹林",
            schedule_times=["08:00"],
            meal_relation="unspecified",
            source_type="manual",
            source_ref="manual:user-confirmed",
            source_snapshot={},
            status="active",
            version=1,
            confirmed_by_user_id=1,
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(plan)
        db.commit()
        db.add(
            MedicationDoseEvent(
                plan_id=plan.id,
                user_id=2,
                subject_user_id=2,
                actor_user_id=2,
                client_event_id="cross-tenant-dose",
                request_fingerprint="a" * 64,
                occurrence_key="dose:cross-tenant",
                scheduled_local_date=date(2026, 7, 15),
                scheduled_time="08:00",
                action="taken",
                effective_status="taken",
                occurrence_version=1,
                source_type="user_confirmed",
                confirmed_by_user_id=2,
                confirmed_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_recognize_only_creates_unconfirmed_prefill_until_explicit_plan_confirmation(
    monkeypatch: pytest.MonkeyPatch,
):
    client, factory, headers = _client(monkeypatch)
    with factory() as db:
        db.add(
            Medication(
                user_id=1,
                name="未确认旧药品",
                schedule_times=["08:00"],
                enabled=True,
            )
        )
        db.commit()
        assert _get_current_medications(db, "1") == []

    recognize_payload = {
        "raw_text": "二甲双胍缓释片\n每日一次，每次1片",
        "subject_user_id": 1,
        "client_event_id": "ocr-prefill-1",
    }
    recognized = client.post(
        "/api/medications/recognize", headers=headers, json=recognize_payload
    )
    assert recognized.status_code == 200, recognized.text
    candidate = recognized.json()
    assert candidate["trust_state"] == "unconfirmed_prefill"
    assert candidate["requires_user_confirmation"] is True
    assert candidate["plan_created"] is False
    assert candidate["confirmation_endpoint"] == "/api/medications/trust/plans/confirm"
    assert candidate["low_confidence_fields"]

    replay = client.post(
        "/api/medications/recognize", headers=headers, json=recognize_payload
    )
    assert replay.status_code == 200
    assert replay.json() == candidate
    reused_event = client.post(
        "/api/medications/recognize",
        headers=headers,
        json={**recognize_payload, "raw_text": "另一种药"},
    )
    cross_subject = client.post(
        "/api/medications/recognize",
        headers=headers,
        json={**recognize_payload, "subject_user_id": 2},
    )
    assert reused_event.status_code == 409
    assert cross_subject.status_code == 403

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TrustedMedicationPlan)) == 0
        stored = db.get(MedicationPrefillCandidate, candidate["candidate_id"])
        assert stored.review_status == "pending_review"
        assert stored.source_snapshot["raw_text_stored"] is False
        assert recognize_payload["raw_text"] not in str(stored.source_snapshot)

    plan = _confirm_plan(
        client,
        headers,
        event_id="confirm-ocr-1",
        request_id="request-ocr-1",
        candidate=candidate,
    )
    assert plan["trust_state"] == "user_confirmed"
    assert plan["reminder_management"] == "client_managed"
    assert plan["reminder_default_enabled"] is False
    assert plan["server_notification_scheduled"] is False
    with factory() as db:
        stored = db.get(MedicationPrefillCandidate, candidate["candidate_id"])
        assert stored.review_status == "accepted"
        assert stored.accepted_plan_id == plan["plan_id"]
        assert [item["name"] for item in _get_current_medications(db, "1")] == [
            "二甲双胍"
        ]


def test_today_tasks_actions_are_idempotent_correctable_and_never_assert_missed(
    monkeypatch: pytest.MonkeyPatch,
):
    client, factory, headers = _client(monkeypatch)
    empty_today = client.get(
        "/api/medications/trust/today",
        headers=headers,
        params={"local_date": "2020-01-01", "timezone_offset_minutes": 480},
    )
    assert empty_today.status_code == 200, empty_today.text
    assert empty_today.json()["subject_user_id"] == 1
    assert empty_today.json()["tasks"] == []

    plan = _confirm_plan(
        client, headers, event_id="confirm-actions", request_id="request-actions"
    )
    old_date = date(2020, 1, 1)
    with factory() as db:
        summary = build_today_summary(
            db,
            user_id=1,
            subject_user_id=1,
            local_date=old_date,
            timezone_offset_minutes=480,
            now=datetime(2020, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
    task = summary["tasks"][0]
    assert summary["subject_user_id"] == 1
    assert task["status"] == "possibly_missed"
    assert task["status_assertion"] == "schedule_derived"
    assert task["possibly_missed_is_not_confirmation"] is True
    assert summary["missed_assertion_policy"] == "elapsed_time_never_confirms_missed"

    taken_payload = _dose_payload(
        plan,
        event_id="dose-taken-1",
        local_date=old_date,
        expected_occurrence_version=0,
        action="taken",
    )
    taken = client.post(
        "/api/medications/trust/dose-events", headers=headers, json=taken_payload
    )
    replay = client.post(
        "/api/medications/trust/dose-events", headers=headers, json=taken_payload
    )
    assert taken.status_code == 200, taken.text
    assert replay.status_code == 200
    assert replay.json()["event_id"] == taken.json()["event_id"]
    assert taken.json()["trust_state"] == "user_confirmed"

    implicit_overwrite = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="dose-skip-without-correction",
            local_date=old_date,
            expected_occurrence_version=1,
            action="skip",
        ),
    )
    assert implicit_overwrite.status_code == 409
    corrected = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="dose-correct-1",
            local_date=old_date,
            expected_occurrence_version=1,
            action="correct",
            corrected_status="pending",
            correction_of_event_id=taken.json()["event_id"],
        ),
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["occurrence_version"] == 2
    assert corrected.json()["supersedes_event_id"] == taken.json()["event_id"]

    future_date = date.today() + timedelta(days=1)
    snoozed = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="dose-snooze-1",
            local_date=future_date,
            expected_occurrence_version=0,
            action="snooze",
            snoozed_until=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        ),
    )
    skipped = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="dose-skip-1",
            local_date=future_date + timedelta(days=1),
            expected_occurrence_version=0,
            action="skip",
            reason="用户确认本次不服用",
        ),
    )
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["notification_schedule_status"] == "client_must_schedule"
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["effective_status"] == "skipped"


def test_estimated_remaining_uses_only_latest_confirmed_taken_records(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _factory, headers = _client(monkeypatch)
    plan = _confirm_plan(
        client,
        headers,
        event_id="confirm-inventory",
        request_id="request-inventory",
        initial_quantity=10,
        dose_quantity=2,
    )
    first_date = date(2026, 7, 10)
    first_taken = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="inventory-taken-1",
            local_date=first_date,
            expected_occurrence_version=0,
            action="taken",
        ),
    )
    assert first_taken.status_code == 200, first_taken.text
    plans_after_taken = client.get(
        "/api/medications/trust/plans", headers=headers
    ).json()["items"]
    assert plans_after_taken[0]["inventory"] == {
        "is_estimate": True,
        "label": "预计剩余",
        "estimated_remaining": 8.0,
        "estimated_consumed": 2.0,
        "inventory_unit": "片",
        "basis": "user_confirmed_taken_events_only",
        "unavailable_reason": None,
    }

    correction = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="inventory-correct-1",
            local_date=first_date,
            expected_occurrence_version=1,
            action="correct",
            corrected_status="skipped",
            correction_of_event_id=first_taken.json()["event_id"],
        ),
    )
    assert correction.status_code == 200, correction.text
    after_correction = client.get(
        "/api/medications/trust/plans", headers=headers
    ).json()["items"][0]["inventory"]
    assert after_correction["estimated_consumed"] == 0.0
    assert after_correction["estimated_remaining"] == 10.0

    second_taken = client.post(
        "/api/medications/trust/dose-events",
        headers=headers,
        json=_dose_payload(
            plan,
            event_id="inventory-taken-2",
            local_date=first_date + timedelta(days=1),
            expected_occurrence_version=0,
            action="taken",
            taken_quantity=3,
        ),
    )
    assert second_taken.status_code == 200, second_taken.text
    final_estimate = client.get(
        "/api/medications/trust/plans", headers=headers
    ).json()["items"][0]["inventory"]
    assert final_estimate["estimated_consumed"] == 3.0
    assert final_estimate["estimated_remaining"] == 7.0


def test_adverse_reactions_are_temporal_only_and_correctable(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _factory, headers = _client(monkeypatch)
    plan = _confirm_plan(
        client, headers, event_id="confirm-reaction", request_id="request-reaction"
    )
    created_payload = {
        "subject_user_id": 1,
        "client_event_id": "reaction-create-1",
        "reaction_key": "reaction-1",
        "plan_id": plan["plan_id"],
        "symptoms": "服药后出现皮疹",
        "onset_at": "2026-07-15T09:30:00+08:00",
        "severity": "moderate",
        "duration_minutes": 30,
        "related_occurrence_key": None,
        "notes": "仅记录时间关系",
    }
    created = client.post(
        "/api/medications/trust/reactions", headers=headers, json=created_payload
    )
    replay = client.post(
        "/api/medications/trust/reactions", headers=headers, json=created_payload
    )
    assert created.status_code == 200, created.text
    assert replay.status_code == 200
    assert created.json()["causal_attribution"] == "temporal_association_only"
    assert "不能据此认定" in created.json()["user_facing_causality"]
    assert replay.json()["reaction_version"] == 1

    correction_payload = {
        "subject_user_id": 1,
        "client_event_id": "reaction-correct-1",
        "expected_version": 1,
        "plan_id": plan["plan_id"],
        "symptoms": "轻微皮疹",
        "onset_at": "2026-07-15T09:40:00+08:00",
        "severity": "mild",
        "duration_minutes": 15,
        "related_occurrence_key": None,
        "notes": "用户修正",
    }
    corrected = client.post(
        "/api/medications/trust/reactions/reaction-1/correct",
        headers=headers,
        json=correction_payload,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["reaction_version"] == 2
    assert corrected.json()["symptoms"] == "轻微皮疹"

    stale = client.post(
        "/api/medications/trust/reactions/reaction-1/retract",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "reaction-stale-retract",
            "expected_version": 1,
        },
    )
    assert stale.status_code == 409
    retracted = client.post(
        "/api/medications/trust/reactions/reaction-1/retract",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "reaction-retract-1",
            "expected_version": 2,
        },
    )
    assert retracted.status_code == 200, retracted.text
    assert retracted.json()["status"] == "retracted"
    listed = client.get(
        "/api/medications/trust/reactions", headers=headers
    ).json()["items"]
    assert listed[0]["reaction_version"] == 3
    assert listed[0]["status"] == "retracted"


def test_only_confirmed_long_term_medications_reach_profile_candidates_and_ai_context(
    monkeypatch: pytest.MonkeyPatch,
):
    client, factory, headers = _client(monkeypatch)
    recognized = client.post(
        "/api/medications/recognize",
        headers=headers,
        json={"raw_text": "未确认候选药", "client_event_id": "profile-ocr-only"},
    )
    assert recognized.status_code == 200
    with factory() as db:
        assert _get_current_medications(db, "1") == []
        assert db.scalar(select(func.count()).select_from(HealthProfileCandidate)) == 0

    _confirm_plan(
        client,
        headers,
        event_id="confirm-short-plan",
        request_id="request-short-plan",
        name="短期用药",
        is_long_term=False,
    )
    with factory() as db:
        assert [item["name"] for item in _get_current_medications(db, "1")] == [
            "短期用药"
        ]
        assert db.scalar(select(func.count()).select_from(HealthProfileCandidate)) == 0

    long_plan = _confirm_plan(
        client,
        headers,
        event_id="confirm-long-plan",
        request_id="request-long-plan",
        name="长期用药",
        is_long_term=True,
    )
    with factory() as db:
        candidate = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.fact_key == "medication.long_term_summary"
            )
        )
        assert candidate is not None
        assert candidate.review_status == "pending_review"
        assert candidate.is_safety_critical is False
        assert candidate.proposed_value["kind"] == "confirmed_long_term_medication_summary"
        assert db.scalar(select(func.count()).select_from(HealthProfileFact)) == 0
        sources = db.scalars(
            select(HealthProfileSource).where(
                HealthProfileSource.candidate_id == candidate.id
            )
        ).all()
        assert [source.source_ref for source in sources] == [
            f"trusted-medication-plan:{long_plan['plan_id']}:v1"
        ]
        context = _get_current_medications(db, "1")
        assert {item["name"] for item in context} == {"短期用药", "长期用药"}
        assert all(item["trust_state"] == "user_confirmed" for item in context)

    paused = client.post(
        f"/api/medications/trust/plans/{long_plan['plan_id']}/status",
        headers=headers,
        json={
            "subject_user_id": 1,
            "client_event_id": "pause-long-plan",
            "expected_version": long_plan["version"],
            "action": "pause",
            "reason": "用户暂停",
        },
    )
    assert paused.status_code == 200, paused.text
    with factory() as db:
        context = _get_current_medications(db, "1")
        assert [item["name"] for item in context] == ["短期用药"]
        current_candidate = db.get(HealthProfileCandidate, candidate.id)
        assert current_candidate.review_status == "superseded"
