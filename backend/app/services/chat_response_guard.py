from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.providers.base import ChatLLMResult
from app.services.chat_evidence import build_evidence_limited_reply
from app.services.chat_routing import ChatRouteDecision
from app.services.symptom_triage import missing_symptom_boundary


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)
_ISO_TIME_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?|\n+")
_SAFETY_SENTENCE_RE = re.compile(r"急诊|急救|立即就医|呼吸困难|胸痛|昏厥|自伤|自杀|不想活|大出血")
_OVERREASSURANCE_RE = re.compile(r"排除.{0,8}(?:严重|急症|疾病)|肯定没事|绝对安全|完全不用担心|不会有事")
_GENERIC_OFFER_RE = re.compile(r"要不要我帮你|需要我帮你|要我帮你|想不想让我|我可以帮你.{0,20}吗")
_ACTION_RE = re.compile(r"建议|现在|先|可以先|需要|保持|补充|复测|记录|避免")


@dataclass(frozen=True)
class GuardOutcome:
    result: ChatLLMResult
    quality_flags: tuple[str, ...]


def guard_chat_result(
    result: ChatLLMResult,
    *,
    context: dict,
    route: ChatRouteDecision,
    user_query: str,
    history: list[dict] | None = None,
) -> GuardOutcome:
    """Sanitize and validate user-visible model output before persistence."""

    flags: list[str] = []
    summary = _sanitize_text(result.summary or result.answer_markdown)
    analysis = _sanitize_text(result.analysis or summary)

    if "provider_error" in result.safety_flags:
        summary = "这次回答没有完整生成，请稍后重试。你的消息已经保留，不需要重新输入。"
        analysis = "模型服务暂时不可用。请稍后点击原消息下方的重试，小捷会沿用同一会话和数据范围继续处理。"
        flags.append("provider_error_redacted")

    structure = context.get("message_structure") or {}
    evidence = (structure.get("response_plan") or {}).get("evidence_sufficiency") or {}
    if route.primary_intent == "trend_analysis" and evidence.get("status") in {"missing", "insufficient"}:
        replacement = build_evidence_limited_reply(evidence)
        summary = replacement["summary"]
        analysis = replacement["analysis"]
        flags.append("insufficient_trend_claim_replaced")

    primary_intent = str((structure.get("health_nlu") or {}).get("primary_intent") or "")
    if primary_intent == "symptom_triage":
        summary, changed_summary = _remove_sentences(summary, lambda sentence: bool(_OVERREASSURANCE_RE.search(sentence)))
        analysis, changed_analysis = _remove_sentences(analysis, lambda sentence: bool(_OVERREASSURANCE_RE.search(sentence)))
        if changed_summary or changed_analysis:
            boundary = "目前只能确认你没有出现已明确否认的红旗信号，仍需按当前症状及其他相关红旗继续观察。"
            summary = _append_if_missing(summary, boundary)
            analysis = _append_if_missing(analysis, boundary)
            flags.append("overreassurance_removed")
        concept_keys = list((structure.get("health_nlu") or {}).get("concept_keys") or [])
        symptom_boundary = missing_symptom_boundary(concept_keys, summary + "\n" + analysis)
        if symptom_boundary:
            summary = _append_if_missing(summary, symptom_boundary)
            analysis = _append_if_missing(analysis, symptom_boundary)
            flags.append("symptom_boundary_added")

    subject = structure.get("active_subject") or {}
    if subject.get("type") != "self":
        summary, removed_summary = _remove_relative_self_data(summary, structure, user_query)
        analysis, removed_analysis = _remove_relative_self_data(analysis, structure, user_query)
        if removed_summary or removed_analysis:
            prefix = f"当前问题主体是{subject.get('display') or '家属'}，我不会把你账号里的本人数据套到这个病例上。"
            summary = prefix + summary.lstrip()
            if prefix not in analysis:
                analysis = prefix + "\n\n" + analysis.lstrip()
            flags.append("relative_self_data_removed")

    connected = (structure.get("data_source_memory") or {}).get("connected") or {}
    if connected.get("apple_health"):
        summary, changed_summary = _remove_device_requestions(summary, "apple_health")
        analysis, changed_analysis = _remove_device_requestions(analysis, "apple_health")
        if changed_summary or changed_analysis:
            confirmation = "已确认 Apple 健康数据已接入，后续会直接使用已入库指标。"
            summary = _append_if_missing(summary, confirmation)
            analysis = _append_if_missing(analysis, confirmation)
            flags.append("apple_health_requestion_removed")
    if connected.get("cgm"):
        summary, changed_summary = _remove_device_requestions(summary, "cgm")
        analysis, changed_analysis = _remove_device_requestions(analysis, "cgm")
        if changed_summary or changed_analysis:
            confirmation = "已确认连续血糖数据来源已接入，趋势分析会直接使用已入库记录。"
            summary = _append_if_missing(summary, confirmation)
            analysis = _append_if_missing(analysis, confirmation)
            flags.append("cgm_requestion_removed")

    repetition = (structure.get("session_memory") or {}).get("repetition_policy") or {}
    if repetition.get("mode") == "delta_only":
        summary, removed = _remove_exact_repetition(summary, history or [])
        if removed:
            flags.append("exact_session_repetition_removed")

    summary, removed_offer_summary = _remove_sentences(summary, lambda sentence: bool(_GENERIC_OFFER_RE.search(sentence)))
    analysis, removed_offer_analysis = _remove_sentences(analysis, lambda sentence: bool(_GENERIC_OFFER_RE.search(sentence)))
    if removed_offer_summary or removed_offer_analysis:
        flags.append("generic_offer_removed")

    if not summary.strip():
        summary = _safe_fallback(structure, route)
        flags.append("empty_summary_replaced")
    if not analysis.strip():
        analysis = summary
        flags.append("empty_analysis_replaced")

    followups = _sanitize_followups(result.followups, max_items=route.max_followups)
    if len(followups) != len(result.followups):
        flags.append("followups_filtered")

    summary, compacted = _compact_summary(summary, route=route)
    if compacted:
        flags.append("summary_compacted")

    guarded = result.model_copy(update={
        "answer_markdown": analysis,
        "summary": summary,
        "analysis": analysis,
        "followups": followups,
        "safety_flags": list(dict.fromkeys(result.safety_flags + [f"quality_guard:{flag}" for flag in flags])),
    })
    return GuardOutcome(result=guarded, quality_flags=tuple(dict.fromkeys(flags)))


def _sanitize_text(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json|markdown)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    value = _EMOJI_RE.sub("", value)
    replacements = {
        "apple_health": "Apple 健康",
        "healthkit": "Apple 健康",
        "vendor_cgm": "连续血糖设备",
        "fresh": "数据较新",
        "stale": "数据需更新",
        "outdated": "数据已过期",
        "manual": "手动记录",
    }
    for internal, display in replacements.items():
        value = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(internal)}(?![A-Za-z0-9_])", display, value, flags=re.IGNORECASE)
    value = _ISO_TIME_RE.sub(lambda match: _format_iso_time(match.group(0)), value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _format_iso_time(raw: str) -> str:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Asia/Shanghai"))
        return f"{parsed.year}年{parsed.month}月{parsed.day}日 {parsed.hour:02d}:{parsed.minute:02d}"
    except ValueError:
        return raw


def _remove_relative_self_data(text: str, structure: dict, user_query: str) -> tuple[str, bool]:
    fact_index = structure.get("health_fact_index") or {}
    leak_tokens = [
        "你的尿酸", "你的血糖", "你的 TIR", "你的TIR", "你的血压", "你的 HRV", "你的HRV",
        "你目前的尿酸", "你目前的血糖", "你最近的尿酸", "你最近的血糖",
    ]
    query_compact = re.sub(r"\s+", "", user_query.lower())
    for fact in fact_index.get("facts") or []:
        metric = str(fact.get("metric") or "").strip()
        value = fact.get("value")
        unit = str(fact.get("unit") or "").strip()
        if value is None:
            continue
        value_text = f"{value:g}" if isinstance(value, float) else str(value)
        candidates = [f"{metric}{value_text}"] if metric else []
        if unit:
            candidates.extend([f"{value_text}{unit}", f"{value_text} {unit}"])
        for candidate in candidates:
            if re.sub(r"\s+", "", candidate.lower()) not in query_compact:
                leak_tokens.append(candidate)

    return _remove_sentences(text, lambda sentence: any(token.lower() in sentence.lower() for token in leak_tokens))


def _remove_device_requestions(text: str, source: str) -> tuple[str, bool]:
    if source == "apple_health":
        pattern = re.compile(
            r"(?:你|平时).{0,8}(?:戴|有|使用|同步).{0,12}(?:Apple\s*Watch|苹果手表|Apple\s*健康|苹果健康|HealthKit)|"
            r"(?:把|发).{0,16}HRV.{0,10}(?:截图|趋势)",
            re.IGNORECASE,
        )
    else:
        pattern = re.compile(r"(?:你|平时).{0,10}(?:有|使用|佩戴|接入).{0,12}(?:CGM|连续血糖|血糖设备|血糖传感器)", re.IGNORECASE)
    return _remove_sentences(text, lambda sentence: bool(pattern.search(sentence)))


def _remove_exact_repetition(text: str, history: list[dict]) -> tuple[str, bool]:
    previous = "\n".join((item.get("content") or "") for item in history[-8:] if item.get("role") == "assistant")
    previous_normalized = _normalize_for_repeat(previous)
    if not previous_normalized:
        return text, False

    def is_repeated(sentence: str) -> bool:
        normalized = _normalize_for_repeat(sentence)
        return len(normalized) >= 10 and normalized in previous_normalized and not _SAFETY_SENTENCE_RE.search(sentence)

    return _remove_sentences(text, is_repeated)


def _remove_sentences(text: str, predicate) -> tuple[str, bool]:
    parts = _SENTENCE_RE.findall(text)
    kept: list[str] = []
    removed = False
    for part in parts:
        if part.strip() and predicate(part):
            removed = True
            continue
        kept.append(part)
    return "".join(kept).strip(), removed


def _compact_summary(text: str, *, route: ChatRouteDecision) -> tuple[str, bool]:
    limit = 230
    if len(text) <= limit:
        return text, False

    sentences = [part.strip() for part in _SENTENCE_RE.findall(text) if part.strip()]
    if not sentences:
        return text[:limit].rstrip(), True

    selected = [sentences[0]]
    action = next((item for item in sentences[1:] if _ACTION_RE.search(item) and not _SAFETY_SENTENCE_RE.search(item)), None)
    if action and action not in selected:
        selected.append(action)
    for item in sentences[1:]:
        if (_SAFETY_SENTENCE_RE.search(item) or "红旗" in item or "一侧无力" in item) and item not in selected:
            selected.append(item)
    compact = "".join(selected)
    return compact if compact else text[:limit].rstrip(), True


def _sanitize_followups(items: list[str], *, max_items: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    ai_question = re.compile(r"^(你|请问|能否|是否|有没有|告诉我|可以告诉我|要不要告诉我|方便说说)")
    for raw in items or []:
        item = _sanitize_text(str(raw)).strip(" -\n")
        if not item or ai_question.search(item) or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= max_items:
            break
    return result


def _append_if_missing(text: str, sentence: str) -> str:
    if sentence in text:
        return text
    if not text:
        return sentence
    return text.rstrip() + ("" if text.rstrip().endswith(("。", "！", "？")) else "。") + sentence


def _normalize_for_repeat(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:\-_*#`]+", "", (text or "").lower())


def _safe_fallback(structure: dict, route: ChatRouteDecision) -> str:
    subject = structure.get("active_subject") or {}
    concepts = (structure.get("health_nlu") or {}).get("matched_concepts") or []
    concept_text = "、".join(str(item.get("display")) for item in concepts[:3] if item.get("display")) or "这个健康问题"
    if subject.get("type") != "self":
        return f"当前问题主体是{subject.get('display') or '家属'}。我会只根据你这轮提供的{concept_text}信息回答，不会引用你账号里的本人数据。"
    if route.safety_level in {"high", "emergency"}:
        return "这次回答没有通过安全校验。请先按页面上的风险提示处理，并稍后重试完整分析。"
    return "这次回答没有完整生成，请稍后重试。你的消息和当前会话已经保留。"
