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

# ── Emoji stripper ────────────────────────────────────────

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental
    "\U0001FA00-\U0001FA6F"  # chess, etc.
    "\U0001FA70-\U0001FAFF"  # symbols extended
    "\U0001F7E0-\U0001F7EB"  # large colored circles/squares
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "\U0001F004"             # mahjong tile
    "\U0001F0CF"             # playing card
    "\U0001F170-\U0001F171"  # neg squared A/B
    "\U0001F17E-\U0001F17F"  # neg squared O/P
    "\U0001F18E"             # neg squared AB
    "\U0001F191-\U0001F19A"  # squared CL..VS
    "\U0001F201-\U0001F251"  # squared koko..accept
    "]+",
    flags=re.UNICODE,
)

def _strip_emoji(text: str) -> str:
    """Remove emoji characters from text."""
    return _EMOJI_RE.sub("", text)


# ── LLM client ──────────────────────────────────────────

def _get_client() -> OpenAI:
    kwargs: dict = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _llm_call(system: str, user: str, max_tokens: int = 4096) -> tuple[str, int]:
    """Call LLM and return (content, total_tokens)."""
    client = _get_client()
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
        **settings.llm_temperature_kwargs(),
    )
    tokens = 0
    if resp.usage:
        tokens = (resp.usage.prompt_tokens or 0) + (resp.usage.completion_tokens or 0)
    return _strip_emoji(resp.choices[0].message.content or ""), tokens


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
) -> tuple[str, int]:
    """Generate or retrieve cached L1 summary. Returns (text, tokens_used)."""
    # Check cache
    cached = db.execute(
        select(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 1,
            HealthDocumentSummary.period_key == period_key,
        )
    ).scalars().first()

    if cached and cached.doc_count == len(docs):
        return cached.summary_text, 0

    # Generate
    data_text = _docs_to_text(docs)
    is_record = all(d.doc_type == "record" for d in docs)
    system = L1_RECORD_SYSTEM if is_record else L1_SYSTEM

    summary, tokens = _llm_call(
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

    return summary, tokens


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
) -> tuple[str, int]:
    """Generate or retrieve cached L2 summary. Returns (text, tokens_used)."""
    cached = db.execute(
        select(HealthDocumentSummary).where(
            HealthDocumentSummary.user_id == user_id,
            HealthDocumentSummary.level == 2,
            HealthDocumentSummary.period_key == year,
        )
    ).scalars().first()

    expected_count = len(l1_summaries)
    if cached and cached.doc_count == expected_count:
        return cached.summary_text, 0

    # Build input from L1 summaries
    parts = []
    for date_key in sorted(l1_summaries.keys()):
        parts.append(f"[{date_key}] {l1_summaries[date_key]}")
    combined = "\n\n".join(parts)

    summary, tokens = _llm_call(
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

    return summary, tokens


# ── L3: Final longitudinal summary ──────────────────────

L3_SYSTEM = """\
你是 Xjie AI 健康分析师。请根据用户多年的年度健康摘要，生成一份纵向健康总结报告。

报告必须严格按以下四部分结构输出，每部分用 ## 标题，**第一部分必须是"核心摘要"且严格遵守其格式**：

## 核心摘要
本部分用于一目了然展示，必须严格遵守如下格式，不得添加其它内容、不要寒暄、不要总评价：

**最重要指标**
1. 指标名（最新数值/单位）：一句话简短解释；趋势：上升/下降/稳定/新发，并附最近一次相对历史的简短描述。
2. 同上格式。
3. 同上格式。
（如不足 3 个值得关注的指标，则只列出实际数量，不要凑数；如完全没有异常或值得关注的指标，可省略本小节。）

**最重要建议**
1. 一句话可执行建议。
2. 同上。
3. 同上。
（必须给出 3 条，措辞简洁，避免空话。）

## 当前重点指标
列出当前最需要关注的 3-5 个异常指标，每个指标说明：
- 指标名称和最新数值
- 这个指标代表什么，为什么异常值得关注

## 历史趋势分析
分析关键指标多年来的变化趋势：
- 哪些指标持续恶化、哪些改善、哪些新出现异常
- 基于趋势推测后续可能的发展方向

## 需要注意的事项
给出 3-5 条具体、可执行的建议：
- 需要复查或就医的项目
- 饮食、运动等生活方式建议
- 如有危急值，务必突出提醒

格式要求：
- 用中文，Markdown 格式（仅标题、加粗、列表，禁止使用表格）
- 不要使用任何 emoji 符号
- 用温和专业的语气
- 全文控制在 1000 字以内"""


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
        summary, tokens = _llm_call(L3_SYSTEM, user_msg, max_tokens=4096)
        _save_l3(user_id, summary, db)
        return summary, tokens


def _stream_l3(user_id: int, user_msg: str, db: Session):
    """Generator that yields SSE events for L3 summary."""
    client = _get_client()
    emitted: list[str] = []

    stream = client.chat.completions.create(
        model=settings.OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": L3_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4096,
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"thinking": {"type": "disabled"}},
        **settings.llm_temperature_kwargs(),
    )

    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            emitted.append(delta.content)
            yield json.dumps({"type": "token", "delta": delta.content}, ensure_ascii=False)

    final_text = _strip_emoji("".join(emitted).strip())
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
    token_callback=None,
):
    """Run the full L1→L2→L3 pipeline.

    Args:
        progress_callback: Optional callable(stage, current, total) for progress updates.
        token_callback: Optional callable(tokens_delta) to accumulate token usage.
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
        text, tokens = generate_l1(user_id, date_key, group, db)
        l1_results[date_key] = text
        if token_callback and tokens:
            token_callback(tokens)
    db.commit()

    # 4. L2: Per-year summaries
    year_groups = _group_by_year(l1_results)
    total_l2 = len(year_groups)
    l2_results: dict[str, str] = {}
    for i, (year, year_l1s) in enumerate(year_groups.items()):
        if progress_callback:
            progress_callback("l2", i + 1, total_l2)
        text, tokens = generate_l2(user_id, year, year_l1s, db)
        l2_results[year] = text
        if token_callback and tokens:
            token_callback(tokens)
    db.commit()

    # 5. L3: Final summary
    if progress_callback:
        progress_callback("l3", 1, 1)
    result = generate_l3(user_id, l2_results, db, stream=stream)
    if not stream and isinstance(result, tuple):
        text, tokens = result
        if token_callback and tokens:
            token_callback(tokens)
        return text
    return result


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


# ── Background task runner ───────────────────────────────

import secrets
import threading

from app.db.session import SessionLocal
from app.models.health_document import SummaryTask


def _generate_task_id() -> str:
    return secrets.token_hex(8)


def _compute_pct(stage: str, current: int, total: int, l1_total: int, l2_total: int) -> float:
    """Compute overall progress percentage.  L1=60%, L2=25%, L3=15%."""
    if stage == "l1" and l1_total > 0:
        return round((current / l1_total) * 0.60, 3)
    elif stage == "l2" and l2_total > 0:
        return round(0.60 + (current / l2_total) * 0.25, 3)
    elif stage == "l3":
        return 0.85
    return 0.0


def start_summary_task(user_id: int) -> SummaryTask:
    """Create a pending task and spawn a background thread."""
    db = SessionLocal()
    try:
        # Reuse running task if exists
        running = db.execute(
            select(SummaryTask).where(
                SummaryTask.user_id == user_id,
                SummaryTask.status.in_(["pending", "running"]),
            )
        ).scalars().first()
        if running:
            task_snapshot = SummaryTask(
                id=running.id, user_id=running.user_id,
                status=running.status, stage=running.stage,
                stage_current=running.stage_current,
                stage_total=running.stage_total,
                progress_pct=running.progress_pct,
                token_used=running.token_used,
            )
            db.close()
            return task_snapshot

        task = SummaryTask(
            id=_generate_task_id(),
            user_id=user_id,
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    t = threading.Thread(
        target=_run_task_background,
        args=(task_id, user_id),
        daemon=True,
    )
    t.start()
    return SummaryTask(id=task_id, user_id=user_id, status="pending",
                       stage_current=0, stage_total=0, token_used=0,
                       progress_pct=0.0)


def _run_task_background(task_id: str, user_id: int):
    """Execute the full pipeline in a background thread."""
    db = SessionLocal()
    try:
        task = db.get(SummaryTask, task_id)
        if not task:
            return
        task.status = "running"
        db.commit()

        totals: dict[str, int] = {"l1": 0, "l2": 0}

        def progress_cb(stage: str, current: int, total: int):
            totals[stage] = total
            task.stage = stage
            task.stage_current = current
            task.stage_total = total
            task.progress_pct = _compute_pct(
                stage, current, total,
                totals.get("l1", total), totals.get("l2", total),
            )
            task.updated_at = datetime.utcnow()
            db.commit()

        def token_cb(delta: int):
            task.token_used = (task.token_used or 0) + delta
            db.commit()

        run_full_pipeline(
            user_id, db, stream=False,
            progress_callback=progress_cb,
            token_callback=token_cb,
        )

        task.status = "done"
        task.progress_pct = 1.0
        task.stage = "l3"
        task.stage_current = 1
        task.stage_total = 1
        db.commit()
        logger.info("Summary task %s done, tokens=%d", task_id, task.token_used or 0)

    except Exception as e:
        logger.exception("Summary task %s failed", task_id)
        try:
            task = db.get(SummaryTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def get_task_status(task_id: str, db: Session) -> SummaryTask | None:
    return db.get(SummaryTask, task_id)
