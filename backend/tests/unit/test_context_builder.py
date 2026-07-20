from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.services import context_builder


@dataclass
class MealObj:
    meal_ts: datetime
    kcal: int
    tags: list[str]
    meal_ts_source: type("src", (), {"value": "user_confirmed"})
    photo_id: str | None = None


@dataclass
class SymptomObj:
    ts: datetime
    severity: int
    text: str


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class FakeDB:
    def __init__(self, meals, symptoms):
        self.calls = 0
        self.meals = meals
        self.symptoms = symptoms

    def execute(self, _stmt):
        self.calls += 1
        # calls 1=meals(.all), 2=symptoms(.all), 3+=feature/profile(.first)
        if self.calls == 1:
            return _FakeResult(self.meals)
        elif self.calls == 2:
            return _FakeResult(self.symptoms)
        else:
            return _FakeResult([])


def test_build_user_context(monkeypatch):
    now = datetime(2026, 2, 18, 12, 0, tzinfo=timezone.utc)
    meal = MealObj(now, 500, ["high_carb"], type("src", (), {"value": "user_confirmed"}), None)
    symptom = SymptomObj(now, 2, "胃胀")

    monkeypatch.setattr(
        context_builder,
        "build_message_structure",
        lambda *_args, **_kwargs: {},
    )

    db = FakeDB([meal], [symptom])
    context = context_builder.build_user_context(
        db,
        user_id="u1",
        trusted_health_consumer="chat_question",
    )

    assert "glucose_summary" in context
    assert context["glucose_summary"]["last_24h"] == {"gaps_hours": None}
    assert context["data_quality"]["kcal_today"] == 0
    assert context["meals_today"] == []
    assert context["symptoms_last_7d"] == []
    assert db.calls == 0


def test_trusted_context_failure_returns_no_health_values_from_fallback_paths(
    monkeypatch,
):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("trust store unavailable")

    def raw_health_fallback(*_args, **_kwargs):
        pytest.fail("raw health fallback must not run")

    monkeypatch.setattr(context_builder, "build_trusted_health_context", unavailable)
    monkeypatch.setattr(
        context_builder,
        "get_glucose_summary",
        raw_health_fallback,
        raising=False,
    )
    monkeypatch.setattr(
        context_builder,
        "build_message_structure",
        lambda *_args, **_kwargs: {"health_fact_index": {"facts": []}},
    )

    context = context_builder.build_user_context(
        FakeDB([], []),
        user_id=1,
        trusted_health_consumer="daily_advice",
    )

    assert context["glucose_summary"]["last_24h"] == {"gaps_hours": None}
    assert context["meals_today"] == []
    assert context["symptoms_last_7d"] == []
    assert context["agent_features"] == {}
    assert context["user_profile_info"] == {}
    assert context["health_report_text"] == ""
    assert context["patient_history"] == {}
    assert context["omics_analyses"] == []
    assert context["current_medications"] == []
    assert context["recent_conversation_summaries"] == []


def test_build_user_context_has_no_raw_indicator_or_legacy_profile_bypass(
    monkeypatch,
):
    numeric_sentinel = 987654.321
    raw_glucose_calls: list[tuple] = []
    recent_summary_calls: list[tuple] = []
    trusted = {
        "consumer": "chat_question",
        "profile_facts": [
            {
                "fact_key": "basic.weight",
                "category": "basic",
                "value": {
                    "response_state": "value",
                    "value": {"weight_kg": 70},
                },
                "version": 2,
                "confirmed_at": "2026-07-15T00:00:00+00:00",
            }
        ],
    }
    monkeypatch.setattr(
        context_builder,
        "build_trusted_health_context",
        lambda *_args, **_kwargs: trusted,
    )

    def raw_glucose(*args, **_kwargs):
        raw_glucose_calls.append(args)
        return {"gaps_hours": numeric_sentinel, "avg": numeric_sentinel}

    monkeypatch.setattr(
        context_builder,
        "get_glucose_summary",
        raw_glucose,
        raising=False,
    )
    monkeypatch.setattr(
        context_builder,
        "_get_profile_info",
        lambda *_args, **_kwargs: pytest.fail("legacy UserProfile must not be read"),
    )

    def raw_recent_summaries(*args, **_kwargs):
        recent_summary_calls.append(args)
        return [{"messages": [{"content": str(numeric_sentinel)}]}]

    monkeypatch.setattr(
        context_builder,
        "_get_recent_conversation_summaries",
        raw_recent_summaries,
        raising=False,
    )
    captured: dict = {}

    def message_structure(*_args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(context_builder, "build_message_structure", message_structure)

    now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    db = FakeDB(
        [
            MealObj(
                now,
                int(numeric_sentinel),
                [str(numeric_sentinel)],
                type("src", (), {"value": str(numeric_sentinel)}),
                None,
            )
        ],
        [SymptomObj(now, 9, str(numeric_sentinel))],
    )
    authorized_history = [
        {"role": "user", "content": "这是当前已授权会话中的问题"},
        {"role": "assistant", "content": "这是当前已授权会话中的回复"},
    ]
    context = context_builder.build_user_context(
        db,
        user_id=1,
        trusted_health_consumer="chat_question",
        conversation_id=73,
        history=authorized_history,
    )

    assert context["user_profile_info"] == {"weight_kg": 70}
    assert captured["trusted_health_context"] is trusted
    assert captured["conversation_id"] == 73
    assert captured["history"] is authorized_history
    assert context["glucose_summary"]["last_24h"] == {"gaps_hours": None}
    assert context["meals_today"] == []
    assert context["symptoms_last_7d"] == []
    assert context["recent_conversation_summaries"] == []
    assert raw_glucose_calls == []
    assert recent_summary_calls == []
    assert db.calls == 0
    assert str(numeric_sentinel) not in str(context)

    raw = {
        "sources": [],
        "metrics": [
            {
                "metric": "unconfirmed_raw_metric",
                "source": "raw",
                "last_value": 777,
                "display_value": "777",
                "recent_samples": [{"value": 777}],
            }
        ],
        "connected": {"apple_health": True},
        "metric_conflicts": [{"metric": "raw", "samples": [{"value": 777}]}],
    }
    projected = context_builder._trusted_data_source_memory(raw)
    assert projected["metrics"] == [
        {
            "metric": "unconfirmed_raw_metric",
            "source": "raw",
            "unit": None,
            "measured_at": None,
            "freshness": None,
            "trust_state": "metadata_only",
        }
    ]
    assert projected["metric_conflicts"] == []
    assert "777" not in str(projected)
