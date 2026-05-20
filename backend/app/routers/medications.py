"""Medication CRUD + LLM structuring + reminder helper."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user_id, get_db
from app.models.medication import Medication

logger = logging.getLogger(__name__)
router = APIRouter()


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_times(times: list[str]) -> list[str]:
    out: list[str] = []
    for t in times or []:
        t = (t or "").strip()
        if not _TIME_RE.match(t):
            raise HTTPException(status_code=400, detail=f"非法时间：{t!r}，需为 HH:MM 24h 格式")
        out.append(t)
    # 去重并排序
    return sorted(set(out))


class MedicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    dosage: str | None = Field(default=None, max_length=64)
    frequency: str | None = Field(default=None, max_length=64)
    instructions: str | None = Field(default=None, max_length=2000)
    schedule_times: list[str] = Field(default_factory=list)
    course_start: date | None = None
    course_end: date | None = None
    photo_url: str | None = Field(default=None, max_length=512)
    enabled: bool = True


class MedicationOut(BaseModel):
    id: int
    name: str
    dosage: str | None
    frequency: str | None
    instructions: str | None
    schedule_times: list[str]
    course_start: date | None
    course_end: date | None
    photo_url: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class MedicationListOut(BaseModel):
    items: list[MedicationOut]


def _to_out(m: Medication) -> MedicationOut:
    return MedicationOut(
        id=m.id,
        name=m.name,
        dosage=m.dosage,
        frequency=m.frequency,
        instructions=m.instructions,
        schedule_times=list(m.schedule_times or []),
        course_start=m.course_start,
        course_end=m.course_end,
        photo_url=m.photo_url,
        enabled=m.enabled,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=MedicationListOut)
def list_medications(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationListOut:
    uid = int(user_id)
    rows = (
        db.scalars(select(Medication).where(Medication.user_id == uid).order_by(desc(Medication.updated_at))).all()
    )
    return MedicationListOut(items=[_to_out(r) for r in rows])


@router.post("", response_model=MedicationOut)
def create_medication(
    payload: MedicationIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationOut:
    times = _validate_times(payload.schedule_times)
    m = Medication(
        user_id=int(user_id),
        name=payload.name.strip(),
        dosage=(payload.dosage or "").strip() or None,
        frequency=(payload.frequency or "").strip() or None,
        instructions=(payload.instructions or "").strip() or None,
        schedule_times=times,
        course_start=payload.course_start,
        course_end=payload.course_end,
        photo_url=payload.photo_url,
        enabled=payload.enabled,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.patch("/{med_id}", response_model=MedicationOut)
def update_medication(
    med_id: int,
    payload: MedicationIn,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MedicationOut:
    uid = int(user_id)
    m = db.scalars(select(Medication).where(Medication.id == med_id, Medication.user_id == uid)).first()
    if not m:
        raise HTTPException(status_code=404, detail="medication not found")
    m.name = payload.name.strip()
    m.dosage = (payload.dosage or "").strip() or None
    m.frequency = (payload.frequency or "").strip() or None
    m.instructions = (payload.instructions or "").strip() or None
    m.schedule_times = _validate_times(payload.schedule_times)
    m.course_start = payload.course_start
    m.course_end = payload.course_end
    m.photo_url = payload.photo_url
    m.enabled = payload.enabled
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.delete("/{med_id}")
def delete_medication(
    med_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    uid = int(user_id)
    m = db.scalars(select(Medication).where(Medication.id == med_id, Medication.user_id == uid)).first()
    if not m:
        raise HTTPException(status_code=404, detail="medication not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# OCR/LLM 结构化：客户端先做端侧 OCR，把原始文字传过来，由 LLM 提取字段
# ---------------------------------------------------------------------------


class RecognizeIn(BaseModel):
    raw_text: str = Field(min_length=1, max_length=4000)


class RecognizeOut(BaseModel):
    name: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    instructions: str | None = None
    schedule_times: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "你是用药说明书解析助手。用户提供一段从药盒/说明书拍照 OCR 出来的中文文本，"
    "你的任务是抽取关键字段并返回严格的 JSON（不要任何额外解释）。字段：\n"
    "  name: 药品通用名或商品名（字符串）\n"
    "  dosage: 单次剂量，如 '5mg'、'1片'（字符串，可空）\n"
    "  frequency: 服用频次，如 '每日3次'、'每12小时1次'（字符串，可空）\n"
    "  instructions: 重要使用说明摘要（字符串，可空，<=200字）\n"
    "  schedule_times: 推荐提醒时间列表，HH:MM 24h 格式；如说明 '每日三次' 可给"
    " ['08:00','13:00','20:00']；若 OCR 已写明具体时间则优先采用。返回 JSON 形如：\n"
    '{"name":"...","dosage":"...","frequency":"...","instructions":"...","schedule_times":["08:00"]}'
)


def _heuristic_times(freq: str | None) -> list[str]:
    if not freq:
        return []
    s = freq.replace(" ", "")
    if "1次" in s or "每日1次" in s or "qd" in s.lower():
        return ["08:00"]
    if "2次" in s or "bid" in s.lower():
        return ["08:00", "20:00"]
    if "3次" in s or "tid" in s.lower():
        return ["08:00", "13:00", "20:00"]
    if "4次" in s or "qid" in s.lower():
        return ["08:00", "12:00", "17:00", "21:00"]
    return []


@router.post("/recognize", response_model=RecognizeOut)
def recognize_label(
    payload: RecognizeIn,
    user_id: str = Depends(get_current_user_id),
) -> RecognizeOut:
    """Send OCR text to the configured LLM and return structured medication fields.

    Falls back to a heuristic extractor if LLM call fails or is not configured.
    """
    text = payload.raw_text.strip()

    # Try OpenAI directly (gracefully fall back to heuristic if not configured)
    data: dict = {}
    try:
        from app.core.config import settings as app_settings

        if app_settings.OPENAI_API_KEY:
            from openai import OpenAI

            client = OpenAI(api_key=app_settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=getattr(app_settings, "OPENAI_MODEL_TEXT", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = resp.choices[0].message.content or "{}"
            data = json.loads(content)
    except Exception:
        logger.exception("medication recognize LLM failed; using heuristic")
        data = {}

    name = (data.get("name") or "").strip() or None
    dosage = (data.get("dosage") or "").strip() or None
    frequency = (data.get("frequency") or "").strip() or None
    instructions = (data.get("instructions") or "").strip() or None
    times_raw = data.get("schedule_times") or []
    if not isinstance(times_raw, list):
        times_raw = []
    times: list[str] = []
    for t in times_raw:
        if isinstance(t, str) and _TIME_RE.match(t.strip()):
            times.append(t.strip())
    if not times:
        times = _heuristic_times(frequency)

    # Fallback name from first line of OCR text
    if not name:
        first = text.splitlines()[0].strip() if text else ""
        if first:
            name = first[:64]

    return RecognizeOut(
        name=name,
        dosage=dosage,
        frequency=frequency,
        instructions=instructions,
        schedule_times=sorted(set(times)),
    )
