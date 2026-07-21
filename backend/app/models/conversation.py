"""Conversation & ChatMessage models for multi-turn chat persistence."""


from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.compat import JSONB


class Conversation(Base):
    """A conversation thread between a user and MetaBot."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("user_account.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="conversation", order_by="ChatMessage.seq", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """A single message in a conversation (user or assistant)."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)  # user message or summary for assistant
    analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # detailed analysis (assistant only)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)  # safety_flags, confidence, etc.
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class ChatRequestReceipt(Base):
    """Database-backed idempotency lease for one client chat request."""

    __tablename__ = "chat_request_receipts"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    client_message_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    lease_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lease_expires_at = mapped_column(DateTime(timezone=True), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
