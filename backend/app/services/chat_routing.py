from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal


ROUTER_VERSION = "2026-07-10"

RouteStrategy = Literal["emergency", "deterministic", "clarification", "llm"]


@dataclass(frozen=True)
class ChatRouteDecision:
    version: str
    route_id: str
    strategy: RouteStrategy
    handler: str | None
    primary_intent: str
    depth: str
    safety_level: str
    subject_type: str
    needs_llm: bool
    needs_literature: bool
    max_followups: int
    progress_steps: tuple[str, ...]
    reason_codes: tuple[str, ...]
    fallback_route: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["progress_steps"] = list(self.progress_steps)
        payload["reason_codes"] = list(self.reason_codes)
        return payload


def resolve_chat_route(message_structure: dict, *, safety_flags: list[str] | None = None) -> ChatRouteDecision:
    """Resolve one canonical execution route for a chat turn.

    The router consumes the deterministic message envelope. It never reads raw
    database models and never calls an LLM, which keeps the decision auditable
    and identical for synchronous and SSE endpoints.
    """

    safety_flags = safety_flags or []
    nlu = message_structure.get("health_nlu") or {}
    intent = message_structure.get("intent") or {}
    plan = message_structure.get("response_plan") or {}
    subject = message_structure.get("active_subject") or {}
    data_memory = message_structure.get("data_source_memory") or {}

    primary_intent = str(nlu.get("primary_intent") or intent.get("semantic_intent") or intent.get("kind") or "general_chat")
    depth = str(nlu.get("depth_hint") or intent.get("depth") or "standard")
    safety_level = str((nlu.get("safety_profile") or {}).get("level") or intent.get("safety_level") or "low")
    subject_type = str(subject.get("type") or "self")
    progress_steps = tuple(str(step) for step in (plan.get("progress_steps") or []) if str(step).strip())
    reason_codes = [f"intent:{primary_intent}", f"subject:{subject_type}", f"safety:{safety_level}"]

    if safety_level == "emergency" or "emergency_symptom" in safety_flags:
        return _decision(
            route_id="safety.emergency",
            strategy="emergency",
            handler="emergency_template",
            primary_intent=primary_intent,
            depth="quick",
            safety_level="emergency",
            subject_type=subject_type,
            progress_steps=("已识别紧急风险信号", "正在生成立即处理指引"),
            reason_codes=reason_codes + ["priority:emergency"],
        )

    numeric_risk = nlu.get("numeric_risk") or {}
    if safety_level == "high" and (numeric_risk.get("reason_codes") or []):
        return _decision(
            route_id="safety.high_numeric",
            strategy="deterministic",
            handler="high_numeric_risk",
            primary_intent=primary_intent,
            depth="quick",
            safety_level="high",
            subject_type=subject_type,
            progress_steps=("已核对数值、单位和高风险阈值", "正在生成立即处理和复测步骤"),
            reason_codes=reason_codes + ["priority:high_numeric", "execution:deterministic"],
        )

    deterministic_handlers = {
        "greeting": "greeting",
        "data_source_query": "data_source_query",
        "report_status_query": "report_status",
        "subject_correction": "subject_correction",
    }
    handler = deterministic_handlers.get(primary_intent)
    if handler:
        return _decision(
            route_id=f"fast.{handler}",
            strategy="deterministic",
            handler=handler,
            primary_intent=primary_intent,
            depth="quick",
            safety_level=safety_level,
            subject_type=subject_type,
            progress_steps=progress_steps or ("已完成上下文核对", "正在生成直接回复"),
            reason_codes=reason_codes + ["execution:deterministic"],
        )

    if primary_intent == "conflict_analysis" and (data_memory.get("metric_conflicts") or []):
        return _decision(
            route_id="fast.metric_conflict",
            strategy="deterministic",
            handler="metric_conflict",
            primary_intent=primary_intent,
            depth="quick",
            safety_level=safety_level,
            subject_type=subject_type,
            progress_steps=("已核对同一指标的来源和时间", "正在整理差异与复测建议"),
            reason_codes=reason_codes + ["data:material_conflict", "execution:deterministic"],
        )

    evidence = plan.get("evidence_sufficiency") or {}
    if primary_intent == "trend_analysis" and evidence.get("status") in {"missing", "insufficient"}:
        return _decision(
            route_id="fast.insufficient_trend_evidence",
            strategy="deterministic",
            handler="insufficient_trend_evidence",
            primary_intent=primary_intent,
            depth="quick",
            safety_level=safety_level,
            subject_type=subject_type,
            progress_steps=("已核对指标样本数量和覆盖日期", "正在返回可验证的数据结论"),
            reason_codes=reason_codes + [f"evidence:{evidence.get('status')}", "execution:deterministic"],
        )

    if _needs_targeted_clarification(message_structure):
        return _decision(
            route_id="clarify.missing_referent",
            strategy="clarification",
            handler="missing_referent",
            primary_intent=primary_intent,
            depth="quick",
            safety_level=safety_level,
            subject_type=subject_type,
            progress_steps=("当前信息无法唯一对应到健康指标", "正在生成最小必要确认"),
            reason_codes=reason_codes + ["ambiguity:missing_referent"],
        )

    health_related = bool(intent.get("health_related") or nlu.get("has_health_signal"))
    needs_literature = bool(plan.get("needs_literature"))
    route_depth = "deep" if depth == "deep" else "standard"
    if health_related:
        route_id = f"llm.health.{route_depth}"
        reasons = reason_codes + ["execution:llm", f"evidence:{'required' if needs_literature else 'not_required'}"]
    else:
        route_id = "llm.general"
        needs_literature = False
        reasons = reason_codes + ["execution:llm", "domain:general"]

    return _decision(
        route_id=route_id,
        strategy="llm",
        handler=None,
        primary_intent=primary_intent,
        depth=route_depth,
        safety_level=safety_level,
        subject_type=subject_type,
        needs_llm=True,
        needs_literature=needs_literature,
        max_followups=int(plan.get("max_followup_questions") or 1),
        progress_steps=progress_steps or ("已识别问题和上下文", "正在整理回答"),
        reason_codes=reasons,
        fallback_route="fallback.safe_response",
    )


def route_from_structure(message_structure: dict) -> ChatRouteDecision:
    route = message_structure.get("interaction_route") or {}
    if not route:
        return resolve_chat_route(message_structure)
    return ChatRouteDecision(
        version=str(route.get("version") or ROUTER_VERSION),
        route_id=str(route.get("route_id") or "llm.general"),
        strategy=str(route.get("strategy") or "llm"),  # type: ignore[arg-type]
        handler=route.get("handler"),
        primary_intent=str(route.get("primary_intent") or "general_chat"),
        depth=str(route.get("depth") or "standard"),
        safety_level=str(route.get("safety_level") or "low"),
        subject_type=str(route.get("subject_type") or "self"),
        needs_llm=bool(route.get("needs_llm", True)),
        needs_literature=bool(route.get("needs_literature", False)),
        max_followups=max(0, int(route.get("max_followups") or 0)),
        progress_steps=tuple(route.get("progress_steps") or []),
        reason_codes=tuple(route.get("reason_codes") or []),
        fallback_route=route.get("fallback_route"),
    )


def public_route_payload(route: ChatRouteDecision) -> dict:
    """Return route metadata that is useful to clients without prompt internals."""

    return {
        "version": route.version,
        "route_id": route.route_id,
        "strategy": route.strategy,
        "primary_intent": route.primary_intent,
        "depth": route.depth,
        "safety_level": route.safety_level,
        "subject_type": route.subject_type,
        "needs_literature": route.needs_literature,
        "max_followups": route.max_followups,
        "progress_steps": list(route.progress_steps),
    }


def _decision(
    *,
    route_id: str,
    strategy: RouteStrategy,
    handler: str | None,
    primary_intent: str,
    depth: str,
    safety_level: str,
    subject_type: str,
    progress_steps: tuple[str, ...],
    reason_codes: list[str],
    needs_llm: bool = False,
    needs_literature: bool = False,
    max_followups: int = 1,
    fallback_route: str | None = None,
) -> ChatRouteDecision:
    return ChatRouteDecision(
        version=ROUTER_VERSION,
        route_id=route_id,
        strategy=strategy,
        handler=handler,
        primary_intent=primary_intent,
        depth=depth,
        safety_level=safety_level,
        subject_type=subject_type,
        needs_llm=needs_llm,
        needs_literature=needs_literature,
        max_followups=max(0, min(max_followups, 1)),
        progress_steps=progress_steps[:5],
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        fallback_route=fallback_route,
    )


def _needs_targeted_clarification(message_structure: dict) -> bool:
    nlu = message_structure.get("health_nlu") or {}
    user_message = message_structure.get("user_message") or {}
    session_memory = message_structure.get("session_memory") or {}
    text = str(user_message.get("normalized") or "").strip()
    if not text:
        return False
    numeric_risk = nlu.get("numeric_risk") or {}
    for observation in numeric_risk.get("observations") or []:
        if observation.get("metric") == "blood_pressure" and not (
            observation.get("systolic") and observation.get("diastolic")
        ):
            return True
    if "glucose:unit_missing" in (numeric_risk.get("reason_codes") or []):
        return True
    if nlu.get("concept_keys"):
        return False
    if re.fullmatch(r"\d{1,4}(?:\.\d+)?\s*(?:正常吗|高吗|低吗|严重吗)?[？?。!！]*", text):
        return True
    if session_memory.get("covered_facts"):
        return False
    if re.fullmatch(r"(?:这个|那个|它|这项|上面这个|刚才这个)?\s*(?:正常吗|严重吗|危险吗|怎么办|什么意思)[？?。!！]*", text):
        return True
    return False
