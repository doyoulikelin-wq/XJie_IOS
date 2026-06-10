"""Schemas for mobile app release update checks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Platform = Literal["ios", "android"]


class AppReleaseBase(BaseModel):
    platform: Platform
    latest_version: str = Field(min_length=1, max_length=32)
    latest_build: int = Field(ge=1)
    min_supported_build: int = Field(default=1, ge=1)
    force_update: bool = False
    title: str = Field(default="发现新版本", max_length=120)
    message: str = Field(default="", max_length=2000)
    changelog: str = Field(default="", max_length=4000)
    download_url: str | None = Field(default=None, max_length=512)
    store_url: str | None = Field(default=None, max_length=512)
    sha256: str | None = Field(default=None, max_length=128)

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        return value.lower().strip()


class AppReleaseCreate(AppReleaseBase):
    pass


class AppReleaseUpdate(BaseModel):
    latest_version: str | None = Field(default=None, min_length=1, max_length=32)
    latest_build: int | None = Field(default=None, ge=1)
    min_supported_build: int | None = Field(default=None, ge=1)
    force_update: bool | None = None
    title: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=2000)
    changelog: str | None = Field(default=None, max_length=4000)
    download_url: str | None = Field(default=None, max_length=512)
    store_url: str | None = Field(default=None, max_length=512)
    sha256: str | None = Field(default=None, max_length=128)


class AppReleaseRead(AppReleaseBase):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class AppReleaseListOut(BaseModel):
    items: list[AppReleaseRead]


class AppUpdateCheckOut(BaseModel):
    platform: Platform
    current_version: str | None = None
    current_build: int | None = None
    latest_version: str
    latest_build: int
    min_supported_build: int
    update_available: bool
    required: bool
    force_update: bool
    title: str
    message: str
    changelog: str
    download_url: str | None = None
    store_url: str | None = None
    sha256: str | None = None
    updated_at: datetime | None = None
