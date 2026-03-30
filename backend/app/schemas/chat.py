from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None  # conversation UUID; None = create new


class ChatResult(BaseModel):
    answer_markdown: str
    confidence: float = Field(ge=0, le=1)
    followups: list[str] = []
    safety_flags: list[str] = []
    used_context: dict
    thread_id: str | None = None


class ChatStreamResult(BaseModel):
    """Extended result returned in 'done' SSE event."""
    summary: str
    analysis: str
    confidence: float = Field(ge=0, le=1, default=0.85)
    followups: list[str] = []
    safety_flags: list[str] = []
    thread_id: str
    message_id: str


# ── Conversation list & history ──────────────────────────

class ConversationItem(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: str
    created_at: str


class ChatMessageItem(BaseModel):
    id: str
    seq: int
    role: str
    content: str
    analysis: str | None = None
    created_at: str

