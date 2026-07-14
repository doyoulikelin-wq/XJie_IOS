"""Retrieval & citation formatting.

For 500 claims we keep retrieval simple: load all enabled claims with
matching evidence/topic filters into memory and run cosine similarity
in Python. This avoids pgvector setup and works on SQLite tests.
When the corpus grows >5K, swap this layer for pgvector.

Hybrid scoring: cosine(embedding) + keyword overlap boost. The boost is
critical when the embedding service is unavailable and we fall back to
the local hash-based pseudo-embedding.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.literature import EVIDENCE_LEVELS, Claim, Literature
from app.schemas.literature import CitationBundle
from app.services.literature.embedding import cosine_similarity, embed_text

logger = logging.getLogger(__name__)


# Minimum combined score to consider a claim relevant.
SCORE_THRESHOLD = 0.30
# Per-keyword overlap boost.
KEYWORD_BOOST = 0.18
# Stop words removed before keyword extraction.
_STOP = {
    "的", "了", "是", "我", "你", "他", "她", "它", "和", "与", "或",
    "吗", "呢", "啊", "吧", "在", "有", "为", "从", "到", "都",
    "the", "a", "an", "is", "are", "and", "or", "of", "to", "in",
    "for", "on", "with", "by", "this", "that",
}
_TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]+|[a-zA-Z][a-zA-Z0-9]*")
_ASCII_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9+._/\- ]*$", re.IGNORECASE)


@dataclass
class _Candidate:
    claim: Claim
    literature: Literature
    score: float


def _evidence_floor(min_level: str) -> set[str]:
    if min_level not in EVIDENCE_LEVELS:
        min_level = "L4"
    idx = EVIDENCE_LEVELS.index(min_level)
    return set(EVIDENCE_LEVELS[: idx + 1])  # e.g. min_level=L2 → {L1, L2}


def _keywords(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text or ""):
        t = tok.lower()
        if t in _STOP:
            continue
        # For Chinese tokens longer than 2 chars, also add bigrams to widen recall
        if len(t) >= 2:
            out.append(t)
        if "\u4e00" <= t[:1] <= "\u9fa5" and len(t) >= 3:
            for i in range(len(t) - 1):
                out.append(t[i : i + 2])
    return out


def _claim_haystack(claim: Claim) -> str:
    parts = [
        claim.claim_text,
        claim.claim_text_en or "",
        claim.exposure,
        claim.outcome,
        " ".join(claim.tags or []),
        " ".join(claim.topics or []),
    ]
    return " ".join(p for p in parts if p).lower()


def retrieve_claims(
    db: Session,
    *,
    query: str,
    topics: list[str] | None = None,
    min_evidence_level: str = "L4",
    top_k: int = 5,
    threshold: float | None = None,
    concept_groups: dict[str, list[str]] | None = None,
    min_concept_groups: int = 0,
) -> list[CitationBundle]:
    """Return top-K matching CitationBundles for the query."""
    threshold = SCORE_THRESHOLD if threshold is None else threshold
    allowed_levels = _evidence_floor(min_evidence_level)

    stmt = (
        select(Claim)
        .options(joinedload(Claim.literature))
        .where(Claim.enabled.is_(True))
        .where(Claim.evidence_level.in_(allowed_levels))
    )
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return []

    if topics:
        topic_set = set(topics)
        rows = [r for r in rows if topic_set.intersection(r.topics or [])]
        if not rows:
            return []

    q_vec, embedding_model = embed_text(query)
    q_keywords = _keywords(query)

    cands: list[_Candidate] = []
    for c in rows:
        haystack = _claim_haystack(c)
        if concept_groups and _matched_concept_groups(haystack, concept_groups) < min_concept_groups:
            continue
        cos = cosine_similarity(q_vec, c.embedding) if c.embedding else 0.0
        # Keyword overlap boost
        boost = 0.0
        seen: set[str] = set()
        for kw in q_keywords:
            if kw in seen:
                continue
            if kw in haystack:
                boost += KEYWORD_BOOST
                seen.add(kw)
        if embedding_model.startswith("local-hash") and not seen and not concept_groups:
            continue
        score = max(cos, 0.0) + boost
        if score < threshold:
            continue
        cands.append(_Candidate(claim=c, literature=c.literature, score=score))

    cands.sort(key=lambda x: x.score, reverse=True)
    return [_to_bundle(c) for c in cands[:top_k]]


def _matched_concept_groups(haystack: str, concept_groups: dict[str, list[str]]) -> int:
    matched = 0
    for aliases in concept_groups.values():
        if any(_alias_matches(haystack, alias) for alias in aliases):
            matched += 1
    return matched


def _alias_matches(haystack: str, alias: str) -> bool:
    raw_alias = str(alias or "").strip().lower()
    if not raw_alias:
        return False
    if _ASCII_ALIAS_RE.fullmatch(raw_alias):
        normalized_haystack = re.sub(r"[^a-z0-9]+", " ", haystack.lower()).strip()
        normalized_alias = re.sub(r"[^a-z0-9]+", " ", raw_alias).strip()
        if not normalized_alias:
            return False
        token_pattern = r"\s+".join(re.escape(token) for token in normalized_alias.split())
        return bool(
            re.search(
                rf"(?<![a-z0-9]){token_pattern}(?![a-z0-9])",
                normalized_haystack,
            )
        )
    normalized_haystack = _normalize_term(haystack)
    normalized_alias = _normalize_term(raw_alias)
    return bool(normalized_alias and normalized_alias in normalized_haystack)


def _normalize_term(value: object) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def _to_bundle(cand: _Candidate) -> CitationBundle:
    return citation_bundle_from_claim(cand.claim, score=round(cand.score, 4))


def citation_bundle_from_claim(claim: Claim, *, score: float | None = None) -> CitationBundle:
    """Build the stable public citation payload from a persisted claim."""

    lit = claim.literature
    return CitationBundle(
        claim_id=claim.id,
        literature_id=lit.id,
        claim_text=claim.claim_text,
        evidence_level=claim.evidence_level,  # type: ignore[arg-type]
        short_ref=format_short_ref(lit),
        journal=lit.journal,
        year=lit.year,
        sample_size=lit.sample_size,
        population=claim.population_summary or lit.population,
        study_design=lit.study_design,
        confidence=claim.confidence,
        score=score,
    )


def format_short_ref(lit: Literature) -> str:
    """e.g. 'Segal et al., Cell 2015'."""
    if lit.authors:
        first = lit.authors[0]
        # Use last name only when possible
        last_name = first.split()[-1] if first else ""
        suffix = " et al." if len(lit.authors) > 1 else ""
        prefix = f"{last_name}{suffix}"
    else:
        prefix = "Anonymous"
    journal = lit.journal or ""
    year = f" {lit.year}" if lit.year else ""
    if journal:
        return f"{prefix}, {journal}{year}".strip()
    return f"{prefix}{year}".strip()


def build_citation_block(citations: list[CitationBundle]) -> str:
    """Plain-text block to append to AI prompts.

    Returns empty string if no citations.
    Each entry includes the applicable population and an explicit evidence
    boundary so the model cannot silently generalise adult, observational, or
    low-confidence findings to the current user.
    """
    if not citations:
        return ""
    lines = []
    for i, c in enumerate(citations, start=1):
        population = c.population or "适用人群未明确"
        design = c.study_design or "研究类型未记录"
        sample = str(c.sample_size) if c.sample_size is not None else "未报告"
        boundary = _citation_evidence_boundary(c)
        lines.append(
            f"[{i}] {c.short_ref}\n"
            f"结论：{c.claim_text}\n"
            f"适用人群：{population}\n"
            f"证据：层级={c.evidence_level}；研究类型={design}；样本量={sample}；"
            f"claim confidence={c.confidence}\n"
            f"使用边界：{boundary}"
        )
    return "\n".join(lines)


def _citation_evidence_boundary(citation: CitationBundle) -> str:
    boundaries = ["只能支持上面的具体结论，不能跨主题引用"]
    if citation.population:
        boundaries.append("只可在与上述适用人群和条件相符时谨慎外推")
    else:
        boundaries.append("适用人群不明时不得直接外推到当前用户")
    design = (citation.study_design or "").lower()
    if citation.evidence_level in {"L3", "L4"} or any(
        term in design for term in ("observational", "mechanistic", "case", "expert")
    ):
        boundaries.append("不能据此确认个体因果或诊断")
    if citation.confidence != "high":
        boundaries.append(f"该 claim 置信度为 {citation.confidence}，必须明确不确定性")
    return "；".join(boundaries) + "。"
