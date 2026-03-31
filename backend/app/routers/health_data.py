"""Health data router – AI summary, medical records, exam reports."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from openai import OpenAI
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user_id, get_db
from app.models.health_document import HealthDocument, HealthSummary
from app.schemas.health_document import (
    HealthDocumentListOut,
    HealthDocumentOut,
    HealthSummaryOut,
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
        model="kimi-k2.5",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": user_prompt},
            ]},
        ],
        max_tokens=4096,
        temperature=0.1,
        extra_body={"thinking": {"type": "disabled"}},
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


def _doc_to_out(doc: HealthDocument) -> HealthDocumentOut:
    return HealthDocumentOut(
        id=str(doc.id),
        doc_type=doc.doc_type,
        source_type=doc.source_type,
        name=doc.name,
        hospital=doc.hospital,
        doc_date=doc.doc_date.isoformat() if doc.doc_date else None,
        csv_data=doc.csv_data,
        abnormal_flags=doc.abnormal_flags,
        extraction_status=doc.extraction_status,
        created_at=doc.created_at,
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
                "你是体检报告 OCR 专家。请从体检报告照片中提取检查项目数据。"
                "返回严格 JSON 格式（不要多余文本）：\n"
                '{"items": [{"name":"检查项目名","value":"数值","unit":"单位",'
                '"ref_range":"参考范围","is_abnormal":true/false},...], '
                '"summary":"体检小结（如有）"}'
            ),
            user_prompt="请从这张体检报告照片中提取所有检查项目，包括数值、单位、参考范围，并标注异常项。",
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
    """Generate a new AI health summary from all user medical records & exam reports."""
    # Gather all documents for context
    docs = db.execute(
        select(HealthDocument)
        .where(HealthDocument.user_id == user_id)
        .order_by(HealthDocument.doc_date.desc().nulls_last())
    ).scalars().all()

    # TODO: Replace with real LLM call using docs as context
    if docs:
        record_count = sum(1 for d in docs if d.doc_type == "record")
        exam_count = sum(1 for d in docs if d.doc_type == "exam")
        summary_text = (
            f"基于您上传的 {record_count} 份病例和 {exam_count} 份体检报告进行综合分析：\n\n"
            f"📋 病例记录共 {record_count} 份\n"
            f"🔬 体检报告共 {exam_count} 份\n\n"
            f"⏳ AI 详细分析功能即将上线，当前为占位摘要。\n"
            f"上线后将自动结合您的所有病例和体检数据，生成个性化健康总结。"
        )
    else:
        summary_text = "暂无健康数据，请先上传病例或体检报告后再生成 AI 总结。"

    # Upsert summary
    existing = db.execute(
        select(HealthSummary).where(HealthSummary.user_id == user_id).limit(1)
    ).scalars().first()

    if existing:
        existing.summary_text = summary_text
        existing.updated_at = datetime.utcnow()
    else:
        existing = HealthSummary(user_id=user_id, summary_text=summary_text)
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return HealthSummaryOut(summary_text=existing.summary_text, updated_at=existing.updated_at)


# ─── Document Upload ─────────────────────────────────────

@router.post("/upload", response_model=HealthDocumentOut)
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(..., pattern=r"^(record|exam)$"),
    name: str = Form(default=""),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Upload a photo/CSV/PDF and extract structured data.

    For photo uploads, LLM auto-extracts name (hospital+date) and data.
    For CSV/PDF non-image uploads, `name` is required from user.
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

    # Auto-extract name for images, require manual for non-images
    if is_image:
        auto_name = _extract_name_from_image(file_bytes, doc_type)
        doc_name = name or auto_name
    else:
        if not name:
            # For CSV, derive name from filename: "张朝晖 - 2024-07-25.csv" → "张朝晖-2024-07-25-病例"
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            label = "病例" if doc_type == "record" else "体检报告"
            doc_name = f"{stem}-{label}"
        else:
            doc_name = name

    # Store file as base64 in DB for simplicity (MVP)
    # TODO: Move to MinIO/OSS for production
    file_b64 = base64.b64encode(file_bytes).decode("ascii")

    # Extract structured data
    if source_type == "csv":
        csv_data = _parse_csv_record(file_bytes, filename)
        abnormal_flags = None
    elif doc_type == "record":
        csv_data = _extract_record_from_image(file_bytes, filename)
        abnormal_flags = None
    else:
        csv_data, abnormal_flags = _extract_exam_from_image(file_bytes, filename)

    # Try to extract date from doc_name
    doc_date = datetime.utcnow()
    import re
    date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", doc_name)
    if date_match:
        try:
            doc_date = datetime.strptime(date_match.group(1).replace("/", "-"), "%Y-%m-%d")
        except ValueError:
            pass

    doc = HealthDocument(
        user_id=user_id,
        doc_type=doc_type,
        source_type=source_type,
        name=doc_name,
        hospital=doc_name.split("-")[0] if "-" in doc_name else None,
        doc_date=doc_date,
        original_file_path=f"data:base64:{filename}",  # placeholder
        csv_data=csv_data,
        abnormal_flags=abnormal_flags,
        extraction_status="done",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    logger.info("Health document uploaded: type=%s, name=%s, user=%s", doc_type, doc_name, str(user_id)[:8])
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
    return _doc_to_out(doc)


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
