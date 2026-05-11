"""Schemas for feature parity tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


PlatformStatus = Literal["not_started", "in_progress", "shipped", "deprecated"]
Priority = Literal["P0", "P1", "P2", "P3"]


class FeatureParityBase(BaseModel):
    name: str
    module: str = "general"
    priority: Priority = "P1"
    ios_status: PlatformStatus = "not_started"
    android_status: PlatformStatus = "not_started"
    ios_version: str | None = None
    android_version: str | None = None
    backend_apis: str | None = None
    spec_link: str | None = None
    notes: str | None = None
    sort_order: int = 100


class FeatureParityCreate(FeatureParityBase):
    pass


class FeatureParityUpdate(BaseModel):
    name: str | None = None
    module: str | None = None
    priority: Priority | None = None
    ios_status: PlatformStatus | None = None
    android_status: PlatformStatus | None = None
    ios_version: str | None = None
    android_version: str | None = None
    backend_apis: str | None = None
    spec_link: str | None = None
    notes: str | None = None
    sort_order: int | None = None


class FeatureParityRead(FeatureParityBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeatureParityListOut(BaseModel):
    items: list[FeatureParityRead]
    total: int
