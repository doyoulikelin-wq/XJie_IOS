"""Health data router – AI summary, medical records, exam reports, indicator trends."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openai import OpenAI
from sqlalchemy import select, func as sa_func, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user_id, get_db
from app.models.health_document import HealthDocument, HealthSummary, IndicatorKnowledge, PatientHistoryProfile, SummaryTask, WatchedIndicator
from app.schemas.health_document import (
    HealthDocumentListOut,
    HealthDocumentOut,
    HealthSummaryOut,
    IndicatorInfo,
    IndicatorListOut,
    IndicatorTrend,
    IndicatorTrendOut,
    PatientHistoryProfileIn,
    PatientHistoryProfileOut,
    SummaryTaskOut,
    TrendPoint,
    WatchedIndicatorIn,
    WatchedIndicatorOut,
    WatchedListOut,
)
from app.services.patient_history_service import (
    build_default_doctor_summary,
    build_evidence_overview,
    build_key_metrics,
    compute_completeness,
    compute_missing_sections,
    normalize_sections,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Helper ──────────────────────────────────────────────

def _get_llm_client() -> OpenAI:
    kwargs: dict = {"api_key": settings.OPENAI_API_KEY}
    if settings.OPENAI_BASE_URL:
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _llm_vision_call(image_b64: str, system_prompt: str, user_prompt: str) -> str:
    """Call Kimi K2.5 vision with a base64 image, return raw text."""
    client = _get_llm_client()
    data_url = f"data:image/jpeg;base64,{image_b64}"
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL_VISION,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": user_prompt},
            ]},
        ],
        max_tokens=4096,
        extra_body={"thinking": {"type": "disabled"}},
        **settings.llm_temperature_kwargs(settings.OPENAI_MODEL_VISION),
    )
    return resp.choices[0].message.content or ""


def _parse_json_from_llm(raw: str) -> dict:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    text = raw.strip()
    if "```" in text:
        text = text.split("```json")[-1].split("```")[0].strip() if "```json" in text else text.split("```")[-2].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def _generate_doc_summary(csv_data: dict | None, abnormal_flags: list | None, doc_type: str) -> tuple[str, str]:
    """Use LLM to generate a brief (≤10 chars) and detailed summary from extracted data.

    Returns (ai_brief, ai_summary). On failure returns empty strings.
    """
    if not csv_data or not csv_data.get("rows"):
        return "", ""

    # Build a text representation of the data
    columns = csv_data.get("columns", [])
    rows = csv_data.get("rows", [])
    lines = []
    for row in rows[:50]:  # cap to avoid token overflow
        pairs = [f"{columns[i]}: {row[i]}" for i in range(min(len(columns), len(row))) if row[i]]
        lines.append(" | ".join(pairs))
    data_text = "\n".join(lines)

    abnormal_text = ""
    if abnormal_flags:
        abnormal_text = "\n异常项: " + ", ".join(
            f.get("field", f.get("name", "")) for f in abnormal_flags if isinstance(f, dict)
        )

    type_label = "病例" if doc_type == "record" else "体检报告"

    client = _get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=settings.OPENAI_MODEL_TEXT,
            messages=[
                {"role": "system", "content": (
                    f"你是医疗文档整理专家。用户上传了一份{type_label}，下面是从中提取的结构化数据。"
                    "请完成两个任务：\n"
                    "1. brief: 用10个字以内概括这份文档的核心内容（如\"甲功五项复查\"、\"肝功能异常\"、\"年度体检正常\"）\n"
                    "2. summary: 用通俗易懂的语言整理这份文档的完整内容，分段清晰，重点突出异常项和医嘱建议。"
                    "不要使用表格格式，用自然段落书写。\n\n"
                    '返回严格JSON: {"brief":"≤10字概括","summary":"详细整理内容"}'
                )},
                {"role": "user", "content": f"以下是{type_label}数据：\n{data_text}{abnormal_text}"},
            ],
            max_tokens=2048,
            **settings.llm_temperature_kwargs(),
        )
        raw = resp.choices[0].message.content or ""
        data = _parse_json_from_llm(raw)
        brief = (data.get("brief") or "")[:20]
        summary = data.get("summary") or ""
        if brief and summary:
            return brief, summary
    except Exception as e:
        logger.warning("LLM doc summary generation failed: %s", e)

    return "", ""


def _save_original_file(user_id: int, doc_id: int, filename: str, file_bytes: bytes) -> str:
    """Save the original uploaded file to LOCAL_STORAGE_DIR and return the relative path."""
    safe_name = re.sub(r'[^\w.\-]', '_', filename)
    rel_path = f"{user_id}/{doc_id}_{safe_name}"
    full_path = Path(settings.LOCAL_STORAGE_DIR) / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(file_bytes)
    return rel_path


def _doc_to_out(doc: HealthDocument) -> HealthDocumentOut:
    file_url = None
    if doc.original_file_path and not doc.original_file_path.startswith("data:"):
        file_url = f"/api/health-data/documents/{doc.id}/file"
    return HealthDocumentOut(
        id=str(doc.id),
        doc_type=doc.doc_type,
        source_type=doc.source_type,
        name=doc.name,
        hospital=doc.hospital,
        doc_date=doc.doc_date.isoformat() if doc.doc_date else None,
        csv_data=doc.csv_data,
        abnormal_flags=doc.abnormal_flags,
        ai_brief=doc.ai_brief,
        ai_summary=doc.ai_summary,
        extraction_status=doc.extraction_status,
        created_at=doc.created_at,
        file_url=file_url,
    )


def _patient_history_to_out(profile: PatientHistoryProfile | None, db: Session, user_id: int) -> PatientHistoryProfileOut:
    sections = normalize_sections(profile.sections if profile else None)
    doctor_summary = (profile.doctor_summary if profile else "") or build_default_doctor_summary(db, user_id)
    missing_sections = compute_missing_sections(sections)
    return PatientHistoryProfileOut(
        doctor_summary=doctor_summary,
        sections=sections,
        key_metrics=build_key_metrics(db, user_id),
        evidence_overview=build_evidence_overview(db, user_id),
        missing_sections=missing_sections,
        completeness=compute_completeness(sections, doctor_summary),
        updated_at=profile.updated_at if profile else None,
        verified_at=profile.verified_at if profile else None,
    )


def _extract_record_from_image(file_bytes: bytes, filename: str) -> dict:
    """LLM extraction for medical record photos → structured CSV data."""
    b64 = base64.b64encode(file_bytes).decode("ascii")
    try:
        raw = _llm_vision_call(
            b64,
            system_prompt=(
                "你是医疗文档 OCR 专家。请从门诊病历/病例照片中提取结构化信息。"
                "返回严格 JSON 格式（不要多余文本）：\n"
                '{"columns": ["项目", "内容"], "rows": [["姓名","xxx"],["性别","xxx"],'
                '["年龄","xxx"],["就诊科室","xxx"],["记录时间","xxx"],["主诉","xxx"],'
                '["现病史","xxx"],["既往史","xxx"],["体格检查","xxx"],'
                '["辅助检查结果","xxx"],["诊断","xxx"],["治疗计划","xxx"],'
                '["随访医嘱","xxx"]]}'
            ),
            user_prompt="请从这张门诊病历照片中提取所有可读信息，按要求的JSON格式输出。如果某项无法识别就填\"未提及\"。",
        )
        data = _parse_json_from_llm(raw)
        if data.get("columns") and data.get("rows"):
            return data
    except Exception as e:
        logger.warning("LLM record extraction failed: %s", e)

    return {
        "columns": ["项目", "内容"],
        "rows": [["提取失败", f"LLM未能识别，原文件: {filename}"]],
    }


def _extract_exam_from_image(file_bytes: bytes, filename: str) -> tuple[dict, list]:
    """LLM extraction for exam report photos → (csv_data, abnormal_flags)."""
    b64 = base64.b64encode(file_bytes).decode("ascii")
    try:
        raw = _llm_vision_call(
            b64,
            system_prompt=(
                "你是体检报告 OCR 专家。请从体检报告照片中提取所有检查项目的具体数据。"
                "务必提取精确数值，不要只写'偏高'或'偏低'。"
                "返回严格 JSON 格式（不要多余文本）：\n"
                '{"items": [{"name":"检查项目名","value":"具体数值(如6.8)","unit":"单位(如mmol/L)",'
                '"ref_range":"参考范围(如3.9-6.1)","is_abnormal":true/false},...], '
                '"summary":"体检小结/医师建议（如有）"}'
            ),
            user_prompt="请从这张体检报告照片中逐项提取所有检查项目，必须包含具体数值、单位和参考范围。每个异常项标注is_abnormal:true。",
        )
        data = _parse_json_from_llm(raw)
        items = data.get("items", [])
        if items:
            csv_data = {
                "columns": ["检查项目", "数值", "单位", "参考范围", "异常"],
                "rows": [
                    [it.get("name", ""), str(it.get("value", "")), it.get("unit", ""),
                     it.get("ref_range", ""), "↑异常" if it.get("is_abnormal") else ""]
                    for it in items
                ],
            }
            abnormal_flags = [
                {"field": it["name"], "value": str(it.get("value", "")),
                 "ref_range": it.get("ref_range", ""), "is_abnormal": True}
                for it in items if it.get("is_abnormal")
            ]
            if data.get("summary"):
                csv_data["rows"].append(["体检小结", data["summary"], "", "", ""])
            return csv_data, abnormal_flags
    except Exception as e:
        logger.warning("LLM exam extraction failed: %s", e)

    csv_data = {
        "columns": ["检查项目", "数值", "单位", "参考范围", "异常"],
        "rows": [["提取失败", "", "", f"LLM未能识别: {filename}", ""]],
    }
    return csv_data, []


def _extract_name_from_image(file_bytes: bytes, doc_type: str) -> str:
    """LLM extraction of document name (hospital + date) from image."""
    b64 = base64.b64encode(file_bytes).decode("ascii")
    try:
        raw = _llm_vision_call(
            b64,
            system_prompt=(
                "你是医疗文档识别专家。请从图片中识别医院名称和文档日期。"
                '返回严格 JSON: {"hospital":"医院名","date":"YYYY-MM-DD"}'
            ),
            user_prompt="请识别这张医疗文档图片中的医院名称和日期。",
        )
        data = _parse_json_from_llm(raw)
        hospital = data.get("hospital", "未识别医院")
        date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        label = "病例" if doc_type == "record" else "体检报告"
        return f"{hospital}-{date_str}-{label}"
    except Exception as e:
        logger.warning("LLM name extraction failed: %s", e)
    now = datetime.now().strftime("%Y-%m-%d")
    label = "病例" if doc_type == "record" else "体检报告"
    return f"未识别医院-{now}-{label}"


def _parse_csv_record(file_bytes: bytes, filename: str) -> dict:
    """Parse CSV file directly into structured data (no LLM needed)."""
    text = file_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"columns": ["项目", "内容"], "rows": []}
    # CSV has header row
    columns = rows[0] if rows else ["项目", "内容"]
    data_rows = rows[1:] if len(rows) > 1 else []
    return {"columns": columns, "rows": data_rows}


# ─── AI Summary ──────────────────────────────────────────

@router.get("/summary", response_model=HealthSummaryOut)
def get_summary(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get latest AI health summary for user."""
    row = db.execute(
        select(HealthSummary)
        .where(HealthSummary.user_id == user_id)
        .order_by(HealthSummary.updated_at.desc())
        .limit(1)
    ).scalars().first()

    if row:
        return HealthSummaryOut(summary_text=row.summary_text, updated_at=row.updated_at)
    return HealthSummaryOut(summary_text="", updated_at=None)


@router.post("/summary/generate", response_model=HealthSummaryOut)
def generate_summary(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Generate a new AI health summary using three-layer hierarchical pipeline (sync)."""
    from app.services.health_summary_service import run_full_pipeline

    result = run_full_pipeline(user_id, db, stream=False)

    row = db.execute(
        select(HealthSummary)
        .where(HealthSummary.user_id == user_id)
        .order_by(HealthSummary.updated_at.desc())
        .limit(1)
    ).scalars().first()

    if row:
        return HealthSummaryOut(summary_text=row.summary_text, updated_at=row.updated_at)
    return HealthSummaryOut(summary_text=result if isinstance(result, str) else "", updated_at=None)


@router.post("/summary/generate-async", response_model=SummaryTaskOut)
def generate_summary_async(
    user_id: int = Depends(get_current_user_id),
):
    """Submit an async background task to generate the AI health summary."""
    from app.services.health_summary_service import start_summary_task

    task = start_summary_task(user_id)
    return SummaryTaskOut(
        task_id=task.id,
        status=task.status,
        stage=task.stage,
        stage_current=task.stage_current,
        stage_total=task.stage_total,
        progress_pct=task.progress_pct,
        token_used=task.token_used or 0,
    )


@router.get("/summary/task/{task_id}", response_model=SummaryTaskOut)
def get_summary_task(
    task_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Query the status of a background summary generation task."""
    task = db.get(SummaryTask, task_id)
    if not task or task.user_id != user_id:
        raise HTTPException(404, "Task not found")
    return SummaryTaskOut(
        task_id=task.id,
        status=task.status,
        stage=task.stage,
        stage_current=task.stage_current,
        stage_total=task.stage_total,
        progress_pct=task.progress_pct,
        token_used=task.token_used or 0,
        error_message=task.error_message,
    )


@router.get("/summary/generate-stream")
def generate_summary_stream(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Stream the AI health summary generation with progress events."""
    from app.services.health_summary_service import run_full_pipeline

    def event_stream():
        def progress_cb(stage: str, current: int, total: int):
            evt = json.dumps({
                "type": "progress",
                "stage": stage,
                "current": current,
                "total": total,
            }, ensure_ascii=False)
            return evt

        progress_events: list[str] = []

        def collect_progress(stage, current, total):
            progress_events.append(progress_cb(stage, current, total))

        gen = run_full_pipeline(user_id, db, stream=True, progress_callback=collect_progress)

        # Yield progress events first
        for evt in progress_events:
            yield f"data: {evt}\n\n"

        # Then yield L3 stream tokens
        if hasattr(gen, '__iter__') or hasattr(gen, '__next__'):
            for chunk in gen:
                yield f"data: {chunk}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'done', 'text': str(gen)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Document Upload (async) ─────────────────────────────

def _process_document_background(doc_id: int, file_bytes: bytes, filename: str, doc_type: str, source_type: str):
    """Background thread: run LLM extraction + summary, then update the document."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        doc = db.get(HealthDocument, doc_id)
        if not doc:
            return

        # 1️⃣  Extract structured data
        if source_type == "csv":
            csv_data = _parse_csv_record(file_bytes, filename)
            abnormal_flags = None
        elif doc_type == "record":
            csv_data = _extract_record_from_image(file_bytes, filename)
            abnormal_flags = None
        else:
            csv_data, abnormal_flags = _extract_exam_from_image(file_bytes, filename)

        # Validate — mark failed if LLM could not recognise
        if csv_data and csv_data.get("rows"):
            first_row = csv_data["rows"][0]
            if first_row and str(first_row[0]).startswith("提取失败"):
                doc.extraction_status = "failed"
                doc.ai_brief = "识别失败"
                db.commit()
                return
            if doc_type == "record" and len(csv_data["rows"]) > 0:
                content_values = [
                    str(r[1]) for r in csv_data["rows"]
                    if len(r) > 1 and str(r[1]).strip() not in ("", "未提及")
                ]
                if not content_values:
                    doc.extraction_status = "failed"
                    doc.ai_brief = "识别失败"
                    db.commit()
                    return

        # 2️⃣  Extract name from image (hospital + date)
        if source_type == "photo":
            auto_name = _extract_name_from_image(file_bytes, doc_type)
            doc.name = auto_name
            doc.hospital = auto_name.split("-")[0] if "-" in auto_name else None
            date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", auto_name)
            if date_match:
                try:
                    doc.doc_date = datetime.strptime(date_match.group(1).replace("/", "-"), "%Y-%m-%d")
                except ValueError:
                    pass

        # 3️⃣  Generate AI summary
        ai_brief, ai_summary = _generate_doc_summary(csv_data, abnormal_flags, doc_type)

        # 4️⃣  Commit results
        doc.csv_data = csv_data
        doc.abnormal_flags = abnormal_flags
        doc.ai_brief = ai_brief or None
        doc.ai_summary = ai_summary or None
        doc.extraction_status = "done"
        db.commit()

        logger.info("Document %d processing done: %s", doc_id, doc.name)

    except Exception as e:
        logger.exception("Background processing failed for doc %d: %s", doc_id, e)
        try:
            doc = db.get(HealthDocument, doc_id)
            if doc:
                doc.extraction_status = "failed"
                doc.ai_brief = "处理失败"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/upload", response_model=HealthDocumentOut)
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(..., pattern=r"^(record|exam)$"),
    name: str = Form(default=""),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Upload a photo/CSV/PDF — saves immediately and processes LLM extraction in background.

    Returns the document with extraction_status='pending' (for images) or 'done' (for CSV).
    Client should poll GET /documents/{doc_id} until extraction_status != 'pending'.
    """
    file_bytes = file.file.read()
    filename = file.filename or "unknown"
    content_type = file.content_type or ""

    is_image = content_type.startswith("image/") or filename.lower().endswith((".jpg", ".jpeg", ".png", ".heic"))

    # Determine source type
    if is_image:
        source_type = "photo"
    elif filename.lower().endswith(".csv"):
        source_type = "csv"
    elif filename.lower().endswith(".pdf"):
        source_type = "pdf"
    else:
        source_type = "photo"  # default

    # For non-image uploads, derive name
    if not is_image:
        if not name:
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            label = "病例" if doc_type == "record" else "体检报告"
            doc_name = f"{stem}-{label}"
        else:
            doc_name = name
    else:
        label = "病例" if doc_type == "record" else "体检报告"
        doc_name = name or f"正在识别-{label}"

    # For CSV: process synchronously (fast, no LLM needed)
    if source_type == "csv":
        csv_data = _parse_csv_record(file_bytes, filename)
        ai_brief, ai_summary = _generate_doc_summary(csv_data, None, doc_type)
        doc_date = datetime.utcnow()
        date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", doc_name)
        if date_match:
            try:
                doc_date = datetime.strptime(date_match.group(1).replace("/", "-"), "%Y-%m-%d")
            except ValueError:
                pass
        doc = HealthDocument(
            user_id=user_id, doc_type=doc_type, source_type=source_type,
            name=doc_name, hospital=doc_name.split("-")[0] if "-" in doc_name else None,
            doc_date=doc_date, original_file_path=f"data:base64:{filename}",
            csv_data=csv_data, abnormal_flags=None,
            ai_brief=ai_brief or None, ai_summary=ai_summary or None,
            extraction_status="done",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        # Save original CSV file
        rel = _save_original_file(user_id, doc.id, filename, file_bytes)
        doc.original_file_path = rel
        db.commit()
        db.refresh(doc)
        return _doc_to_out(doc)

    # For images: save immediately with pending status, process in background
    doc = HealthDocument(
        user_id=user_id, doc_type=doc_type, source_type=source_type,
        name=doc_name, doc_date=datetime.utcnow(),
        original_file_path=f"data:base64:{filename}",
        extraction_status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    # Save original file to disk
    rel = _save_original_file(user_id, doc.id, filename, file_bytes)
    doc.original_file_path = rel
    db.commit()

    logger.info("Health document created (pending): id=%d, user=%s", doc.id, str(user_id)[:8])

    # Start background thread for LLM processing
    thread = threading.Thread(
        target=_process_document_background,
        args=(doc.id, file_bytes, filename, doc_type, source_type),
        daemon=True,
    )
    thread.start()

    return _doc_to_out(doc)


# ─── Document List & Detail ──────────────────────────────

@router.get("/documents", response_model=HealthDocumentListOut)
def list_documents(
    doc_type: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List documents, optionally filtered by doc_type ('record' or 'exam')."""
    q = select(HealthDocument).where(HealthDocument.user_id == user_id)
    if doc_type:
        q = q.where(HealthDocument.doc_type == doc_type)
    q = q.order_by(HealthDocument.doc_date.desc().nulls_last(), HealthDocument.created_at.desc())

    docs = db.execute(q).scalars().all()
    return HealthDocumentListOut(
        items=[_doc_to_out(d) for d in docs],
        total=len(docs),
    )


@router.get("/documents/{doc_id}", response_model=HealthDocumentOut)
def get_document(
    doc_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get a single document detail (with CSV data)."""
    doc = db.execute(
        select(HealthDocument).where(
            HealthDocument.id == int(doc_id),
            HealthDocument.user_id == user_id,
        )
    ).scalars().first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Lazy-generate AI summary for legacy docs that don't have one yet
    if not doc.ai_summary and doc.csv_data:
        ai_brief, ai_summary = _generate_doc_summary(doc.csv_data, doc.abnormal_flags, doc.doc_type)
        if ai_summary:
            doc.ai_brief = ai_brief or None
            doc.ai_summary = ai_summary
            db.commit()
            db.refresh(doc)

    return _doc_to_out(doc)


@router.get("/documents/{doc_id}/file")
def get_document_file(
    doc_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Serve the original uploaded file (image/CSV/PDF)."""
    doc = db.execute(
        select(HealthDocument).where(
            HealthDocument.id == int(doc_id),
            HealthDocument.user_id == user_id,
        )
    ).scalars().first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.original_file_path or doc.original_file_path.startswith("data:"):
        raise HTTPException(status_code=404, detail="Original file not available")

    full_path = Path(settings.LOCAL_STORAGE_DIR) / doc.original_file_path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(str(full_path))


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Delete a health document."""
    doc = db.execute(
        select(HealthDocument).where(
            HealthDocument.id == int(doc_id),
            HealthDocument.user_id == user_id,
        )
    ).scalars().first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"ok": True}


@router.get("/patient-history", response_model=PatientHistoryProfileOut)
def get_patient_history(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.execute(
        select(PatientHistoryProfile).where(PatientHistoryProfile.user_id == user_id)
    ).scalars().first()
    return _patient_history_to_out(profile, db, user_id)


@router.put("/patient-history", response_model=PatientHistoryProfileOut)
def save_patient_history(
    payload: PatientHistoryProfileIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.execute(
        select(PatientHistoryProfile).where(PatientHistoryProfile.user_id == user_id)
    ).scalars().first()
    if not profile:
        profile = PatientHistoryProfile(user_id=user_id)
        db.add(profile)

    profile.doctor_summary = payload.doctor_summary.strip()
    profile.sections = normalize_sections(payload.sections)
    profile.verified_at = payload.verified_at

    db.commit()
    db.refresh(profile)
    return _patient_history_to_out(profile, db, user_id)


# ─── Indicator helpers ───────────────────────────────────

# Indicators that are typically numeric and trackable
_SKIP_NAMES = {"体检小结", "提取失败", "医师建议", "小结", "备注"}


def _is_numeric(val: str) -> bool:
    """Check if a string can be parsed as a float."""
    try:
        float(val.replace("+", "").replace("-", "").strip())
        return True
    except (ValueError, AttributeError):
        return False


def _parse_ref_range(ref: str) -> tuple[float | None, float | None]:
    """Parse reference range like '3.9-6.1' or '<5.0' or '>1.0'."""
    if not ref:
        return None, None
    ref = ref.strip()
    # Range: 3.9-6.1 or 3.9~6.1
    m = re.match(r"([\d.]+)\s*[-~]\s*([\d.]+)", ref)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            return None, None
    # Upper bound: <5.0 or ≤5.0
    m = re.match(r"[<≤]\s*([\d.]+)", ref)
    if m:
        try:
            return None, float(m.group(1))
        except ValueError:
            return None, None
    # Lower bound: >1.0 or ≥1.0
    m = re.match(r"[>≥]\s*([\d.]+)", ref)
    if m:
        try:
            return float(m.group(1)), None
        except ValueError:
            return None, None
    return None, None


def _extract_indicators_from_docs(docs: list[HealthDocument]) -> dict[str, list[dict]]:
    """Extract all numeric indicators across documents.

    Returns {indicator_name: [{date, value, unit, ref_range, abnormal}, ...]}
    """
    indicators: dict[str, list[dict]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)  # avoid duplicates per date

    for doc in docs:
        if doc.doc_type != "exam":
            continue
        csv = doc.csv_data or {}
        rows = csv.get("rows", [])
        cols = csv.get("columns", [])
        if not rows or len(cols) < 2:
            continue

        date_str = doc.doc_date.strftime("%Y-%m-%d") if doc.doc_date else None
        if not date_str:
            continue

        for row in rows:
            if len(row) < 2:
                continue
            name = row[0].strip()
            value_str = row[1].strip() if row[1] else ""

            if name in _SKIP_NAMES or not name or not _is_numeric(value_str):
                continue

            # Deduplicate same indicator on same date
            if date_str in seen[name]:
                continue
            seen[name].add(date_str)

            unit = row[2].strip() if len(row) > 2 and row[2] else ""
            ref_range = row[3].strip() if len(row) > 3 and row[3] else ""
            abnormal_flag = row[4].strip() if len(row) > 4 and row[4] else ""

            try:
                value = float(value_str.replace("+", "").replace("-", "").strip())
            except ValueError:
                continue

            indicators[name].append({
                "date": date_str,
                "value": value,
                "unit": unit,
                "ref_range": ref_range,
                "abnormal": bool(abnormal_flag),
            })

    # Sort each indicator's points by date
    for name in indicators:
        indicators[name].sort(key=lambda p: p["date"])

    return dict(indicators)


# Known indicator categories
_CATEGORY_MAP = {
    "血常规": ["白细胞", "红细胞", "血红蛋白", "血小板", "中性粒细胞", "淋巴细胞",
               "单核细胞", "嗜酸性", "嗜碱性", "红细胞压积", "平均红细胞", "网织红细胞"],
    "肝功能": ["谷丙转氨酶", "谷草转氨酶", "总胆红素", "直接胆红素", "间接胆红素",
               "碱性磷酸酶", "谷氨酰转肽酶", "总蛋白", "白蛋白", "球蛋白", "白球比"],
    "肾功能": ["肌酐", "尿素", "尿素氮", "尿酸", "胱抑素", "肾小球滤过率"],
    "血脂": ["总胆固醇", "甘油三酯", "高密度脂蛋白", "低密度脂蛋白", "载脂蛋白"],
    "血糖": ["空腹血糖", "葡萄糖", "糖化血红蛋白", "餐后血糖", "胰岛素"],
    "甲状腺": ["促甲状腺激素", "游离T3", "游离T4", "甲状腺球蛋白", "TSH"],
    "肿瘤标志物": ["甲胎蛋白", "癌胚抗原", "糖类抗原", "CA125", "CA199", "CA153", "PSA"],
}


def _guess_category(name: str) -> str | None:
    for cat, keywords in _CATEGORY_MAP.items():
        for kw in keywords:
            if kw in name:
                return cat
    return None


# ─── Indicator Endpoints ─────────────────────────────────

@router.get("/indicators", response_model=IndicatorListOut)
def list_indicators(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List all trackable numeric indicators found in user's exam reports."""
    docs = db.execute(
        select(HealthDocument).where(
            HealthDocument.user_id == user_id,
            HealthDocument.doc_type == "exam",
            HealthDocument.extraction_status == "done",
        )
    ).scalars().all()

    all_indicators = _extract_indicators_from_docs(list(docs))

    items = []
    for name, points in sorted(all_indicators.items(), key=lambda x: -len(x[1])):
        if len(points) < 2:  # need at least 2 points for a trend
            continue
        items.append(IndicatorInfo(
            name=name,
            category=_guess_category(name),
            count=len(points),
        ))

    return IndicatorListOut(indicators=items)


@router.get("/indicators/trend", response_model=IndicatorTrendOut)
def get_indicator_trends(
    names: str = Query(..., description="Comma-separated indicator names"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get time-series trend data for specified indicators."""
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    if not name_list:
        raise HTTPException(status_code=400, detail="No indicator names provided")
    if len(name_list) > 10:
        raise HTTPException(status_code=400, detail="Max 10 indicators at a time")

    docs = db.execute(
        select(HealthDocument).where(
            HealthDocument.user_id == user_id,
            HealthDocument.doc_type == "exam",
            HealthDocument.extraction_status == "done",
        )
    ).scalars().all()

    all_indicators = _extract_indicators_from_docs(list(docs))

    results = []
    for name in name_list:
        points = all_indicators.get(name, [])
        if not points:
            continue
        # Get unit and ref_range from most recent point
        latest = points[-1]
        ref_low, ref_high = _parse_ref_range(latest.get("ref_range", ""))

        results.append(IndicatorTrend(
            name=name,
            unit=latest.get("unit") or None,
            ref_low=ref_low,
            ref_high=ref_high,
            points=[
                TrendPoint(date=p["date"], value=p["value"], abnormal=p.get("abnormal", False))
                for p in points
            ],
        ))

    return IndicatorTrendOut(indicators=results)


# ─── Watched Indicators ─────────────────────────────────

@router.get("/indicators/watched", response_model=WatchedListOut)
def get_watched_indicators(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get user's watched indicator list."""
    rows = db.execute(
        select(WatchedIndicator)
        .where(WatchedIndicator.user_id == user_id)
        .order_by(WatchedIndicator.display_order)
    ).scalars().all()

    return WatchedListOut(items=[
        WatchedIndicatorOut(
            indicator_name=r.indicator_name,
            category=r.category,
            display_order=r.display_order,
        ) for r in rows
    ])


@router.post("/indicators/watch")
def watch_indicator(
    body: WatchedIndicatorIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Add an indicator to the user's watch list."""
    existing = db.execute(
        select(WatchedIndicator).where(
            WatchedIndicator.user_id == user_id,
            WatchedIndicator.indicator_name == body.indicator_name,
        )
    ).scalars().first()

    if existing:
        return {"ok": True, "message": "already watched"}

    # Get current max order
    max_order = db.execute(
        select(sa_func.max(WatchedIndicator.display_order))
        .where(WatchedIndicator.user_id == user_id)
    ).scalar() or 0

    row = WatchedIndicator(
        user_id=user_id,
        indicator_name=body.indicator_name,
        category=body.category or _guess_category(body.indicator_name),
        display_order=max_order + 1,
    )
    db.add(row)
    db.commit()
    return {"ok": True}


@router.delete("/indicators/watch/{indicator_name}")
def unwatch_indicator(
    indicator_name: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Remove an indicator from the user's watch list."""
    db.execute(
        delete(WatchedIndicator).where(
            WatchedIndicator.user_id == user_id,
            WatchedIndicator.indicator_name == indicator_name,
        )
    )
    db.commit()
    return {"ok": True}


# ─── Indicator Knowledge Base ────────────────────────────

@router.get("/indicators/{indicator_name}/explain")
def explain_indicator(
    indicator_name: str,
    db: Session = Depends(get_db),
):
    """Return indicator explanation. Check local knowledge base first, fallback to AI."""
    # 1. Check local knowledge base
    cached = db.execute(
        select(IndicatorKnowledge).where(IndicatorKnowledge.name == indicator_name)
    ).scalars().first()

    if cached:
        return {
            "name": cached.name,
            "brief": cached.brief,
            "detail": cached.detail,
            "normal_range": cached.normal_range,
            "clinical_meaning": cached.clinical_meaning,
            "source": cached.source,
        }

    # 2. Fallback: AI generate
    client = _get_llm_client()
    resp = client.chat.completions.create(
        model=settings.OPENAI_MODEL_TEXT,
        messages=[
            {"role": "system", "content": (
                "你是医学检验指标专家。用中文回答。返回 JSON 格式，包含以下字段：\n"
                '{"brief": "一句话解释该指标是什么", '
                '"detail": "2-3句详细说明其临床意义", '
                '"normal_range": "正常参考范围", '
                '"clinical_meaning": "偏高和偏低分别代表什么"}\n'
                "不要使用任何 emoji。不要添加额外文字。"
            )},
            {"role": "user", "content": f"请解释医学检验指标：{indicator_name}"},
        ],
        max_tokens=512,
        extra_body={"thinking": {"type": "disabled"}},
        **settings.llm_temperature_kwargs(),
    )

    text = resp.choices[0].message.content or ""
    # Parse JSON from LLM response
    try:
        # Try to extract JSON from the response
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = {"brief": text[:200], "detail": text, "normal_range": "", "clinical_meaning": ""}
    except json.JSONDecodeError:
        data = {"brief": text[:200], "detail": text, "normal_range": "", "clinical_meaning": ""}

    # 3. Cache into knowledge base
    knowledge = IndicatorKnowledge(
        name=indicator_name,
        brief=data.get("brief", ""),
        detail=data.get("detail", ""),
        normal_range=data.get("normal_range", ""),
        clinical_meaning=data.get("clinical_meaning", ""),
        source="ai",
    )
    db.add(knowledge)
    db.commit()

    return {
        "name": indicator_name,
        "brief": knowledge.brief,
        "detail": knowledge.detail,
        "normal_range": knowledge.normal_range,
        "clinical_meaning": knowledge.clinical_meaning,
        "source": "ai",
    }
