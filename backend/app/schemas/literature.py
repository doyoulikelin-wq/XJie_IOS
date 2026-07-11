"""Schemas for the literature/citation system."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


EvidenceLevel = Literal["L1", "L2", "L3", "L4"]
Topic = Literal["ppgr", "omics", "diet", "exercise", "sleep", "drug", "general"]
Direction = Literal["decrease", "increase", "neutral", "mixed"]


class LiteratureBase(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    language: str = "en"
    evidence_level: EvidenceLevel
    study_design: str | None = None
    sample_size: int | None = None
    population: str | None = None
    conclusion_zh: str
    conclusion_en: str | None = None
    topics: list[Topic] = Field(default_factory=list)


class LiteratureCreate(LiteratureBase):
    source: str = "pubmed"
    reviewed: bool = False
    reviewer: str | None = None


class LiteratureRead(LiteratureBase):
    id: int
    source: str
    reviewed: bool
    reviewer: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ClaimBase(BaseModel):
    claim_text: str
    claim_text_en: str | None = None
    exposure: str
    outcome: str
    effect_size: str | None = None
    direction: Direction | None = None
    population_summary: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    topics: list[Topic] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ClaimCreate(ClaimBase):
    literature_id: int
    evidence_level: EvidenceLevel


class ClaimRead(ClaimBase):
    id: int
    literature_id: int
    evidence_level: EvidenceLevel
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CitationBundle(BaseModel):
    """Compact citation payload returned alongside AI answers."""

    claim_id: int
    literature_id: int
    claim_text: str
    evidence_level: EvidenceLevel
    short_ref: str  # e.g. "Segal et al., Cell 2015"
    journal: str | None = None
    year: int | None = None
    sample_size: int | None = None
    population: str | None = None
    study_design: str | None = None
    confidence: str
    score: float | None = None  # similarity score, 0-1


class IngestRequest(BaseModel):
    query: str
    topic: Topic
    max_results: int = Field(default=50, ge=1, le=500)
    min_year: int | None = None
    auto_extract: bool = True
    auto_embed: bool = True


class IngestJobRead(BaseModel):
    id: int
    query: str
    topic: str
    status: str
    fetched_count: int
    inserted_count: int
    skipped_count: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None

    class Config:
        from_attributes = True


class RetrievalRequest(BaseModel):
    query: str
    topics: list[Topic] | None = None
    min_evidence_level: EvidenceLevel = "L4"
    top_k: int = Field(default=5, ge=1, le=20)


class RetrievalResponse(BaseModel):
    matches: list[CitationBundle]
    used_fallback: bool = False  # true when no good matches → fall back to general LLM
