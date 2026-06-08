from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FamilyGroupCreate(BaseModel):
    name: str = Field(default="我的家庭", min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip() or "我的家庭"


class FamilyInviteCreate(BaseModel):
    group_id: int | None = None
    target_phone: str | None = Field(default=None, max_length=32)
    relation: str | None = Field(default=None, max_length=40)
    role: str = Field(default="member", max_length=24)

    @field_validator("target_phone", "relation", "role")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FamilyInviteAccept(BaseModel):
    invite_code: str = Field(min_length=4, max_length=32)
    display_name: str | None = Field(default=None, max_length=80)

    @field_validator("invite_code", "display_name")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FamilyPermissionUpdate(BaseModel):
    can_view_glucose_detail: bool | None = None
    can_view_medication: bool | None = None
    can_view_health_data: bool | None = None
    can_view_documents: bool | None = None
    can_view_omics: bool | None = None
    can_view_ai_summary: bool | None = None


class FamilyCareEventCreate(BaseModel):
    subject_user_id: int
    event_type: str = Field(default="care_reminder", min_length=1, max_length=40)
    message: str | None = Field(default=None, max_length=500)

    @field_validator("event_type", "message")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FamilyGroupOut(BaseModel):
    id: int
    name: str
    owner_user_id: int
    created_at: datetime


class FamilyMemberOut(BaseModel):
    id: int
    group_id: int
    user_id: int
    role: str
    relation: str | None = None
    display_name: str | None = None
    status: str
    phone: str | None = None
    username: str | None = None
    profile_name: str | None = None
    created_at: datetime


class FamilyPermissionOut(BaseModel):
    id: int | None = None
    subject_user_id: int
    viewer_user_id: int
    can_view_glucose_detail: bool = False
    can_view_medication: bool = False
    can_view_health_data: bool = False
    can_view_documents: bool = False
    can_view_omics: bool = False
    can_view_ai_summary: bool = False


class FamilyInviteOut(BaseModel):
    id: int
    group_id: int
    invite_code: str
    target_phone: str | None = None
    relation: str | None = None
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class FamilySubjectOut(BaseModel):
    user_id: int
    display_name: str
    relation: str | None = None
    group_id: int | None = None
    member_id: int | None = None
    permissions: FamilyPermissionOut


class FamilyCareEventOut(BaseModel):
    id: int
    subject_user_id: int
    actor_user_id: int
    event_type: str
    message: str | None = None
    status: str
    created_at: datetime
    handled_at: datetime | None = None


class FamilySubjectSummaryOut(BaseModel):
    subject: FamilySubjectOut
    health_status: dict
    plan: dict
    care: dict
    permissions: FamilyPermissionOut
    alerts: list[str]
    generated_at: datetime
