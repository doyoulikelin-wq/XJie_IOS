"""Chat router — multi-turn conversations with summary + analysis output."""

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue
from threading import Thread
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user_id, get_db
from app.db.session import SessionLocal
from app.models.audit import LLMAuditLog
from app.models.consent import Consent
from app.models.conversation import ChatMessage, ChatRequestReceipt, Conversation
from app.models.literature import Claim
from app.models.user_profile import UserProfile
from app.providers.factory import get_provider
from app.providers.base import ChatLLMResult
from app.schemas.chat import (
    ChatMessageItem,
    ChatRequest,
    ChatResult,
    ConversationItem,
)
from app.schemas.literature import CitationBundle
from app.services.context_builder import build_user_context
from app.services.chat_citations import select_citations_for_response
from app.services.chat_evidence import build_evidence_limited_reply
from app.services.chat_response_guard import guard_chat_result
from app.services.chat_routing import (
    ChatRouteDecision,
    public_route_payload,
    resolve_chat_route,
    route_from_structure,
)
from app.services.feature_service import build_skill_prompt, is_feature_enabled
from app.services.health_nlu import concept_alias_groups
from app.services.literature.retrieval import (
    build_citation_block,
    citation_bundle_from_claim,
    retrieve_claims,
)
from app.services.numeric_health_risk import build_high_numeric_risk_reply
from app.services.safety_service import detect_safety_flags, emergency_response
from app.utils.hash import context_hash

router = APIRouter()
logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────

_PROFILE_FIELDS = {"sex", "age", "height_cm", "weight_kg", "display_name"}
_APPLE_HEALTH_SOURCE_KEYS = {"apple_health", "healthkit", "apple"}
_CGM_SOURCE_KEYS = {"cgm", "vendor_cgm", "dexcom", "libre"}
_IDEMPOTENCY_LEASE_SECONDS = 180
_CITATION_SNAPSHOT_VERSION = 1
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
                "message": "需要先同意 AI 健康问答的数据处理授权",
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


def _load_history(db: Session, conversation_id: int, *, before_seq: int | None = None) -> list[dict]:
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before_seq is not None:
        stmt = stmt.where(ChatMessage.seq < before_seq)
    msgs = db.execute(stmt.order_by(ChatMessage.seq.asc())).scalars().all()
    return [{"role": m.role, "content": m.content} for m in msgs]


def _save_user_message(db: Session, conv: Conversation, text: str, client_message_id: str | None = None) -> ChatMessage:
    seq = conv.message_count + 1
    meta = {
        "processing_status": "processing",
        "processing_started_at": datetime.now(timezone.utc).isoformat(),
    }
    if client_message_id:
        meta["client_message_id"] = client_message_id
    msg = ChatMessage(conversation_id=conv.id, seq=seq, role="user", content=text, meta=meta)
    conv.message_count = seq
    # Auto-title from first user message
    if conv.message_count <= 1:
        conv.title = text[:80].rstrip("。，,")
    db.add(msg)
    db.flush()
    return msg


def _mark_user_message_status(user_msg: ChatMessage, status: str) -> None:
    meta = dict(user_msg.meta or {})
    meta["processing_status"] = status
    meta["processing_updated_at"] = datetime.now(timezone.utc).isoformat()
    user_msg.meta = meta


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
    base = (
        select(Conversation, ChatMessage)
        .join(ChatMessage, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, ChatMessage.role == "user")
    )
    try:
        row = db.execute(
            base.where(ChatMessage.meta["client_message_id"].as_string() == client_message_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        ).first()
        if row:
            return row[0], row[1]
    except Exception:  # noqa: BLE001
        logger.debug("JSON client_message_id lookup unavailable; using compatibility scan", exc_info=True)
    rows = db.execute(base.order_by(ChatMessage.created_at.desc()).limit(500)).all()
    for conv, msg in rows:
        if (msg.meta or {}).get("client_message_id") == client_message_id:
            return conv, msg
    return None


def _assistant_after(db: Session, conv_id: int, user_seq: int, user_message_id: int | None = None) -> ChatMessage | None:
    assistants = db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conv_id,
            ChatMessage.role == "assistant",
            ChatMessage.seq > user_seq,
        )
        .order_by(ChatMessage.seq.asc())
    ).scalars().all()
    if user_message_id is not None:
        expected = str(user_message_id)
        for assistant in assistants:
            reply_to = (assistant.meta or {}).get("reply_to_user_message_id")
            if reply_to is not None and str(reply_to) == expected:
                return assistant
    # Legacy rows did not store reply_to_user_message_id.  Only the immediately
    # adjacent assistant is safe to associate; a later answer may belong to a
    # different user turn and must never be replayed across messages.
    for assistant in assistants:
        if assistant.seq == user_seq + 1 and not (assistant.meta or {}).get("reply_to_user_message_id"):
            return assistant
    return None


def _citation_ids(meta: dict | None) -> list[int]:
    ids: list[int] = []
    for raw in (meta or {}).get("citation_ids") or []:
        try:
            claim_id = int(raw)
        except (TypeError, ValueError):
            continue
        if claim_id not in ids:
            ids.append(claim_id)
    return ids


def _load_citation_claims(db: Session, claim_ids: list[int]) -> dict[int, Claim]:
    if not claim_ids:
        return {}
    rows = db.execute(
        select(Claim)
        .options(joinedload(Claim.literature))
        .where(Claim.id.in_(claim_ids))
    ).scalars().all()
    # Legacy ID-only rows follow the current withdrawal state.  If any claim
    # is missing or disabled, _citation_bundles suppresses the whole positional
    # set rather than compressing it into the wrong [N].
    return {claim.id: claim for claim in rows if claim.enabled}


def _citation_bundles(
    claim_ids: list[int],
    claim_map: dict[int, Claim],
) -> list[CitationBundle]:
    if any(claim_id not in claim_map for claim_id in claim_ids):
        # Never compress a legacy sparse ID list: doing so would change the
        # positional [N] contract and could bind a surviving card to the wrong
        # sentence.  New messages use immutable snapshots below.
        return []
    return [
        citation_bundle_from_claim(claim_map[claim_id])
        for claim_id in claim_ids
    ]


def _citation_snapshots(meta: dict | None) -> list[CitationBundle] | None:
    if "citation_snapshots" not in (meta or {}):
        return None
    if (meta or {}).get("citation_snapshot_version") != _CITATION_SNAPSHOT_VERSION:
        logger.warning("stored citation snapshot has an unsupported version; suppressing evidence cards")
        return []
    raw_snapshots = (meta or {}).get("citation_snapshots")
    if not isinstance(raw_snapshots, list):
        return []
    snapshots: list[CitationBundle] = []
    try:
        for raw in raw_snapshots:
            snapshots.append(CitationBundle.model_validate(raw))
    except (TypeError, ValueError, ValidationError):
        logger.warning("stored citation snapshot is invalid; suppressing evidence cards")
        return []
    snapshot_ids = [snapshot.claim_id for snapshot in snapshots]
    if len(snapshot_ids) != len(set(snapshot_ids)) or snapshot_ids != _citation_ids(meta):
        logger.warning("stored citation snapshot IDs do not match citation_ids; suppressing evidence cards")
        return []
    # Snapshots deliberately preserve exactly what supported the historical
    # answer, even if the live claim is later edited or disabled.  A future
    # withdrawal policy should be explicit rather than silently re-binding [N].
    return snapshots


def _citations_for_meta(
    meta: dict | None,
    claim_map: dict[int, Claim],
) -> list[CitationBundle]:
    snapshots = _citation_snapshots(meta)
    if snapshots is not None:
        return snapshots
    return _citation_bundles(_citation_ids(meta), claim_map)


def _message_citations(db: Session, message: ChatMessage) -> list[CitationBundle]:
    snapshots = _citation_snapshots(message.meta or {})
    if snapshots is not None:
        return snapshots
    claim_ids = _citation_ids(message.meta or {})
    return _citation_bundles(claim_ids, _load_citation_claims(db, claim_ids))


def _duplicate_chat_result(
    db: Session,
    conv: Conversation,
    user_msg: ChatMessage,
    assistant: ChatMessage | None,
) -> ChatResult:
    if assistant:
        meta = assistant.meta or {}
        stored_confidence = meta.get("confidence")
        return ChatResult(
            summary=str(meta.get("summary") or assistant.content),
            analysis=assistant.analysis or "",
            answer_markdown=str(meta.get("answer_markdown") or assistant.analysis or assistant.content),
            confidence=float(stored_confidence) if stored_confidence is not None else 0.85,
            followups=list(meta.get("followups") or []),
            safety_flags=meta.get("safety_flags") or [],
            used_context={"idempotent_replay": True},
            thread_id=str(conv.id),
            message_id=str(assistant.id),
            interaction_route=meta.get("interaction_route"),
            quality_flags=meta.get("quality_flags") or [],
            response_state=str(meta.get("response_state") or "completed"),
            citations=_message_citations(db, assistant),
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
        response_state="processing",
        citations=[],
    )


@dataclass(frozen=True)
class _RequestClaim:
    receipt: ChatRequestReceipt | None
    owns_lease: bool
    created: bool
    lease_id: str | None


def _claim_request_receipt(db: Session, user_id: int, payload: ChatRequest) -> _RequestClaim:
    client_message_id = payload.client_message_id
    if not client_message_id:
        return _RequestClaim(receipt=None, owns_lease=True, created=False, lease_id=None)

    now = datetime.now(timezone.utc)
    lease_id = str(uuid.uuid4())
    receipt = ChatRequestReceipt(
        user_id=user_id,
        client_message_id=client_message_id,
        message_hash=hashlib.sha256(payload.message.encode("utf-8")).hexdigest(),
        status="processing",
        lease_id=lease_id,
        lease_expires_at=now + timedelta(seconds=_IDEMPOTENCY_LEASE_SECONDS),
    )
    db.add(receipt)
    try:
        db.flush()
        return _RequestClaim(receipt=receipt, owns_lease=True, created=True, lease_id=lease_id)
    except IntegrityError:
        db.rollback()

    receipt = db.get(ChatRequestReceipt, (user_id, client_message_id))
    if receipt is None:
        raise HTTPException(status_code=409, detail="消息标识正在被另一请求占用，请重试")
    expected_hash = hashlib.sha256(payload.message.encode("utf-8")).hexdigest()
    if receipt.message_hash != expected_hash:
        raise HTTPException(status_code=409, detail="同一消息标识不能用于不同内容")
    if receipt.status == "completed" or _receipt_lease_is_active(receipt, now):
        return _RequestClaim(receipt=receipt, owns_lease=False, created=False, lease_id=receipt.lease_id)

    previous_lease_id = receipt.lease_id
    previous_status = receipt.status
    lease_condition = (
        ChatRequestReceipt.lease_id == previous_lease_id
        if previous_lease_id is not None
        else ChatRequestReceipt.lease_id.is_(None)
    )
    claimed = db.execute(
        update(ChatRequestReceipt)
        .where(
            ChatRequestReceipt.user_id == user_id,
            ChatRequestReceipt.client_message_id == client_message_id,
            ChatRequestReceipt.status == previous_status,
            lease_condition,
        )
        .values(
            status="processing",
            lease_id=lease_id,
            lease_expires_at=now + timedelta(seconds=_IDEMPOTENCY_LEASE_SECONDS),
            updated_at=now,
        )
    )
    if claimed.rowcount == 1:
        db.expire_all()
        receipt = db.get(ChatRequestReceipt, (user_id, client_message_id))
        return _RequestClaim(receipt=receipt, owns_lease=True, created=False, lease_id=lease_id)

    db.expire_all()
    receipt = db.get(ChatRequestReceipt, (user_id, client_message_id))
    return _RequestClaim(
        receipt=receipt,
        owns_lease=False,
        created=False,
        lease_id=receipt.lease_id if receipt else None,
    )


def _receipt_lease_is_active(receipt: ChatRequestReceipt, now: datetime | None = None) -> bool:
    if receipt.status != "processing" or receipt.lease_expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    expires = receipt.lease_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > current


def _legacy_message_is_processing(user_msg: ChatMessage) -> bool:
    meta = user_msg.meta or {}
    if meta.get("processing_status") != "processing":
        return False
    raw_started = meta.get("processing_started_at")
    if not raw_started:
        return False
    try:
        started = datetime.fromisoformat(str(raw_started).replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started + timedelta(seconds=_IDEMPOTENCY_LEASE_SECONDS) > datetime.now(timezone.utc)


def _receipt_linked_message(
    db: Session,
    receipt: ChatRequestReceipt | None,
    user_id: int,
) -> tuple[Conversation, ChatMessage] | None:
    if receipt is None or receipt.conversation_id is None or receipt.user_message_id is None:
        return None
    conv = db.get(Conversation, receipt.conversation_id)
    user_msg = db.get(ChatMessage, receipt.user_message_id)
    if conv is None or user_msg is None or conv.user_id != user_id or user_msg.conversation_id != conv.id:
        return None
    return conv, user_msg


def _link_request_receipt(
    receipt: ChatRequestReceipt | None,
    conv: Conversation,
    user_msg: ChatMessage,
) -> None:
    if receipt is None:
        return
    receipt.conversation_id = conv.id
    receipt.user_message_id = user_msg.id


def _request_lease_is_owned(
    db: Session,
    *,
    user_id: int,
    client_message_id: str | None,
    lease_id: str | None,
) -> bool:
    if not client_message_id:
        return True
    if not lease_id:
        return False
    row = db.execute(
        select(ChatRequestReceipt.status, ChatRequestReceipt.lease_id).where(
            ChatRequestReceipt.user_id == user_id,
            ChatRequestReceipt.client_message_id == client_message_id,
        )
    ).one_or_none()
    return row is not None and row.status == "processing" and row.lease_id == lease_id


def _mark_request_receipt(
    db: Session,
    *,
    user_id: int,
    client_message_id: str | None,
    lease_id: str | None,
    status: str,
) -> None:
    if not client_message_id or not lease_id:
        return
    now = datetime.now(timezone.utc)
    db.execute(
        update(ChatRequestReceipt)
        .where(
            ChatRequestReceipt.user_id == user_id,
            ChatRequestReceipt.client_message_id == client_message_id,
            ChatRequestReceipt.lease_id == lease_id,
        )
        .values(status=status, lease_expires_at=now, updated_at=now)
    )


def _unlinked_processing_result(receipt: ChatRequestReceipt | None) -> ChatResult:
    return ChatResult(
        summary="这条消息已收到，小捷仍在处理中，请稍后查看历史对话。",
        analysis="",
        answer_markdown="这条消息已收到，小捷仍在处理中，请稍后查看历史对话。",
        confidence=0.5,
        followups=[],
        safety_flags=[],
        used_context={"idempotent_replay": True},
        thread_id=str(receipt.conversation_id) if receipt and receipt.conversation_id else None,
        response_state="processing",
        citations=[],
    )


def _message_structure(context: dict) -> dict:
    return context.get("message_structure") or {}


def _fast_chat_reply(context: dict, user_query: str) -> dict | None:
    """Return deterministic replies for low-latency, high-precision turns."""
    structure = _message_structure(context)
    if not structure:
        return None
    route = route_from_structure(structure)
    handler = route.handler
    subject = structure.get("active_subject") or {}
    memory = structure.get("session_memory") or {}
    data_memory = structure.get("data_source_memory") or {}
    sources = data_memory.get("sources") or []
    connected = data_memory.get("connected") or {}
    metric_conflicts = data_memory.get("metric_conflicts") or []
    report_status = structure.get("report_status") or {}

    if handler == "high_numeric_risk":
        numeric_risk = (structure.get("health_nlu") or {}).get("numeric_risk") or {}
        reply = build_high_numeric_risk_reply(
            numeric_risk,
            subject=subject,
            profile=context.get("user_profile_info") or {},
        )
        return {
            **reply,
            "confidence": 1.0,
            "safety_flags": ["fast_path:high_numeric_risk"],
        }

    if handler == "insufficient_trend_evidence":
        evidence = (structure.get("response_plan") or {}).get("evidence_sufficiency") or {}
        reply = build_evidence_limited_reply(evidence)
        return {
            **reply,
            "confidence": 0.99,
            "safety_flags": ["fast_path:insufficient_trend_evidence"],
        }

    if handler == "greeting":
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
            "followups": ["继续刚才的问题"],
            "safety_flags": ["fast_path:greeting"],
        }

    if handler == "data_source_query":
        if subject.get("type") != "self":
            display = subject.get("display") or "家属"
            repetition = memory.get("repetition_policy") or {}
            if repetition.get("mode") == "delta_only":
                summary = (
                    f"同步状态没有新增变化：当前账号仍无法读取{display}的 Apple 健康或设备同步状态；"
                    f"需要{display}本人授权共享后才能确认。"
                )
            else:
                summary = (
                    f"当前问题主体是{display}。我不能用你账号里的 Apple 健康、设备或手动记录来判断{display}是否已经同步；"
                    f"只有{display}本人授权共享后，才能读取对应数据源状态。"
                )
            return {
                "summary": summary,
                "analysis": summary,
                "confidence": 0.99,
                "followups": ["查看家庭授权方式"],
                "safety_flags": ["fast_path:relative_data_source_boundary"],
            }
        summary = _build_data_source_reply_summary(sources, connected, user_query)
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.94,
            "followups": ["看最近同步了哪些指标"],
            "safety_flags": ["fast_path:data_source_query"],
        }

    if handler == "report_status":
        if subject.get("type") != "self":
            display = subject.get("display") or "家属"
            summary = (
                f"当前问题主体是{display}。你账号里的报告状态不能代表{display}的报告进度；"
                f"需要由{display}本人授权共享，或在明确标注主体后上传该病例资料，才能查询对应状态。"
            )
            return {
                "summary": summary,
                "analysis": summary,
                "confidence": 0.99,
                "followups": ["查看家庭授权方式"],
                "safety_flags": ["fast_path:relative_report_boundary"],
            }
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
            "followups": ["打开历史报告"],
            "safety_flags": ["fast_path:report_status"],
        }

    if handler == "metric_conflict" and metric_conflicts:
        conflict_lines = []
        for conflict in metric_conflicts[:3]:
            metric = conflict.get("metric") or "指标"
            samples = conflict.get("samples") or []
            sample_text = "；".join(_format_conflict_sample(sample) for sample in samples[:3])
            if sample_text:
                conflict_lines.append(f"{metric}：{sample_text}")
        detail = "；".join(conflict_lines)
        action_text, explanation_text = _conflict_guidance(metric_conflicts)
        summary = (
            f"这次变化不是一个数被覆盖掉了，而是同一指标存在不同来源/时间的记录。{detail}。"
            + action_text
        )
        analysis = (
            summary
            + "\n\n我会保留每条记录的来源和测量时间，不把不同场景的数据强行合并。"
            + explanation_text
        )
        return {
            "summary": summary,
            "analysis": analysis,
            "confidence": 0.93,
            "followups": ["查看各来源的测量记录"],
            "safety_flags": ["fast_path:metric_conflict"],
        }

    if handler == "subject_correction" and subject.get("relation") == "wife" and "nt" in user_query.lower():
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

    if handler == "subject_correction":
        concepts = (structure.get("health_nlu") or {}).get("matched_concepts") or []
        concept_text = "、".join(item.get("display") for item in concepts[:3] if item.get("display")) or "这个健康问题"
        display = subject.get("display") or "家属"
        summary = (
            f"明白，当前问题主体已经切换为{display}，不是你本人。"
            f"接下来讨论{concept_text}时，我只使用你为{display}提供的信息和该病例自己的报告，"
            "不会引用你账号里的血糖、尿酸、Apple 健康或用药数据。"
        )
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.95,
            "followups": [f"继续分析{display}的{concept_text}"],
            "safety_flags": ["fast_path:subject_correction"],
        }

    if handler == "missing_referent":
        normalized = str((structure.get("user_message") or {}).get("normalized") or "")
        covered = set((structure.get("session_memory") or {}).get("covered_facts") or [])
        concept_keys = set((structure.get("health_nlu") or {}).get("concept_keys") or [])
        numeric_risk = (structure.get("health_nlu") or {}).get("numeric_risk") or {}
        if re.search(r"\d", normalized):
            value_match = re.search(r"\d{1,4}(?:\.\d+)?", normalized)
            value = value_match.group(0) if value_match else "这个数值"
            reason_codes = set(numeric_risk.get("reason_codes") or [])
            current_bp_keys = {"blood_pressure", "systolic_bp", "diastolic_bp"}
            if "glucose:unit_missing" in reason_codes:
                summary = (
                    f"我已经识别到血糖数值 {value}，但缺少单位。请确认是 mmol/L 还是 mg/dL，"
                    "并补充这是空腹、餐后还是随机测量；单位不同会得到完全不同的风险判断。"
                )
                followup = f"血糖 {value} mmol/L，测量场景是空腹"
            elif concept_keys.intersection(current_bp_keys):
                summary = (
                    f"我已经识别到这是血压。若 {value} 是收缩压，单独一个数还不能判断完整血压；"
                    "请补充舒张压和单位，例如 120/80 mmHg。补齐后我会按完整读数判断。"
                )
                followup = f"完整血压是 {value}/80 mmHg"
            elif not concept_keys and "blood_pressure" in covered:
                summary = (
                    f"结合上一轮，你很可能是在说血压。若 {value} 是收缩压，单独一个数还不能判断完整血压；"
                    "请补充舒张压和单位，例如 120/80 mmHg。我会沿用上一轮背景，不需要重述症状。"
                )
                followup = f"完整血压是 {value}/80 mmHg"
            elif covered.intersection({"hba1c", "tir", "uric_acid"}):
                summary = (
                    f"我知道你在延续上一轮指标，但 {value} 仍缺少具体指标名和单位。"
                    "只补这两项即可，我会沿用之前的主体和背景，不让你重复整段信息。"
                )
                followup = "我补充指标名称和单位"
            else:
                summary = "我看到了这个数值，但还不能确定它指血压、血糖、心率还是其他指标。请只补充指标名称和单位，我就能直接判断，不需要你重新描述整段背景。"
                followup = "这是血压数值"
        else:
            summary = "我还不能确定“这个”具体指哪项指标、报告结果或症状。请补充名称或把对应数值发出来，我会沿用当前会话继续判断，不会让你重复已经说过的内容。"
            followup = "我补充具体指标名称"
        return {
            "summary": summary,
            "analysis": summary,
            "confidence": 0.99,
            "followups": [followup],
            "safety_flags": ["fast_path:targeted_clarification"],
        }

    return None


def _conflict_guidance(metric_conflicts: list[dict]) -> tuple[str, str]:
    names = " ".join(str(item.get("metric") or "") for item in metric_conflicts).lower()
    if any(term in names for term in ("血压", "收缩压", "舒张压", "systolic", "diastolic")):
        return (
            "先安静坐 5 分钟，用同一上臂和同一设备连续测 2-3 次取平均；如果静息血压仍反复升高，再把复测记录和来源一起给医生看。",
            "血压差异常受姿势、袖带位置、活动后测量和设备算法影响。",
        )
    if any(term in names for term in ("血糖", "glucose", "tir")):
        return (
            "先核对这些记录是否处于同一空腹/餐后时点；有低血糖症状或设备读数异常时，用指尖血糖复核，并按既定医疗方案处理。",
            "血糖差异常受测量时点、组织液滞后、进餐和设备校准影响。",
        )
    return (
        "先在相同时间、相同测量条件下复测，并保留设备、手动记录和报告各自的来源；持续明显不一致时，再带原始记录咨询医生。",
        "不同来源可能采用不同采样条件、算法和单位，必须先统一条件后再比较趋势。",
    )


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
    value_text = f"{float(value):g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    unit_text = f" {unit}" if unit else ""
    return f"{source} {value_text}{unit_text}（{when}）"


@dataclass
class _PreparedChatTurn:
    conv: Conversation
    user_msg: ChatMessage
    history: list[dict]
    context: dict
    safety_flags: list[str]
    route: ChatRouteDecision
    client_message_id: str | None
    receipt_lease_id: str | None


@dataclass(frozen=True)
class _StreamTurnSnapshot:
    conversation_id: int
    user_message_id: int
    history: list[dict]
    context: dict
    safety_flags: list[str]
    route: ChatRouteDecision
    client_message_id: str | None
    receipt_lease_id: str | None


def _prepare_chat_turn(
    db: Session,
    *,
    user_id: int,
    payload: ChatRequest,
) -> tuple[_PreparedChatTurn | None, ChatResult | None]:
    claim = _claim_request_receipt(db, user_id, payload)
    duplicate = _receipt_linked_message(db, claim.receipt, user_id)
    if duplicate is None:
        duplicate = _find_client_message(db, user_id, payload.client_message_id)
    if duplicate:
        conv, user_msg = duplicate
        _link_request_receipt(claim.receipt, conv, user_msg)
        assistant = _assistant_after(db, conv.id, user_msg.seq, user_msg.id)
        if assistant:
            _mark_request_receipt(
                db,
                user_id=user_id,
                client_message_id=payload.client_message_id,
                lease_id=claim.lease_id,
                status="completed",
            )
            db.commit()
            return None, _duplicate_chat_result(db, conv, user_msg, assistant)
        if not claim.owns_lease or (claim.created and _legacy_message_is_processing(user_msg)):
            db.commit()
            return None, _duplicate_chat_result(db, conv, user_msg, assistant=None)
        history = _load_history(db, conv.id, before_seq=user_msg.seq)
    else:
        if claim.receipt is not None and not claim.owns_lease:
            db.commit()
            return None, _unlinked_processing_result(claim.receipt)
        conv = _get_or_create_conversation(db, user_id, payload.thread_id)
        history = _load_history(db, conv.id)
        user_msg = _save_user_message(db, conv, payload.message, payload.client_message_id)
        _link_request_receipt(claim.receipt, conv, user_msg)

    safety_flags = detect_safety_flags(payload.message)
    trusted_health_consumer = (
        "medication_allergy_risk"
        if re.search(r"药|用药|过敏|相互作用|副作用|禁忌", payload.message)
        else "chat_question"
    )
    context = build_user_context(
        db,
        user_id,
        trusted_health_consumer=trusted_health_consumer,
        conversation_id=conv.id,
        user_query=payload.message,
        history=history,
    )
    structure = _message_structure(context)
    route = resolve_chat_route(structure, safety_flags=safety_flags)
    structure["interaction_route"] = route.to_dict()
    _mark_user_message_status(user_msg, "processing")
    db.commit()
    return _PreparedChatTurn(
        conv=conv,
        user_msg=user_msg,
        history=history,
        context=context,
        safety_flags=safety_flags,
        route=route,
        client_message_id=payload.client_message_id,
        receipt_lease_id=claim.lease_id if claim.owns_lease else None,
    ), None


def _public_used_context(turn: _PreparedChatTurn) -> dict:
    structure = _message_structure(turn.context)
    data_memory = structure.get("data_source_memory") or {}
    report_status = structure.get("report_status") or {}
    return {
        "message_structure_version": structure.get("version"),
        "interaction_route": public_route_payload(turn.route),
        "connected_sources": [key for key, value in (data_memory.get("connected") or {}).items() if value],
        "available_fact_count": len((structure.get("health_fact_index") or {}).get("facts") or []),
        "pending_report_count": int(report_status.get("pending_count") or 0),
    }


def _build_skill_and_citations(db: Session, turn: _PreparedChatTurn, user_query: str):
    skill_prompt = build_skill_prompt(user_query, db)
    citations = []
    if turn.route.needs_literature:
        try:
            nlu = (_message_structure(turn.context).get("health_nlu") or {})
            concept_groups = concept_alias_groups(nlu.get("concept_keys") or [])
            min_groups = 2 if turn.route.primary_intent == "causal_assessment" else (1 if concept_groups else 0)
            citations = retrieve_claims(
                db,
                query=user_query,
                top_k=5,
                concept_groups=concept_groups,
                min_concept_groups=min_groups,
            )
        except Exception:  # noqa: BLE001
            logger.warning("literature retrieval failed; continuing without citations", exc_info=True)
    if citations:
        block = build_citation_block(citations)
        skill_prompt = (
            (skill_prompt + "\n\n" if skill_prompt else "")
            + "# 文献证据库（编号硬约束）\n"
            + "以下是与用户问题相关的已发表文献结论。每个 [N] 只允许引用同编号证据，禁止换号、"
            + "重新排序或让该证据支撑其结论之外的话。角标紧跟在被直接支持的句子后；"
            + "证据不相关时不要引用，也不要另写参考文献列表。\n"
            + block
        )
    return skill_prompt, citations


def _execute_chat_turn(
    db: Session,
    *,
    user_id: int,
    payload: ChatRequest,
    turn: _PreparedChatTurn,
    stream: bool = False,
) -> ChatResult:
    citations = []
    quality_flags: list[str] = []
    provider_name = "policy"
    model_name = turn.route.route_id
    prompt_tokens = None
    completion_tokens = None
    started = time.perf_counter()

    if turn.route.strategy == "emergency":
        emergency = emergency_response(payload.message)
        result = ChatLLMResult(
            answer_markdown=emergency["analysis"],
            confidence=1.0,
            followups=["帮我整理急救时要说明的信息"],
            safety_flags=["emergency_symptom"],
            summary=emergency["summary"],
            analysis=emergency["analysis"],
        )
        model_name = "emergency-template-v2"
    elif turn.route.strategy in {"deterministic", "clarification"}:
        reply = _fast_chat_reply(turn.context, payload.message)
        if reply is None:
            logger.error("deterministic route has no handler: %s", turn.route.route_id)
            result = ChatLLMResult(
                answer_markdown="这次问题路由没有完成，请稍后重试。",
                confidence=0.0,
                followups=["重新处理这条消息"],
                safety_flags=["route_handler_missing"],
                summary="这次问题路由没有完成，请稍后重试。",
                analysis="消息已经保留，重试时会沿用同一会话。",
            )
            quality_flags.append("route_handler_missing")
        else:
            result = ChatLLMResult(
                answer_markdown=reply["analysis"],
                confidence=float(reply["confidence"]),
                followups=list(reply.get("followups") or [])[: turn.route.max_followups],
                safety_flags=list(reply.get("safety_flags") or []),
                summary=reply["summary"],
                analysis=reply["analysis"],
            )
        model_name = "deterministic-router"
    else:
        skill_prompt, citations = _build_skill_and_citations(db, turn, payload.message)
        provider = get_provider()
        provider_name = provider.provider_name
        model_name = provider.text_model
        result = provider.generate_text(
            turn.context,
            payload.message,
            history=turn.history,
            skill_prompt=skill_prompt,
        )
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
    guarded = guard_chat_result(
        result,
        context=turn.context,
        route=turn.route,
        user_query=payload.message,
        history=turn.history,
    )
    result = guarded.result
    quality_flags.extend(guarded.quality_flags)

    citation_selection = select_citations_for_response(
        summary=result.summary,
        analysis=result.analysis,
        answer_markdown=result.answer_markdown,
        candidates=citations,
    )
    citations = citation_selection.citations
    if citation_selection.removed_candidate_count:
        quality_flags.append("uncited_candidate_evidence_removed")
    if citation_selection.removed_marker_count:
        quality_flags.append("unsupported_citation_marker_removed")
    result = result.model_copy(update={
        "summary": citation_selection.summary,
        "analysis": citation_selection.analysis,
        "answer_markdown": citation_selection.answer_markdown,
    })

    if not _request_lease_is_owned(
        db,
        user_id=user_id,
        client_message_id=turn.client_message_id,
        lease_id=turn.receipt_lease_id,
    ):
        existing_assistant = _assistant_after(
            db,
            turn.conv.id,
            turn.user_msg.seq,
            turn.user_msg.id,
        )
        return _duplicate_chat_result(db, turn.conv, turn.user_msg, existing_assistant)

    latency_ms = int((time.perf_counter() - started) * 1000)
    combined_flags = list(dict.fromkeys(turn.safety_flags + result.safety_flags))
    route_payload = public_route_payload(turn.route)
    response_state = "degraded" if "provider_error" in result.safety_flags else "completed"
    replay_followups = result.followups[: turn.route.max_followups]
    assistant = _save_assistant_message(
        db,
        turn.conv,
        _primary_display_text(result, turn.route),
        result.analysis,
        {
            "safety_flags": combined_flags,
            "confidence": result.confidence,
            "citation_ids": [citation.claim_id for citation in citations],
            "citation_snapshot_version": _CITATION_SNAPSHOT_VERSION,
            "citation_snapshots": [citation.model_dump(mode="json") for citation in citations],
            "reply_to_user_message_id": turn.user_msg.id,
            "summary": result.summary,
            "answer_markdown": result.answer_markdown,
            "followups": replay_followups,
            "response_state": response_state,
            "interaction_route": route_payload,
            "quality_flags": quality_flags,
        },
    )
    _mark_user_message_status(turn.user_msg, "completed")
    _mark_request_receipt(
        db,
        user_id=user_id,
        client_message_id=turn.client_message_id,
        lease_id=turn.receipt_lease_id,
        status="completed",
    )
    db.commit()

    if result.profile_extracted:
        try:
            _apply_profile_extraction(db, user_id, result.profile_extracted)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.warning("chat profile extraction persistence failed", exc_info=True)

    try:
        _save_audit(
            db,
            user_id,
            provider_name,
            model_name,
            latency_ms,
            turn.context,
            {
                "message_hash": hashlib.sha256(payload.message.encode("utf-8")).hexdigest(),
                "message_length": len(payload.message),
                "safety_flags": combined_flags,
                "client_message_id": payload.client_message_id,
                "stream": stream,
                "interaction_route": route_payload,
                "quality_flags": quality_flags,
            },
            feature="chat",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("chat audit persistence failed", exc_info=True)

    return ChatResult(
        summary=result.summary,
        analysis=result.analysis,
        answer_markdown=result.answer_markdown or result.analysis,
        confidence=result.confidence,
        followups=replay_followups,
        safety_flags=combined_flags,
        used_context=_public_used_context(turn),
        thread_id=str(turn.conv.id),
        message_id=str(assistant.id),
        response_state=response_state,
        interaction_route=route_payload,
        quality_flags=quality_flags,
        citations=citations,
    )


def _primary_display_text(result: ChatLLMResult, route: ChatRouteDecision) -> str:
    if route.depth == "deep" and "provider_error" not in result.safety_flags:
        return result.answer_markdown or result.analysis or result.summary
    return result.summary or result.answer_markdown or result.analysis


def _snapshot_stream_turn(turn: _PreparedChatTurn) -> _StreamTurnSnapshot:
    return _StreamTurnSnapshot(
        conversation_id=turn.conv.id,
        user_message_id=turn.user_msg.id,
        history=turn.history,
        context=turn.context,
        safety_flags=turn.safety_flags,
        route=turn.route,
        client_message_id=turn.client_message_id,
        receipt_lease_id=turn.receipt_lease_id,
    )


def _mark_failed_turn(db: Session, *, snapshot: _StreamTurnSnapshot, user_id: int) -> None:
    user_msg = db.get(ChatMessage, snapshot.user_message_id)
    if user_msg is None:
        return
    assistant = _assistant_after(
        db,
        snapshot.conversation_id,
        user_msg.seq,
        user_msg.id,
    )
    status = "completed" if assistant is not None else "failed"
    _mark_user_message_status(user_msg, status)
    _mark_request_receipt(
        db,
        user_id=user_id,
        client_message_id=snapshot.client_message_id,
        lease_id=snapshot.receipt_lease_id,
        status=status,
    )
    db.commit()


def _run_stream_turn(
    *,
    snapshot: _StreamTurnSnapshot,
    user_id: int,
    payload: ChatRequest,
    output: Queue,
) -> None:
    worker_db = SessionLocal()
    try:
        conv = worker_db.get(Conversation, snapshot.conversation_id)
        user_msg = worker_db.get(ChatMessage, snapshot.user_message_id)
        if conv is None or user_msg is None:
            raise RuntimeError("prepared chat turn no longer exists")
        turn = _PreparedChatTurn(
            conv=conv,
            user_msg=user_msg,
            history=snapshot.history,
            context=snapshot.context,
            safety_flags=snapshot.safety_flags,
            route=snapshot.route,
            client_message_id=snapshot.client_message_id,
            receipt_lease_id=snapshot.receipt_lease_id,
        )
        result = _execute_chat_turn(worker_db, user_id=user_id, payload=payload, turn=turn, stream=True)
        output.put(_sse_event("done", result=result.model_dump(mode="json")))
    except Exception:  # noqa: BLE001
        logger.exception("chat stream execution failed")
        worker_db.rollback()
        _mark_failed_turn(worker_db, snapshot=snapshot, user_id=user_id)
        output.put(_sse_event(
            "error",
            message="这次回答没有完成。原消息已经保留，请点击重试。",
            retryable=True,
        ))
    finally:
        worker_db.close()
        output.put(None)


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
    turn, replay = _prepare_chat_turn(db, user_id=user_id, payload=payload)
    if replay is not None:
        return replay
    assert turn is not None
    snapshot = _snapshot_stream_turn(turn)
    try:
        return _execute_chat_turn(db, user_id=user_id, payload=payload, turn=turn)
    except Exception:
        db.rollback()
        _mark_failed_turn(db, snapshot=snapshot, user_id=user_id)
        raise


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
    turn, replay = _prepare_chat_turn(db, user_id=user_id, payload=payload)
    snapshot = _snapshot_stream_turn(turn) if turn is not None else None

    def event_stream():
        if replay is not None:
            if replay.interaction_route:
                yield _sse_event("route", route=replay.interaction_route.model_dump(mode="json"))
            yield _sse_event("done", result=replay.model_dump(mode="json"))
            return

        assert turn is not None
        yield _sse_event("route", route=public_route_payload(turn.route))
        assert snapshot is not None
        output: Queue = Queue()
        worker = Thread(
            target=_run_stream_turn,
            kwargs={
                "snapshot": snapshot,
                "user_id": user_id,
                "payload": payload,
                "output": output,
            },
            name=f"chat-stream-{snapshot.conversation_id}-{snapshot.user_message_id}",
            daemon=True,
        )
        worker.start()
        while True:
            try:
                event = output.get(timeout=12)
            except Empty:
                yield _sse_event("progress", step="仍在处理当前问题，连接正常")
                continue
            if event is None:
                break
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse_event(event_type: str, **payload) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


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

    # Hydrate citations from stored claim ids in meta while preserving the
    # compact order persisted with the assistant response.
    all_ids: list[int] = []
    for m in msgs:
        if _citation_snapshots(m.meta or {}) is not None:
            continue
        for claim_id in _citation_ids(m.meta or {}):
            if claim_id not in all_ids:
                all_ids.append(claim_id)
    claim_map = _load_citation_claims(db, all_ids)

    return [
        ChatMessageItem(id=str(m.id), seq=m.seq, role=m.role, content=m.content,
                        analysis=m.analysis, created_at=m.created_at.isoformat() if m.created_at else "",
                        citations=_citations_for_meta(m.meta or {}, claim_map))
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
