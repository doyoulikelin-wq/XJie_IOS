from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health_document import HealthDocument, HealthSummary


SECTION_DEFAULTS: dict[str, dict[str, object]] = {
    "diagnoses": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "surgeries": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "medications": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "allergies": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "recent_findings": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "document",
        "source_ref": None,
        "verified_by_user": False,
    },
    "care_goals": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "family_history": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
    "lifestyle_risks": {
        "value": "",
        "date_label": None,
        "status": "missing",
        "source_type": "user",
        "source_ref": None,
        "verified_by_user": False,
    },
}

SECTION_LABELS: dict[str, str] = {
    "diagnoses": "既往明确诊断",
    "surgeries": "手术或住院史",
    "medications": "长期或当前用药",
    "allergies": "过敏或不良反应",
    "recent_findings": "近一年重要异常检查",
    "care_goals": "本次就诊重点关注",
    "family_history": "家族史",
    "lifestyle_risks": "生活方式风险因素",
}


def build_default_sections() -> dict[str, dict[str, object]]:
    return {key: value.copy() for key, value in SECTION_DEFAULTS.items()}


def normalize_sections(raw_sections: dict | None) -> dict[str, dict[str, object]]:
    sections = build_default_sections()
    if not isinstance(raw_sections, dict):
        return sections

    for key, base_value in sections.items():
        incoming = raw_sections.get(key)
        if isinstance(incoming, dict):
            merged = dict(base_value)
            merged.update({
                "value": incoming.get("value") or "",
                "date_label": incoming.get("date_label"),
                "status": incoming.get("status") or base_value["status"],
                "source_type": incoming.get("source_type") or base_value["source_type"],
                "source_ref": incoming.get("source_ref"),
                "verified_by_user": bool(incoming.get("verified_by_user", False)),
            })
            sections[key] = merged
    return sections


def build_evidence_overview(db: Session, user_id: int) -> dict[str, object]:
    docs = db.execute(
        select(HealthDocument)
        .where(HealthDocument.user_id == user_id)
        .order_by(HealthDocument.doc_date.desc().nullslast(), HealthDocument.created_at.desc())
    ).scalars().all()

    records = [doc for doc in docs if doc.doc_type == "record"]
    exams = [doc for doc in docs if doc.doc_type == "exam"]

    latest_record = next((doc for doc in records if doc.doc_date), None)
    latest_exam = next((doc for doc in exams if doc.doc_date), None)

    return {
        "record_count": len(records),
        "exam_count": len(exams),
        "latest_record_date": latest_record.doc_date.date().isoformat() if latest_record and latest_record.doc_date else None,
        "latest_exam_date": latest_exam.doc_date.date().isoformat() if latest_exam and latest_exam.doc_date else None,
    }


def build_key_metrics(db: Session, user_id: int, limit: int = 6) -> list[dict[str, object]]:
    docs = db.execute(
        select(HealthDocument)
        .where(HealthDocument.user_id == user_id, HealthDocument.doc_type == "exam")
        .order_by(HealthDocument.doc_date.desc().nullslast(), HealthDocument.created_at.desc())
    ).scalars().all()

    metrics: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for doc in docs:
        abnormal_flags = doc.abnormal_flags or []
        csv_rows = _rows_by_name(doc.csv_data or {})
        for flag in abnormal_flags:
            name = str(flag.get("field") or flag.get("name") or "").strip()
            value = str(flag.get("value") or "").strip()
            if not name or not value or name in seen_names:
                continue

            row = csv_rows.get(name)
            unit = row[2] if row and len(row) > 2 else flag.get("unit")
            date_label = doc.doc_date.date().isoformat() if doc.doc_date else None
            metrics.append({
                "name": name,
                "value": value,
                "unit": unit or None,
                "date_label": date_label,
                "status": "documented" if date_label else "pending_review",
                "source_type": "document",
                "source_ref": str(doc.id),
                "focus": "exams",
            })
            seen_names.add(name)
            if len(metrics) >= limit:
                return metrics
    return metrics


def build_default_doctor_summary(db: Session, user_id: int) -> str:
    row = db.execute(
        select(HealthSummary)
        .where(HealthSummary.user_id == user_id)
        .order_by(HealthSummary.updated_at.desc())
        .limit(1)
    ).scalars().first()
    if row and row.summary_text:
        return row.summary_text[:1200]
    return ""


def compute_missing_sections(sections: dict[str, dict[str, object]]) -> list[dict[str, str]]:
    missing = []
    for key, value in sections.items():
        status = str(value.get("status") or "missing")
        text = str(value.get("value") or "").strip()
        if status == "missing" or not text:
            missing.append({"key": key, "label": SECTION_LABELS.get(key, key)})
    return missing


def compute_completeness(sections: dict[str, dict[str, object]], doctor_summary: str) -> float:
    total = len(sections) + 1
    completed = 0
    if doctor_summary.strip():
        completed += 1
    for value in sections.values():
        status = str(value.get("status") or "missing")
        text = str(value.get("value") or "").strip()
        if status != "missing" and text:
            completed += 1
    return round(completed / total, 3)


def _rows_by_name(csv_data: dict) -> dict[str, list[str]]:
    rows = csv_data.get("rows") if isinstance(csv_data, dict) else None
    if not isinstance(rows, list):
        return {}

    result: dict[str, list[str]] = {}
    for row in rows:
        if isinstance(row, list) and row:
            key = str(row[0]).strip()
            if key:
                result[key] = [str(item) for item in row]
    return result