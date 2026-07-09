import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.cgm_integration import CGMDeviceBinding
from app.models.health_document import HealthDocument
from app.models.user import User
from app.models.user_indicator_value import UserIndicatorValue
from app.providers.openai_provider import _build_messages
from app.routers.chat import _fast_chat_reply
from app.services.context_builder import build_message_structure


def _db_session():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserIndicatorValue.__table__.create(engine)
    CGMDeviceBinding.__table__.create(engine)
    HealthDocument.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _add_user(db, user_id: int = 1):
    db.add(User(id=user_id, phone=f"1880000000{user_id}", username=f"u{user_id}", password="x"))
    db.commit()


def _now():
    return datetime.now(timezone.utc)


def _add_indicator(
    db,
    *,
    user_id: int = 1,
    name: str,
    value: float,
    unit: str,
    source: str,
    measured_at: datetime | None = None,
):
    db.add(UserIndicatorValue(
        user_id=user_id,
        indicator_name=name,
        value=value,
        unit=unit,
        measured_at=measured_at or _now(),
        notes="unit-test",
        source=source,
    ))
    db.commit()


def _add_cgm_binding(db, *, user_id: int = 1):
    db.add(CGMDeviceBinding(
        user_id=user_id,
        provider="vendor_cgm",
        device_id=f"unit-test-device-{user_id}",
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    ))
    db.commit()


def _add_report(db, *, user_id: int = 1, status: str = "pending", name: str = "2026体检报告.pdf"):
    db.add(HealthDocument(
        user_id=user_id,
        doc_type="exam",
        source_type="pdf",
        name=name,
        extraction_status=status,
        created_at=_now(),
    ))
    db.commit()


def test_apple_health_memory_forbids_device_requestioning():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="HRV", value=42, unit="ms", source="apple_health")
    _add_indicator(db, name="睡眠", value=7.1, unit="小时", source="apple_health")
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")
    _add_indicator(db, name="尿酸", value=419.7, unit="umol/L", source="manual")

    structure = build_message_structure(db, 1, user_query="我是不是已经同步过 Apple 健康？")
    memory = structure["data_source_memory"]
    plan = structure["response_plan"]

    assert structure["intent"]["kind"] == "data_source_query"
    assert structure["health_nlu"]["primary_intent"] == "data_source_query"
    assert "apple_health" in structure["health_nlu"]["concept_keys"]
    assert memory["connected"]["apple_health"] is True
    assert plan["needs_literature"] is False
    forbidden = "\n".join(plan["forbidden_questions"])
    assert "Apple Watch" in forbidden
    assert "HRV 趋势截图" in forbidden

    reply = _fast_chat_reply({"message_structure": structure}, "我是不是已经同步过 Apple 健康？")
    assert reply is not None
    assert "已经同步过 Apple 健康" in reply["summary"]
    assert "不再把同步状态当成未知前提" in reply["summary"]
    assert "apple_health" not in reply["summary"]
    assert "fresh" not in reply["summary"]
    assert "cgm" not in reply["summary"].lower()
    assert "manual" not in reply["summary"].lower()
    assert "TIR" not in reply["summary"]
    assert "尿酸" not in reply["summary"]
    assert re.search(r"\d{4}-\d{2}-\d{2}T", reply["summary"]) is None


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
    assert structure["health_nlu"]["primary_intent"] == "subject_correction"
    assert "nt" in structure["health_nlu"]["concept_keys"]
    assert "user_self_health_facts" in structure["response_plan"]["blocked_context"]

    messages = _build_messages(context, "nt 是帮我老婆问的", history=history)
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    all_prompt_text = "\n".join(m["content"] for m in messages)
    assert "419.7 umol/L" not in system_text
    assert "TIR 93.8" not in system_text
    assert "419.7 umol/L" not in all_prompt_text
    assert "TIR 93.8" not in all_prompt_text
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


def test_followup_session_memory_uses_delta_policy_for_repeated_health_advice():
    db = _db_session()
    _add_user(db)
    history = [
        {
            "role": "assistant",
            "content": (
                "你的血压需要静坐 5 分钟后用上臂袖带复测。"
                "如果出现胸痛、呼吸困难或昏厥，要立即急诊。"
                "睡前避免咖啡因，先固定入睡时间。"
            ),
        },
    ]

    structure = build_message_structure(db, 1, user_query="那如果晚上又头疼呢", history=history)
    memory = structure["session_memory"]
    policy = structure["response_plan"]["repetition_policy"]

    assert structure["health_nlu"]["primary_intent"] == "symptom_triage"
    assert policy["mode"] == "delta_only"
    assert policy["answer_delta_first"] is True
    assert "blood_pressure" in memory["covered_facts"]
    assert "symptom_red_flags" in memory["covered_facts"]
    assert "bp_remeasure_resting" in memory["avoid_repeating"]
    assert "emergency_seek_care" in memory["avoid_repeating"]
    assert "如果 session_memory.repetition_policy.mode=delta_only，本轮只补新增判断和下一步，不重讲旧结论。" in structure["response_plan"]["quality_gates"]


def test_hrv_analysis_uses_apple_health_memory_without_screenshot_request():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="HRV", value=43, unit="ms", source="apple_health")
    _add_indicator(db, name="睡眠", value=7.3, unit="小时", source="apple_health")

    structure = build_message_structure(db, 1, user_query="帮我分析一下心率变异性")
    plan = structure["response_plan"]

    assert structure["intent"]["kind"] == "medical_question"
    assert structure["intent"]["semantic_intent"] == "medical_question"
    assert "hrv" in structure["health_nlu"]["concept_keys"]
    assert structure["active_subject"]["type"] == "self"
    assert structure["data_source_memory"]["connected"]["apple_health"] is True
    assert "user_self_health_facts" in plan["allowed_context"]
    assert plan["needs_literature"] is True
    assert "把最近一周 HRV 趋势截图发给我" in plan["forbidden_questions"]


def test_relative_nt_question_isolated_from_self_data_without_explicit_correction():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="尿酸", value=419.7, unit="umol/L", source="manual")
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")

    structure = build_message_structure(db, 1, user_query="我老婆 NT 2.8 正常吗？")
    context = {
        "message_structure": structure,
        "glucose_summary": {"last_7d": {"tir_70_180_pct": 93.8, "avg": 108, "variability": "low"}},
        "health_summary_text": "本人尿酸 419.7 umol/L，TIR 93.8%。",
        "meals_today": [],
        "symptoms_last_7d": [],
        "data_quality": {},
        "recent_conversation_summaries": [],
    }

    assert structure["active_subject"]["relation"] == "wife"
    assert structure["intent"]["kind"] == "medical_question"
    assert structure["health_nlu"]["primary_intent"] == "pregnancy_risk"
    assert "pregnancy_reproductive" in structure["health_nlu"]["semantic_categories"]
    assert "user_self_health_facts" in structure["response_plan"]["blocked_context"]

    messages = _build_messages(context, "我老婆 NT 2.8 正常吗？")
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "419.7 umol/L" not in system_text
    assert "TIR 93.8" not in system_text
    assert "本轮问题主体是妻子" in system_text


def test_stale_blood_pressure_is_marked_not_today_status():
    db = _db_session()
    _add_user(db)
    old_ts = _now() - timedelta(days=120)
    _add_indicator(db, name="收缩压", value=132, unit="mmHg", source="manual", measured_at=old_ts)
    _add_indicator(db, name="舒张压", value=84, unit="mmHg", source="manual", measured_at=old_ts)

    structure = build_message_structure(db, 1, user_query="我今天血压怎么样？")
    facts = {fact["metric"]: fact for fact in structure["health_fact_index"]["facts"]}

    assert structure["intent"]["kind"] == "medical_question"
    assert facts["收缩压"]["freshness"] == "outdated"
    assert facts["舒张压"]["freshness"] == "outdated"
    assert "freshness 为 stale/outdated 的指标必须说明数据时效，不能当作今天状态。" in structure["health_fact_index"]["rules"]


def test_same_day_blood_pressure_source_conflict_is_explicit():
    db = _db_session()
    _add_user(db)
    base_ts = _now() - timedelta(hours=3)
    _add_indicator(db, name="收缩压", value=145, unit="mmHg", source="manual", measured_at=base_ts)
    _add_indicator(db, name="收缩压", value=124, unit="mmHg", source="apple_health", measured_at=base_ts + timedelta(hours=1))

    structure = build_message_structure(db, 1, user_query="我的血压为什么变化这么大？")
    conflicts = structure["data_source_memory"]["metric_conflicts"]

    assert structure["intent"]["depth"] == "deep"
    assert structure["health_nlu"]["primary_intent"] == "conflict_analysis"
    assert structure["response_plan"]["answer_style"] == "source_time_then_reason"
    assert conflicts
    assert conflicts[0]["metric"] == "收缩压"
    assert {sample["source"] for sample in conflicts[0]["samples"]} == {"manual", "apple_health"}
    assert "不能简单覆盖成单个结论" in conflicts[0]["rule"]

    reply = _fast_chat_reply({"message_structure": structure}, "我的血压为什么变化这么大？")
    assert reply is not None
    assert "fast_path:metric_conflict" in reply["safety_flags"]
    assert "手动记录" in reply["summary"]
    assert "Apple 健康" in reply["summary"]
    assert "145" in reply["summary"]
    assert "124" in reply["summary"]


def test_pending_report_status_uses_fast_path_without_literature():
    db = _db_session()
    _add_user(db)
    _add_report(db, status="pending", name="孕检报告.pdf")

    structure = build_message_structure(db, 1, user_query="我的报告分析好了吗？")
    reply = _fast_chat_reply({"message_structure": structure}, "我的报告分析好了吗？")

    assert structure["intent"]["kind"] == "report_status_query"
    assert structure["health_nlu"]["route_hint"] == "deterministic_fast_path"
    assert structure["intent"]["requires_llm"] is False
    assert structure["response_plan"]["needs_literature"] is False
    assert structure["report_status"]["pending_count"] == 1
    assert reply is not None
    assert "后台识别中" in reply["summary"]
    assert "fast_path:report_status" in reply["safety_flags"]


def test_mother_glucose_query_blocks_self_cgm_data():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")
    _add_indicator(db, name="血糖", value=106, unit="mg/dL", source="cgm")
    history = [
        {"role": "user", "content": "帮我分析我的血糖"},
        {"role": "assistant", "content": "你的血糖 106 mg/dL，TIR 93.8%，整体控制很好。"},
    ]

    structure = build_message_structure(db, 1, user_query="看看我妈的血糖", history=history)
    context = {
        "message_structure": structure,
        "glucose_summary": {"last_7d": {"tir_70_180_pct": 93.8, "avg": 108, "variability": "low"}},
        "health_summary_text": "本人血糖 106 mg/dL，TIR 93.8%，血糖控制很好。",
        "meals_today": [],
        "symptoms_last_7d": [],
        "data_quality": {},
        "recent_conversation_summaries": [],
    }

    assert structure["active_subject"]["relation"] == "mother"
    assert structure["health_nlu"]["primary_intent"] == "medical_question"
    assert "user_self_glucose_data" in structure["response_plan"]["blocked_context"]

    messages = _build_messages(context, "看看我妈的血糖", history=history)
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    all_prompt_text = "\n".join(m["content"] for m in messages)
    assert "TIR 93.8" not in system_text
    assert "TIR 93.8" not in all_prompt_text
    assert "106 mg/dL" not in all_prompt_text
    assert "本轮问题主体是母亲" in system_text


def test_relative_subject_memory_carries_mother_into_pronoun_followup():
    db = _db_session()
    _add_user(db)
    history = [
        {"role": "user", "content": "我妈血糖 15 mmol/L，没有恶心呕吐"},
        {"role": "assistant", "content": "需要检查酮体并联系医生。"},
    ]

    structure = build_message_structure(db, 1, user_query="她现在降到 12 了，接下来怎么办？", history=history)

    assert structure["active_subject"]["type"] == "relative"
    assert structure["active_subject"]["relation"] == "mother"
    assert structure["active_subject"]["source"] == "recent_conversation"
    assert "user_self_health_facts" in structure["response_plan"]["blocked_context"]
    reply = _fast_chat_reply({"message_structure": structure}, "她现在降到 12 了，接下来怎么办？")
    assert reply is None or "你账号里的" not in reply["summary"]


def test_repeated_relative_source_query_returns_delta_not_full_boundary_again():
    db = _db_session()
    _add_user(db)
    history = [
        {"role": "user", "content": "我妈同步 Apple 健康了吗？"},
        {
            "role": "assistant",
            "content": "当前问题主体是母亲。我不能用你账号里的 Apple 健康记录判断母亲是否已经同步。",
        },
    ]

    structure = build_message_structure(db, 1, user_query="那她的同步状态呢？", history=history)
    reply = _fast_chat_reply({"message_structure": structure}, "那她的同步状态呢？")

    assert structure["session_memory"]["repetition_policy"]["mode"] == "delta_only"
    assert reply is not None
    assert reply["summary"].startswith("同步状态没有新增变化")
    assert "当前问题主体是母亲" not in reply["summary"]


@pytest.mark.parametrize(
    "query",
    [
        "我现在也有点头疼",
        "其实是我现在头晕",
        "这次是我自己的血压",
        "说回我，我今天睡得不好",
        "回到我本人，我刚测了血糖",
    ],
)
def test_explicit_self_reference_switches_back_from_relative_history(query: str):
    db = _db_session()
    _add_user(db)
    history = [
        {"role": "user", "content": "我妈最近头疼"},
        {"role": "assistant", "content": "先观察红旗信号。"},
    ]

    structure = build_message_structure(db, 1, user_query=query, history=history)

    assert structure["active_subject"]["type"] == "self"
    assert structure["active_subject"]["relation"] == "self"
    assert structure["active_subject"]["source"] == "current_user_message"
    assert structure["active_subject"]["correction_applied"] is True


@pytest.mark.parametrize(
    "query,relation",
    [
        ("我妈现在也头疼", "mother"),
        ("我老婆今天也头晕", "wife"),
        ("我朋友刚测了血压", "friend"),
    ],
)
def test_self_pronoun_inside_explicit_relative_does_not_switch_to_self(query: str, relation: str):
    db = _db_session()
    _add_user(db)

    structure = build_message_structure(db, 1, user_query=query)

    assert structure["active_subject"]["type"] == "relative"
    assert structure["active_subject"]["relation"] == relation


def test_unowned_pronoun_case_does_not_default_to_wife_or_self():
    db = _db_session()
    _add_user(db)

    structure = build_message_structure(db, 1, user_query="她的 NT 2.8 正常吗？")

    assert structure["active_subject"]["type"] == "other_case"
    assert structure["active_subject"]["relation"] == "unspecified_other"
    assert "user_self_health_facts" in structure["response_plan"]["blocked_context"]


def test_relative_data_source_query_never_returns_logged_in_users_sources():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="HRV", value=43, unit="ms", source="apple_health")
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")

    structure = build_message_structure(db, 1, user_query="我妈同步 Apple 健康了吗？")
    reply = _fast_chat_reply({"message_structure": structure}, "我妈同步 Apple 健康了吗？")

    assert structure["active_subject"]["relation"] == "mother"
    assert structure["health_nlu"]["primary_intent"] == "data_source_query"
    assert reply is not None
    assert "不能用你账号里的 Apple 健康" in reply["summary"]
    assert "43" not in reply["summary"]
    assert "TIR" not in reply["summary"]
    assert "relative_data_source_boundary" in reply["safety_flags"][0]


def test_subject_correction_does_not_override_active_health_risk_question():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="血糖", value=106, unit="mg/dL", source="cgm")

    structure = build_message_structure(db, 1, user_query="不是我，是我妈，她血糖 20 mmol/L 怎么办？")

    assert structure["active_subject"]["relation"] == "mother"
    assert structure["active_subject"]["correction_applied"] is True
    assert structure["health_nlu"]["primary_intent"] == "risk_judgment"
    assert structure["intent"]["kind"] == "medical_question"
    assert structure["interaction_route"]["strategy"] == "deterministic"
    assert structure["interaction_route"]["route_id"] == "safety.high_numeric"
    assert "user_self_glucose_data" in structure["response_plan"]["blocked_context"]


def test_cgm_device_query_uses_binding_memory_without_requestioning():
    db = _db_session()
    _add_user(db)
    _add_cgm_binding(db)

    structure = build_message_structure(db, 1, user_query="我有血糖设备吗？")
    reply = _fast_chat_reply({"message_structure": structure}, "我有血糖设备吗？")

    assert structure["intent"]["kind"] == "data_source_query"
    assert structure["response_plan"]["route_hint"] == "deterministic_fast_path"
    assert structure["data_source_memory"]["connected"]["cgm"] is True
    assert "你是否使用 CGM" in structure["response_plan"]["forbidden_questions"]
    assert reply is not None
    assert "连续血糖数据来源" in reply["summary"]


def test_uric_acid_risk_keeps_self_context_and_requests_literature():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="尿酸", value=419.7, unit="umol/L", source="manual")
    _add_indicator(db, name="胱抑素C", value=0.81, unit="mg/L", source="manual")

    structure = build_message_structure(db, 1, user_query="尿酸 419.7 对我风险大吗？")
    facts = {fact["metric"]: fact for fact in structure["health_fact_index"]["facts"]}

    assert structure["active_subject"]["type"] == "self"
    assert structure["intent"]["latent_purpose"] == "risk_judgment"
    assert structure["intent"]["semantic_intent"] == "risk_judgment"
    assert "uric_acid" in structure["health_nlu"]["concept_keys"]
    assert structure["response_plan"]["needs_literature"] is True
    assert "user_self_health_facts" in structure["response_plan"]["allowed_context"]
    assert facts["尿酸"]["value"] == 419.7
    assert facts["胱抑素C"]["value"] == 0.81


def test_emergency_context_marks_safety_profile_without_literature():
    db = _db_session()
    _add_user(db)

    structure = build_message_structure(db, 1, user_query="胸痛喘不上气还冒冷汗怎么办")

    assert structure["intent"]["kind"] == "medical_question"
    assert structure["health_nlu"]["primary_intent"] == "emergency_triage"
    assert structure["response_plan"]["safety_profile"]["level"] == "emergency"
    assert structure["response_plan"]["answer_style"] == "emergency_direct"
    assert structure["response_plan"]["needs_literature"] is False


def test_hrv_prompt_projects_out_unrelated_glucose_uric_acid_and_report_summary():
    db = _db_session()
    _add_user(db)
    _add_indicator(db, name="HRV", value=43, unit="ms", source="apple_health")
    _add_indicator(db, name="睡眠", value=7.2, unit="小时", source="apple_health")
    _add_indicator(db, name="TIR", value=93.8, unit="%", source="cgm")
    _add_indicator(db, name="尿酸", value=419.7, unit="umol/L", source="manual")
    structure = build_message_structure(db, 1, user_query="帮我分析最近 HRV 下降")
    context = {
        "message_structure": structure,
        "glucose_summary": {"last_7d": {"avg": 108, "tir_70_180_pct": 93.8, "variability": "low"}},
        "health_summary_text": "尿酸 419.7 umol/L，TIR 93.8%，肾功能正常。",
        "meals_today": [{"kcal": 600, "ts": "18:00"}],
        "symptoms_last_7d": [],
        "data_quality": {"kcal_today": 1800},
        "recent_conversation_summaries": [],
    }

    messages = _build_messages(context, "帮我分析最近 HRV 下降")
    prompt = "\n".join(message["content"] for message in messages)

    assert "\"metric\": \"HRV\"" in prompt
    assert "43" in prompt
    assert "419.7" not in prompt
    assert "TIR 93.8" not in prompt
    assert "均值=108mg/dL" not in prompt
    assert "今日热量: 1800" not in prompt


def test_report_summary_route_keeps_uploaded_health_summary_context():
    db = _db_session()
    _add_user(db)
    structure = build_message_structure(db, 1, user_query="帮我整理病史摘要")
    context = {
        "message_structure": structure,
        "glucose_summary": {},
        "health_summary_text": "2026年体检：ALT 68 U/L，建议结合复查趋势。",
        "meals_today": [],
        "symptoms_last_7d": [],
        "data_quality": {},
        "recent_conversation_summaries": [],
    }

    messages = _build_messages(context, "帮我整理病史摘要")
    prompt = "\n".join(message["content"] for message in messages)

    assert "ALT 68 U/L" in prompt


def test_pregnancy_risk_trait_survives_same_subject_followup_and_routes_deterministically():
    db = _db_session()
    _add_user(db)
    history = [
        {"role": "user", "content": "我老婆怀孕 32 周"},
        {"role": "assistant", "content": "已按妻子的孕期情况继续。"},
    ]

    structure = build_message_structure(
        db,
        1,
        user_query="她现在血压 165/112 mmHg，没有剧烈头痛",
        history=history,
    )
    reply = _fast_chat_reply({"message_structure": structure}, "她现在血压 165/112 mmHg，没有剧烈头痛")

    assert structure["active_subject"]["relation"] == "wife"
    assert structure["health_nlu"]["subject_traits"]["pregnancy_context_source"] == "recent_same_subject"
    assert structure["interaction_route"]["route_id"] == "safety.high_numeric"
    assert reply is not None
    assert "收缩压达到 160 或舒张压达到 110" in reply["summary"]
    assert "产科急诊" in reply["summary"]


def test_subject_switch_prevents_relative_pregnancy_trait_from_leaking_to_self():
    db = _db_session()
    _add_user(db)
    history = [{"role": "user", "content": "我老婆怀孕 32 周"}]

    structure = build_message_structure(
        db,
        1,
        user_query="说回我，我现在血压 165/110 mmHg",
        history=history,
    )

    assert structure["active_subject"]["type"] == "self"
    assert structure["health_nlu"]["subject_traits"]["pregnancy_or_postpartum"] is False
    assert "bp:pregnancy_severe" not in structure["health_nlu"]["numeric_risk"]["reason_codes"]
    assert structure["health_nlu"]["numeric_risk"]["level"] == "medium"
