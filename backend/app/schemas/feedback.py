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

    @field_validator("category", "content", "contact", "app_platform", "app_version", "device_info")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
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
