from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.schemas.literature import CitationBundle


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None  # conversation UUID; None = create new
    client_message_id: str | None = Field(default=None, max_length=80)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class ChatInteractionRoute(BaseModel):
    version: str
    route_id: str
    strategy: str
    primary_intent: str
    depth: str
    safety_level: str
    subject_type: str
    needs_literature: bool = False
    max_followups: int = 1
    progress_steps: list[str] = Field(default_factory=list)


class ChatResult(BaseModel):
    summary: str = ""
    analysis: str = ""
    answer_markdown: str
    confidence: float = Field(ge=0, le=1)
    followups: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    used_context: dict = Field(default_factory=dict)
    thread_id: str | None = None
    message_id: str | None = None
    response_state: str = "completed"
    interaction_route: ChatInteractionRoute | None = None
    quality_flags: list[str] = Field(default_factory=list)
    citations: list[CitationBundle] = Field(default_factory=list)


class ChatStreamResult(BaseModel):
    """Extended result returned in 'done' SSE event."""
    summary: str
    analysis: str
    confidence: float = Field(ge=0, le=1, default=0.85)
    followups: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    thread_id: str
    message_id: str
    interaction_route: ChatInteractionRoute | None = None
    quality_flags: list[str] = Field(default_factory=list)
    citations: list[CitationBundle] = Field(default_factory=list)


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
    citations: list[CitationBundle] = Field(default_factory=list)
