import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.chat as chat_module  # imports complete model metadata
from app.db.base import Base
from app.models.audit import LLMAuditLog
from app.models.consent import Consent
from app.models.conversation import ChatMessage, ChatRequestReceipt, Conversation
from app.models.literature import Claim, Literature
from app.models.user import User
from app.routers.chat import chat_stream
from app.schemas.chat import ChatRequest
from app.services.feature_service import invalidate_cache


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return factory(), factory


async def _events(response) -> list[dict]:
    events = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


@pytest.mark.asyncio
async def test_sse_pipeline_emits_route_then_done_and_replays_idempotently(monkeypatch):
    db, factory = _db_session()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000101", username="route-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()
    payload = ChatRequest(message="你好", client_message_id="route-test-message-1")

    first = await _events(chat_stream(payload, user_id=1, db=db))

    assert [event["type"] for event in first] == ["route", "done"]
    assert first[0]["route"]["route_id"] == "fast.greeting"
    assert first[1]["result"]["interaction_route"]["route_id"] == "fast.greeting"
    assert first[1]["result"]["response_state"] == "completed"
    assert first[1]["result"]["used_context"]["message_structure_version"] == "2026-07-10"

    second = await _events(chat_stream(payload, user_id=1, db=db))

    assert [event["type"] for event in second] == ["route", "done"]
    assert second[1]["result"]["used_context"] == {"idempotent_replay": True}
    for field in (
        "summary",
        "analysis",
        "answer_markdown",
        "confidence",
        "followups",
        "safety_flags",
        "response_state",
        "interaction_route",
        "quality_flags",
        "citations",
    ):
        assert second[1]["result"][field] == first[1]["result"][field]
    conversations = db.execute(select(Conversation)).scalars().all()
    messages = db.execute(select(ChatMessage).order_by(ChatMessage.seq)).scalars().all()
    assert len(conversations) == 1
    assert [(message.role, message.seq) for message in messages] == [("user", 1), ("assistant", 2)]
    receipt = db.get(ChatRequestReceipt, (1, payload.client_message_id))
    assert receipt is not None
    assert receipt.status == "completed"
    audit = db.execute(select(LLMAuditLog).order_by(LLMAuditLog.id.desc())).scalars().first()
    assert audit is not None
    assert "message" not in audit.meta
    assert len(audit.meta["message_hash"]) == 64


def test_completed_idempotent_replay_restores_citations_and_response_fields(monkeypatch):
    db, factory = _db_session()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000105", username="citation-replay-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()
    payload = ChatRequest(
        message="鼻炎和脊柱侧弯会不会影响睡眠",
        client_message_id="route-test-citation-replay",
    )

    turn, replay = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)
    assert turn is not None
    assert replay is None
    first_claim = _add_claim(
        db,
        pmid="replay-1",
        claim_text="过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。",
        population="成人观察性研究人群",
    )
    second_claim = _add_claim(
        db,
        pmid="replay-2",
        claim_text="严重胸椎脊柱侧弯在肺活量降低时可导致夜间低氧。",
        population="严重胸椎脊柱侧弯患者",
    )
    summary = "鼻炎与睡眠问题存在关联[1]。"
    analysis = "鼻炎与睡眠问题存在关联[1]；严重脊柱侧弯可能影响夜间呼吸[2]。"
    answer_markdown = "完整回答：鼻炎与睡眠问题存在关联[1]，严重脊柱侧弯可能影响夜间呼吸[2]。"
    response_state = "degraded"
    citation_snapshots = [
        chat_module.citation_bundle_from_claim(first_claim, score=0.91).model_dump(mode="json"),
        chat_module.citation_bundle_from_claim(second_claim, score=0.82).model_dump(mode="json"),
    ]
    assistant = chat_module._save_assistant_message(
        db,
        turn.conv,
        summary,
        analysis,
        {
            "citation_ids": [first_claim.id, second_claim.id],
            "citation_snapshot_version": 1,
            "citation_snapshots": citation_snapshots,
            "reply_to_user_message_id": turn.user_msg.id,
            "summary": summary,
            "answer_markdown": answer_markdown,
            "followups": ["查看睡眠评估路径"],
            "response_state": response_state,
            "confidence": 0.0,
            "quality_flags": ["test_quality_flag"],
        },
    )
    turn.user_msg.meta = {**(turn.user_msg.meta or {}), "processing_status": "completed"}
    receipt = db.get(ChatRequestReceipt, (1, payload.client_message_id))
    assert receipt is not None
    receipt.status = "completed"
    db.commit()
    db.expunge(receipt)
    first_claim.claim_text = "后来被编辑、不得改变历史展示的结论"
    first_claim.population_summary = "后来被编辑的人群"
    first_claim.enabled = False
    second_claim.claim_text = "后来被编辑的第二条结论"
    db.commit()

    duplicate_turn, duplicate = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)

    assert duplicate_turn is None
    assert duplicate is not None
    assert duplicate.message_id == str(assistant.id)
    assert duplicate.summary == summary
    assert duplicate.analysis == analysis
    assert duplicate.answer_markdown == answer_markdown
    assert duplicate.confidence == 0.0
    assert duplicate.followups == ["查看睡眠评估路径"]
    assert duplicate.response_state == response_state
    assert duplicate.quality_flags == ["test_quality_flag"]
    assert [citation.claim_id for citation in duplicate.citations] == [first_claim.id, second_claim.id]
    assert [citation.population for citation in duplicate.citations] == [
        "成人观察性研究人群",
        "严重胸椎脊柱侧弯患者",
    ]
    assert [citation.score for citation in duplicate.citations] == [0.91, 0.82]
    assert duplicate.citations[0].claim_text == "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。"
    history = chat_module.get_conversation_messages(
        str(turn.conv.id),
        user_id=1,
        db=db,
    )
    history_assistant = next(message for message in history if message.role == "assistant")
    assert [citation.claim_id for citation in history_assistant.citations] == [
        first_claim.id,
        second_claim.id,
    ]
    assert history_assistant.citations[0].claim_text == "过敏性鼻炎与失眠和睡眠呼吸障碍风险增加相关。"
    assert history_assistant.citations[0].score == 0.91


def test_legacy_citation_id_hydration_never_compresses_a_missing_position() -> None:
    db, _factory = _db_session()
    claim = _add_claim(
        db,
        pmid="legacy-citation",
        claim_text="高血压与心血管事件风险增加相关。",
        population="成人",
    )
    db.commit()
    legacy = ChatMessage(
        conversation_id=999,
        seq=1,
        role="assistant",
        content="高血压风险增加[1]。",
        meta={"citation_ids": [claim.id]},
    )
    missing_first = ChatMessage(
        conversation_id=999,
        seq=2,
        role="assistant",
        content="第一条缺失[1]，第二条仍在[2]。",
        meta={"citation_ids": [999999, claim.id]},
    )

    assert [citation.claim_id for citation in chat_module._message_citations(db, legacy)] == [claim.id]
    assert chat_module._message_citations(db, missing_first) == []


def test_corrupt_or_mismatched_citation_snapshot_is_suppressed() -> None:
    bundle = {
        "claim_id": 10,
        "literature_id": 20,
        "claim_text": "证据结论",
        "evidence_level": "L1",
        "short_ref": "Author, 2026",
        "confidence": "high",
    }

    assert chat_module._citation_snapshots({
        "citation_ids": [11],
        "citation_snapshot_version": 1,
        "citation_snapshots": [bundle],
    }) == []
    assert chat_module._citation_snapshots({
        "citation_ids": [10, 10],
        "citation_snapshot_version": 1,
        "citation_snapshots": [bundle, bundle],
    }) == []
    assert chat_module._citation_snapshots({
        "citation_ids": [10],
        "citation_snapshot_version": 999,
        "citation_snapshots": [bundle],
    }) == []


def test_orphan_user_turn_does_not_replay_later_turn_assistant(monkeypatch):
    db, factory = _db_session()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000106", username="orphan-turn-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()
    payload = ChatRequest(message="第一轮问题", client_message_id="route-test-orphan-turn")

    first_turn, replay = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)
    assert first_turn is not None
    assert replay is None
    second_user = chat_module._save_user_message(db, first_turn.conv, "第二轮问题", "second-turn")
    later_assistant = chat_module._save_assistant_message(
        db,
        first_turn.conv,
        "第二轮回答",
        "第二轮详细回答",
        {"reply_to_user_message_id": second_user.id},
    )
    db.commit()

    assert later_assistant.seq > first_turn.user_msg.seq + 1
    assert chat_module._assistant_after(
        db,
        first_turn.conv.id,
        first_turn.user_msg.seq,
        first_turn.user_msg.id,
    ) is None


def test_active_idempotency_lease_returns_processing_without_duplicate_message(monkeypatch):
    db, factory = _db_session()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000102", username="lease-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()
    payload = ChatRequest(message="帮我分析睡眠", client_message_id="route-test-active-lease")

    first_turn, first_replay = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)
    second_turn, second_replay = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)

    assert first_turn is not None
    assert first_replay is None
    assert second_turn is None
    assert second_replay is not None
    assert second_replay.response_state == "processing"
    messages = db.execute(select(ChatMessage).where(ChatMessage.role == "user")).scalars().all()
    assert len(messages) == 1


def test_lease_ownership_check_observes_takeover_from_another_session(monkeypatch):
    db, factory = _db_session()
    other_db = factory()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000104", username="lease-takeover-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()
    payload = ChatRequest(message="帮我分析睡眠", client_message_id="route-test-lease-takeover")

    turn, replay = chat_module._prepare_chat_turn(db, user_id=1, payload=payload)
    assert turn is not None
    assert replay is None
    original_lease = turn.receipt_lease_id
    assert original_lease

    receipt = other_db.get(ChatRequestReceipt, (1, payload.client_message_id))
    assert receipt is not None
    receipt.lease_id = "replacement-lease"
    other_db.commit()

    assert chat_module._request_lease_is_owned(
        db,
        user_id=1,
        client_message_id=payload.client_message_id,
        lease_id=original_lease,
    ) is False


@pytest.mark.asyncio
async def test_reusing_client_message_id_for_different_content_is_rejected(monkeypatch):
    db, factory = _db_session()
    monkeypatch.setattr(chat_module, "SessionLocal", factory)
    db.add(User(id=1, phone="18800000103", username="conflict-user", password="x"))
    db.add(Consent(user_id=1, allow_ai_chat=True, allow_data_upload=True))
    db.commit()
    invalidate_cache()

    await _events(chat_stream(
        ChatRequest(message="你好", client_message_id="route-test-content-conflict"),
        user_id=1,
        db=db,
    ))

    with pytest.raises(HTTPException) as error:
        chat_stream(
            ChatRequest(message="这是另一条内容", client_message_id="route-test-content-conflict"),
            user_id=1,
            db=db,
        )

    assert error.value.status_code == 409


def _add_claim(
    db,
    *,
    pmid: str,
    claim_text: str,
    population: str,
) -> Claim:
    literature = Literature(
        pmid=pmid,
        title=f"Evidence {pmid}",
        authors=["Test Author"],
        journal="Test Journal",
        year=2026,
        language="en",
        evidence_level="L3",
        study_design="observational_study",
        population=population,
        conclusion_zh=claim_text,
        topics=["sleep"],
        reviewed=True,
    )
    db.add(literature)
    db.flush()
    claim = Claim(
        literature_id=literature.id,
        claim_text=claim_text,
        exposure="睡眠因素",
        outcome="睡眠结局",
        population_summary=population,
        confidence="medium",
        topics=["sleep"],
        tags=[],
        evidence_level="L3",
        enabled=True,
    )
    db.add(claim)
    db.flush()
    return claim
