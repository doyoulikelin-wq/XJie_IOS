from app.providers.base import ChatLLMResult
from app.services.chat_response_guard import guard_chat_result
from app.services.chat_routing import resolve_chat_route


def _context(
    *,
    subject_type: str = "self",
    connected: dict | None = None,
    facts: list[dict] | None = None,
    repetition_mode: str = "normal",
    evidence: dict | None = None,
) -> dict:
    structure = {
        "user_message": {"normalized": "帮我分析"},
        "health_nlu": {
            "primary_intent": "trend_analysis",
            "depth_hint": "deep",
            "has_health_signal": True,
            "concept_keys": ["hrv"],
            "matched_concepts": [{"display": "心率变异性"}],
            "safety_profile": {"level": "low"},
        },
        "intent": {"kind": "medical_question", "health_related": True, "depth": "deep"},
        "active_subject": {
            "type": subject_type,
            "display": "妻子" if subject_type != "self" else "本人",
        },
        "data_source_memory": {"connected": connected or {}},
        "health_fact_index": {"facts": facts or []},
        "session_memory": {"repetition_policy": {"mode": repetition_mode}},
        "response_plan": {
            "needs_literature": True,
            "max_followup_questions": 1,
            "progress_steps": ["正在整理回答"],
            "evidence_sufficiency": evidence or {},
        },
    }
    structure["interaction_route"] = resolve_chat_route(structure).to_dict()
    return {"message_structure": structure}


def _result(summary: str, *, analysis: str | None = None, followups: list[str] | None = None, flags: list[str] | None = None):
    return ChatLLMResult(
        answer_markdown=analysis or summary,
        confidence=0.85,
        followups=followups or [],
        safety_flags=flags or [],
        summary=summary,
        analysis=analysis or summary,
    )


def test_guard_removes_internal_source_keys_and_formats_iso_time():
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result("apple_health: fresh，最近样本 2026-07-08T04:59:35+00:00")

    guarded = guard_chat_result(result, context=context, route=route, user_query="同步状态", history=[])

    assert "apple_health" not in guarded.result.summary
    assert "fresh" not in guarded.result.summary
    assert "2026-07-08T" not in guarded.result.summary
    assert "Apple 健康" in guarded.result.summary
    assert "2026年7月8日 12:59" in guarded.result.summary


def test_guard_removes_apple_health_requestion_when_source_is_known():
    context = _context(connected={"apple_health": True})
    route = resolve_chat_route(context["message_structure"])
    result = _result("你的 HRV 最近下降。你平时戴 Apple Watch 吗？把最近一周 HRV 趋势截图发给我。")

    guarded = guard_chat_result(result, context=context, route=route, user_query="帮我分析 HRV", history=[])

    assert "戴 Apple Watch" not in guarded.result.summary
    assert "截图" not in guarded.result.summary
    assert "已确认 Apple 健康数据已接入" in guarded.result.summary
    assert "apple_health_requestion_removed" in guarded.quality_flags


def test_guard_removes_self_fact_leakage_from_relative_case():
    context = _context(
        subject_type="relative",
        facts=[{"metric": "尿酸", "value": 419.7, "unit": "umol/L"}],
    )
    route = resolve_chat_route(context["message_structure"])
    result = _result("你的尿酸 419.7 umol/L 偏高。她的 NT 需要结合孕周判断。")

    guarded = guard_chat_result(result, context=context, route=route, user_query="我老婆 NT 正常吗", history=[])

    assert "419.7" not in guarded.result.summary
    assert "你的尿酸" not in guarded.result.summary
    assert guarded.result.summary.startswith("当前问题主体是妻子")
    assert "relative_self_data_removed" in guarded.quality_flags


def test_guard_filters_ai_voice_followups_and_caps_to_route_limit():
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result(
        "先看最近 HRV 趋势。",
        followups=["你最近睡得好吗？", "帮我看最近一周睡眠", "帮我看最近一周睡眠"],
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="帮我分析 HRV", history=[])

    assert guarded.result.followups == ["帮我看最近一周睡眠"]
    assert "followups_filtered" in guarded.quality_flags


def test_guard_redacts_provider_error_details():
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result(
        "错误信息: upstream api key rejected sk-secret",
        analysis="Traceback: connection failed",
        flags=["provider_error"],
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="帮我分析", history=[])

    visible = guarded.result.summary + guarded.result.analysis
    assert "sk-secret" not in visible
    assert "Traceback" not in visible
    assert "消息已经保留" in visible


def test_guard_rejects_dangling_provider_output_even_without_error_flag():
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result(
        "这三者可能存在关联，但不宜简单归因于",
        analysis="鼻炎可能影响睡眠，脊柱侧弯只有在严重时才可能导致",
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="这些问题有关系吗", history=[])

    assert "简单归因于" not in guarded.result.summary
    assert "没有完整生成" in guarded.result.summary
    assert "provider_error" in guarded.result.safety_flags
    assert "incomplete_response_replaced" in guarded.quality_flags


def test_guard_enforces_hypoxia_boundary_for_compound_causal_answer():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "causal_assessment",
        "concept_keys": ["insomnia", "low_mood", "rhinitis", "scoliosis", "hypoxia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])
    result = _result(
        "失眠和抑郁与缺氧之间存在一定的关联。需要客观检查。",
        analysis="失眠和抑郁与缺氧之间存在一定的关联。鼻炎和脊柱侧弯需要分别评估。",
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="这些问题有关系吗", history=[])

    assert "失眠和抑郁与缺氧之间存在一定的关联" not in guarded.result.analysis
    assert guarded.result.analysis.startswith("这些问题可能存在需要核对的间接路径")
    assert "不能确认鼻炎或脊柱侧弯已经造成缺氧" in guarded.result.analysis
    assert "自伤或轻生念头" in guarded.result.analysis
    assert "causal_hypoxia_boundary_enforced" in guarded.quality_flags
    assert "mental_crisis_boundary_added" in guarded.quality_flags


def test_guard_removes_direct_hypoxia_causal_chain_in_cause_first_wording():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "causal_assessment",
        "concept_keys": ["insomnia", "rhinitis", "hypoxia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])
    direct_claim = "鼻炎造成缺氧，从而引起失眠。"
    result = _result(
        direct_claim + "需要用客观评估核对。",
        analysis=direct_claim + "建议核对鼻塞、睡眠呼吸和规范血氧。",
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="这些问题有关系吗", history=[])

    assert direct_claim not in guarded.result.summary
    assert direct_claim not in guarded.result.analysis
    assert "不能确认鼻炎已经造成缺氧" in guarded.result.summary
    assert "causal_hypoxia_boundary_enforced" in guarded.quality_flags


def test_guard_removes_hypoxia_first_and_false_hedge_assertions():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "causal_assessment",
        "concept_keys": ["insomnia", "rhinitis", "hypoxia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])

    for unsupported in (
        "缺氧导致失眠。",
        "缺氧是失眠的主要原因。",
        "可能存在间接路径，但鼻炎造成缺氧。",
    ):
        result = _result(unsupported + "需要客观评估核对。")
        guarded = guard_chat_result(
            result,
            context=context,
            route=route,
            user_query="这些问题有关系吗",
            history=[],
        )
        assert unsupported not in guarded.result.summary
        assert "不能确认鼻炎已经造成缺氧" in guarded.result.summary


def test_guard_preserves_hypoxia_claims_that_include_explicit_evidence_boundaries():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "causal_assessment",
        "concept_keys": ["insomnia", "rhinitis", "scoliosis", "hypoxia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])
    bounded = "鼻炎可能影响睡眠，但不能据此确认已经发生缺氧。"
    conditional = "脊柱侧弯只有在严重并伴呼吸受限时才可能导致夜间低氧。"
    result = _result(bounded, analysis=conditional)

    guarded = guard_chat_result(result, context=context, route=route, user_query="这些问题有关系吗", history=[])

    assert bounded in guarded.result.summary
    assert conditional in guarded.result.analysis


def test_guard_hypoxia_boundary_mentions_only_causal_concepts_from_the_query():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "causal_assessment",
        "concept_keys": ["sleep_disordered_breathing", "hypoxia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])
    result = _result("打鼾造成夜间低氧。", analysis="打鼾造成夜间低氧。需要客观评估。")

    guarded = guard_chat_result(result, context=context, route=route, user_query="打鼾会导致夜间低氧吗", history=[])

    visible = guarded.result.summary + guarded.result.analysis
    assert "睡眠呼吸症状" in visible
    assert "鼻炎" not in visible
    assert "脊柱侧弯" not in visible


def test_guard_does_not_duplicate_existing_mental_crisis_boundary():
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "mental_health_support",
        "concept_keys": ["low_mood", "insomnia"],
        "depth_hint": "deep",
        "safety_profile": {"level": "medium"},
    })
    route = resolve_chat_route(context["message_structure"])
    existing = "出现自伤念头、无法维持基本生活或情绪危机时，应立即寻求线下帮助。"
    result = _result("失眠和情绪低落会相互影响。" + existing, analysis="先评估持续时间和日常功能。" + existing)

    guarded = guard_chat_result(result, context=context, route=route, user_query="最近失眠又情绪低落", history=[])

    assert guarded.result.analysis.count("自伤念头") == 1
    assert "mental_crisis_boundary_added" not in guarded.quality_flags


def test_delta_guard_removes_exact_repeated_sentence_but_keeps_new_action():
    context = _context(repetition_mode="delta_only")
    route = resolve_chat_route(context["message_structure"])
    repeated = "睡前避免咖啡因，并固定入睡时间。"
    result = _result(repeated + "今晚新增记录一次入睡时间和夜醒次数。")

    guarded = guard_chat_result(
        result,
        context=context,
        route=route,
        user_query="那今晚怎么做",
        history=[{"role": "assistant", "content": repeated}],
    )

    assert repeated not in guarded.result.summary
    assert "今晚新增记录一次入睡时间和夜醒次数" in guarded.result.summary
    assert "exact_session_repetition_removed" in guarded.quality_flags


def test_guard_removes_emoji_from_user_visible_output():
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result("先休息一下。✅", analysis="建议记录睡眠。💡")

    guarded = guard_chat_result(result, context=context, route=route, user_query="睡不好", history=[])

    assert "✅" not in guarded.result.summary
    assert "💡" not in guarded.result.analysis


def test_guard_replaces_unsupported_trend_claim_with_evidence_limited_reply():
    context = _context(evidence={
        "status": "insufficient",
        "display_name": "心率变异性",
        "window_days": 7,
        "sample_count": 1,
        "distinct_days": 1,
        "min_required_samples": 4,
        "min_required_days": 4,
        "latest_sample": {
            "value": 43,
            "unit": "ms",
            "source": "apple_health",
            "measured_at": "2026-07-09T02:35:00+00:00",
        },
    })
    route = resolve_chat_route(context["message_structure"])
    result = _result("最近一周整体稳定，但有几天偏低。")

    guarded = guard_chat_result(result, context=context, route=route, user_query="最近一周 HRV 趋势", history=[])

    assert "整体稳定" not in guarded.result.summary
    assert "只有 1 个心率变异性样本" in guarded.result.summary
    assert "insufficient_trend_claim_replaced" in guarded.quality_flags


def test_symptom_guard_removes_overconfident_exclusion_claim() -> None:
    context = _context()
    context["message_structure"]["health_nlu"]["primary_intent"] = "symptom_triage"
    route = resolve_chat_route(context["message_structure"])
    result = _result(
        "你没有胸痛，所以可以排除严重健康问题。先休息。",
        analysis="目前可以排除急症。头痛仍需观察。",
    )

    guarded = guard_chat_result(result, context=context, route=route, user_query="昨晚没睡好头痛", history=[])

    assert "排除严重" not in guarded.result.summary
    assert "排除急症" not in guarded.result.analysis
    assert "仍需按当前症状" in guarded.result.summary
    assert "overreassurance_removed" in guarded.quality_flags


def test_symptom_guard_adds_headache_specific_red_flags() -> None:
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "symptom_triage",
        "concept_keys": ["headache"],
    })
    route = resolve_chat_route(context["message_structure"])
    result = _result("昨晚没睡好可以诱发头痛。先补水并休息。")

    guarded = guard_chat_result(result, context=context, route=route, user_query="昨晚没睡好头痛", history=[])

    assert "发热颈部僵硬" in guarded.result.summary
    assert "一侧无力" in guarded.result.summary
    assert "symptom_boundary_added" in guarded.quality_flags


def test_guard_removes_generic_capability_offer_from_summary() -> None:
    context = _context()
    route = resolve_chat_route(context["message_structure"])
    result = _result("先记录今晚睡眠。要不要我帮你总结最近的模式？")

    guarded = guard_chat_result(result, context=context, route=route, user_query="今晚怎么做", history=[])

    assert "要不要我帮你" not in guarded.result.summary
    assert guarded.result.summary == "先记录今晚睡眠。"
    assert "generic_offer_removed" in guarded.quality_flags


def test_long_summary_keeps_conclusion_action_and_safety_boundary() -> None:
    context = _context()
    context["message_structure"]["health_nlu"].update({
        "primary_intent": "symptom_triage",
        "concept_keys": ["headache"],
    })
    route = resolve_chat_route(context["message_structure"])
    long_background = "这是背景说明。" * 30
    result = _result("睡眠不足可以诱发头痛。建议今天补水并休息。" + long_background)

    guarded = guard_chat_result(result, context=context, route=route, user_query="头痛", history=[])

    assert guarded.result.summary.startswith("睡眠不足可以诱发头痛。建议今天补水并休息。")
    assert "一侧无力" in guarded.result.summary
    assert len(guarded.result.summary) < 230
    assert "summary_compacted" in guarded.quality_flags
