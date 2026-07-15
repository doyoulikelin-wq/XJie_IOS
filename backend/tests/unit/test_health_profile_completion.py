"""Focused regressions for the completed trusted health-profile slice."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.health_trust import (
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileRevision,
    HealthProfileSource,
)
from app.models.health_trust_expansion import (
    HealthProfileDeviceSourceLink,
    HealthProfileFactSourceVersion,
    HealthProfileGoal,
    TrustedDeviceProfileObservation,
)
from app.models.health_plan import HealthPlan, PlanTask
from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.schemas.health_profile_trust import (
    HealthProfileCandidateReviewIn,
    HealthProfileFactUpsertIn,
    HealthProfileGoalCreateIn,
    HealthProfileGoalMetricIn,
    HealthProfileGoalStatusIn,
    HealthProfileGoalUpdateIn,
    HealthProfileOut,
)
from app.schemas.medication_trust import MedicationPlanConfirmIn, MedicationPlanStatusIn
from app.services.health_profile_completion_service import sanitize_medication_payload
from app.services.health_profile_trust_service import (
    build_profile,
    create_profile_goal,
    list_fact_revisions,
    list_goal_revisions,
    review_candidate,
    sync_device_profile_observation,
    update_profile_goal,
    update_profile_goal_status,
    upsert_manual_fact,
)
from app.services.medication_trust_service import (
    confirm_plan,
    list_confirmed_long_term_medication_summaries,
    update_plan_status,
)
from app.services.trusted_health_context_service import (
    DECLARED_TRUSTED_HEALTH_CONSUMERS,
    TrustedHealthContextAccessError,
    build_trusted_health_context,
)


@pytest.fixture
def factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with maker() as db:
        db.add_all(
            [
                User(id=1, phone="18800000901", username="profile-owner", password="x"),
                User(id=2, phone="18800000902", username="other-owner", password="x"),
            ]
        )
        db.commit()
    return maker


def _fact_payload(
    *,
    event_id: str,
    fact_key: str,
    category: str,
    value,
    expected_version: int | None = None,
) -> HealthProfileFactUpsertIn:
    return HealthProfileFactUpsertIn(
        subject_user_id=1,
        client_event_id=event_id,
        fact_key=fact_key,
        category=category,
        response_state="value",
        value=value,
        is_safety_critical=False,
        expected_version=expected_version,
    )


def _confirm_and_accept_long_term_medication(
    db,
    *,
    event_prefix: str,
    name: str,
):
    plan = confirm_plan(
        db,
        user_id=1,
        payload=MedicationPlanConfirmIn(
            subject_user_id=1,
            client_request_id=f"{event_prefix}-request",
            client_event_id=f"{event_prefix}-confirm",
            generic_name=name,
            purpose="回归测试",
            frequency="每日一次",
            schedule_times=["08:00"],
            course_start=date(2026, 1, 1),
            is_long_term=True,
            source_type="manual",
        ),
    )
    candidate = db.scalar(
        select(HealthProfileCandidate)
        .where(
            HealthProfileCandidate.fact_key == "medication.long_term_summary",
            HealthProfileCandidate.review_status.in_(["pending_review", "conflict"]),
        )
        .order_by(HealthProfileCandidate.id.desc())
    )
    assert candidate is not None
    review_candidate(
        db,
        candidate_id=candidate.id,
        user_id=1,
        payload=HealthProfileCandidateReviewIn(
            subject_user_id=1,
            client_event_id=f"{event_prefix}-accept-profile",
            candidate_version=candidate.version,
            action="accept",
        ),
    )
    fact = db.scalar(
        select(HealthProfileFact).where(
            HealthProfileFact.fact_key == "medication.long_term_summary",
            HealthProfileFact.status == "active",
        )
    )
    assert fact is not None
    return plan, fact


def test_profile_revision_history_is_subject_scoped_append_only_and_ordered(factory):
    with factory() as db:
        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="med-create",
                fact_key="medication.long_term_summary",
                category="medication",
                value={
                    "items": [
                        {
                            "generic_name": "阿司匹林",
                            "dose_text": "100mg",
                            "frequency": "每日一次",
                            "purpose": "二级预防",
                            "course_start": "2026-01-01",
                            "status": "active",
                            "source": "user_added",
                            "confirmed_at": "2026-07-15T00:00:00Z",
                        }
                    ]
                },
            ),
        )
        fact = db.scalar(select(HealthProfileFact))
        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="med-update",
                fact_key="medication.long_term_summary",
                category="medication",
                value={"items": []},
                expected_version=1,
            ),
        )
        history = list_fact_revisions(
            db,
            fact_id=fact.id,
            user_id=1,
            subject_user_id=1,
            after_revision_id=None,
            limit=20,
        )
        assert [item["target_version"] for item in history["items"]] == [1, 2]
        first_item = history["items"][0]["after_data"]["value_data"]["value"]["items"][0]
        assert set(first_item) == {
            "medication_name",
            "purpose",
            "started_on",
            "is_still_taking",
            "source",
            "last_confirmed_at",
        }
        assert "dose_text" not in str(history)
        with pytest.raises(HTTPException) as cross_subject:
            list_fact_revisions(
                db,
                fact_id=fact.id,
                user_id=1,
                subject_user_id=2,
                after_revision_id=None,
                limit=20,
            )
        assert cross_subject.value.status_code == 404
        assert db.scalar(select(func.count()).select_from(HealthProfileRevision)) == 2


def test_profile_device_measurement_and_manual_edit_preserve_sources_and_conflict(factory):
    with factory() as db:
        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="weight-manual",
                fact_key="basic.weight",
                category="basic",
                value={"weight_kg": 70},
            ),
        )
        source_row = UserIndicatorValue(
            user_id=1,
            indicator_name="体重",
            value=72,
            unit="kg",
            measured_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            source="apple_health",
            source_metric="bodyWeight",
            source_id="weight-sample-1",
            value_kind="numeric",
        )
        db.add(source_row)
        db.flush()
        first = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )
        candidate = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.review_status == "conflict"
            )
        )
        assert first is not None
        assert candidate is not None
        assert db.scalar(select(HealthProfileFact)).value_data["value"] == {"weight_kg": 70}
        assert db.scalar(select(func.count()).select_from(HealthProfileDeviceSourceLink)) == 1

        source_row.value = 73
        second = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )
        observations = list(
            db.scalars(
                select(TrustedDeviceProfileObservation).order_by(
                    TrustedDeviceProfileObservation.version
                )
            )
        )
        assert second.id != first.id
        assert [item.status for item in observations] == ["superseded", "active"]
        assert [float(item.value_numeric) for item in observations] == [72.0, 73.0]
        assert candidate.review_status == "superseded"

        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="weight-manual-update",
                fact_key="basic.weight",
                category="basic",
                value={"weight_kg": 71},
                expected_version=1,
            ),
        )
        current_candidate = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.review_status == "conflict"
            )
        )
        current_fact = db.scalar(select(HealthProfileFact))
        assert current_fact.value_data["value"] == {"weight_kg": 71}
        assert current_candidate.conflict_with_fact_id == current_fact.id


def test_unconfirmed_or_conflicting_device_observation_never_reaches_any_ai_consumer(
    factory,
):
    with factory() as db:
        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="confirmed-weight-before-device-conflict",
                fact_key="basic.weight",
                category="basic",
                value={"weight_kg": 70},
            ),
        )
        source_row = UserIndicatorValue(
            user_id=1,
            indicator_name="体重",
            value=99,
            unit="kg",
            measured_at=datetime(2026, 7, 15, 8, tzinfo=timezone.utc),
            source="apple_health",
            source_metric="bodyWeight",
            source_id="unconfirmed-conflicting-weight",
            value_kind="numeric",
        )
        db.add(source_row)
        db.flush()
        observation = sync_device_profile_observation(
            db,
            user_id=1,
            source="apple_health",
            indicator_value=source_row,
        )
        assert observation is not None
        candidate = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.fact_key == "basic.weight",
                HealthProfileCandidate.review_status == "conflict",
            )
        )
        assert candidate is not None

        for consumer in DECLARED_TRUSTED_HEALTH_CONSUMERS:
            context = build_trusted_health_context(db, user_id=1, consumer=consumer)
            assert context.get("device_observations", []) == []

        review_candidate(
            db,
            candidate_id=candidate.id,
            user_id=1,
            payload=HealthProfileCandidateReviewIn(
                subject_user_id=1,
                client_event_id="accept-conflicting-device-weight",
                candidate_version=candidate.version,
                action="accept",
            ),
        )
        admitted = build_trusted_health_context(
            db, user_id=1, consumer="chat_question"
        )["device_observations"]
        assert [item["observation_id"] for item in admitted] == [observation.id]


def test_device_source_content_reversion_creates_new_active_version(factory):
    with factory() as db:
        source_row = UserIndicatorValue(
            user_id=1,
            indicator_name="体重",
            value=72,
            unit="kg",
            measured_at=datetime(2026, 7, 15, 9, tzinfo=timezone.utc),
            source="apple_health",
            source_metric="bodyWeight",
            source_id="reverting-weight-sample",
            value_kind="numeric",
        )
        db.add(source_row)
        db.flush()
        first = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )
        source_row.value = 73
        second = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )
        source_row.value = 72
        third = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )
        replay = sync_device_profile_observation(
            db, user_id=1, source="apple_health", indicator_value=source_row
        )

        assert first is not None and second is not None and third is not None
        assert third.id != first.id
        assert replay.id == third.id
        rows = list(
            db.scalars(
                select(TrustedDeviceProfileObservation).order_by(
                    TrustedDeviceProfileObservation.version
                )
            )
        )
        assert [row.version for row in rows] == [1, 2, 3]
        assert [float(row.value_numeric) for row in rows] == [72.0, 73.0, 72.0]
        assert [row.status for row in rows] == ["superseded", "superseded", "active"]
        assert [row.active_slot for row in rows] == [None, None, 1]
        assert sum(row.status == "active" for row in rows) == 1


def test_profile_primary_action_and_source_count_are_server_authoritative(factory):
    with factory() as db:
        fact = HealthProfileFact(
            user_id=1,
            subject_user_id=1,
            fact_key="medication.long_term_summary",
            category="medication",
            value_data={"response_state": "value", "value": {"items": []}},
            is_safety_critical=False,
            confirmation_method="user",
            status="active",
            version=1,
            confirmed_by_user_id=1,
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(fact)
        db.flush()
        for suffix in ("v1", "v2"):
            db.add(
                HealthProfileSource(
                    user_id=1,
                    subject_user_id=1,
                    fact_id=fact.id,
                    candidate_id=None,
                    source_type="medication",
                    source_ref=f"trusted-medication-plan:7:{suffix}",
                    source_snapshot={},
                    idempotency_key=f"source-{suffix}",
                )
            )
        db.add(
            HealthProfileCandidate(
                user_id=1,
                subject_user_id=1,
                fact_key="basic.height",
                category="basic",
                proposed_value={"response_state": "value", "value": "170 cm"},
                is_safety_critical=False,
                review_status="pending_review",
                idempotency_key="pending-height",
                version=1,
            )
        )
        db.flush()
        profile = build_profile(db, user_id=1, subject_user_id=1)
        assert profile["overview"]["independent_source_count"] == 1
        assert profile["overview"]["primary_action"]["kind"] == "review_updates"
        assert profile["overview"]["primary_action"]["item_count"] == 1
        assert profile["profile_status"] == "needs_attention"


def test_profile_supports_multiple_user_created_goals_without_ai_auto_creation(factory):
    with factory() as db:
        plan = HealthPlan(
            user_id=1,
            title="七天稳糖计划",
            goal="稳定餐后血糖",
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 21),
            status="active",
            created_by="questionnaire",
        )
        db.add(plan)
        db.flush()
        db.add_all(
            [
                PlanTask(
                    user_id=1,
                    plan_id=plan.id,
                    date=date(2026, 7, 15),
                    task_type="diet",
                    title="记录早餐",
                    status="completed",
                    source_type="plan",
                    source_ref=f"plan:{plan.id}:breakfast",
                ),
                PlanTask(
                    user_id=1,
                    plan_id=plan.id,
                    date=date(2026, 7, 15),
                    task_type="exercise",
                    title="餐后散步",
                    status="pending",
                    source_type="plan",
                    source_ref=f"plan:{plan.id}:walk",
                ),
            ]
        )
        first = create_profile_goal(
            db,
            user_id=1,
            payload=HealthProfileGoalCreateIn(
                subject_user_id=1,
                client_event_id="goal-create-1",
                name="改善睡眠",
                started_on=date(2026, 7, 15),
                metrics=[HealthProfileGoalMetricIn(metric_key="sleep.duration")],
            ),
        )
        create_profile_goal(
            db,
            user_id=1,
            payload=HealthProfileGoalCreateIn(
                subject_user_id=1,
                client_event_id="goal-create-2",
                name="增加步数",
                started_on=date(2026, 7, 16),
                metrics=[HealthProfileGoalMetricIn(metric_key="activity.steps")],
            ),
        )
        update_profile_goal(
            db,
            goal_id=first.id,
            user_id=1,
            payload=HealthProfileGoalUpdateIn(
                subject_user_id=1,
                client_event_id="goal-update-1",
                expected_version=1,
                name="稳定改善睡眠",
            ),
        )
        update_profile_goal_status(
            db,
            goal_id=first.id,
            user_id=1,
            payload=HealthProfileGoalStatusIn(
                subject_user_id=1,
                client_event_id="goal-pause-1",
                expected_version=2,
                action="pause",
            ),
        )
        history = list_goal_revisions(
            db,
            goal_id=first.id,
            user_id=1,
            subject_user_id=1,
            after_revision_id=None,
            limit=20,
        )
        assert [item["target_version"] for item in history["items"]] == [1, 2, 3]
        assert db.scalar(select(func.count()).select_from(HealthProfileGoal)) == 2

        suggestion = HealthProfileCandidate(
            user_id=1,
            subject_user_id=1,
            fact_key="goal.suggested",
            category="goal",
            proposed_value={"response_state": "value", "value": "AI suggestion"},
            is_safety_critical=False,
            review_status="pending_review",
            idempotency_key="ai-goal-suggestion",
            version=1,
        )
        db.add(suggestion)
        db.flush()
        with pytest.raises(HTTPException) as denied:
            review_candidate(
                db,
                candidate_id=suggestion.id,
                user_id=1,
                payload=HealthProfileCandidateReviewIn(
                    subject_user_id=1,
                    client_event_id="accept-ai-goal",
                    candidate_version=1,
                    action="accept",
                ),
            )
        assert denied.value.status_code == 409
        assert db.scalar(select(func.count()).select_from(HealthProfileGoal)) == 2

        profile = build_profile(db, user_id=1, subject_user_id=1)
        assert profile["management_plans"] == [
            {
                "plan_id": plan.id,
                "title": "七天稳糖计划",
                "goal": "稳定餐后血糖",
                "start_date": date(2026, 7, 15),
                "end_date": date(2026, 7, 21),
                "status": "active",
                "created_by": "questionnaire",
                "updated_at": plan.updated_at,
                "task_count": 2,
                "completed_task_count": 1,
            }
        ]
        assert len(profile["goals"]) == 2
        validated = HealthProfileOut.model_validate(profile)
        assert validated.management_plans[0].task_count == 2
        assert validated.management_plans[0].completed_task_count == 1
        assert build_profile(db, user_id=1, subject_user_id=2)["management_plans"] == []


def test_confirmed_long_term_medication_summary_exposes_exact_required_fields_only(factory):
    with factory() as db:
        confirm_plan(
            db,
            user_id=1,
            payload=MedicationPlanConfirmIn(
                subject_user_id=1,
                client_request_id="med-summary-request",
                client_event_id="med-summary-confirm",
                generic_name="阿司匹林",
                brand_name="拜阿司匹灵",
                purpose="二级预防",
                strength="100mg",
                dose_text="每次一片",
                frequency="每日一次",
                schedule_times=["08:00"],
                course_start=date(2026, 1, 1),
                is_long_term=True,
                source_type="manual",
            ),
        )
        items = list_confirmed_long_term_medication_summaries(
            db, user_id=1, subject_user_id=1
        )
        assert len(items) == 1
        assert set(items[0]) == {
            "medication_name",
            "purpose",
            "started_on",
            "is_still_taking",
            "source",
            "last_confirmed_at",
        }
        assert items[0]["source"] == "user_added"
        assert "dose_text" not in items[0]


def test_completed_last_long_term_medication_clears_profile_fact_before_ai_context(factory):
    with factory() as db:
        plan, fact = _confirm_and_accept_long_term_medication(
            db,
            event_prefix="complete-last-medication",
            name="药物A",
        )
        assert fact.value_data["items"][0]["is_still_taking"] is True
        before_context = build_trusted_health_context(
            db, user_id=1, consumer="chat_question"
        )
        assert any(
            item["fact_key"] == "medication.long_term_summary"
            for item in before_context["profile_facts"]
        )

        update_plan_status(
            db,
            plan_id=plan.id,
            user_id=1,
            payload=MedicationPlanStatusIn(
                subject_user_id=1,
                client_event_id="complete-last-medication-status",
                expected_version=plan.version,
                action="complete",
            ),
        )
        replacement = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.fact_key == "medication.long_term_summary",
                HealthProfileCandidate.review_status == "conflict",
            )
        )
        assert replacement is not None
        assert replacement.proposed_value["items"] == []

        for consumer in DECLARED_TRUSTED_HEALTH_CONSUMERS:
            context = build_trusted_health_context(db, user_id=1, consumer=consumer)
            assert all(
                item["fact_key"] != "medication.long_term_summary"
                for item in context["profile_facts"]
            )
            assert all(
                item.get("status") != "active"
                for item in context.get("medications", [])
            )
        review_candidate(
            db,
            candidate_id=replacement.id,
            user_id=1,
            payload=HealthProfileCandidateReviewIn(
                subject_user_id=1,
                client_event_id="reject-empty-medication-profile-replacement",
                candidate_version=replacement.version,
                action="reject",
            ),
        )
        rejected_context = build_trusted_health_context(
            db, user_id=1, consumer="chat_question"
        )
        assert all(
            item["fact_key"] != "medication.long_term_summary"
            for item in rejected_context["profile_facts"]
        )


@pytest.mark.parametrize("action", ["pause", "retract"])
def test_paused_or_retracted_medication_updates_profile_fact_atomically(factory, action):
    with factory() as db:
        plan, _fact = _confirm_and_accept_long_term_medication(
            db,
            event_prefix=f"{action}-last-medication",
            name="药物A",
        )
        update_plan_status(
            db,
            plan_id=plan.id,
            user_id=1,
            payload=MedicationPlanStatusIn(
                subject_user_id=1,
                client_event_id=f"{action}-last-medication-status",
                expected_version=plan.version,
                action=action,
            ),
        )
        replacement = db.scalar(
            select(HealthProfileCandidate).where(
                HealthProfileCandidate.fact_key == "medication.long_term_summary",
                HealthProfileCandidate.review_status == "conflict",
            )
        )
        assert replacement is not None
        if action == "pause":
            assert replacement.proposed_value["items"][0]["is_still_taking"] is False
        else:
            assert replacement.proposed_value["items"] == []

        context = build_trusted_health_context(
            db, user_id=1, consumer="chat_question"
        )
        assert all(
            item["fact_key"] != "medication.long_term_summary"
            for item in context["profile_facts"]
        )
        assert all(
            item.get("status") != "active" for item in context["medications"]
        )


def test_current_fact_source_membership_excludes_retired_medication_plans(factory):
    with factory() as db:
        first_plan, fact = _confirm_and_accept_long_term_medication(
            db,
            event_prefix="source-plan-a",
            name="药物A",
        )
        update_plan_status(
            db,
            plan_id=first_plan.id,
            user_id=1,
            payload=MedicationPlanStatusIn(
                subject_user_id=1,
                client_event_id="source-plan-a-complete",
                expected_version=first_plan.version,
                action="complete",
            ),
        )
        second_plan = confirm_plan(
            db,
            user_id=1,
            payload=MedicationPlanConfirmIn(
                subject_user_id=1,
                client_request_id="source-plan-b-request",
                client_event_id="source-plan-b-confirm",
                generic_name="药物B",
                purpose="回归测试",
                frequency="每日一次",
                schedule_times=["08:00"],
                course_start=date(2026, 2, 1),
                is_long_term=True,
                source_type="manual",
            ),
        )
        candidate = db.scalar(
            select(HealthProfileCandidate)
            .where(
                HealthProfileCandidate.fact_key == "medication.long_term_summary",
                HealthProfileCandidate.review_status == "conflict",
            )
            .order_by(HealthProfileCandidate.id.desc())
        )
        assert candidate is not None
        assert [item["medication_name"] for item in candidate.proposed_value["items"]] == [
            "药物B"
        ]
        review_candidate(
            db,
            candidate_id=candidate.id,
            user_id=1,
            payload=HealthProfileCandidateReviewIn(
                subject_user_id=1,
                client_event_id="source-plan-b-accept-profile",
                candidate_version=candidate.version,
                action="accept",
            ),
        )
        db.refresh(fact)
        current_sources = list(
            db.scalars(
                select(HealthProfileFactSourceVersion).where(
                    HealthProfileFactSourceVersion.fact_id == fact.id,
                    HealthProfileFactSourceVersion.fact_version == fact.version,
                )
            )
        )
        assert [row.source_identity for row in current_sources] == [
            f"trusted-medication-plan:{second_plan.id}"
        ]
        assert all(
            f"trusted-medication-plan:{first_plan.id}" != row.source_identity
            for row in current_sources
        )
        profile = build_profile(db, user_id=1, subject_user_id=1)
        assert profile["overview"]["independent_source_count"] == 1


def test_legacy_medication_payload_redacts_all_dose_schedule_reminder_aliases():
    sanitized = sanitize_medication_payload(
        {
            "response_state": "value",
            "kind": "confirmed_long_term_medication_summary",
            "items": [
                {
                    "medication_name": "药物A",
                    "purpose": "回归测试",
                    "started_on": "2026-01-01",
                    "is_still_taking": True,
                    "source": "user_added",
                    "last_confirmed_at": "2026-07-15T00:00:00Z",
                    "dose": "100 mg",
                    "dosage": "每日一片",
                    "schedule": "daily",
                    "schedule_times": ["08:00"],
                    "reminder_time": "07:55",
                    "private_extension": {"dose": "must-not-escape"},
                }
            ],
            "dose": "top-level-must-not-escape",
            "unknown_extension": {"reminder_time": "must-not-escape"},
        }
    )
    assert set(sanitized) == {"response_state", "kind", "items"}
    assert set(sanitized["items"][0]) == {
        "medication_name",
        "purpose",
        "started_on",
        "is_still_taking",
        "source",
        "last_confirmed_at",
    }
    rendered = str(sanitized)
    for secret in (
        "100 mg",
        "每日一片",
        "daily",
        "08:00",
        "07:55",
        "must-not-escape",
        "top-level-must-not-escape",
    ):
        assert secret not in rendered


def test_every_declared_profile_consumer_rejects_unconfirmed_candidates(factory):
    with factory() as db:
        upsert_manual_fact(
            db,
            user_id=1,
            payload=_fact_payload(
                event_id="confirmed-lifestyle",
                fact_key="basic.lifestyle",
                category="basic",
                value="regular exercise",
            ),
        )
        db.add_all(
            [
                HealthProfileCandidate(
                    user_id=1,
                    subject_user_id=1,
                    fact_key="long_term_health.unconfirmed",
                    category="long_term_health",
                    proposed_value={"sentinel": "UNCONFIRMED_SENTINEL"},
                    is_safety_critical=False,
                    review_status="pending_review",
                    idempotency_key="unconfirmed-context-candidate",
                    version=1,
                ),
                HealthProfileFact(
                    user_id=1,
                    subject_user_id=1,
                    fact_key="long_term_health.automatic",
                    category="long_term_health",
                    value_data={"response_state": "value", "value": "AUTOMATIC_SENTINEL"},
                    is_safety_critical=False,
                    confirmation_method="automatic",
                    status="active",
                    version=1,
                ),
            ]
        )
        db.flush()
        for consumer in DECLARED_TRUSTED_HEALTH_CONSUMERS:
            context = build_trusted_health_context(db, user_id=1, consumer=consumer)
            rendered = str(context)
            assert "UNCONFIRMED_SENTINEL" not in rendered
            assert "AUTOMATIC_SENTINEL" not in rendered
            assert "candidates" not in context
        for denied_consumer in ("x_age", "unknown", ""):
            with pytest.raises(TrustedHealthContextAccessError):
                build_trusted_health_context(
                    db, user_id=1, consumer=denied_consumer
                )
