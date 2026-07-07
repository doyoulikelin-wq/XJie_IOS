from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.providers.openai_provider import _build_messages
from app.routers.chat import _fast_chat_reply
from app.services.context_builder import build_message_structure


def _db_session():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserIndicatorValue.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _add_user(db, user_id: int = 1):
    db.add(User(id=user_id, phone=f"1880000000{user_id}", username=f"u{user_id}", password="x"))
    db.commit()


def _add_indicator(db, *, user_id: int = 1, name: str, value: float, unit: str, source: str):
    db.add(UserIndicatorValue(
        user_id=user_id,
        indicator_name=name,
        value=value,
        unit=unit,
        measured_at=datetime(2026, 7, 7, 8, 0, tzinfo=timezone.utc),
        notes="unit-test",
        source=source,
    ))
    db.commit()


def test_apple_health_memory_forbids_device_requestioning():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="HRV", value=42, unit="ms", source="apple_health")
    _add_indicator(db, name="睡眠", value=7.1, unit="小时", source="apple_health")

    structure = build_message_structure(db, 1, user_query="我是不是已经同步过 Apple 健康？")
    memory = structure["data_source_memory"]
    plan = structure["response_plan"]

    assert structure["intent"]["kind"] == "data_source_query"
    assert memory["connected"]["apple_health"] is True
    assert plan["needs_literature"] is False
    forbidden = "\n".join(plan["forbidden_questions"])
    assert "Apple Watch" in forbidden
    assert "HRV 趋势截图" in forbidden

    reply = _fast_chat_reply({"message_structure": structure}, "我是不是已经同步过 Apple 健康？")
    assert reply is not None
    assert "已经同步过 Apple 健康" in reply["summary"]
    assert "不会再反问" in reply["summary"]


def test_relative_nt_correction_blocks_self_health_data_in_prompt():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="尿酸", value=419.7, unit="umol/L", source="manual")
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")
    history = [
        {"role": "user", "content": "帮我整理病史摘要"},
        {"role": "assistant", "content": "你的尿酸 419.7 umol/L，TIR 93.8%，血糖控制很好。"},
    ]

    structure = build_message_structure(db, 1, user_query="nt 是帮我老婆问的", history=history)
    context = {
        "message_structure": structure,
        "glucose_summary": {
            "last_24h": {"avg": 110, "tir_70_180_pct": 93.8, "variability": "low"},
            "last_7d": {"avg": 108, "tir_70_180_pct": 93.8, "variability": "low"},
        },
        "health_summary_text": "你的尿酸 419.7 umol/L，TIR 93.8%，血糖控制很好。",
        "meals_today": [],
        "symptoms_last_7d": [],
        "data_quality": {"kcal_today": 0},
        "recent_conversation_summaries": [],
    }

    assert structure["active_subject"]["type"] == "relative"
    assert structure["active_subject"]["relation"] == "wife"
    assert "user_self_health_facts" in structure["response_plan"]["blocked_context"]

    messages = _build_messages(context, "nt 是帮我老婆问的", history=history)
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "419.7 umol/L" not in system_text
    assert "TIR 93.8" not in system_text
    assert "本轮问题主体是妻子" in system_text

    reply = _fast_chat_reply(context, "nt 是帮我老婆问的")
    assert reply is not None
    assert "妻子" in reply["summary"]
    assert "不能用你的尿酸、血糖或 TIR" in reply["summary"]


def test_greeting_uses_session_memory_without_repeating_full_summary():
    db = _db_session()
    _add_user(db)
    history = [
        {"role": "assistant", "content": "你的尿酸 419.7 umol/L，建议每天喝够 2000ml 水，少吃内脏和海鲜。"},
    ]

    structure = build_message_structure(db, 1, user_query="你好", conversation_id=1, history=history)
    assert structure["intent"]["kind"] == "greeting"
    assert "uric_acid" in structure["session_memory"]["covered_facts"]
    assert "drink_2000ml_water" in structure["session_memory"]["avoid_repeating"]

    reply = _fast_chat_reply({"message_structure": structure}, "你好")
    assert reply is not None
    assert "不会重复整段病史摘要" in reply["summary"]
    assert "419.7" not in reply["summary"]
    assert "2000ml" not in reply["summary"]
