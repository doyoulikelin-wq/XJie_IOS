from app.routers.chat import _fast_chat_reply
from app.services.chat_routing import public_route_payload, resolve_chat_route
from app.services.health_nlu import analyze_health_message
from app.services.safety_service import detect_safety_flags


def _structure(
    *,
    query: str,
    primary_intent: str,
    health_related: bool = True,
    depth: str = "standard",
    safety_level: str = "low",
    subject_type: str = "self",
    concept_keys: list[str] | None = None,
    covered_facts: list[str] | None = None,
    conflicts: list[dict] | None = None,
    needs_literature: bool = False,
    evidence_status: str | None = None,
) -> dict:
    return {
        "user_message": {"normalized": query.lower()},
        "health_nlu": {
            "primary_intent": primary_intent,
            "depth_hint": depth,
            "has_health_signal": health_related,
            "concept_keys": concept_keys or [],
            "safety_profile": {"level": safety_level},
        },
        "intent": {"kind": "medical_question", "health_related": health_related, "depth": depth},
        "active_subject": {"type": subject_type},
        "data_source_memory": {"metric_conflicts": conflicts or []},
        "session_memory": {"covered_facts": covered_facts or []},
        "response_plan": {
            "needs_literature": needs_literature,
            "max_followup_questions": 1,
            "progress_steps": ["已识别当前问题主体", "正在整理回答"],
            "evidence_sufficiency": {"status": evidence_status} if evidence_status else {},
        },
    }


def test_emergency_route_has_priority_over_every_other_hint():
    structure = _structure(
        query="我胸痛喘不上气",
        primary_intent="data_source_query",
        safety_level="emergency",
    )

    route = resolve_chat_route(structure)

    assert route.route_id == "safety.emergency"
    assert route.strategy == "emergency"
    assert route.needs_llm is False
    assert route.needs_literature is False


def test_conflict_fast_path_only_runs_when_conflict_data_exists():
    no_conflict = resolve_chat_route(_structure(
        query="为什么两个血压不一样",
        primary_intent="conflict_analysis",
        depth="deep",
        concept_keys=["blood_pressure"],
        needs_literature=True,
    ))
    with_conflict = resolve_chat_route(_structure(
        query="为什么两个血压不一样",
        primary_intent="conflict_analysis",
        depth="deep",
        concept_keys=["blood_pressure"],
        conflicts=[{"metric": "收缩压", "samples": []}],
        needs_literature=True,
    ))

    assert no_conflict.route_id == "llm.health.deep"
    assert no_conflict.needs_literature is True
    assert with_conflict.route_id == "fast.metric_conflict"
    assert with_conflict.needs_literature is False


def test_bare_number_uses_targeted_clarification_without_llm():
    route = resolve_chat_route(_structure(
        query="120 正常吗",
        primary_intent="risk_judgment",
        concept_keys=[],
    ))

    assert route.route_id == "clarify.missing_referent"
    assert route.strategy == "clarification"
    assert route.handler == "missing_referent"


def test_known_session_fact_prevents_unnecessary_pronoun_clarification():
    route = resolve_chat_route(_structure(
        query="这个正常吗",
        primary_intent="risk_judgment",
        covered_facts=["blood_pressure"],
    ))

    assert route.route_id == "llm.health.standard"


def test_bare_number_still_requires_missing_parameter_clarification_with_context():
    route = resolve_chat_route(_structure(
        query="120 正常吗",
        primary_intent="risk_judgment",
        covered_facts=["blood_pressure"],
    ))

    assert route.route_id == "clarify.missing_referent"
    assert route.handler == "missing_referent"


def test_incomplete_blood_pressure_and_unitless_glucose_request_minimum_clarification():
    blood_pressure = _structure(
        query="血压 120 正常吗",
        primary_intent="risk_judgment",
        concept_keys=["blood_pressure"],
    )
    blood_pressure["health_nlu"]["numeric_risk"] = {
        "level": "low",
        "reason_codes": [],
        "observations": [{"metric": "blood_pressure", "systolic": 120, "diastolic": 0}],
    }
    glucose = _structure(
        query="血糖 5.5 正常吗",
        primary_intent="risk_judgment",
        concept_keys=["glucose"],
    )
    glucose["health_nlu"]["numeric_risk"] = {
        "level": "low",
        "reason_codes": ["glucose:unit_missing"],
        "observations": [{"metric": "blood_glucose", "value": 5.5, "unit": None}],
    }

    assert resolve_chat_route(blood_pressure).route_id == "clarify.missing_referent"
    assert resolve_chat_route(glucose).route_id == "clarify.missing_referent"


def test_current_glucose_concept_overrides_previous_blood_pressure_context():
    structure = _structure(
        query="glucose 5.5",
        primary_intent="risk_judgment",
        concept_keys=["glucose"],
        covered_facts=["blood_pressure"],
    )
    structure["health_nlu"]["numeric_risk"] = {
        "level": "low",
        "reason_codes": ["glucose:unit_missing"],
        "observations": [{"metric": "blood_glucose", "value": 5.5, "unit": None}],
    }

    reply = _fast_chat_reply({"message_structure": structure}, "glucose 5.5")

    assert reply is not None
    assert "血糖数值 5.5" in reply["summary"]
    assert "mmol/L 还是 mg/dL" in reply["summary"]
    assert "舒张压" not in reply["summary"]


def test_public_route_payload_excludes_internal_reason_codes_and_handler():
    route = resolve_chat_route(_structure(
        query="帮我分析 HRV",
        primary_intent="trend_analysis",
        depth="deep",
        concept_keys=["hrv"],
        needs_literature=True,
    ))

    public = public_route_payload(route)

    assert public["route_id"] == "llm.health.deep"
    assert public["needs_literature"] is True
    assert "reason_codes" not in public
    assert "handler" not in public


def test_insufficient_trend_evidence_uses_deterministic_route() -> None:
    route = resolve_chat_route(_structure(
        query="帮我分析最近一周 HRV",
        primary_intent="trend_analysis",
        depth="deep",
        concept_keys=["hrv"],
        needs_literature=True,
        evidence_status="insufficient",
    ))

    assert route.route_id == "fast.insufficient_trend_evidence"
    assert route.strategy == "deterministic"
    assert route.handler == "insufficient_trend_evidence"
    assert route.needs_literature is False


def test_high_numeric_risk_uses_deterministic_safety_route() -> None:
    structure = _structure(
        query="血压 190/125，没有胸痛",
        primary_intent="risk_judgment",
        safety_level="high",
        concept_keys=["blood_pressure"],
    )
    structure["health_nlu"]["numeric_risk"] = {
        "level": "high",
        "reason_codes": ["bp:severe_range"],
        "observations": [{"metric": "blood_pressure", "systolic": 190, "diastolic": 125}],
    }

    route = resolve_chat_route(structure)

    assert route.route_id == "safety.high_numeric"
    assert route.strategy == "deterministic"
    assert route.handler == "high_numeric_risk"


def test_negated_emergency_symptom_does_not_trigger_emergency_route():
    message = "我没有胸痛，也没有呼吸困难，只是昨晚没睡好有点头疼"
    nlu = analyze_health_message(message)

    assert nlu["emergency_context"] == "none"
    assert nlu["safety_profile"]["level"] != "emergency"
    assert detect_safety_flags(message) == []


def test_educational_emergency_question_is_not_current_emergency():
    nlu = analyze_health_message("哪些情况下胸痛需要立即急诊？")

    assert nlu["emergency_context"] == "educational"
    assert nlu["primary_intent"] != "emergency_triage"
    assert detect_safety_flags("哪些情况下胸痛需要立即急诊？") == []


def test_hypothetical_emergency_question_is_educational_but_current_case_is_not():
    hypothetical = analyze_health_message("如果胸痛该怎么办？")
    current = analyze_health_message("如果我现在胸痛该怎么办？")

    assert hypothetical["emergency_context"] == "educational"
    assert hypothetical["primary_intent"] != "emergency_triage"
    assert current["emergency_context"] == "active"
    assert current["primary_intent"] == "emergency_triage"


def test_hypothetical_relative_emergency_does_not_claim_it_is_current():
    hypothetical = analyze_health_message("如果我妈胸痛怎么办？")
    current = analyze_health_message("我妈现在胸痛，应该怎么办？")

    assert hypothetical["emergency_context"] == "educational"
    assert hypothetical["primary_intent"] != "emergency_triage"
    assert current["emergency_context"] == "active"
    assert current["primary_intent"] == "emergency_triage"


def test_resolved_prior_emergency_signal_routes_to_high_risk_followup():
    nlu = analyze_health_message("昨天胸痛出冷汗，现在已经缓解了，还要去医院吗？")

    assert nlu["emergency_context"] == "resolved_history"
    assert nlu["primary_intent"] == "risk_judgment"
    assert nlu["safety_profile"]["level"] == "high"
    assert detect_safety_flags("昨天胸痛出冷汗，现在已经缓解了，还要去医院吗？") == []


def test_active_stroke_language_is_caught_even_with_colloquial_wording():
    message = "我突然半边发麻，一侧无力，说不清话"
    nlu = analyze_health_message(message)

    assert nlu["emergency_context"] == "active"
    assert nlu["primary_intent"] == "emergency_triage"
    assert detect_safety_flags(message) == ["emergency_symptom"]
