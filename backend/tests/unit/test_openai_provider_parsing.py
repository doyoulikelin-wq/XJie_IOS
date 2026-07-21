import json
from types import SimpleNamespace

import pytest

from app.providers.openai_provider import OpenAIProvider, _parse_structured_response
from app.services.response_completeness import (
    response_incompleteness_reasons,
    visible_response_incompleteness,
)


def test_smart_quote_json_is_repaired_without_exposing_serialized_object() -> None:
    raw = """
    {
      “summary”: “昨晚睡眠不足可以诱发头痛。”,
      “analysis”: “不能因否认胸痛就说已排除严重问题。”,
      “followups”: [“记录头痛持续时间”],
      "profile_extracted": {}
    }
    """

    parsed = _parse_structured_response(raw)

    assert parsed["_parse_status"] == "repaired"
    assert parsed["summary"] == "昨晚睡眠不足可以诱发头痛。"
    assert parsed["analysis"] == "不能因否认胸痛就说已排除严重问题。"
    assert parsed["followups"] == ["记录头痛持续时间"]
    assert not parsed["summary"].lstrip().startswith("{")


def test_smart_quote_repair_preserves_quoted_prose_inside_value() -> None:
    raw = "{“summary”: “不能得出“一周稳定”结论。”, “analysis”: “按实际样本回答。”, “followups”: []}"

    parsed = _parse_structured_response(raw)

    assert parsed["summary"] == "不能得出“一周稳定”结论。"
    assert parsed["_parse_status"] == "repaired"


def test_unrecoverable_object_returns_retry_contract_not_raw_json() -> None:
    raw = '{"summary": [broken], "analysis": ???}'

    parsed = _parse_structured_response(raw)

    assert parsed["_parse_status"] == "invalid"
    assert parsed["summary"] == "这次回答没有完整生成，请稍后重试。"
    assert raw not in parsed["summary"]


def test_plain_text_provider_response_remains_usable() -> None:
    parsed = _parse_structured_response("先补水并休息，持续加重时就医。")

    assert parsed["_parse_status"] == "plain_text"
    assert parsed["summary"] == "先补水并休息，持续加重时就医。"


def test_truncated_structured_payload_is_marked_incomplete() -> None:
    raw = '{"summary":"这三者可能存在关联，但不宜简单归因于","analysis":"鼻炎会影响睡眠，形成'
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="length",
        depth="deep",
        is_health=True,
    )

    assert parsed["_parse_status"] == "partial_repair"
    assert "finish_reason:length" in reasons
    assert "unclosed_json" in reasons
    assert "deep_analysis_too_short" in reasons


def test_deep_delta_only_accepts_complete_short_increment() -> None:
    summary = "新增判断：目前不能确认夜间低氧，先记录三晚打鼾和憋醒情况。"
    analysis = "这轮只补充下一步：记录打鼾、憋醒和日间嗜睡；若持续出现，再做规范睡眠呼吸评估。"
    raw = json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="stop",
        depth="deep",
        is_health=True,
        delta_only=True,
    )

    assert reasons == []


def test_deep_delta_only_still_rejects_unclosed_and_dangling_payload() -> None:
    raw = '{"summary":"新增判断仍不能归因于","analysis":"下一步包括"'
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="length",
        depth="deep",
        is_health=True,
        delta_only=True,
    )

    assert "finish_reason:length" in reasons
    assert "unclosed_json" in reasons
    assert "dangling_summary" in reasons
    assert "dangling_analysis" in reasons


def test_deep_delta_only_still_rejects_empty_fields() -> None:
    raw = json.dumps({"summary": "", "analysis": "", "followups": [], "profile_extracted": {}})
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="stop",
        depth="deep",
        is_health=True,
        delta_only=True,
    )

    assert "empty_summary" in reasons
    assert "empty_analysis" in reasons


def test_dangling_end_is_detected_around_trailing_citations() -> None:
    for summary in ("但[1]。", "但。[1]", "但[1][2]？！"):
        reasons = visible_response_incompleteness(
            summary,
            "分析已经完整。",
            depth="deep",
            is_health=True,
            delta_only=True,
        )

        assert "dangling_summary" in reasons


def test_complete_sentence_with_trailing_citations_is_not_dangling() -> None:
    for summary in (
        "目前不能确认两者存在直接因果关系[1]。",
        "目前不能确认两者存在直接因果关系。[1]",
        "目前不能确认两者存在直接因果关系[1][2]？！",
    ):
        reasons = visible_response_incompleteness(
            summary,
            "分析已经完整。",
            depth="deep",
            is_health=True,
            delta_only=True,
        )

        assert "dangling_summary" not in reasons


def test_causal_concept_coverage_accepts_synonyms_without_section_headings() -> None:
    summary = (
        "血压与脉搏可能会受活动、情绪和测量条件共同影响，但现有信息不能据此确定单一因果方向，"
        "需要结合来源和时间核对。"
    )
    analysis = (
        "血压反映血管压力，脉搏反映每分钟搏动，两者会受到运动、疼痛、睡眠和情绪的共同影响。"
        "一次同时升高只能说明当时存在共同变化，不能证明其中一个直接造成另一个。"
        "先在相同坐姿和安静条件下连续记录数日，并保留每次测量时间、活动状态和设备来源。"
        "如果两项长期同步异常，再由临床人员结合症状、用药和检查判断可能机制；当前回答不依赖固定章节标题。"
    )
    raw = json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="stop",
        depth="deep",
        is_health=True,
        required_concepts=[
            {"key": "blood_pressure", "display": "血压", "terms": ["血压", "BP"]},
            {"key": "heart_rate", "display": "心率", "terms": ["心率", "脉搏", "heart rate"]},
        ],
    )

    assert reasons == []


def test_causal_concept_coverage_reports_only_the_missing_factor() -> None:
    summary = (
        "血压会随活动、情绪和测量条件变化，但现有信息不能据此确定单一因果方向，"
        "需要结合连续记录、来源和时间核对。"
    )
    analysis = (
        "血压是当前唯一被正文实际讨论的核心因素，需要先确认测量姿势、袖带、设备来源和测量时间。"
        "一次升高不能证明稳定趋势，也不能证明某个未说明的生理因素直接造成变化。"
        "下一步在相同条件下连续记录数日，并保留活动、睡眠和用药背景，再判断是否存在一致模式。"
        "如果持续异常或伴随明显不适，应由临床人员结合检查评估，而不是根据单次结果下结论。"
    )
    raw = json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )
    parsed = _parse_structured_response(raw)

    reasons = response_incompleteness_reasons(
        parsed,
        raw=raw,
        finish_reason="stop",
        depth="deep",
        is_health=True,
        required_concepts=[
            {"key": "blood_pressure", "display": "血压", "terms": ["血压", "BP"]},
            {"key": "heart_rate", "display": "心率", "terms": ["心率", "脉搏", "heart rate"]},
        ],
    )

    assert "missing_causal_concept:heart_rate" in reasons
    assert "missing_causal_concept:blood_pressure" not in reasons


def test_causal_concept_coverage_rejects_dismissal_only_mentions() -> None:
    for dismissal in (
        "本轮跳过脊柱侧弯。",
        "脊柱侧弯暂不讨论。",
        "关于脊柱侧弯，本轮不分析。",
        "请忽略脊柱侧弯。",
    ):
        parsed = {
            "summary": "本轮先分析鼻炎可能增加夜间呼吸阻力。",
            "analysis": dismissal + "鼻炎仍需结合鼻塞严重度判断。",
            "_parse_status": "valid",
        }

        reasons = response_incompleteness_reasons(
            parsed,
            depth="deep",
            is_health=True,
            delta_only=True,
            required_concepts=[
                {"key": "rhinitis", "display": "鼻炎", "terms": ["鼻炎", "鼻塞"]},
                {"key": "scoliosis", "display": "脊柱侧弯", "terms": ["脊柱侧弯", "脊柱侧凸"]},
            ],
        )

        assert "missing_causal_concept:scoliosis" in reasons
        assert "missing_causal_concept:rhinitis" not in reasons


def test_dismissal_of_one_concept_does_not_poison_another_in_same_sentence() -> None:
    parsed = {
        "summary": "本轮不讨论脊柱侧弯，但鼻炎可能影响睡眠。",
        "analysis": "鼻炎或鼻塞可能增加夜间呼吸阻力，仍需结合症状和时间变化判断。",
        "_parse_status": "valid",
    }

    reasons = response_incompleteness_reasons(
        parsed,
        depth="deep",
        is_health=True,
        delta_only=True,
        required_concepts=[
            {"key": "rhinitis", "display": "鼻炎", "terms": ["鼻炎", "鼻塞"]},
            {"key": "scoliosis", "display": "脊柱侧弯", "terms": ["脊柱侧弯", "脊柱侧凸"]},
        ],
    )

    assert "missing_causal_concept:scoliosis" in reasons
    assert "missing_causal_concept:rhinitis" not in reasons


def test_nondismissal_causal_judgment_counts_despite_an_earlier_skip() -> None:
    parsed = {
        "summary": "本轮先不分析心率。",
        "analysis": "现有信息不能确认心率与血压存在直接因果关系，需要按相同条件连续记录。",
        "_parse_status": "valid",
    }

    reasons = response_incompleteness_reasons(
        parsed,
        depth="deep",
        is_health=True,
        delta_only=True,
        required_concepts=[
            {"key": "blood_pressure", "display": "血压", "terms": ["血压", "BP"]},
            {"key": "heart_rate", "display": "心率", "terms": ["心率", "脉搏"]},
        ],
    )

    assert "missing_causal_concept:heart_rate" not in reasons
    assert "missing_causal_concept:blood_pressure" not in reasons


def test_pronominal_dismissal_binds_to_the_preceding_concept_mention() -> None:
    required = [{"key": "heart_rate", "display": "心率", "terms": ["心率", "脉搏"]}]

    for analysis in (
        "问题还提到了心率，但本次不讨论它。",
        "问题还提到了心率；本次不讨论它。",
        "问题还提到了心率。本次不讨论它。",
    ):
        reasons = response_incompleteness_reasons(
            {"summary": "需要逐项判断。", "analysis": analysis, "_parse_status": "valid"},
            depth="deep",
            is_health=True,
            delta_only=True,
            required_concepts=required,
        )

        assert "missing_causal_concept:heart_rate" in reasons


def test_pronominal_causal_judgment_is_substantive_coverage() -> None:
    reasons = response_incompleteness_reasons(
        {
            "summary": "需要逐项判断。",
            "analysis": "问题提到了心率，但目前不能确认它与血压有直接因果关系。",
            "_parse_status": "valid",
        },
        depth="deep",
        is_health=True,
        delta_only=True,
        required_concepts=[
            {"key": "blood_pressure", "display": "血压", "terms": ["血压", "BP"]},
            {"key": "heart_rate", "display": "心率", "terms": ["心率", "脉搏"]},
        ],
    )

    assert "missing_causal_concept:heart_rate" not in reasons
    assert "missing_causal_concept:blood_pressure" not in reasons


def test_generate_text_accepts_complete_short_deep_delta_without_retry() -> None:
    summary = "新增判断：目前不能确认夜间低氧，先记录三晚打鼾和憋醒情况。"
    analysis = "这轮只补充下一步：记录打鼾、憋醒和日间嗜睡；若持续出现，再做规范睡眠呼吸评估。"
    assert len(summary) < 45
    assert len(analysis) < 160
    complete = json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )
    completions = _FakeCompletions([_fake_response(complete, finish_reason="stop")])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        {
            "message_structure": {
                "interaction_route": {"depth": "deep", "safety_level": "medium"},
                "health_nlu": {
                    "primary_intent": "causal_assessment",
                    "concept_keys": ["insomnia", "sleep_disordered_breathing", "hypoxia"],
                    "matched_concepts": [
                        {"key": "sleep_disordered_breathing", "display": "睡眠呼吸障碍"},
                        {"key": "hypoxia", "display": "缺氧/低氧"},
                    ],
                    "compound_assessment": {
                        "required": True,
                        "concepts": [
                            {"key": "rhinitis", "display": "鼻炎"},
                            {"key": "scoliosis", "display": "脊柱侧弯"},
                            {"key": "sleep_disordered_breathing", "display": "睡眠呼吸障碍"},
                            {"key": "hypoxia", "display": "缺氧/低氧"},
                        ],
                    },
                },
                "session_memory": {"repetition_policy": {"mode": "delta_only"}},
                "response_plan": {"allowed_context": ["user_self_health_facts"]},
                "active_subject": {"type": "self"},
            }
        },
        "那我下一步先做什么",
        history=[{"role": "assistant", "content": "上一轮已经解释了鼻炎、打鼾与夜间低氧的因果链。"}],
    )

    assert result.summary == summary
    assert result.analysis == analysis
    assert "provider_error" not in result.safety_flags
    assert len(completions.calls) == 1


def test_generate_text_retries_incomplete_payload_with_thinking_disabled() -> None:
    incomplete = '{"summary":"这三者可能存在关联，但不宜简单归因于","analysis":"鼻炎会影响睡眠，形成'
    summary = "这些问题可能相互影响，但不能把失眠和抑郁直接归因于鼻炎或脊柱侧弯造成的缺氧；需要分别核对每条证据链。"
    analysis = (
        "鼻炎与失眠存在关联，鼻塞可增加夜间呼吸阻力并打断睡眠，但鼻炎本身不能证明低氧。"
        "脊柱侧弯只有在程度严重、胸廓受限并伴肺活量下降或低通气时，才支持夜间低氧这一机制。"
        "失眠与抑郁还存在双向影响，因此不能用一个缺氧假设解释全部症状。"
        "下一步先记录打鼾、憋醒和日间嗜睡，完成耳鼻喉评估；若有相关信号，再做规范睡眠监测和肺功能检查。"
        "若出现明显呼吸困难、自伤念头或日常功能显著受损，应及时线下就医。"
    )
    complete = json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )
    completions = _FakeCompletions([
        _fake_response(incomplete, finish_reason="length"),
        _fake_response(complete, finish_reason="stop"),
    ])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        {
            "message_structure": {
                "interaction_route": {"depth": "deep", "safety_level": "medium"},
                "health_nlu": {"primary_intent": "causal_assessment", "concept_keys": []},
                "response_plan": {"allowed_context": ["user_self_health_facts"]},
                "active_subject": {"type": "self"},
            }
        },
        "我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系",
    )

    assert result.summary == summary
    assert result.analysis == analysis
    assert "provider_incomplete_retried" in result.safety_flags
    assert "provider_error" not in result.safety_flags
    assert len(completions.calls) == 2
    assert all(call["extra_body"] == {"thinking": {"type": "disabled"}} for call in completions.calls)


def test_generate_text_retries_when_compound_causal_answer_omits_one_factor() -> None:
    missing_summary, missing_analysis = _compound_causal_answer(include_scoliosis=False)
    complete_summary, complete_analysis = _compound_causal_answer(include_scoliosis=True)
    completions = _FakeCompletions([
        _fake_response(_structured_payload(missing_summary, missing_analysis), finish_reason="stop"),
        _fake_response(_structured_payload(complete_summary, complete_analysis), finish_reason="stop"),
    ])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        _compound_causal_context(),
        "我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系",
    )

    assert result.summary == complete_summary
    assert result.analysis == complete_analysis
    assert "provider_incomplete_retried" in result.safety_flags
    assert "provider_error" not in result.safety_flags
    assert len(completions.calls) == 2
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    assert "missing_causal_concept:scoliosis" in retry_prompt
    assert "每个核心概念" in retry_prompt


def test_generate_text_degrades_after_two_causal_coverage_failures() -> None:
    missing_summary, missing_analysis = _compound_causal_answer(include_scoliosis=False)
    missing_payload = _structured_payload(missing_summary, missing_analysis)
    completions = _FakeCompletions([
        _fake_response(missing_payload, finish_reason="stop"),
        _fake_response(missing_payload, finish_reason="stop"),
    ])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        _compound_causal_context(),
        "我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系",
    )

    assert result.summary == "这次回答没有完整生成，请稍后重试。"
    assert {"provider_error", "provider_incomplete"}.issubset(set(result.safety_flags))
    assert len(completions.calls) == 2


def test_generate_text_does_not_apply_causal_coverage_to_general_chat() -> None:
    summary = "可以，先把你想表达的重点告诉我。"
    analysis = "我会根据你的目标整理成清楚、自然的一段文字。"
    completions = _FakeCompletions([
        _fake_response(_structured_payload(summary, analysis), finish_reason="stop"),
    ])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        {
            "message_structure": {
                "interaction_route": {"depth": "standard", "safety_level": "low"},
                "health_nlu": {
                    "primary_intent": "general_chat",
                    "compound_assessment": {
                        "required": False,
                        "concepts": [{"key": "blood_pressure", "display": "血压"}],
                    },
                },
                "response_plan": {"allowed_context": ["current_user_message"]},
                "active_subject": {"type": "self"},
            }
        },
        "帮我写一句问候",
    )

    assert result.summary == summary
    assert "provider_error" not in result.safety_flags
    assert len(completions.calls) == 1


def test_generate_text_never_exposes_partial_payload_after_second_failure() -> None:
    incomplete = '{"summary":"回答到一半但","analysis":"分析仍未完成，形成'
    completions = _FakeCompletions([
        _fake_response(incomplete, finish_reason="length"),
        _fake_response(incomplete, finish_reason="length"),
    ])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.generate_text(
        {
            "message_structure": {
                "interaction_route": {"depth": "deep", "safety_level": "medium"},
                "health_nlu": {"primary_intent": "causal_assessment", "concept_keys": []},
                "response_plan": {"allowed_context": ["user_self_health_facts"]},
                "active_subject": {"type": "self"},
            }
        },
        "我的失眠抑郁是不是跟鼻炎脊柱侧弯导致缺氧有关系",
    )

    assert result.summary == "这次回答没有完整生成，请稍后重试。"
    assert incomplete not in result.answer_markdown
    assert {"provider_error", "provider_incomplete"}.issubset(set(result.safety_flags))
    assert result.prompt_tokens == 200
    assert result.completion_tokens == 400
    assert len(completions.calls) == 2


def _structured_payload(summary: str, analysis: str) -> str:
    return json.dumps(
        {"summary": summary, "analysis": analysis, "followups": [], "profile_extracted": {}},
        ensure_ascii=False,
    )


def _compound_causal_context() -> dict:
    concepts = [
        {"key": "insomnia", "display": "失眠"},
        {"key": "low_mood", "display": "情绪低落"},
        {"key": "rhinitis", "display": "鼻炎"},
        {"key": "scoliosis", "display": "脊柱侧弯"},
        {"key": "hypoxia", "display": "缺氧/低氧"},
    ]
    return {
        "message_structure": {
            "interaction_route": {"depth": "deep", "safety_level": "medium"},
            "health_nlu": {
                "primary_intent": "causal_assessment",
                "concept_keys": [item["key"] for item in concepts],
                "matched_concepts": concepts,
                "compound_assessment": {
                    "required": True,
                    "concepts": concepts,
                    "required_sections": [
                        "direct_answer",
                        "supported_links",
                        "unproven_links",
                        "objective_evaluation",
                        "safety_boundary",
                    ],
                },
            },
            "session_memory": {"repetition_policy": {"mode": "normal"}},
            "response_plan": {"allowed_context": ["user_self_health_facts"]},
            "active_subject": {"type": "self"},
        }
    }


def _compound_causal_answer(*, include_scoliosis: bool) -> tuple[str, str]:
    scoliosis_summary = "脊柱侧弯需要按严重度单独判断；" if include_scoliosis else ""
    scoliosis_analysis = (
        "脊柱侧弯只有在程度严重并伴胸廓或呼吸受限时，才可能参与夜间呼吸问题，也不能据此直接确认缺氧。"
        if include_scoliosis
        else ""
    )
    summary = (
        "鼻炎可能影响睡眠，失眠和抑郁也可能相互维持；"
        + scoliosis_summary
        + "现有信息不能确认已经缺氧，必须分别核对每条路径。"
    )
    analysis = (
        "鼻炎或鼻塞可能增加夜间呼吸阻力并干扰睡眠，但鼻炎本身不能证明缺氧。"
        "失眠与抑郁可能双向影响，因此不能把两者统一归因于一个尚未证实的低氧假设。"
        + scoliosis_analysis
        + "是否缺氧需要规范血氧或睡眠呼吸评估，结果正常会反对低氧链路，持续异常才支持继续检查。"
        "下一步应分别记录鼻塞、睡眠和情绪变化，并根据客观结果调整判断，而不是先设定单一病因。"
    )
    return summary, analysis


class _FakeCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _fake_response(content: str, *, finish_reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )


def test_daily_diet_summary_provider_uses_minimal_strict_payload_and_rejects_invalid_output() -> None:
    valid = json.dumps(
        {
            "balance_assessment": "insufficient_data",
            "conclusion": "昨天只确认了一餐，记录有限，无法代表全天。",
            "today_suggestion": "今天午餐增加一份深色蔬菜，并继续记录其他餐次。",
            "confidence": 0.78,
        },
        ensure_ascii=False,
    )
    completions = _FakeCompletions([_fake_response(valid, finish_reason="stop")])
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = provider.summarize_daily_diet(
        {
            "diet_date": "2026-07-20",
            "confirmed_meal_count": 1,
            "meals": [
                {
                    "meal_type": "lunch",
                    "food_items": [{"name": "米饭", "portion_text": "一碗"}],
                    "structure": {"staple": "present"},
                    "estimated_nutrition": {"energy_kcal_range": [200, 400]},
                    "confidence": 0.8,
                }
            ],
        }
    )

    assert result.balance_assessment == "insufficient_data"
    assert result.today_suggestion == "今天午餐增加一份深色蔬菜，并继续记录其他餐次。"
    assert len(completions.calls) == 1
    call = completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    serialized_messages = json.dumps(call["messages"], ensure_ascii=False)
    assert "聊天历史" not in serialized_messages
    assert "原始图片" not in serialized_messages
    assert "单餐" in serialized_messages

    invalid = _FakeCompletions(
        [
            _fake_response(
                '{"balance_assessment":"certain","conclusion":"完整全天都均衡"}',
                finish_reason="stop",
            )
        ]
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=invalid))
    with pytest.raises(ValueError, match="daily diet summary"):
        provider.summarize_daily_diet(
            {
                "diet_date": "2026-07-20",
                "confirmed_meal_count": 1,
                "meals": [],
            }
        )
