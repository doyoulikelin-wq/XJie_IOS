"""Chat router — multi-turn conversations with summary + analysis output."""

import json
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.audit import LLMAuditLog
from app.models.consent import Consent
from app.models.conversation import ChatMessage, Conversation
from app.providers.factory import get_provider
from app.providers.openai_provider import _parse_structured_response
from app.schemas.chat import (
    ChatMessageItem,
    ChatRequest,
    ChatResult,
    ConversationItem,
)
from app.services.context_builder import build_user_context
from app.services.safety_service import detect_safety_flags, emergency_template
from app.utils.hash import context_hash

router = APIRouter()

# ── helpers ──────────────────────────────────────────────


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
) -> None:
    log = LLMAuditLog(
        user_id=user_id,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        prompt_tokens=None,
        completion_tokens=None,
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


def _save_user_message(db: Session, conv: Conversation, text: str) -> ChatMessage:
    seq = conv.message_count + 1
    msg = ChatMessage(conversation_id=conv.id, seq=seq, role="user", content=text)
    conv.message_count = seq
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
    # Auto-title from first assistant summary
    if conv.message_count <= 2 and summary:
        conv.title = summary[:80].rstrip("。，,")
    db.add(msg)
    db.flush()
    return msg


# ── POST /api/chat (sync) ───────────────────────────────


@router.post("", response_model=ChatResult)
def chat(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _check_consent(db, user_id)
    flags = detect_safety_flags(payload.message)
    context = build_user_context(db, user_id)

    conv = _get_or_create_conversation(db, user_id, payload.thread_id)
    history = _load_history(db, conv.id)
    _save_user_message(db, conv, payload.message)

    if "emergency_symptom" in flags:
        _save_assistant_message(db, conv, "检测到紧急症状，请立即就医", emergency_template(), {"safety_flags": flags})
        db.commit()
        _save_audit(db, user_id, "policy", "emergency-template", 0, context, {"message": payload.message, "safety_flags": flags})
        return ChatResult(answer_markdown=emergency_template(), confidence=1.0,
                          followups=["如果你愿意，我可以帮你整理就医时要描述的关键信息。"],
                          safety_flags=flags, used_context=context, thread_id=str(conv.id))

    provider = get_provider()
    t0 = time.perf_counter()
    result = provider.generate_text(context, payload.message, history=history)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    _save_assistant_message(db, conv, result.summary, result.analysis, {"safety_flags": flags, "confidence": result.confidence})
    db.commit()
    _save_audit(db, user_id, provider.provider_name, provider.text_model, latency_ms, context, {"message": payload.message, "safety_flags": flags})

    return ChatResult(answer_markdown=result.answer_markdown, confidence=result.confidence,
                      followups=result.followups, safety_flags=flags + result.safety_flags, used_context=context,
                      thread_id=str(conv.id))


# ── POST /api/chat/stream (SSE) ─────────────────────────


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _check_consent(db, user_id)
    flags = detect_safety_flags(payload.message)
    context = build_user_context(db, user_id)

    conv = _get_or_create_conversation(db, user_id, payload.thread_id)
    history = _load_history(db, conv.id)
    _save_user_message(db, conv, payload.message)
    db.commit()  # persist user msg even if stream crashes

    if "emergency_symptom" in flags:
        summary_text = "检测到紧急症状，请立即就医"
        analysis_text = emergency_template()
        ast_msg = _save_assistant_message(db, conv, summary_text, analysis_text, {"safety_flags": flags})
        db.commit()
        _save_audit(db, user_id, "policy", "emergency-template", 0, context,
                    {"message": payload.message, "safety_flags": flags, "stream": True})

        done_payload = {"summary": summary_text, "analysis": analysis_text,
                        "confidence": 1.0, "followups": ["如果你愿意，我可以帮你整理就医时要描述的关键信息。"],
                        "safety_flags": flags, "thread_id": str(conv.id), "message_id": str(ast_msg.id)}

        def emergency_gen():
            yield f"data: {json.dumps({'type': 'done', 'result': done_payload}, ensure_ascii=False)}\n\n"
        return StreamingResponse(emergency_gen(), media_type="text/event-stream")

    provider = get_provider()
    thread_id_str = str(conv.id)

    def event_stream():
        started = time.perf_counter()
        emitted_parts: list[str] = []
        for chunk in provider.stream_text(context, payload.message, history=history):
            emitted_parts.append(chunk)
            yield f"data: {json.dumps({'type': 'token', 'delta': chunk}, ensure_ascii=False)}\n\n"

        final_text = "".join(emitted_parts).strip()
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = _parse_structured_response(final_text)
        summary = parsed.get("summary", final_text[:60] + "…" if len(final_text) > 60 else final_text)
        analysis = parsed.get("analysis", final_text)

        ast_msg = _save_assistant_message(db, conv, summary, analysis, {"safety_flags": flags, "confidence": 0.85})
        db.commit()
        _save_audit(db, user_id, provider.provider_name, provider.text_model, latency_ms, context,
                    {"message": payload.message, "safety_flags": flags, "stream": True})

        done_payload = {"summary": summary, "analysis": analysis, "confidence": 0.85,
                        "followups": [], "safety_flags": flags,
                        "thread_id": thread_id_str, "message_id": str(ast_msg.id)}
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
    return [
        ChatMessageItem(id=str(m.id), seq=m.seq, role=m.role, content=m.content,
                        analysis=m.analysis, created_at=m.created_at.isoformat() if m.created_at else "")
        for m in msgs
    ]


# ── GET /api/chat/history (legacy compat) ────────────────


@router.get("/history")
def history(thread_id: str):
    _ = thread_id
    return []
