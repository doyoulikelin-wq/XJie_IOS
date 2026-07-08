"""Chat router — multi-turn conversations with summary + analysis output."""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.audit import LLMAuditLog
from app.models.consent import Consent
from app.models.conversation import ChatMessage, Conversation
from app.models.user_profile import UserProfile
from app.providers.factory import get_provider
from app.providers.openai_provider import _parse_structured_response
from app.schemas.chat import (
    ChatMessageItem,
    ChatRequest,
    ChatResult,
    ConversationItem,
)
from app.services.context_builder import build_user_context
from app.services.feature_service import build_skill_prompt, is_feature_enabled
from app.services.literature.retrieval import build_citation_block, retrieve_claims
from app.services.safety_service import detect_safety_flags, emergency_template
from app.utils.hash import context_hash

router = APIRouter()

# ── helpers ──────────────────────────────────────────────

_PROFILE_FIELDS = {"sex", "age", "height_cm", "weight_kg", "display_name"}
_APPLE_HEALTH_SOURCE_KEYS = {"apple_health", "healthkit", "apple"}
_CGM_SOURCE_KEYS = {"cgm", "vendor_cgm", "dexcom", "libre"}
_METRIC_DISPLAY_LABELS = {
    "heart_rate_variability": "HRV",
    "resting_heart_rate": "静息心率",
    "heart_rate": "心率",
    "step_count": "步数",
    "steps": "步数",
    "sleep_analysis": "睡眠",
    "sleep": "睡眠",
    "systolic_blood_pressure": "收缩压",
    "diastolic_blood_pressure": "舒张压",
    "blood_pressure_systolic": "收缩压",
    "blood_pressure_diastolic": "舒张压",
    "blood_glucose": "血糖",
}


def _apply_profile_extraction(db: Session, user_id: int, extracted: dict) -> None:
    """Write AI-extracted profile fields to user_profiles."""
    updates = {k: v for k, v in extracted.items() if k in _PROFILE_FIELDS and v is not None}
    if not updates:
        return
    profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalars().first()
    if not profile:
        profile = UserProfile(user_id=user_id, subject_id=f"auto_{user_id}")
        db.add(profile)
        db.flush()
    for key, val in updates.items():
        # Only update if the field is currently empty
        if getattr(profile, key, None) in (None, "", 0):
            setattr(profile, key, val)
    db.commit()


def _check_consent(db: Session, user_id: int) -> None:
    consent = db.execute(select(Consent).where(Consent.user_id == user_id)).scalars().first()
    if consent is None or not consent.allow_ai_chat:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "AI_CONSENT_REQUIRED",
                "message": "Please enable AI data processing consent in settings",
            },
        )


def _save_audit(
    db: Session,
    user_id: int,
    provider: str,
    model: str,
    latency_ms: int,
    used_context: dict,
    meta: dict,
    *,
    feature: str = "chat",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> None:
    log = LLMAuditLog(
        user_id=user_id,
        provider=provider,
        model=model,
        feature=feature,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        context_hash=context_hash(used_context),
        meta=meta,
    )
    db.add(log)
    db.commit()


def _get_or_create_conversation(
    db: Session, user_id: int, thread_id: str | None,
) -> Conversation:
    if thread_id:
        try:
            tid = int(thread_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid thread_id format")
        conv = db.execute(
            select(Conversation).where(Conversation.id == tid, Conversation.user_id == user_id)
        ).scalars().first()
        if conv:
            return conv
    conv = Conversation(user_id=user_id, title="新对话")
    db.add(conv)
    db.flush()
    return conv


def _load_history(db: Session, conversation_id: int) -> list[dict]:
    msgs = db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.seq.asc())
    ).scalars().all()
    return [{"role": m.role, "content": m.content} for m in msgs]


def _save_user_message(db: Session, conv: Conversation, text: str, client_message_id: str | None = None) -> ChatMessage:
    seq = conv.message_count + 1
    meta = {"client_message_id": client_message_id} if client_message_id else {}
    msg = ChatMessage(conversation_id=conv.id, seq=seq, role="user", content=text, meta=meta)
    conv.message_count = seq
    # Auto-title from first user message
    if conv.message_count <= 1:
        conv.title = text[:80].rstrip("。，,")
    db.add(msg)
    db.flush()
    return msg


def _save_assistant_message(
    db: Session, conv: Conversation, summary: str, analysis: str, meta: dict,
) -> ChatMessage:
    seq = conv.message_count + 1
    msg = ChatMessage(
        conversation_id=conv.id, seq=seq, role="assistant",
        content=summary, analysis=analysis, meta=meta,
    )
    conv.message_count = seq
    db.add(msg)
    db.flush()
    return msg


def _find_client_message(
    db: Session,
    user_id: int,
    client_message_id: str | None,
) -> tuple[Conversation, ChatMessage] | None:
    if not client_message_id:
        return None
    rows = db.execute(
        select(Conversation, ChatMessage)
        .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.desc())
        .limit(200)
    ).all()
    for conv, msg in rows:
        if (msg.meta or {}).get("client_message_id") == client_message_id:
            return conv, msg
    return None


def _assistant_after(db: Session, conv_id: int, user_seq: int) -> ChatMessage | None:
    return db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conv_id,
            ChatMessage.role == "assistant",
            ChatMessage.seq > user_seq,
        )
        .order_by(ChatMessage.seq.asc())
    ).scalars().first()


def _duplicate_chat_result(conv: Conversation, user_msg: ChatMessage, assistant: ChatMessage | None) -> ChatResult:
    if assistant:
        meta = assistant.meta or {}
        return ChatResult(
            summary=assistant.content,
            analysis=assistant.analysis or "",
            answer_markdown=assistant.analysis or assistant.content,
            confidence=float(meta.get("confidence") or 0.85),
            followups=[],
            safety_flags=meta.get("safety_flags") or [],
            used_context={"idempotent_replay": True},
            thread_id=str(conv.id),
            citations=[],
        )
    return ChatResult(
        summary="这条消息已收到，小捷仍在处理中，请稍后查看历史对话。",
        analysis="",
        answer_markdown="这条消息已收到，小捷仍在处理中，请稍后查看历史对话。",
        confidence=0.5,
        followups=[],
        safety_flags=[],
        used_context={"idempotent_replay": True, "pending_user_message_id": str(user_msg.id)},
        thread_id=str(conv.id),
        citations=[],
    )


def _message_structure(context: dict) -> dict:
    return context.get("message_structure") or {}


def _context_needs_literature(context: dict) -> bool:
    structure = _message_structure(context)
    plan = structure.get("response_plan") or {}
    return bool(plan.get("needs_literature", True))


def _fast_chat_reply(context: dict, user_query: str) -> dict | None:
    """Return deterministic replies for low-latency, high-precision turns."""
    structure = _message_structure(context)
    if not structure:
        return None
    intent = structure.get("intent") or {}
    kind = intent.get("kind")
    subject = structure.get("active_subject") or {}
    memory = structure.get("session_memory") or {}
    data_memory = structure.get("data_source_memory") or {}
    sources = data_memory.get("sources") or []
    connected = data_memory.get("connected") or {}
    metric_conflicts = data_memory.get("metric_conflicts") or []
    report_status = structure.get("report_status") or {}

    if kind == "greeting":
        covered = memory.get("covered_facts") or []
        if covered:
            context_hint = "我还记得刚才讨论过 " + "、".join(covered[:3]) + "。"
        else:
            context_hint = "我在，可以继续接着看数据、报告或某个具体问题。"
        summary = f"在。{context_hint}你直接说现在想看哪一块，我会按当前主体和已有数据接着分析，不会重复整段病史摘要。"
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.95,
            "followups": ["继续刚才的问题", "查看我的同步数据"],
            "safety_flags": ["fast_path:greeting"],
        }

    if kind == "data_source_query":
        summary = _build_data_source_reply_summary(sources, connected, user_query)
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.94,
            "followups": ["看最近同步了哪些指标", "帮我解释为什么显示待同步"],
            "safety_flags": ["fast_path:data_source_query"],
        }

    if kind == "report_status_query":
        latest = report_status.get("latest") or {}
        pending_count = int(report_status.get("pending_count") or 0)
        done_count = int(report_status.get("done_count") or 0)
        failed_count = int(report_status.get("failed_count") or 0)
        if latest:
            name = latest.get("name") or "最近上传的报告"
            status = latest.get("extraction_status") or "pending"
            if status == "pending":
                summary = (
                    f"{name} 还在后台识别中。当前有 {pending_count} 份报告待分析，"
                    "识别完成后会进入历史报告，并可打开单份 AI 汇总；这类状态问题我会直接查入库状态，不做重复医学分析。"
                )
            elif status == "done":
                summary = (
                    f"{name} 已完成识别和入库。当前已有 {done_count} 份报告可查看汇总，"
                    "你可以打开历史报告看单份结论，也可以继续问我按时间整理异常指标。"
                )
            elif status == "failed":
                summary = (
                    f"{name} 识别失败。当前失败 {failed_count} 份，建议重新上传更清晰的 PDF 或图片；"
                    "我会保留状态判断，不把未识别报告当成已完成结果。"
                )
            else:
                summary = f"{name} 当前状态是 {status}。我会按上传记录状态回答，不把它当成已经完成的医学分析。"
        else:
            summary = "当前账号还没有查到已上传报告。报告列表会显示待上传；上传 PDF 或图片后，我会先显示识别中，完成后再生成单份汇总。"
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.94,
            "followups": ["打开历史报告", "继续上传一份报告"],
            "safety_flags": ["fast_path:report_status"],
        }

    if kind == "medical_question" and intent.get("semantic_intent") == "conflict_analysis" and metric_conflicts:
        conflict_lines = []
        for conflict in metric_conflicts[:3]:
            metric = conflict.get("metric") or "指标"
            samples = conflict.get("samples") or []
            sample_text = "；".join(_format_conflict_sample(sample) for sample in samples[:3])
            if sample_text:
                conflict_lines.append(f"{metric}：{sample_text}")
        detail = "；".join(conflict_lines)
        summary = (
            f"这次变化不是一个数被覆盖掉了，而是同一指标存在不同来源/时间的记录。{detail}。"
            "先按安静坐位、同一上臂、连续测 2-3 次取平均来复测；如果静息血压仍反复升高，"
            "再把家庭复测记录和设备来源一起给医生看。"
        )
        analysis = (
            summary
            + "\n\n我会保留这些来源差异：手动记录更接近当时测量场景，Apple 健康/设备数据更适合看趋势。"
            "两者时间接近但数值差异明显时，结论要先解释测量姿势、袖带位置、活动后测量、设备算法和记录来源，不能直接合并成单一血压。"
        )
        return {
            "summary": summary,
            "analysis": analysis,
            "confidence": 0.93,
            "followups": ["我按静息复测记录一组血压", "查看血压来源差异"],
            "safety_flags": ["fast_path:metric_conflict"],
        }

    if kind == "correction_followup" and subject.get("relation") == "wife" and "nt" in user_query.lower():
        summary = (
            "明白，这是你妻子的情况，不是你的体检数据。如果这里的 NT 指胎儿颈项透明层检查，"
            "它本身就是孕早期超声筛查，通常在孕 11 到 13 周加 6 天做。能做 NT，一般说明已经确认宫内妊娠并进入对应孕周；"
            "是否正常主要看报告上的孕周、CRL 和 NT 数值，不能用你的尿酸、血糖或 TIR 来判断她的情况。"
        )
        analysis = (
            "当前主体已切换为妻子病例，未授权使用登录用户本人的健康指标。"
            "NT 检查用于孕早期筛查，核心读取项是孕周、CRL 和 NT 值；后续风险判断通常还会结合年龄、血清学筛查或 NIPT/产科医生意见。"
        )
        return {
            "summary": summary,
            "analysis": analysis,
            "confidence": 0.93,
            "followups": ["我把 NT 报告数值发给你看"],
            "safety_flags": ["fast_path:subject_correction"],
        }

    return None


def _build_data_source_reply_summary(sources: list[dict], connected: dict, user_query: str) -> str:
    if _query_mentions_apple_health(user_query):
        source = _latest_source_for_keys(sources, _APPLE_HEALTH_SOURCE_KEYS)
        if connected.get("apple_health") and source:
            detail = _source_detail_sentence(source)
            return (
                f"你已经同步过 Apple 健康。{detail}"
                "后续涉及睡眠、HRV、步数、心率或血压的问题，我会直接使用这些已入库数据，"
                "不再把同步状态当成未知前提。"
            )
        if connected.get("apple_health"):
            return (
                "我能确认 Apple 健康已经接入，但这次没有拿到最近样本时间。"
                "相关指标会按待同步或待更新处理；同步刷新后，我会直接使用睡眠、HRV、步数、心率和血压等数据。"
            )
        return (
            "目前还没有看到已入库的 Apple 健康数据。"
            "同步成功后，我会直接使用睡眠、HRV、步数、心率和血压等指标；在此之前，这些指标会显示为待同步或待上传。"
        )

    if _query_mentions_cgm(user_query):
        source = _latest_source_for_keys(sources, _CGM_SOURCE_KEYS)
        if connected.get("cgm") and source:
            detail = _source_detail_sentence(source)
            return f"你已经有连续血糖数据来源接入。{detail}后续血糖趋势、TIR 和波动分析会直接结合这些数据。"
        if connected.get("cgm"):
            return (
                "你已经有连续血糖数据来源接入，但这次没有拿到最近样本时间。"
                "血糖趋势分析会标注为待同步或待更新，不会当作实时数据。"
            )
        return "目前还没有看到已接入的连续血糖数据来源。接入后，血糖趋势、TIR 和波动分析会直接使用设备数据。"

    source_lines = [_source_overview_line(source) for source in sources[:4]]
    source_lines = [line for line in source_lines if line]
    if not source_lines:
        return "当前账号还没有可确认的硬件或 Apple 健康样本，相关指标会显示为待同步或待上传。"
    return (
        "我现在能直接使用的数据来源包括："
        + "；".join(source_lines)
        + "。后续相关问题会直接结合这些数据，不会重复询问已经确认的同步状态。"
    )


def _query_mentions_apple_health(user_query: str) -> bool:
    text = user_query or ""
    lowered = text.lower()
    return (
        "healthkit" in lowered
        or "apple health" in lowered
        or "苹果健康" in text
        or ("apple" in lowered and "健康" in text)
    )


def _query_mentions_cgm(user_query: str) -> bool:
    text = user_query or ""
    lowered = text.lower()
    return "cgm" in lowered or "连续血糖" in text or "动态血糖" in text or "血糖设备" in text


def _latest_source_for_keys(sources: list[dict], keys: set[str]) -> dict | None:
    matches = [
        source for source in sources
        if str(source.get("source_key") or "").strip().lower() in keys
    ]
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda item: item.get("last_sample_at") or item.get("last_sync_at") or "",
        reverse=True,
    )[0]


def _source_detail_sentence(source: dict) -> str:
    when = _format_user_facing_time(source.get("last_sample_at") or source.get("last_sync_at"))
    metrics = _format_metric_list(source.get("available_metrics") or [], limit=6)
    parts = []
    if when:
        parts.append(f"最近一次可用样本是 {when}")
    else:
        parts.append("目前已有可用记录")
    if metrics:
        parts.append(f"已入库指标包括 {metrics}")
    return "，".join(parts) + "。"


def _source_overview_line(source: dict) -> str:
    label = _source_display_label(source.get("source_key"))
    if not label:
        return ""
    when = _format_user_facing_time(source.get("last_sample_at") or source.get("last_sync_at"))
    metrics = _format_metric_list(source.get("available_metrics") or [], limit=4)
    pieces = [label]
    if when:
        pieces.append(f"最近样本 {when}")
    if metrics:
        pieces.append(f"包含 {metrics}")
    return "，".join(pieces)


def _source_display_label(source_key: str | None) -> str:
    key = str(source_key or "").strip().lower()
    if key in _APPLE_HEALTH_SOURCE_KEYS:
        return "Apple 健康"
    if key in _CGM_SOURCE_KEYS:
        return "连续血糖设备"
    if key == "manual":
        return "手动记录"
    if key in {"document", "report", "health_document"}:
        return "报告/病历"
    return "其他设备" if key else ""


def _format_metric_list(metrics: list, *, limit: int) -> str:
    labels = []
    seen = set()
    for metric in metrics:
        label = _metric_display_label(metric)
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= limit:
            break
    return "、".join(labels)


def _metric_display_label(metric: object) -> str:
    raw = str(metric or "").strip()
    if not raw:
        return ""
    label = _METRIC_DISPLAY_LABELS.get(raw.lower(), raw)
    return "其他指标" if "_" in label else label


def _format_user_facing_time(value: object) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(timezone(timedelta(hours=8)))
    return f"{local_dt.year}年{local_dt.month}月{local_dt.day}日 {local_dt.hour:02d}:{local_dt.minute:02d}"


def _format_conflict_sample(sample: dict) -> str:
    source = _source_display_label(sample.get("source")) or "未知来源"
    value = sample.get("value")
    unit = sample.get("unit") or ""
    when = _format_user_facing_time(sample.get("measured_at")) or "时间未知"
    return f"{source} {value}{unit}（{when}）"


# ── POST /api/chat (sync) ───────────────────────────────


@router.post("", response_model=ChatResult)
def chat(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _check_consent(db, user_id)

    # Feature flag gate
    if not is_feature_enabled("ai_chat", db):
        raise HTTPException(status_code=503, detail="AI 对话功能暂时关闭")

    duplicate = _find_client_message(db, user_id, payload.client_message_id)
    if duplicate:
        conv, user_msg = duplicate
        return _duplicate_chat_result(conv, user_msg, _assistant_after(db, conv.id, user_msg.seq))

    conv = _get_or_create_conversation(db, user_id, payload.thread_id)
    history = _load_history(db, conv.id)
    flags = detect_safety_flags(payload.message)
    context = build_user_context(
        db,
        user_id,
        conversation_id=conv.id,
        user_query=payload.message,
        history=history,
    )
    _save_user_message(db, conv, payload.message, payload.client_message_id)

    if "emergency_symptom" in flags:
        _save_assistant_message(db, conv, "检测到紧急症状，请立即就医", emergency_template(), {"safety_flags": flags})
        db.commit()
        _save_audit(db, user_id, "policy", "emergency-template", 0, context,
                    {"message": payload.message, "safety_flags": flags, "client_message_id": payload.client_message_id})
        emergency_summary = "检测到紧急症状，请立即就医"
        emergency_analysis = emergency_template()
        return ChatResult(summary=emergency_summary, analysis=emergency_analysis,
                          answer_markdown=emergency_analysis, confidence=1.0,
                          followups=["如果你愿意，我可以帮你整理就医时要描述的关键信息。"],
                          safety_flags=flags, used_context=context, thread_id=str(conv.id))

    fast_reply = _fast_chat_reply(context, payload.message)
    if fast_reply:
        _save_assistant_message(
            db,
            conv,
            fast_reply["summary"],
            fast_reply["analysis"],
            {
                "safety_flags": flags + fast_reply.get("safety_flags", []),
                "confidence": fast_reply["confidence"],
                "response_plan": (_message_structure(context).get("response_plan") or {}),
            },
        )
        db.commit()
        _save_audit(
            db,
            user_id,
            "policy",
            "message-structure-fast-path",
            0,
            context,
            {"message": payload.message, "safety_flags": flags, "client_message_id": payload.client_message_id},
        )
        return ChatResult(
            summary=fast_reply["summary"],
            analysis=fast_reply["analysis"],
            answer_markdown=fast_reply["analysis"],
            confidence=fast_reply["confidence"],
            followups=fast_reply.get("followups", []),
            safety_flags=flags + fast_reply.get("safety_flags", []),
            used_context=context,
            thread_id=str(conv.id),
            citations=[],
        )

    # Build skill prompt based on user query
    skill_prompt = build_skill_prompt(payload.message, db)

    # Literature RAG (soft constraint): retrieve top citations and append to prompt
    citations = retrieve_claims(db, query=payload.message, top_k=5) if _context_needs_literature(context) else []
    if citations:
        block = build_citation_block(citations)
        skill_prompt = (
            (skill_prompt + "\n\n" if skill_prompt else "")
            + "# 文献证据库（软约束）\n"
            + "以下是与用户问题相关的已发表文献结论。如适用，请在 analysis 中以 [1][2] 角标自然引用，"
            + "并在 analysis 末尾用一段不超过 60 字的「参考文献」小字标注（如：参考: [1] xxx; [2] yyy）。"
            + "如证据不充分或不相关，可不引用，按通用知识回答即可。\n"
            + block
        )

    provider = get_provider()
    t0 = time.perf_counter()
    result = provider.generate_text(context, payload.message, history=history, skill_prompt=skill_prompt)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    _save_assistant_message(
        db,
        conv,
        result.summary,
        result.analysis,
        {
            "safety_flags": flags,
            "confidence": result.confidence,
            "citation_ids": [c.claim_id for c in citations],
        },
    )
    db.commit()

    # Auto-extract profile info from AI response
    if result.profile_extracted:
        _apply_profile_extraction(db, user_id, result.profile_extracted)

    _save_audit(db, user_id, provider.provider_name, provider.text_model, latency_ms, context,
                {"message": payload.message, "safety_flags": flags, "client_message_id": payload.client_message_id},
                feature="chat", prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens)

    return ChatResult(summary=result.summary, analysis=result.analysis,
                      answer_markdown=result.answer_markdown, confidence=result.confidence,
                      followups=result.followups, safety_flags=flags + result.safety_flags, used_context=context,
                      thread_id=str(conv.id), citations=citations)


# ── POST /api/chat/stream (SSE) ─────────────────────────


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _check_consent(db, user_id)

    # Feature flag gate
    if not is_feature_enabled("ai_chat", db):
        raise HTTPException(status_code=503, detail="AI 对话功能暂时关闭")

    duplicate = _find_client_message(db, user_id, payload.client_message_id)
    if duplicate:
        conv, user_msg = duplicate
        result = _duplicate_chat_result(conv, user_msg, _assistant_after(db, conv.id, user_msg.seq))

        def duplicate_gen():
            yield f"data: {json.dumps({'type': 'done', 'result': result.model_dump()}, ensure_ascii=False)}\n\n"

        return StreamingResponse(duplicate_gen(), media_type="text/event-stream")

    conv = _get_or_create_conversation(db, user_id, payload.thread_id)
    history = _load_history(db, conv.id)
    flags = detect_safety_flags(payload.message)
    context = build_user_context(
        db,
        user_id,
        conversation_id=conv.id,
        user_query=payload.message,
        history=history,
    )
    _save_user_message(db, conv, payload.message, payload.client_message_id)
    db.commit()  # persist user msg even if stream crashes

    if "emergency_symptom" in flags:
        summary_text = "检测到紧急症状，请立即就医"
        analysis_text = emergency_template()
        ast_msg = _save_assistant_message(db, conv, summary_text, analysis_text, {"safety_flags": flags})
        db.commit()
        _save_audit(db, user_id, "policy", "emergency-template", 0, context,
                    {"message": payload.message, "safety_flags": flags, "stream": True, "client_message_id": payload.client_message_id})

        done_payload = {"summary": summary_text, "analysis": analysis_text,
                        "confidence": 1.0, "followups": ["如果你愿意，我可以帮你整理就医时要描述的关键信息。"],
                        "safety_flags": flags, "thread_id": str(conv.id), "message_id": str(ast_msg.id)}

        def emergency_gen():
            yield f"data: {json.dumps({'type': 'done', 'result': done_payload}, ensure_ascii=False)}\n\n"
        return StreamingResponse(emergency_gen(), media_type="text/event-stream")

    fast_reply = _fast_chat_reply(context, payload.message)
    if fast_reply:
        ast_msg = _save_assistant_message(
            db,
            conv,
            fast_reply["summary"],
            fast_reply["analysis"],
            {
                "safety_flags": flags + fast_reply.get("safety_flags", []),
                "confidence": fast_reply["confidence"],
                "response_plan": (_message_structure(context).get("response_plan") or {}),
            },
        )
        db.commit()
        _save_audit(
            db,
            user_id,
            "policy",
            "message-structure-fast-path",
            0,
            context,
            {"message": payload.message, "safety_flags": flags, "stream": True, "client_message_id": payload.client_message_id},
            feature="chat",
        )
        done_payload = {
            "summary": fast_reply["summary"],
            "analysis": fast_reply["analysis"],
            "confidence": fast_reply["confidence"],
            "followups": fast_reply.get("followups", []),
            "safety_flags": flags + fast_reply.get("safety_flags", []),
            "thread_id": str(conv.id),
            "message_id": str(ast_msg.id),
            "citations": [],
        }

        def fast_gen():
            yield f"data: {json.dumps({'type': 'done', 'result': done_payload}, ensure_ascii=False)}\n\n"

        return StreamingResponse(fast_gen(), media_type="text/event-stream")

    provider = get_provider()
    thread_id_str = str(conv.id)
    skill_prompt = build_skill_prompt(payload.message, db)

    # Literature RAG
    citations = retrieve_claims(db, query=payload.message, top_k=5) if _context_needs_literature(context) else []
    if citations:
        block = build_citation_block(citations)
        skill_prompt = (
            (skill_prompt + "\n\n" if skill_prompt else "")
            + "# 文献证据库（软约束）\n"
            + "以下是与用户问题相关的已发表文献结论。如适用，请在 analysis 中以 [1][2] 角标自然引用，"
            + "并在 analysis 末尾用一段不超过 60 字的「参考文献」小字标注。"
            + "如证据不充分，可不引用，按通用知识回答即可。\n"
            + block
        )

    def event_stream():
        started = time.perf_counter()
        emitted_parts: list[str] = []
        for chunk in provider.stream_text(context, payload.message, history=history, skill_prompt=skill_prompt):
            emitted_parts.append(chunk)
            yield f"data: {json.dumps({'type': 'token', 'delta': chunk}, ensure_ascii=False)}\n\n"

        final_text = "".join(emitted_parts).strip()
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = _parse_structured_response(final_text)
        summary = parsed.get("summary", final_text[:60] + "…" if len(final_text) > 60 else final_text)
        analysis = parsed.get("analysis", final_text)

        ast_msg = _save_assistant_message(
            db,
            conv,
            summary,
            analysis,
            {
                "safety_flags": flags,
                "confidence": 0.85,
                "citation_ids": [c.claim_id for c in citations],
            },
        )
        db.commit()
        _save_audit(db, user_id, provider.provider_name, provider.text_model, latency_ms, context,
                    {"message": payload.message, "safety_flags": flags, "stream": True, "client_message_id": payload.client_message_id},
                    feature="chat")

        done_payload = {"summary": summary, "analysis": analysis, "confidence": 0.85,
                        "followups": [], "safety_flags": flags,
                        "thread_id": thread_id_str, "message_id": str(ast_msg.id),
                        "citations": [c.model_dump() for c in citations]}
        yield f"data: {json.dumps({'type': 'done', 'result': done_payload}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── GET /api/chat/conversations ──────────────────────────


@router.get("/conversations", response_model=List[ConversationItem])
def list_conversations(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=50),
    offset: int = Query(default=0, ge=0),
):
    convs = db.execute(
        select(Conversation).where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return [
        ConversationItem(id=str(c.id), title=c.title, message_count=c.message_count,
                         updated_at=c.updated_at.isoformat() if c.updated_at else "",
                         created_at=c.created_at.isoformat() if c.created_at else "")
        for c in convs
    ]


# ── GET /api/chat/conversations/{id} ────────────────────


@router.get("/conversations/{conversation_id}", response_model=List[ChatMessageItem])
def get_conversation_messages(
    conversation_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        cid = int(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id")
    conv = db.execute(
        select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
    ).scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = db.execute(
        select(ChatMessage).where(ChatMessage.conversation_id == cid).order_by(ChatMessage.seq.asc())
    ).scalars().all()

    # Hydrate citations from stored claim ids in meta.
    from app.models.literature import Claim
    from app.services.literature.retrieval import format_short_ref

    all_ids: set[int] = set()
    for m in msgs:
        for cid_val in (m.meta or {}).get("citation_ids") or []:
            try:
                all_ids.add(int(cid_val))
            except (TypeError, ValueError):
                continue
    claim_map: dict[int, Claim] = {}
    if all_ids:
        rows = db.execute(select(Claim).where(Claim.id.in_(all_ids))).scalars().all()
        claim_map = {c.id: c for c in rows}

    def _citations_for(meta: dict) -> list:
        bundles = []
        for cid_val in (meta or {}).get("citation_ids") or []:
            try:
                cid_int = int(cid_val)
            except (TypeError, ValueError):
                continue
            claim = claim_map.get(cid_int)
            if not claim or not claim.enabled:
                continue
            lit = claim.literature
            bundles.append({
                "claim_id": claim.id,
                "literature_id": lit.id,
                "claim_text": claim.claim_text,
                "evidence_level": claim.evidence_level,
                "short_ref": format_short_ref(lit),
                "journal": lit.journal,
                "year": lit.year,
                "sample_size": lit.sample_size,
                "confidence": claim.confidence,
                "score": None,
            })
        return bundles

    return [
        ChatMessageItem(id=str(m.id), seq=m.seq, role=m.role, content=m.content,
                        analysis=m.analysis, created_at=m.created_at.isoformat() if m.created_at else "",
                        citations=_citations_for(m.meta or {}))
        for m in msgs
    ]


# ── DELETE /api/chat/conversations/{id} ─────────────────


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    try:
        cid = int(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id")
    conv = db.execute(
        select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
    ).scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return None


# ── GET /api/chat/history (legacy compat) ────────────────


@router.get("/history")
def history(thread_id: str):
    _ = thread_id
    return []
