"""Three-layer hierarchical health summarization service.

L1: Per-exam-date / per-record summary  (~150 words each)
L2: Per-year summary                    (~200 words each)
L3: Final longitudinal summary          (~800 words)

Cached in health_document_summaries (L1/L2) and health_summaries (L3).
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime

from openai import OpenAI
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.health_document import (
    HealthDocument,
    HealthDocumentSummary,
    HealthSummary,
)

logger = logging.getLogger(__name__)

# ── LLM client ──────────────────────────────────────────

def _get_client() -> OpenAI:
    kwargs: dict = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _llm_call(system: str, user: str, max_tokens: int = 4096) -> str:
    client = _get_client()
    resp = client.chat.completions.create(
        model="kimi-k2.5",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.6,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return resp.choices[0].message.content or ""


# ── Data helpers ─────────────────────────────────────────

def _docs_to_text(docs: list[HealthDocument]) -> str:
    """Convert a group of documents into a compact text for LLM input."""
    parts: list[str] = []
    for doc in docs:
        csv = doc.csv_data or {}
        cols = csv.get("columns", [])
        rows = csv.get("rows", [])
        if not rows:
            continue
        parts.append(f"--- {doc.name} ({doc.doc_type}) ---")
        # Build compact table
        for row in rows:
            if len(row) >= 2:
                if doc.doc_type == "exam" and len(row) >= 5:
                    # [项目, 数值, 单位, 参考范围, 异常]
                    flag = f" [{row[4]}]" if row[4] else ""
                    ref = f" (参考:{row[3]})" if row[3] else ""
                    parts.append(f"  {row[0]}: {row[1]} {row[2]}{ref}{flag}")
                else:
                    parts.append(f"  {row[0]}: {row[1]}")
    return "\n".join(parts)


def _group_docs_by_date(docs: list[HealthDocument]) -> dict[str, list[HealthDocument]]:
    """Group documents by date string (YYYY-MM-DD)."""
    groups: dict[str, list[HealthDocument]] = defaultdict(list)
    for doc in docs:
        key = doc.doc_date.strftime("%Y-%m-%d") if doc.doc_date else "unknown"
        groups[key].append(doc)
    return dict(sorted(groups.items()))


def _group_by_year(items: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group period_key→summary_text by year."""
    years: dict[str, dict[str, str]] = defaultdict(dict)
    for period_key, text in items.items():
        year = period_key[:4] if len(period_key) >= 4 else "unknown"
        years[year][period_key] = text
    return dict(sorted(years.items()))


def _parse_abnormals_from_text(text: str) -> list[dict]:
    """Extract abnormal items from L1 summary text (best-effort)."""
    abnormals = []
    for line in text.split("\n"):
        if "↑" in line or "↓" in line or "异常" in line or "偏高" in line or "偏低" in line:
            abnormals.append({"text": line.strip()})
    return abnormals


# ── L1: Per-exam-date summary ────────────────────────────

L1_SYSTEM = """\
你是医学数据分析专家。请根据一次体检/就诊的全部检查数据生成简洁摘要。

要求：
1. 用中文，150字以内
2. 列出所有异常指标（含数值和参考范围）
3. 给出该次检查的整体印象
4. 如果是病例记录，提取核心诊断和治疗方案
5. 不要遗漏重要异常"""

L1_RECORD_SYSTEM = """\
你是医学数据分析专家。请根据一份门诊病历记录生成简洁摘要。

要求：
1. 用中文，150字以内
2. 提取核心诊断、主诉、治疗方案
3. 列出关键检查结果
4. 不要遗漏重要信息"""


def generate_l1(
    user_id: int,
    period_key: str,
    docs: list[HealthDocument],
    db: Session,
) -> str:
    """Generate or retrieve cached L1 summary for a specific date's documents."""
    # Check cache
    cached = db.execute(
        select(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 1,
            HealthDocumentSummary.period_key == period_key,
        )
    ).scalars().first()

    if cached and cached.doc_count == len(docs):
        return cached.summary_text

    # Generate
    data_text = _docs_to_text(docs)
    is_record = all(d.doc_type == "record" for d in docs)
    system = L1_RECORD_SYSTEM if is_record else L1_SYSTEM

    summary = _llm_call(
        system,
        f"日期: {period_key}\n数据如下:\n\n{data_text}",
        max_tokens=1024,
    )

    abnormals = _parse_abnormals_from_text(summary)

    # Upsert cache
    if cached:
        cached.summary_text = summary
        cached.abnormal_highlights = abnormals
        cached.doc_count = len(docs)
        cached.created_at = datetime.utcnow()
    else:
        cached = HealthDocumentSummary(
            user_id=user_id,
            level=1,
            period_key=period_key,
            summary_text=summary,
            abnormal_highlights=abnormals,
            doc_count=len(docs),
        )
        db.add(cached)
    db.flush()

    return summary


# ── L2: Per-year summary ─────────────────────────────────

L2_SYSTEM = """\
你是健康趋势分析专家。请根据同一年内的多次体检/就诊摘要，生成该年度的健康趋势总结。

要求：
1. 用中文，200字以内
2. 重点分析该年度的异常指标变化
3. 指出哪些指标恶化、哪些改善
4. 总结该年度整体健康状态
5. 如有严重异常，突出提醒"""


def generate_l2(
    user_id: int,
    year: str,
    l1_summaries: dict[str, str],
    db: Session,
) -> str:
    """Generate or retrieve cached L2 summary for a year."""
    cached = db.execute(
        select(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 2,
            HealthDocumentSummary.period_key == year,
        )
    ).scalars().first()

    expected_count = len(l1_summaries)
    if cached and cached.doc_count == expected_count:
        return cached.summary_text

    # Build input from L1 summaries
    parts = []
    for date_key in sorted(l1_summaries.keys()):
        parts.append(f"[{date_key}] {l1_summaries[date_key]}")
    combined = "\n\n".join(parts)

    summary = _llm_call(
        L2_SYSTEM,
        f"年度: {year}年\n\n该年度各次检查/就诊摘要:\n\n{combined}",
        max_tokens=1024,
    )

    abnormals = _parse_abnormals_from_text(summary)

    if cached:
        cached.summary_text = summary
        cached.abnormal_highlights = abnormals
        cached.doc_count = expected_count
        cached.created_at = datetime.utcnow()
    else:
        cached = HealthDocumentSummary(
            user_id=user_id,
            level=2,
            period_key=year,
            summary_text=summary,
            abnormal_highlights=abnormals,
            doc_count=expected_count,
        )
        db.add(cached)
    db.flush()

    return summary


# ── L3: Final longitudinal summary ──────────────────────

L3_SYSTEM = """\
你是 Xjie AI 健康分析师。请根据用户多年的年度健康摘要，生成一份纵向健康总结报告。

报告要求：
1. 用中文，Markdown 格式
2. 先给出 **整体健康评分**（🟢 正常 / 🟡 需关注 / 🔴 需就医）
3. **核心健康趋势**：哪些指标多年持续异常、哪些恶化、哪些改善
4. **当前重点关注项**：列出最新一次检查中的异常指标
5. 给出 3-5 条 **个性化健康建议**（饮食、运动、就医建议）
6. 如有危急值或持续恶化趋势，务必突出提醒
7. 用温和专业的语气，避免过度恐吓
8. 控制在 800 字以内"""


def generate_l3(
    user_id: int,
    l2_summaries: dict[str, str],
    db: Session,
    stream: bool = False,
):
    """Generate final L3 summary. If stream=True, yields SSE chunks."""
    parts = []
    for year in sorted(l2_summaries.keys()):
        parts.append(f"## {year}年\n{l2_summaries[year]}")
    combined = "\n\n".join(parts)

    user_msg = f"以下是该用户从{min(l2_summaries.keys())}年到{max(l2_summaries.keys())}年的各年度健康摘要:\n\n{combined}"

    if stream:
        return _stream_l3(user_id, user_msg, db)
    else:
        summary = _llm_call(L3_SYSTEM, user_msg, max_tokens=4096)
        _save_l3(user_id, summary, db)
        return summary


def _stream_l3(user_id: int, user_msg: str, db: Session):
    """Generator that yields SSE events for L3 summary."""
    client = _get_client()
    emitted: list[str] = []

    stream = client.chat.completions.create(
        model="kimi-k2.5",
        messages=[
            {"role": "system", "content": L3_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4096,
        temperature=0.6,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"thinking": {"type": "disabled"}},
    )

    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            emitted.append(delta.content)
            yield json.dumps({"type": "token", "delta": delta.content}, ensure_ascii=False)

    final_text = "".join(emitted).strip()
    _save_l3(user_id, final_text, db)
    yield json.dumps({"type": "done", "text": final_text}, ensure_ascii=False)


def _save_l3(user_id: int, text: str, db: Session):
    """Upsert L3 summary into health_summaries."""
    existing = db.execute(
        select(HealthSummary).where(HealthSummary.user_id == user_id).limit(1)
    ).scalars().first()

    if existing:
        existing.summary_text = text
        existing.version = (existing.version or 0) + 1
        existing.updated_at = datetime.utcnow()
    else:
        row = HealthSummary(user_id=user_id, summary_text=text, version=1)
        db.add(row)
    db.commit()


# ── Full pipeline ────────────────────────────────────────

def run_full_pipeline(
    user_id: int,
    db: Session,
    stream: bool = False,
    progress_callback=None,
):
    """Run the full L1→L2→L3 pipeline.

    Args:
        progress_callback: Optional callable(stage, current, total) for progress updates.
        stream: If True, L3 returns a generator of SSE events.
    """
    # 1. Fetch all documents
    docs = db.execute(
        select(HealthDocument)
        .where(
            HealthDocument.user_id == user_id,
            HealthDocument.extraction_status == "done",
        )
        .order_by(HealthDocument.doc_date.asc().nulls_last())
    ).scalars().all()

    if not docs:
        if stream:
            def empty():
                yield json.dumps({"type": "done", "text": "暂无健康数据，请先上传病例或体检报告。"}, ensure_ascii=False)
            return empty()
        return "暂无健康数据，请先上传病例或体检报告。"

    # 2. Group by date
    date_groups = _group_docs_by_date(list(docs))
    total_l1 = len(date_groups)

    # 3. L1: Per-date summaries
    l1_results: dict[str, str] = {}
    for i, (date_key, group) in enumerate(date_groups.items()):
        if progress_callback:
            progress_callback("l1", i + 1, total_l1)
        l1_results[date_key] = generate_l1(user_id, date_key, group, db)
    db.commit()

    # 4. L2: Per-year summaries
    year_groups = _group_by_year(l1_results)
    total_l2 = len(year_groups)
    l2_results: dict[str, str] = {}
    for i, (year, year_l1s) in enumerate(year_groups.items()):
        if progress_callback:
            progress_callback("l2", i + 1, total_l2)
        l2_results[year] = generate_l2(user_id, year, year_l1s, db)
    db.commit()

    # 5. L3: Final summary
    if progress_callback:
        progress_callback("l3", 1, 1)
    return generate_l3(user_id, l2_results, db, stream=stream)


# ── Incremental update ───────────────────────────────────

def invalidate_for_date(user_id: int, date_key: str, db: Session):
    """Invalidate L1 cache for a specific date and its L2 year + L3."""
    # Remove L1 for this date
    db.execute(
        delete(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 1,
            HealthDocumentSummary.period_key == date_key,
        )
    )
    # Remove L2 for the year
    year = date_key[:4]
    db.execute(
        delete(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 2,
            HealthDocumentSummary.period_key == year,
        )
    )
    db.commit()
