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
