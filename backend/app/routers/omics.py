"""Omics router — metabolomics upload + LLM analysis + model placeholder."""

import logging
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.omics import OmicsModelTask, OmicsUpload
from app.providers.factory import get_provider
from app.schemas.omics import (
    MetabolomicsAnalysisResult,
    MetaboliteItem,
    ModelAnalysisStatus,
    ModelAnalysisSubmit,
)
from app.services import omics_demo

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

_METABOLOMICS_PROMPT = """\
你是专业的代谢组学数据分析师。请分析以下代谢组学检测数据，给出：
1. summary: 一句话概括分析结果（50-80字，口语化）
2. analysis: 详细分析（Markdown格式，包含：异常指标解读、代谢通路分析、健康风险评估、生活建议）
3. risk_level: 综合风险等级（"低风险"/"中风险"/"高风险"）
4. metabolites: 识别到的代谢物列表，每个包含 name、value(数值)、unit(单位)、status("normal"/"high"/"low")

严格输出JSON格式:
```json
{
  "summary": "...",
  "analysis": "...",
  "risk_level": "...",
  "metabolites": [{"name": "...", "value": 1.0, "unit": "...", "status": "normal"}]
}
```

以下是用户上传的代谢组学数据:
"""


def _extract_text_from_file(content: bytes, filename: str) -> str:
    """Extract text content from uploaded file."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("csv", "tsv", "txt"):
        text = content.decode("utf-8", errors="replace")
        # Limit to first 8000 chars for LLM context window
        return text[:8000]
    if ext == "pdf":
        # Basic PDF text extraction — just send raw bytes info
        return f"[PDF file: {filename}, {len(content)} bytes. 请基于文件名和常见代谢组学指标给出通用分析]"
    if ext in ("xlsx", "xls"):
        return f"[Excel file: {filename}, {len(content)} bytes. 请基于文件名和常见代谢组学指标给出通用分析]"
    return content.decode("utf-8", errors="replace")[:8000]


def _parse_llm_json(raw: str) -> dict:
    """Parse LLM JSON response with fallback."""
    import json
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    if "```" in text:
        try:
            block = text.split("```json")[-1].split("```")[0].strip() if "```json" in text else text.split("```")[1].strip()
            return json.loads(block)
        except (json.JSONDecodeError, IndexError):
            pass
    # Fallback
    return {
        "summary": text[:100] if text else "分析完成",
        "analysis": text,
        "risk_level": "未评估",
        "metabolites": [],
    }


# ── POST /api/omics/metabolomics/upload ──────────────────

@router.post("/metabolomics/upload", response_model=MetabolomicsAnalysisResult)
def upload_metabolomics(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Upload metabolomics data file → LLM analysis."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = file.file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Extract text for LLM
    raw_text = _extract_text_from_file(content, file.filename)

    # Save upload record
    upload = OmicsUpload(
        user_id=user_id,
        omics_type="metabolomics",
        file_name=file.filename,
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        raw_text=raw_text[:10000],
        meta={},
    )
    db.add(upload)
    db.flush()

    # Call LLM for analysis
    provider = get_provider()
    prompt = _METABOLOMICS_PROMPT + raw_text
    t0 = time.perf_counter()
    try:
        result = provider.generate_text(
            context={"omics_type": "metabolomics", "file_name": file.filename},
            user_query=prompt,
        )
        raw_answer = result.answer_markdown
    except Exception as e:
        logger.error("LLM metabolomics analysis failed: %s", e)
        raw_answer = ""

    latency_ms = int((time.perf_counter() - t0) * 1000)
    logger.info("Metabolomics LLM analysis: %dms", latency_ms)

    # Parse structured response
    parsed = _parse_llm_json(raw_answer)
    summary = parsed.get("summary", "分析完成")
    analysis = parsed.get("analysis", raw_answer or "暂无详细分析")
    risk_level = parsed.get("risk_level", "未评估")
    metabolites_raw = parsed.get("metabolites", [])

    # Update upload record
    upload.llm_summary = summary
    upload.llm_analysis = analysis
    upload.risk_level = risk_level
    db.commit()

    metabolites = []
    for m in metabolites_raw:
        if isinstance(m, dict) and "name" in m:
            metabolites.append(MetaboliteItem(
                name=m["name"],
                value=m.get("value"),
                unit=m.get("unit"),
                status=m.get("status"),
            ))

    return MetabolomicsAnalysisResult(
        summary=summary,
        analysis=analysis,
        risk_level=risk_level,
        metabolites=metabolites,
    )


# ── GET /api/omics/metabolomics/history ──────────────────

@router.get("/metabolomics/history")
def get_metabolomics_history(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get user's metabolomics upload history."""
    uploads = db.execute(
        select(OmicsUpload)
        .where(OmicsUpload.user_id == user_id, OmicsUpload.omics_type == "metabolomics")
        .order_by(OmicsUpload.created_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        {
            "id": u.id,
            "file_name": u.file_name,
            "risk_level": u.risk_level,
            "summary": u.llm_summary,
            "created_at": str(u.created_at),
        }
        for u in uploads
    ]


# ── POST /api/omics/model/submit — 小分析模型占位 ────────

@router.post("/model/submit", response_model=ModelAnalysisStatus)
def submit_model_analysis(
    payload: ModelAnalysisSubmit,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Submit data to external analysis model (placeholder).

    This endpoint is a placeholder for future integration with a
    specialized metabolomics analysis model. Currently it creates
    a task record and returns a pending status.
    """
    # Verify upload exists and belongs to user
    upload = db.execute(
        select(OmicsUpload).where(
            OmicsUpload.id == payload.upload_id,
            OmicsUpload.user_id == user_id,
        )
    ).scalars().first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    task = OmicsModelTask(
        user_id=user_id,
        upload_id=payload.upload_id,
        model_type=payload.model_type,
        status="pending",
        parameters=payload.parameters,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return ModelAnalysisStatus(
        task_id=str(task.id),
        status="pending",
        result=None,
    )


# ── GET /api/omics/model/status/{task_id} ────────────────

@router.get("/model/status/{task_id}", response_model=ModelAnalysisStatus)
def get_model_status(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Check status of a model analysis task."""
    task = db.execute(
        select(OmicsModelTask).where(
            OmicsModelTask.id == task_id,
            OmicsModelTask.user_id == user_id,
        )
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return ModelAnalysisStatus(
        task_id=str(task.id),
        status=task.status,
        result=task.result,
    )


# ── PUT /api/omics/model/result/{task_id} — 模型回写 ─────

@router.put("/model/result/{task_id}", response_model=ModelAnalysisStatus)
def update_model_result(
    task_id: int,
    result: dict,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Update a model task with analysis results (called by model service)."""
    task = db.execute(
        select(OmicsModelTask).where(OmicsModelTask.id == task_id)
    ).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = "completed"
    task.result = result
    db.commit()

    return ModelAnalysisStatus(
        task_id=str(task.id),
        status=task.status,
        result=task.result,
    )


# ── Demo endpoints (deterministic, is_demo=true) ──────────────


@router.get("/demo/metabolomics")
def demo_metabolomics(user_id: int = Depends(get_current_user_id)):
    """Deterministic synthetic metabolomics panel for UI demo."""
    return omics_demo.build_metabolomics(user_id)


@router.get("/demo/proteomics")
def demo_proteomics(user_id: int = Depends(get_current_user_id)):
    return omics_demo.build_proteomics(user_id)


@router.get("/demo/genomics")
def demo_genomics(user_id: int = Depends(get_current_user_id)):
    return omics_demo.build_genomics(user_id)


@router.get("/demo/microbiome")
def demo_microbiome(user_id: int = Depends(get_current_user_id)):
    return omics_demo.build_microbiome(user_id)


@router.get("/demo/triad")
def demo_triad(user_id: int = Depends(get_current_user_id)):
    """Cross-omics × CGM × heart triad for the Venn animation."""
    return omics_demo.build_triad(user_id)
