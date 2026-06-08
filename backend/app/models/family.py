from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FamilyGroup(Base):
    __tablename__ = "family_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("family_groups.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member", server_default="member", index=True)
    relation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_family_members_group_user"),
    )


class FamilyInvite(Base):
    __tablename__ = "family_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("family_groups.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    inviter_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    invite_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    target_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member", server_default="member")
    relation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FamilyPermission(Base):
    __tablename__ = "family_permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    viewer_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    can_view_glucose_detail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_view_medication: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_view_health_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_view_documents: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_view_omics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    can_view_ai_summary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("subject_user_id", "viewer_user_id", name="uq_family_permissions_subject_viewer"),
    )


class FamilyCareEvent(Base):
    __tablename__ = "family_care_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="new", server_default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FamilyAuditLog(Base):
    __tablename__ = "family_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    viewer_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


Index("ix_family_members_user_status", FamilyMember.user_id, FamilyMember.status)
Index("ix_family_permissions_viewer_subject", FamilyPermission.viewer_user_id, FamilyPermission.subject_user_id)
Index("ix_family_care_events_subject_created", FamilyCareEvent.subject_user_id, FamilyCareEvent.created_at)
