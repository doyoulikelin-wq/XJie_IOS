from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.health_document import HealthSummary
from app.models.health_trust import ConfirmedHealthObservation, HealthReportWorkflow


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
        if not isinstance(incoming, Mapping) and callable(getattr(incoming, "model_dump", None)):
            incoming = incoming.model_dump()
        if isinstance(incoming, Mapping):
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
    rows = db.execute(
        select(HealthReportWorkflow, func.max(ConfirmedHealthObservation.effective_at))
        .join(
            ConfirmedHealthObservation,
            ConfirmedHealthObservation.workflow_id == HealthReportWorkflow.id,
        )
        .where(
            HealthReportWorkflow.user_id == user_id,
            HealthReportWorkflow.subject_user_id == user_id,
            HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
            ConfirmedHealthObservation.status == "active",
        )
        .group_by(HealthReportWorkflow.id)
    ).all()
    records = [row for row in rows if row[0].report_type == "medical_record"]
    exams = [row for row in rows if row[0].report_type != "medical_record"]

    latest_record = max((row[1] for row in records if row[1]), default=None)
    latest_exam = max((row[1] for row in exams if row[1]), default=None)

    return {
        "record_count": len(records),
        "exam_count": len(exams),
        "latest_record_date": latest_record.date().isoformat() if latest_record else None,
        "latest_exam_date": latest_exam.date().isoformat() if latest_exam else None,
    }


def build_key_metrics(db: Session, user_id: int, limit: int = 6) -> list[dict[str, object]]:
    observations = db.execute(
        select(ConfirmedHealthObservation)
        .join(
            HealthReportWorkflow,
            HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
        )
        .where(
            ConfirmedHealthObservation.user_id == user_id,
            ConfirmedHealthObservation.subject_user_id == user_id,
            ConfirmedHealthObservation.status == "active",
            ConfirmedHealthObservation.abnormal_state == "abnormal",
            HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
            HealthReportWorkflow.report_type != "medical_record",
        )
        .order_by(ConfirmedHealthObservation.effective_at.desc())
    ).scalars().all()

    metrics: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for observation in observations:
        name = observation.canonical_name.strip()
        if not name or name in seen_names:
            continue
        value = (
            str(observation.value_numeric)
            if observation.value_numeric is not None
            else observation.value_text or ""
        )
        metrics.append({
            "name": name,
            "value": value,
            "unit": observation.unit or None,
            "date_label": observation.effective_at.date().isoformat(),
            "status": "documented",
            "source_type": "document",
            "source_ref": f"observation:{observation.id}",
            "focus": "exams",
        })
        seen_names.add(name)
        if len(metrics) >= limit:
            return metrics
    return metrics


def build_default_doctor_summary(db: Session, user_id: int) -> str:
    admitted = db.scalar(
        select(func.count()).select_from(ConfirmedHealthObservation).join(
            HealthReportWorkflow,
            HealthReportWorkflow.id == ConfirmedHealthObservation.workflow_id,
        ).where(
            ConfirmedHealthObservation.user_id == user_id,
            ConfirmedHealthObservation.subject_user_id == user_id,
            ConfirmedHealthObservation.status == "active",
            HealthReportWorkflow.status.in_(["completed", "completed_score_pending"]),
        )
    )
    if not admitted:
        return ""
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
