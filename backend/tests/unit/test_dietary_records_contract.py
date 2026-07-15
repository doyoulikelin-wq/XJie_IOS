"""Regression coverage for the trusted dietary-records vertical slice.

The legacy ``/api/meals`` contract remains available for older clients, but it
is not a trusted source for the dietary diary.  Every new input must remain a
draft until the authenticated user explicitly confirms it.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import copy
from datetime import date, datetime, timezone
import hashlib
import importlib
import inspect
import io
import json
from pathlib import Path

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
from app.models.meal import Meal
from app.models.user import User
from deploy import production_deploy_guard as deploy_guard


DIETARY_TABLES = {
    "dietary_drafts",
    "dietary_records",
    "dietary_record_events",
    "dietary_days",
    "dietary_daily_summaries",
    "dietary_recognition_cache",
}


def _candidate_manifest() -> dict:
    backend_root = Path(__file__).resolve().parents[2]
    probe = deploy_guard.MIGRATION_PROBE_SOURCE.replace(
        'APPLICATION_ROOT = Path("/app")',
        f"APPLICATION_ROOT = Path({str(backend_root)!r})",
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(
            compile(probe, "candidate_dietary_migration_probe.py", "exec"),
            {"__name__": "__main__"},
        )
    return json.loads(output.getvalue())


def _old_0024_manifest(candidate: dict) -> dict:
    old = copy.deepcopy(candidate)
    old["migrations"] = old["migrations"][:-1]
    old["heads"] = [old["migrations"][-1]["revision"]]
    old["model_schema"] = [
        table for table in old["model_schema"] if table["name"] not in DIETARY_TABLES
    ]
    return old


def _contract_modules():
    models = importlib.import_module("app.models.dietary_records")
    router = importlib.import_module("app.routers.dietary_records")
    service = importlib.import_module("app.services.dietary_records_service")
    migration = importlib.import_module(
        "app.db.migrations.versions.0025_dietary_records"
    )
    return models, router, service, migration


def _client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, sessionmaker, dict[str, str], dict[str, str]]:
    _models, router, _service, _migration = _contract_modules()
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
                User(id=1, phone="18800000701", username="diet-owner", password="x"),
                User(id=2, phone="18800000702", username="diet-other", password="x"),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(router.router, prefix="/api/dietary-records")

    def override_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return (
        TestClient(app, raise_server_exceptions=False),
        factory,
        {"Authorization": f"Bearer {create_access_token('1')}"},
        {"Authorization": f"Bearer {create_access_token('2')}"},
    )


def _draft_payload(
    *,
    event_id: str,
    eaten_at: str = "2026-07-15T12:00:00+08:00",
    diet_date: str | None = "2026-07-15",
    meal_type: str = "lunch",
    source_type: str = "text",
) -> dict:
    payload = {
        "client_event_id": event_id,
        "source_type": source_type,
        "timezone": "Asia/Shanghai",
        "meal_type": meal_type,
        "eaten_at": eaten_at,
        "raw_input": "米饭、青菜和鸡蛋",
        "food_items": [
            {
                "item_id": "manual-item-rice",
                "name": "米饭",
                "portion_text": "一碗",
                "categories": ["staple"],
                "confidence": 0.86,
                "is_estimated": True,
            },
            {
                "name": "青菜",
                "portion_text": "一份",
                "categories": ["vegetables"],
            },
            {
                "name": "鸡蛋",
                "portion_text": "一个",
                "categories": ["protein"],
            },
        ],
        "portion_text": "正常份量",
        "structure": {
            "protein": "present",
            "vegetables": "present",
            "staple": "present",
        },
        "estimated_nutrition": {"energy_kcal_range": [450, 650]},
        "field_confidences": {"meal_type": 0.92, "food_items": 0.86},
        "recognition_confidence": 0.86,
    }
    if diet_date is not None:
        payload["diet_date"] = diet_date
    return payload


def _create_draft(
    client: TestClient,
    headers: dict[str, str],
    *,
    event_id: str,
    **overrides,
) -> dict:
    payload = _draft_payload(event_id=event_id)
    payload.update(overrides)
    response = client.post("/api/dietary-records/drafts", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _confirm_draft(
    client: TestClient,
    headers: dict[str, str],
    draft: dict,
    *,
    event_id: str,
    **overrides,
) -> dict:
    payload = {
        "client_event_id": event_id,
        "expected_version": draft["version"],
        "timezone": "Asia/Shanghai",
        "diet_date": draft["diet_date"],
        "meal_type": draft["meal_type"],
        "eaten_at": draft["eaten_at"],
        "food_items": draft["food_items"],
        "portion_text": draft["portion_text"],
        "structure": draft["structure"],
        "estimated_nutrition": draft["estimated_nutrition"],
        "field_confidences": draft["field_confidences"],
        "recognition_confidence": draft["recognition_confidence"],
    }
    payload.update(overrides)
    response = client.post(
        f"/api/dietary-records/drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_0025_migration_is_additive_and_models_enforce_tenant_confirmation_and_summary_version(
    monkeypatch: pytest.MonkeyPatch,
):
    models, _router, service, migration = _contract_modules()
    _client_instance, factory, _headers, _other_headers = _client(monkeypatch)
    source = inspect.getsource(migration.upgrade)
    assert migration.revision == "0025_dietary_records"
    assert migration.down_revision == "0024_health_profile_report_completion"
    assert "alter_column" not in source
    assert "drop_table" not in source
    assert "execute(" not in source
    assert source.count("op.create_table(") == 6
    expected_server_defaults = {
        "dietary_drafts": {
            "recognition_status": "not_required",
            "input_snapshot": "'{}'",
            "food_items": "'[]'",
            "structure": "'{}'",
            "estimated_nutrition": "'{}'",
            "field_confidences": "'{}'",
            "status": "pending_confirmation",
            "version": "1",
            "created_at": "now()",
            "updated_at": "now()",
        },
        "dietary_records": {
            "source_snapshot": "'{}'",
            "food_items": "'[]'",
            "structure": "'{}'",
            "estimated_nutrition": "'{}'",
            "field_confidences": "'{}'",
            "status": "user_confirmed",
            "version": "1",
            "created_at": "now()",
            "updated_at": "now()",
        },
        "dietary_record_events": {
            "before_snapshot": "'{}'",
            "after_snapshot": "'{}'",
            "created_at": "now()",
        },
        "dietary_days": {
            "state": "open",
            "record_version": "0",
            "exclude_pending_on_close": "false",
            "record_complete": "false",
            "confirmed_meal_count": "0",
            "pending_count": "0",
            "structure_summary": "'{}'",
            "created_at": "now()",
            "updated_at": "now()",
        },
        "dietary_daily_summaries": {
            "structure_summary": "'{}'",
            "evidence": "'{}'",
            "recalculated_after_edit": "false",
        },
        "dietary_recognition_cache": {
            "result_snapshot": "'{}'",
            "created_at": "now()",
            "last_used_at": "now()",
        },
    }
    observed_server_defaults = {
        table_name: {
            column.name: str(column.server_default.arg)
            for column in Base.metadata.tables[table_name].columns
            if column.server_default is not None
        }
        for table_name in sorted(DIETARY_TABLES)
    }
    assert observed_server_defaults == expected_server_defaults
    assert source.count("server_default=") == sum(
        len(defaults) for defaults in expected_server_defaults.values()
    )
    recognition_status = models.DietaryDraft.__table__.c.recognition_status
    assert recognition_status.type.length == 40
    assert '"recognition_status",\n            sa.String(length=40),' in source
    supported_recognition_statuses = {
        "not_required",
        "recognition_pending",
        "recognition_incomplete",
        "failed_manual_entry_available",
        "completed",
        "reused_user_confirmed_record",
    }
    assert max(map(len, supported_recognition_statuses)) == 29
    assert all(
        len(status) <= recognition_status.type.length
        for status in supported_recognition_statuses
    )

    record_table = models.DietaryRecord.__table__
    draft_table = models.DietaryDraft.__table__
    event_table = models.DietaryRecordEvent.__table__
    summary_table = models.DietaryDailySummary.__table__
    draft_scope_constraint = next(
        constraint
        for constraint in draft_table.constraints
        if constraint.name == "uq_dietary_draft_tenant_scope_event"
    )
    assert [column.name for column in draft_scope_constraint.columns] == [
        "user_id",
        "subject_user_id",
        "event_scope",
        "client_event_id",
    ]
    event_scope_constraint = next(
        constraint
        for constraint in event_table.constraints
        if constraint.name == "uq_dietary_record_event_tenant_type_event"
    )
    assert [column.name for column in event_scope_constraint.columns] == [
        "user_id",
        "subject_user_id",
        "event_type",
        "client_event_id",
    ]
    assert {constraint.name for constraint in record_table.constraints} >= {
        "uq_dietary_record_tenant_id",
        "uq_dietary_record_tenant_confirm_event",
        "ck_dietary_record_user_confirmed",
    }
    assert {constraint.name for constraint in summary_table.constraints} >= {
        "uq_dietary_summary_tenant_date_version",
    }

    # Every client mutation shares the same transaction-scoped event lock. The
    # tenant-bound signed key is stable, and PostgreSQL executes the lock before
    # any operation-scoped replay check, provider call, or versioned row
    # mutation. Receipts are tenant + endpoint + event identities; the shared
    # lock is stronger serialization rather than a cross-endpoint global receipt.
    owner_key = service._dietary_client_event_lock_key(
        user_id=1,
        subject_user_id=1,
        client_event_id="concurrent-event",
    )
    assert owner_key == service._dietary_client_event_lock_key(
        user_id=1,
        subject_user_id=1,
        client_event_id="concurrent-event",
    )
    assert -(2**63) <= owner_key < 2**63
    assert owner_key != service._dietary_client_event_lock_key(
        user_id=2,
        subject_user_id=2,
        client_event_id="concurrent-event",
    )

    class RecordingPostgresSession:
        def __init__(self):
            self.calls = []

        def get_bind(self):
            return type(
                "PostgresBind",
                (),
                {"dialect": type("Dialect", (), {"name": "postgresql"})()},
            )()

        def execute(self, statement, parameters):
            self.calls.append((str(statement), parameters))

    lock_session = RecordingPostgresSession()
    service._lock_dietary_client_event(
        lock_session,
        user_id=1,
        subject_user_id=1,
        client_event_id="concurrent-event",
    )
    assert lock_session.calls == [
        ("SELECT pg_advisory_xact_lock(:lock_key)", {"lock_key": owner_key})
    ]
    create_source = inspect.getsource(service.create_draft)
    photo_source = inspect.getsource(service.create_photo_draft)
    assert (
        create_source.index("_lock_dietary_client_event(")
        < create_source.index("existing = db.scalar(")
        < create_source.index("recognized = recognition_hook(payload)")
    )
    assert (
        photo_source.index("_lock_dietary_client_event(")
        < photo_source.index("existing = db.scalar(")
        < photo_source.index("_recognize_dietary_image(")
    )
    for mutation in (
        service.confirm_draft,
        service.update_record,
        service.delete_record,
        service.reuse_record,
        service.retry_photo_draft_recognition,
    ):
        mutation_source = inspect.getsource(mutation)
        assert "_lock_dietary_client_event(" in mutation_source
    assert ".with_for_update()" in inspect.getsource(service.confirm_draft)
    assert ".with_for_update()" in inspect.getsource(
        service.retry_photo_draft_recognition
    )
    assert ".with_for_update()" in inspect.getsource(service._scoped_record)
    for mutation in (
        service.update_record,
        service.delete_record,
        service.reuse_record,
    ):
        assert "for_update=True" in inspect.getsource(mutation)
        assert inspect.getsource(mutation).count("_event_replay(") == 2

    candidate = _candidate_manifest()
    old = _old_0024_manifest(candidate)
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "db"
        / "migrations"
        / "versions"
        / "0025_dietary_records.py"
    )
    plan = deploy_guard.validate_expand_migration_source(
        migration_path.read_bytes(), old, candidate
    )
    assert plan["old_head"] == "0024_health_profile_report_completion"
    assert plan["candidate_head"] == "0025_dietary_records"
    assert [item["op"] for item in plan["operations"]].count("create_table") == 6

    with factory() as db:
        draft = models.DietaryDraft(
            user_id=1,
            subject_user_id=1,
            client_event_id="tenant-draft",
            request_fingerprint="a" * 64,
            source_type="text",
            timezone="Asia/Shanghai",
            diet_date=date(2026, 7, 15),
            meal_type="lunch",
            eaten_at=datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc),
            input_snapshot={},
            food_items=[],
            structure={},
            estimated_nutrition={},
            field_confidences={},
            status="pending_confirmation",
            version=1,
        )
        db.add(draft)
        db.commit()
        db.add(
            models.DietaryRecord(
                source_draft_id=draft.id,
                user_id=2,
                subject_user_id=2,
                confirmation_client_event_id="cross-tenant-confirm",
                confirmation_request_fingerprint="b" * 64,
                diet_date=date(2026, 7, 15),
                timezone="Asia/Shanghai",
                meal_type="lunch",
                eaten_at=datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc),
                source_type="text",
                source_ref="draft:cross-tenant",
                source_snapshot={},
                food_items=[],
                structure={},
                estimated_nutrition={},
                field_confidences={},
                confidence=0.8,
                status="user_confirmed",
                version=1,
                confirmed_by_user_id=2,
                confirmed_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_unconfirmed_draft_never_creates_formal_record_and_subject_defaults_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
):
    models, _router, _service, _migration = _contract_modules()
    client, factory, headers, _other_headers = _client(monkeypatch)
    draft = _create_draft(client, headers, event_id="draft-only-1")
    assert draft["subject_user_id"] == 1
    assert draft["status"] == "pending_confirmation"
    assert draft["requires_user_confirmation"] is True
    assert draft["formal_record_created"] is False

    replay = client.post(
        "/api/dietary-records/drafts",
        headers=headers,
        json=_draft_payload(event_id="draft-only-1"),
    )
    assert replay.status_code == 200
    assert replay.json() == draft
    changed_replay = client.post(
        "/api/dietary-records/drafts",
        headers=headers,
        json={**_draft_payload(event_id="draft-only-1"), "raw_input": "不同内容"},
    )
    cross_subject = client.post(
        "/api/dietary-records/drafts",
        headers=headers,
        json={**_draft_payload(event_id="cross-subject"), "subject_user_id": 2},
    )
    assert changed_replay.status_code == 409
    assert cross_subject.status_code == 403

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(models.DietaryDraft)) == 1
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 0
        assert db.scalar(select(func.count()).select_from(Meal)) == 0

    from app.main import create_app

    paths = {route.path for route in create_app().routes}
    assert "/api/meals" in paths
    assert "/api/dietary-records/drafts" in paths

    # DR-06: text, voice, and chat inputs are extracted only after the
    # tenant/client-event replay check. The original evidence remains intact,
    # while every result is still a pending candidate until explicit confirm.
    from app.core.config import settings
    from app.providers.base import MealTextItem, MealTextResult
    from app.services import dietary_text_extraction

    provider_calls: list[str] = []

    class FixtureTextProvider:
        provider_name = "fixture"
        text_model = "fixture-meal-text-v1"

        def analyze_meal_text(self, raw_text: str) -> MealTextResult:
            provider_calls.append(raw_text)
            if raw_text == "识别服务暂时失败":
                raise RuntimeError("fixture provider unavailable")
            if raw_text == "低置信语音：可能是一碗粥":
                return MealTextResult(
                    items=[
                        MealTextItem(
                            name="粥",
                            portion_text="可能一碗",
                            categories=["staple"],
                            confidence=0.42,
                        )
                    ],
                    meal_type="breakfast",
                    structure={"staple": "present"},
                    estimated_nutrition={
                        "energy_kcal_range": [120, 260],
                        "is_estimate": True,
                    },
                    field_confidences={
                        "food_items": 0.42,
                        "portion_text": 0.31,
                        "meal_type": 0.38,
                        "structure": 0.45,
                        "estimated_nutrition": 0.34,
                    },
                    confidence=0.4,
                    recognized=True,
                )
            if raw_text == "问答同步：夜宵吃了一个苹果":
                return MealTextResult(
                    items=[
                        MealTextItem(
                            name="苹果",
                            portion_text="一个",
                            categories=["fruit"],
                            confidence=0.88,
                        )
                    ],
                    meal_type="snack",
                    structure={"fruit": "present"},
                    estimated_nutrition={
                        "energy_kcal_range": [60, 120],
                        "is_estimate": True,
                    },
                    field_confidences={"food_items": 0.88},
                    confidence=0.84,
                    recognized=True,
                )
            return MealTextResult(
                items=[
                    MealTextItem(
                        name="豆腐饭",
                        portion_text="一份",
                        categories=["protein", "staple", "moralized"],
                        confidence=0.91,
                    )
                ],
                meal_type="dinner",
                portion_text="大约一份",
                structure={"protein": "present", "staple": "present"},
                estimated_nutrition={
                    "energy_kcal": 480,
                    "energy_kcal_range": [620, 420],
                    "is_estimate": False,
                },
                field_confidences={
                    "food_items": 0.91,
                    "portion_text": 0.61,
                    "meal_type": 0.89,
                    "untrusted_field": 1.0,
                },
                confidence=0.9,
                recognized=True,
            )

    fixture_provider = FixtureTextProvider()
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(
        dietary_text_extraction, "get_provider", lambda: fixture_provider
    )
    long_text = ("晚餐吃了豆腐饭；" + "这是需要完整保留的补充说明。" * 400)[:4000]
    text_payload = {
        **_draft_payload(event_id="text-extraction-long", source_type="text"),
        "meal_type": "lunch",
        "raw_input": long_text,
        "food_items": [],
        "portion_text": None,
        "structure": {},
        "estimated_nutrition": {},
        "field_confidences": {},
        "recognition_confidence": None,
    }
    text_response = client.post(
        "/api/dietary-records/drafts", headers=headers, json=text_payload
    )
    assert text_response.status_code == 200, text_response.text
    text_draft = text_response.json()
    assert provider_calls == [long_text]
    assert text_draft["meal_type"] == "dinner"
    assert text_draft["food_items"] == [
        {
            "item_id": "text-item-1",
            "name": "豆腐饭",
            "portion_text": "一份",
            "categories": ["protein", "staple"],
            "confidence": 0.91,
            "is_estimated": True,
        }
    ]
    assert text_draft["portion_text"] == "大约一份"
    assert text_draft["structure"] == {
        "is_estimate": True,
        "protein": "present",
        "staple": "present",
        "category_counts": {"protein": 1, "staple": 1},
    }
    assert text_draft["estimated_nutrition"] == {
        "is_estimate": True,
        "energy_kcal_range": [420.0, 620.0],
    }
    assert "energy_kcal" not in text_draft["estimated_nutrition"]
    assert text_draft["field_confidences"] == {
        "food_items": 0.91,
        "portion_text": 0.61,
        "meal_type": 0.89,
        "structure": 0.9,
        "estimated_nutrition": 0.9,
    }
    assert text_draft["low_confidence_fields"] == ["portion_text"]
    assert text_draft["recognition_status"] == "completed"
    assert text_draft["formal_record_created"] is False

    text_replay = client.post(
        "/api/dietary-records/drafts", headers=headers, json=text_payload
    )
    assert text_replay.status_code == 200
    assert text_replay.json() == text_draft
    assert provider_calls == [long_text]

    voice_draft = _create_draft(
        client,
        headers,
        event_id="voice-extraction-low-confidence",
        source_type="voice",
        raw_input="低置信语音：可能是一碗粥",
        food_items=[],
        portion_text=None,
        structure={},
        estimated_nutrition={},
        field_confidences={},
        recognition_confidence=None,
    )
    assert voice_draft["meal_type"] == "breakfast"
    assert voice_draft["recognition_status"] == "completed"
    assert set(voice_draft["low_confidence_fields"]) == {
        "estimated_nutrition",
        "food_items",
        "meal_type",
        "portion_text",
        "structure",
    }

    chat_draft = _create_draft(
        client,
        headers,
        event_id="chat-extraction-candidate",
        source_type="chat",
        raw_input="问答同步：夜宵吃了一个苹果",
        food_items=[],
        portion_text=None,
        structure={},
        estimated_nutrition={},
        field_confidences={},
        recognition_confidence=None,
    )
    assert chat_draft["meal_type"] == "snack"
    assert chat_draft["food_items"][0]["name"] == "苹果"
    assert chat_draft["formal_record_created"] is False

    failed_draft = _create_draft(
        client,
        headers,
        event_id="text-extraction-provider-failure",
        source_type="text",
        raw_input="识别服务暂时失败",
        food_items=[],
        portion_text=None,
        structure={},
        estimated_nutrition={},
        field_confidences={},
        recognition_confidence=None,
    )
    assert failed_draft["recognition_status"] == "failed_manual_entry_available"
    assert failed_draft["food_items"] == []
    assert failed_draft["formal_record_created"] is False

    calls_before_non_recognition_sources = len(provider_calls)
    for source_type in ("manual", "recent"):
        ignored = _create_draft(
            client,
            headers,
            event_id=f"{source_type}-never-auto-extract",
            source_type=source_type,
            raw_input="即使有原文也不得调用识别器",
            food_items=[],
            portion_text=None,
            structure={},
            estimated_nutrition={},
            field_confidences={},
            recognition_confidence=None,
        )
        assert ignored["recognition_status"] == "not_required"
        assert ignored["food_items"] == []
    assert len(provider_calls) == calls_before_non_recognition_sources

    class ForbiddenProductionMock:
        provider_name = "mock"
        text_model = "mock-text"

        def analyze_meal_text(self, _raw_text: str) -> MealTextResult:
            raise AssertionError("production must fail before invoking mock analysis")

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        dietary_text_extraction,
        "get_provider",
        lambda: ForbiddenProductionMock(),
    )
    production_mock = _create_draft(
        client,
        headers,
        event_id="production-mock-fails-closed",
        source_type="chat",
        raw_input="午餐吃了一碗面",
        food_items=[],
        portion_text=None,
        structure={},
        estimated_nutrition={},
        field_confidences={},
        recognition_confidence=None,
    )
    assert production_mock["recognition_status"] == ("failed_manual_entry_available")
    assert production_mock["food_items"] == []
    assert production_mock["formal_record_created"] is False

    with factory() as db:
        persisted_text = db.scalar(
            select(models.DietaryDraft).where(
                models.DietaryDraft.client_event_id == "text-extraction-long"
            )
        )
        persisted_failure = db.scalar(
            select(models.DietaryDraft).where(
                models.DietaryDraft.client_event_id
                == "text-extraction-provider-failure"
            )
        )
        assert persisted_text.raw_input == long_text
        assert persisted_text.recognition_version == "fixture:fixture-meal-text-v1"
        assert persisted_text.input_snapshot["raw_input_preserved"] is True
        assert persisted_failure.raw_input == "识别服务暂时失败"
        assert persisted_failure.input_snapshot["recognition_last_error"] == (
            "RuntimeError"
        )
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 0
        assert db.scalar(select(func.count()).select_from(Meal)) == 0


def test_explicit_confirmation_is_the_only_write_gate_and_replay_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
):
    models, _router, service, _migration = _contract_modules()
    client, factory, headers, _other_headers = _client(monkeypatch)
    draft = _create_draft(client, headers, event_id="confirm-gate-draft")
    record = _confirm_draft(client, headers, draft, event_id="confirm-gate-record")
    assert record["subject_user_id"] == 1
    assert record["status"] == "user_confirmed"
    assert record["trust_state"] == "user_confirmed"
    assert record["source_draft_id"] == draft["draft_id"]
    assert record["food_items"][0]["item_id"] == "manual-item-rice"
    assert record["food_items"][0]["confidence"] == 0.86
    assert record["food_items"][0]["is_estimated"] is True

    replay = _confirm_draft(client, headers, draft, event_id="confirm-gate-record")
    assert replay == record
    competing_confirmation = client.post(
        f"/api/dietary-records/drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json={
            "client_event_id": "confirm-gate-competing-event",
            "expected_version": draft["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": draft["diet_date"],
            "meal_type": draft["meal_type"],
            "eaten_at": draft["eaten_at"],
            "food_items": draft["food_items"],
            "portion_text": draft["portion_text"],
            "structure": draft["structure"],
            "estimated_nutrition": draft["estimated_nutrition"],
            "field_confidences": draft["field_confidences"],
            "recognition_confidence": draft["recognition_confidence"],
        },
    )
    assert competing_confirmation.status_code == 409
    conflicting = client.post(
        f"/api/dietary-records/drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json={
            "client_event_id": "confirm-gate-record",
            "expected_version": draft["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": draft["diet_date"],
            "meal_type": "dinner",
            "eaten_at": draft["eaten_at"],
            "food_items": draft["food_items"],
            "structure": draft["structure"],
            "estimated_nutrition": draft["estimated_nutrition"],
            "field_confidences": draft["field_confidences"],
        },
    )
    assert conflicting.status_code == 409

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 1
        stored_draft = db.get(models.DietaryDraft, draft["draft_id"])
        assert stored_draft.status == "confirmed"
        same_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 15),
            )
        )
        assert same_day.record_version == 2
        assert same_day.pending_count == 0
        assert same_day.confirmed_meal_count == 1

    old_lunch = _create_draft(
        client,
        headers,
        event_id="cross-date-old-lunch",
        diet_date="2026-07-13",
        meal_type="lunch",
        eaten_at="2026-07-13T12:00:00+08:00",
    )
    _confirm_draft(
        client,
        headers,
        old_lunch,
        event_id="cross-date-old-lunch-confirm",
    )
    moving_draft = _create_draft(
        client,
        headers,
        event_id="cross-date-moving-draft",
        diet_date="2026-07-13",
        meal_type="dinner",
        eaten_at="2026-07-13T19:00:00+08:00",
    )
    with factory() as db:
        waiting = service.complete_day(
            db,
            user_id=1,
            subject_user_id=1,
            diet_date=date(2026, 7, 13),
            timezone_name="Asia/Shanghai",
            method="automatic",
            client_event_id="cross-date-old-day-auto-close",
            complete_with_confirmed_only=False,
        )
        db.commit()
        assert waiting["state"] == "waiting_confirmation"
        assert waiting["pending_count"] == 1

    moved_record = _confirm_draft(
        client,
        headers,
        moving_draft,
        event_id="cross-date-moving-confirm",
        timezone="America/New_York",
        diet_date="2026-07-14",
        meal_type="dinner",
        eaten_at="2026-07-14T19:00:00-04:00",
    )
    assert moved_record["diet_date"] == "2026-07-14"
    assert moved_record["timezone"] == "America/New_York"

    with factory() as db:
        old_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 13),
            )
        )
        new_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 14),
            )
        )
        assert old_day.state == "incomplete"
        assert old_day.pending_count == 0
        assert old_day.timezone == "Asia/Shanghai"
        assert new_day.state == "open"
        assert new_day.confirmed_meal_count == 1
        assert new_day.timezone == "America/New_York"
        old_record_version = old_day.record_version
        new_record_version = new_day.record_version

    moved_replay = _confirm_draft(
        client,
        headers,
        moving_draft,
        event_id="cross-date-moving-confirm",
        timezone="America/New_York",
        diet_date="2026-07-14",
        meal_type="dinner",
        eaten_at="2026-07-14T19:00:00-04:00",
    )
    assert moved_replay == moved_record
    with factory() as db:
        old_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 13),
            )
        )
        new_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 14),
            )
        )
        assert old_day.record_version == old_record_version
        assert new_day.record_version == new_record_version
        assert (
            db.scalar(
                select(func.count())
                .select_from(models.DietaryRecord)
                .where(models.DietaryRecord.source_draft_id == moving_draft["draft_id"])
            )
            == 1
        )


def test_diet_day_uses_local_0400_boundary_and_explicit_confirmation_date_survives_timezone_change(
    monkeypatch: pytest.MonkeyPatch,
):
    _models, _router, service, _migration = _contract_modules()
    assert service.derive_diet_date(
        datetime.fromisoformat("2026-07-15T03:59:59+08:00"),
        "Asia/Shanghai",
    ) == date(2026, 7, 14)
    assert service.derive_diet_date(
        datetime.fromisoformat("2026-07-15T04:00:00+08:00"),
        "Asia/Shanghai",
    ) == date(2026, 7, 15)
    assert service.derive_diet_date(
        datetime.fromisoformat("2026-11-01T03:30:00-05:00"),
        "America/New_York",
    ) == date(2026, 10, 31)

    client, _factory, headers, _other_headers = _client(monkeypatch)
    inferred = _create_draft(
        client,
        headers,
        event_id="before-four-inferred",
        eaten_at="2026-07-15T03:30:00+08:00",
        diet_date=None,
    )
    assert inferred["diet_date"] == "2026-07-14"
    explicitly_changed = _create_draft(
        client,
        headers,
        event_id="before-four-explicit",
        eaten_at="2026-07-15T03:30:00+08:00",
        diet_date="2026-07-15",
    )
    assert explicitly_changed["diet_date"] == "2026-07-15"


def test_auto_and_manual_completion_wait_for_pending_and_use_versioned_rules_without_llm(
    monkeypatch: pytest.MonkeyPatch,
):
    _models, _router, service, _migration = _contract_modules()
    client, factory, headers, other_headers = _client(monkeypatch)
    lunch = _create_draft(client, headers, event_id="auto-lunch", meal_type="lunch")
    _confirm_draft(client, headers, lunch, event_id="auto-lunch-confirm")
    dinner = _create_draft(
        client,
        headers,
        event_id="auto-dinner",
        meal_type="dinner",
        eaten_at="2026-07-15T19:00:00+08:00",
    )
    _confirm_draft(client, headers, dinner, event_id="auto-dinner-confirm")
    _create_draft(
        client,
        headers,
        event_id="auto-pending-snack",
        meal_type="snack",
        eaten_at="2026-07-15T21:00:00+08:00",
    )

    with factory() as db:
        waiting = service.complete_day(
            db,
            user_id=1,
            subject_user_id=1,
            diet_date=date(2026, 7, 15),
            timezone_name="Asia/Shanghai",
            method="automatic",
            client_event_id="auto-close-1",
            complete_with_confirmed_only=False,
        )
        db.commit()
        assert waiting["state"] == "waiting_confirmation"
        assert waiting["summary"] is None

    completed = client.post(
        "/api/dietary-records/days/2026-07-15/complete",
        headers=headers,
        json={
            "client_event_id": "manual-close-confirmed-only",
            "timezone": "Asia/Shanghai",
            "complete_with_confirmed_only": True,
        },
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["state"] == "ready"
    assert body["summary"]["rule_version"] == service.RULE_VERSION
    assert body["summary"]["template_version"] == service.TEMPLATE_VERSION
    assert body["summary"]["pending_count"] == 1
    assert body["summary"]["confidence"] < 1
    assert "好食物" not in str(body)
    assert "坏食物" not in str(body)
    completion_source = inspect.getsource(service.complete_day)
    assert "openai" not in completion_source.lower()
    assert "get_provider" not in completion_source

    # Celery Beat is the primary 04:00 path.  Each saved day timezone is
    # evaluated independently, while dashboard evaluation remains a fallback.
    for owner_headers, prefix, timezone_name, meal_times in (
        (
            headers,
            "worker-shanghai",
            "Asia/Shanghai",
            (
                ("lunch", "2026-07-16T12:00:00+08:00"),
                ("dinner", "2026-07-16T19:00:00+08:00"),
            ),
        ),
        (
            other_headers,
            "worker-new-york",
            "America/New_York",
            (("lunch", "2026-07-16T12:00:00-04:00"),),
        ),
    ):
        for meal_type, eaten_at in meal_times:
            worker_draft = _create_draft(
                client,
                owner_headers,
                event_id=f"{prefix}-{meal_type}",
                diet_date="2026-07-16",
                meal_type=meal_type,
                eaten_at=eaten_at,
                timezone=timezone_name,
            )
            _confirm_draft(
                client,
                owner_headers,
                worker_draft,
                event_id=f"{prefix}-{meal_type}-confirm",
                timezone=timezone_name,
            )

    from app.workers import dietary_tasks
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(dietary_tasks, "SessionLocal", factory)
    celery_app.loader.import_default_modules()
    assert "process_due_dietary_days" in celery_app.tasks
    assert (
        celery_app.conf.beat_schedule["dietary-day-completion-sweep"]["task"]
        == "process_due_dietary_days"
    )
    assert "with_for_update(skip_locked=True)" in inspect.getsource(
        service.auto_complete_due_day_by_id
    )

    # At this UTC instant Shanghai has reached 04:00 on July 17, while New
    # York is still at 16:00 on July 16.  Only the Shanghai day may close.
    shanghai_sweep = dietary_tasks.process_due_dietary_days.run(
        max_days=10,
        now_iso="2026-07-16T20:00:00+00:00",
    )
    assert shanghai_sweep == {
        "discovered": 1,
        "processed": 1,
        "ready": 1,
        "waiting_confirmation": 0,
        "incomplete": 0,
        "skipped": 0,
        "failed": 0,
    }
    replay_sweep = dietary_tasks.process_due_dietary_days.run(
        max_days=10,
        now_iso="2026-07-16T20:00:00+00:00",
    )
    assert replay_sweep["processed"] == 0

    # Four o'clock in New York arrives later.  A single confirmed meal closes
    # as incomplete and must not produce a whole-day conclusion.
    new_york_sweep = dietary_tasks.process_due_dietary_days.run(
        max_days=10,
        now_iso="2026-07-17T08:00:00+00:00",
    )
    assert new_york_sweep["processed"] == 1
    assert new_york_sweep["incomplete"] == 1
    assert new_york_sweep["ready"] == 0

    with factory() as db:
        shanghai_day = db.scalar(
            select(_models.DietaryDay).where(
                _models.DietaryDay.user_id == 1,
                _models.DietaryDay.diet_date == date(2026, 7, 16),
            )
        )
        new_york_day = db.scalar(
            select(_models.DietaryDay).where(
                _models.DietaryDay.user_id == 2,
                _models.DietaryDay.diet_date == date(2026, 7, 16),
            )
        )
        assert shanghai_day.state == "ready"
        assert shanghai_day.close_method == "automatic"
        assert new_york_day.state == "incomplete"
        assert new_york_day.close_method == "automatic"
        assert new_york_day.closed_at is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(_models.DietaryDailySummary)
                .where(
                    _models.DietaryDailySummary.user_id == 1,
                    _models.DietaryDailySummary.diet_date == date(2026, 7, 16),
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(_models.DietaryDailySummary)
                .where(
                    _models.DietaryDailySummary.user_id == 2,
                    _models.DietaryDailySummary.diet_date == date(2026, 7, 16),
                )
            )
            == 0
        )


def test_photo_fingerprint_cache_is_tenant_scoped_and_history_edit_marks_summary_stale_then_recalculates_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    models, router, service, _migration = _contract_modules()
    client, factory, headers, other_headers = _client(monkeypatch)
    from app.core.config import settings
    from app.services import object_storage
    from botocore.exceptions import ClientError

    shared_objects: dict[tuple[str, str], dict] = {}
    storage_instances: list[object] = []

    class FakeS3Client:
        def __init__(self, objects: dict[tuple[str, str], dict]) -> None:
            self.objects = objects
            storage_instances.append(self)

        def head_object(self, *, Bucket: str, Key: str) -> dict:
            stored = self.objects.get((Bucket, Key))
            if stored is None:
                raise ClientError(
                    {
                        "Error": {"Code": "NoSuchKey", "Message": "missing"},
                        "ResponseMetadata": {"HTTPStatusCode": 404},
                    },
                    "HeadObject",
                )
            return {
                "ContentLength": len(stored["Body"]),
                "ContentType": stored["ContentType"],
                "Metadata": dict(stored["Metadata"]),
                "ServerSideEncryption": stored["ServerSideEncryption"],
                **(
                    {"SSEKMSKeyId": stored["SSEKMSKeyId"]}
                    if stored.get("SSEKMSKeyId") is not None
                    else {}
                ),
            }

        def put_object(self, **kwargs) -> dict:
            key = (kwargs["Bucket"], kwargs["Key"])
            self.objects[key] = {
                "Body": bytes(kwargs["Body"]),
                "ContentType": kwargs["ContentType"],
                "Metadata": dict(kwargs["Metadata"]),
                "ServerSideEncryption": kwargs["ServerSideEncryption"],
                "SSEKMSKeyId": kwargs.get("SSEKMSKeyId"),
            }
            return {"ETag": "test-etag"}

        def get_object(self, *, Bucket: str, Key: str) -> dict:
            stored = self.objects.get((Bucket, Key))
            if stored is None:
                raise ClientError(
                    {
                        "Error": {"Code": "NoSuchKey", "Message": "missing"},
                        "ResponseMetadata": {"HTTPStatusCode": 404},
                    },
                    "GetObject",
                )
            return {"Body": io.BytesIO(stored["Body"])}

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DIETARY_IMAGE_STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    with pytest.raises(object_storage.ObjectStorageConfigurationError):
        object_storage.configured_private_object_store(settings)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    local_store = object_storage.configured_private_object_store(settings)
    assert isinstance(local_store, object_storage.LocalPrivateObjectStore)
    legacy_content = b"legacy-unreleased-image"
    legacy_digest = hashlib.sha256(legacy_content).hexdigest()
    legacy_key = f"dietary_records/1/1/{legacy_digest[:2]}/{legacy_digest}.bin"
    legacy_path = tmp_path / legacy_key
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(legacy_content)
    assert (
        local_store.get_legacy(
            key=legacy_key,
            sha256=legacy_digest,
            max_bytes=10 * 1024 * 1024,
        )
        == legacy_content
    )

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DIETARY_IMAGE_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET", "dietary-test")
    monkeypatch.setattr(settings, "S3_REGION", "test-region-1")
    monkeypatch.setattr(settings, "S3_SERVER_SIDE_ENCRYPTION", "AES256")
    monkeypatch.setattr(settings, "S3_SSE_KMS_KEY_ID", "")
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "minioadmin")
    with pytest.raises(object_storage.ObjectStorageConfigurationError):
        object_storage.configured_private_object_store(settings)
    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "https://objects.example.test")
    with pytest.raises(object_storage.ObjectStorageConfigurationError):
        object_storage.configured_private_object_store(settings)
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "test-access-key")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "test-secret-key-value")
    monkeypatch.setattr(
        object_storage.boto3,
        "client",
        lambda *_args, **_kwargs: FakeS3Client(shared_objects),
    )
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "")
    with pytest.raises(object_storage.ObjectStorageConfigurationError):
        object_storage.configured_private_object_store(settings)
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "test-secret-key-value")
    from app import main as app_main

    assert (
        "validate_private_object_storage_configuration(settings)"
        in inspect.getsource(app_main.create_app)
    )
    monkeypatch.setattr(settings, "DIETARY_IMAGE_STORAGE_BACKEND", "local")
    with pytest.raises(object_storage.ObjectStorageConfigurationError):
        with TestClient(app_main.create_app()):
            pass
    monkeypatch.setattr(settings, "DIETARY_IMAGE_STORAGE_BACKEND", "s3")
    calls: list[tuple[bytes, str]] = []

    def fake_recognize(content: bytes, filename: str) -> dict:
        calls.append((content, filename))
        if (
            content == b"retry-image-bytes"
            and sum(seen_content == content for seen_content, _seen_filename in calls)
            <= 2
        ):
            raise RuntimeError("temporary vision failure")
        return {
            "food_items": [
                {
                    "item_id": "recognized-tofu-rice",
                    "name": "豆腐饭",
                    "portion_text": "一份",
                    "categories": ["protein", "staple"],
                    "confidence": 0.8,
                    "is_estimated": True,
                }
            ],
            "structure": {"protein": "present", "staple": "present"},
            "estimated_nutrition": {"energy_kcal_range": [400, 600]},
            "field_confidences": {"food_items": 0.8},
            "recognition_confidence": 0.8,
        }

    monkeypatch.setattr(service, "recognize_image_bytes", fake_recognize)
    form = {
        "diet_date": "2026-07-15",
        "meal_type": "lunch",
        "eaten_at": "2026-07-15T12:00:00+08:00",
        "source": "camera",
        "timezone": "Asia/Shanghai",
    }
    assert not inspect.iscoroutinefunction(router.create_dietary_photo_draft)
    failed_upload = client.put(
        "/api/dietary-records/drafts/photo",
        headers=headers,
        data={**form, "client_event_id": "photo-retry-upload"},
        files={
            "file": (
                "retry-original.jpg",
                b"retry-image-bytes",
                "image/jpeg",
            )
        },
    )
    assert failed_upload.status_code == 200, failed_upload.text
    failed_draft = failed_upload.json()
    assert failed_draft["recognition_status"] == "failed_manual_entry_available"
    assert failed_draft["formal_record_created"] is False
    assert failed_draft["source_ref"].startswith("sha256:")
    failed_upload_call_count = sum(
        content == b"retry-image-bytes" for content, _filename in calls
    )
    failed_upload_replay = client.put(
        "/api/dietary-records/drafts/photo",
        headers=headers,
        data={**form, "client_event_id": "photo-retry-upload"},
        files={
            "file": (
                "retry-original.jpg",
                b"retry-image-bytes",
                "image/jpeg",
            )
        },
    )
    assert failed_upload_replay.status_code == 200
    assert failed_upload_replay.json() == failed_draft
    assert (
        sum(content == b"retry-image-bytes" for content, _filename in calls)
        == failed_upload_call_count
    )
    with factory() as db:
        stored_failed_draft = db.get(models.DietaryDraft, failed_draft["draft_id"])
        image_object = stored_failed_draft.input_snapshot["image_object"]
        assert image_object["storage_version"] == 2
        assert image_object["storage_backend"] == "s3"
        assert image_object["owner_user_id"] == 1
        assert image_object["subject_user_id"] == 1
        assert image_object["original_filename"] == "retry-original.jpg"
        assert image_object["size_bytes"] == len(b"retry-image-bytes")
        assert image_object["content_type"] == "image/jpeg"
        assert image_object["image_object_key"].startswith("dietary_records/1/1/")
        assert (
            b"retry-image-bytes"
            not in json.dumps(
                stored_failed_draft.input_snapshot, sort_keys=True
            ).encode()
        )
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 0

    object_identity = (settings.S3_BUCKET, image_object["image_object_key"])
    stored_object = copy.deepcopy(shared_objects[object_identity])
    assert stored_object["Body"] == b"retry-image-bytes"
    assert stored_object["ContentType"] == "image/jpeg"
    assert stored_object["ServerSideEncryption"] == "AES256"
    assert stored_object["SSEKMSKeyId"] is None
    assert stored_object["Metadata"] == {
        "sha256": image_object["sha256"],
        "size-bytes": str(len(b"retry-image-bytes")),
        "content-type": "image/jpeg",
        "owner-user-id": "1",
        "subject-user-id": "1",
    }

    # A retry uses a freshly constructed S3 client, as another API/container
    # instance would. Missing or modified shared objects must fail closed
    # without consuming the draft version or creating a formal record.
    shared_objects.pop(object_identity)
    missing_object_retry = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json={
            "client_event_id": "photo-retry-missing-object",
            "expected_version": failed_draft["version"],
        },
    )
    assert missing_object_retry.status_code == 409
    shared_objects[object_identity] = copy.deepcopy(stored_object)
    shared_objects[object_identity]["Body"] = b"oversized-image-bytes"
    size_mismatch_retry = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json={
            "client_event_id": "photo-retry-size-mismatch",
            "expected_version": failed_draft["version"],
        },
    )
    assert size_mismatch_retry.status_code == 409
    shared_objects[object_identity] = copy.deepcopy(stored_object)
    shared_objects[object_identity]["Body"] = b"alter-image-bytes"
    digest_mismatch_retry = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json={
            "client_event_id": "photo-retry-digest-mismatch",
            "expected_version": failed_draft["version"],
        },
    )
    assert digest_mismatch_retry.status_code == 409
    shared_objects[object_identity] = copy.deepcopy(stored_object)
    assert (
        sum(content == b"retry-image-bytes" for content, _filename in calls)
        == failed_upload_call_count
    )
    with factory() as db:
        unchanged = db.get(models.DietaryDraft, failed_draft["draft_id"])
        assert unchanged.version == failed_draft["version"]
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 0

    retry_payload = {
        "client_event_id": "photo-retry-recognition-1",
        "expected_version": failed_draft["version"],
    }
    cross_account_retry = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=other_headers,
        json=retry_payload,
    )
    assert cross_account_retry.status_code in {403, 404}
    failed_retry = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json=retry_payload,
    )
    assert failed_retry.status_code == 200, failed_retry.text
    failed_retry_draft = failed_retry.json()
    assert failed_retry_draft["draft_id"] == failed_draft["draft_id"]
    assert failed_retry_draft["version"] == failed_draft["version"] + 1
    assert failed_retry_draft["recognition_status"] == "failed_manual_entry_available"
    failed_retry_call_count = sum(
        content == b"retry-image-bytes" for content, _filename in calls
    )
    failed_retry_replay = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json=retry_payload,
    )
    assert failed_retry_replay.status_code == 200
    assert failed_retry_replay.json() == failed_retry_draft
    assert (
        sum(content == b"retry-image-bytes" for content, _filename in calls)
        == failed_retry_call_count
    )

    success_retry_payload = {
        "client_event_id": "photo-retry-recognition-2",
        "expected_version": failed_retry_draft["version"],
    }
    retried = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json=success_retry_payload,
    )
    assert retried.status_code == 200, retried.text
    retried_draft = retried.json()
    assert retried_draft["draft_id"] == failed_draft["draft_id"]
    assert retried_draft["version"] == failed_retry_draft["version"] + 1
    assert retried_draft["recognition_status"] == "completed"
    assert retried_draft["formal_record_created"] is False
    success_retry_call_count = sum(
        content == b"retry-image-bytes" for content, _filename in calls
    )
    success_retry_replay = client.post(
        f"/api/dietary-records/drafts/{failed_draft['draft_id']}/retry-recognition",
        headers=headers,
        json=success_retry_payload,
    )
    assert success_retry_replay.status_code == 200
    assert success_retry_replay.json() == retried_draft
    assert (
        sum(content == b"retry-image-bytes" for content, _filename in calls)
        == success_retry_call_count
    )
    assert len(storage_instances) >= 8
    assert len({id(instance) for instance in storage_instances}) == len(
        storage_instances
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 0

    first = client.put(
        "/api/dietary-records/drafts/photo",
        headers=headers,
        data={**form, "client_event_id": "photo-owner-1"},
        files={"file": ("meal.jpg", b"same-image-bytes", "image/jpeg")},
    )
    second = client.put(
        "/api/dietary-records/drafts/photo",
        headers=headers,
        data={**form, "client_event_id": "photo-owner-2"},
        files={"file": ("meal-again.jpg", b"same-image-bytes", "image/jpeg")},
    )
    other = client.put(
        "/api/dietary-records/drafts/photo",
        headers=other_headers,
        data={**form, "client_event_id": "photo-other-1"},
        files={"file": ("meal-other.jpg", b"same-image-bytes", "image/jpeg")},
    )
    assert first.status_code == second.status_code == other.status_code == 200
    assert first.json()["recognition_cache_reused"] is False
    assert second.json()["recognition_cache_reused"] is True
    assert other.json()["recognition_cache_reused"] is False
    assert sum(content == b"same-image-bytes" for content, _filename in calls) == 2

    confirmed = _confirm_draft(
        client, headers, first.json(), event_id="photo-owner-confirm"
    )
    closed = client.post(
        "/api/dietary-records/days/2026-07-15/complete",
        headers=headers,
        json={
            "client_event_id": "photo-day-close",
            "timezone": "Asia/Shanghai",
            "complete_with_confirmed_only": True,
        },
    )
    assert closed.status_code == 200
    first_summary_id = closed.json()["summary"]["summary_id"]

    edited = client.patch(
        f"/api/dietary-records/records/{confirmed['record_id']}",
        headers=headers,
        json={
            "client_event_id": "photo-edit-1",
            "expected_version": confirmed["version"],
            "portion_text": "半份",
        },
    )
    assert edited.status_code == 200, edited.text
    with factory() as db:
        day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 15),
            )
        )
        assert day.state == "stale"

    dashboard = client.get(
        "/api/dietary-records/dashboard",
        headers=headers,
        params={"diet_date": "2026-07-15", "timezone": "Asia/Shanghai"},
    )
    replay_dashboard = client.get(
        "/api/dietary-records/dashboard",
        headers=headers,
        params={"diet_date": "2026-07-15", "timezone": "Asia/Shanghai"},
    )
    assert dashboard.status_code == replay_dashboard.status_code == 200
    assert dashboard.json()["day_state"] == "ready"
    # The today dashboard deliberately displays yesterday's conclusion; the
    # selected day's recalculated summary remains separately inspectable.
    assert dashboard.json()["displayed_summary"] is None
    new_summary = dashboard.json()["selected_day_summary"]
    assert new_summary["summary_id"] != first_summary_id
    assert new_summary["recalculated_after_edit"] is True
    assert (
        replay_dashboard.json()["selected_day_summary"]["summary_id"]
        == new_summary["summary_id"]
    )
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(models.DietaryDailySummary)
                .where(
                    models.DietaryDailySummary.user_id == 1,
                    models.DietaryDailySummary.subject_user_id == 1,
                    models.DietaryDailySummary.diet_date == date(2026, 7, 15),
                )
            )
            == 2
        )


def test_record_reuse_recent_edit_delete_and_dashboard_never_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
):
    models, _router, service, _migration = _contract_modules()
    client, factory, headers, other_headers = _client(monkeypatch)
    draft = _create_draft(client, headers, event_id="record-actions-draft")
    record = _confirm_draft(client, headers, draft, event_id="record-actions-confirm")

    recent = client.get(
        "/api/dietary-records/recent", headers=headers, params={"limit": 10}
    )
    assert recent.status_code == 200
    assert [item["record_id"] for item in recent.json()["items"]] == [
        record["record_id"]
    ]
    reused = client.post(
        f"/api/dietary-records/records/{record['record_id']}/reuse",
        headers=headers,
        json={
            "client_event_id": "record-actions-draft",
            "expected_version": record["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": "2026-07-16",
            "meal_type": "lunch",
            "eaten_at": "2026-07-16T12:30:00+08:00",
        },
    )
    assert reused.status_code == 200, reused.text
    assert reused.json()["status"] == "pending_confirmation"
    replayed_reuse = client.post(
        f"/api/dietary-records/records/{record['record_id']}/reuse",
        headers=headers,
        json={
            "client_event_id": "record-actions-draft",
            "expected_version": record["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": "2026-07-16",
            "meal_type": "lunch",
            "eaten_at": "2026-07-16T12:30:00+08:00",
        },
    )
    assert replayed_reuse.status_code == 200
    assert replayed_reuse.json() == reused.json()
    conflicting_reuse = client.post(
        f"/api/dietary-records/records/{record['record_id']}/reuse",
        headers=headers,
        json={
            "client_event_id": "record-actions-draft",
            "expected_version": record["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": "2026-07-18",
            "meal_type": "dinner",
            "eaten_at": "2026-07-18T18:30:00+08:00",
        },
    )
    assert conflicting_reuse.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(models.DietaryRecord)) == 1

    forbidden = client.get(
        "/api/dietary-records/dashboard",
        headers=headers,
        params={"subject_user_id": 2, "timezone": "Asia/Shanghai"},
    )
    other_dashboard = client.get(
        "/api/dietary-records/dashboard",
        headers=other_headers,
        params={"timezone": "Asia/Shanghai", "diet_date": "2026-07-15"},
    )
    assert forbidden.status_code == 403
    assert other_dashboard.status_code == 200
    assert other_dashboard.json()["records"] == []

    timezone_edit = client.patch(
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-timezone-edit",
            "expected_version": record["version"],
            "timezone": "America/New_York",
        },
    )
    assert timezone_edit.status_code == 200, timezone_edit.text
    edited_record = timezone_edit.json()
    timezone_edit_replay = client.patch(
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-timezone-edit",
            "expected_version": record["version"],
            "timezone": "America/New_York",
        },
    )
    assert timezone_edit_replay.status_code == 200
    assert timezone_edit_replay.json() == edited_record
    competing_timezone_edit = client.patch(
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-timezone-edit-competing",
            "expected_version": record["version"],
            "timezone": "Europe/London",
        },
    )
    assert competing_timezone_edit.status_code == 409
    with factory() as db:
        edited_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 15),
            )
        )
        assert edited_day.timezone == "America/New_York"
        assert edited_day.auto_close_due_at.replace(tzinfo=timezone.utc) == (
            service.dietary_day_auto_close_at(date(2026, 7, 15), "America/New_York")
        )

    moved = client.patch(
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-date-and-timezone-edit",
            "expected_version": edited_record["version"],
            "timezone": "Asia/Shanghai",
            "diet_date": "2026-07-17",
            "eaten_at": "2026-07-17T12:00:00+08:00",
        },
    )
    assert moved.status_code == 200, moved.text
    moved_record = moved.json()
    with factory() as db:
        old_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 15),
            )
        )
        new_day = db.scalar(
            select(models.DietaryDay).where(
                models.DietaryDay.user_id == 1,
                models.DietaryDay.subject_user_id == 1,
                models.DietaryDay.diet_date == date(2026, 7, 17),
            )
        )
        assert old_day.timezone == "America/New_York"
        assert old_day.auto_close_due_at.replace(tzinfo=timezone.utc) == (
            service.dietary_day_auto_close_at(date(2026, 7, 15), "America/New_York")
        )
        assert new_day.timezone == "Asia/Shanghai"
        assert new_day.auto_close_due_at.replace(tzinfo=timezone.utc) == (
            service.dietary_day_auto_close_at(date(2026, 7, 17), "Asia/Shanghai")
        )

    deleted = client.request(
        "DELETE",
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-date-and-timezone-edit",
            "expected_version": moved_record["version"],
        },
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "deleted"
    delete_replay = client.request(
        "DELETE",
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-date-and-timezone-edit",
            "expected_version": moved_record["version"],
        },
    )
    assert delete_replay.status_code == 200
    assert delete_replay.json() == deleted.json()
    competing_delete = client.request(
        "DELETE",
        f"/api/dietary-records/records/{record['record_id']}",
        headers=headers,
        json={
            "client_event_id": "record-actions-delete-competing",
            "expected_version": moved_record["version"],
        },
    )
    assert competing_delete.status_code == 409
    assert (
        client.get(
            "/api/dietary-records/recent", headers=headers, params={"limit": 10}
        ).json()["items"]
        == []
    )
