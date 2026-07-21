from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FeedbackCreate(BaseModel):
    category: str = Field(default="general", min_length=1, max_length=32)
    content: str = Field(min_length=2, max_length=2000)
    contact: str | None = Field(default=None, max_length=128)
    app_platform: str | None = Field(default=None, max_length=24)
    app_version: str | None = Field(default=None, max_length=64)
    device_info: str | None = Field(default=None, max_length=255)

    @field_validator("category", "content", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("contact", "app_platform", "app_version", "device_info", mode="before")
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class FeedbackOut(BaseModel):
    id: int
    user_id: int
    category: str
    content: str
    contact: str | None = None
    app_platform: str | None = None
    app_version: str | None = None
    device_info: str | None = None
    status: str
    created_at: datetime


class FeedbackAdminItem(FeedbackOut):
    username: str | None = None
    phone: str | None = None
    handled_at: datetime | None = None
    admin_note: str | None = None


class FeedbackAdminUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=24)
    admin_note: str | None = Field(default=None, max_length=2000)
