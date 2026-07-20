"""Durable, idempotent report score jobs and deterministic score policies."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.health_trust import ConfirmedHealthObservation, HealthReportWorkflow, HealthScoreSnapshot
from app.models.health_trust_expansion import (
    HealthReportScoreJob,
    HealthReportScoreJobItem,
    HealthReportScoreSnapshotLink,
)
from app.models.user_indicator_value import UserIndicatorValue


SCORE_BUNDLE_VERSION = "trusted-report-score-bundle-v1"
SCORE_CATALOG_VERSION = "zh-Hans-report-score-v1"
SCORE_KINDS = ("stress", "recovery", "inflammation")
LEASE_SECONDS = 120

_METHOD_KEYS = {
    "stress": "report.score.method.stress.direct_daily",
    "recovery": "report.score.method.recovery.direct_daily",
    "inflammation": "report.score.method.inflammation.confirmed_labs",
}
_POLICY_IDS = {
    "stress": "direct-daily-stress-score",
    "recovery": "direct-daily-recovery-score",
    "inflammation": "confirmed-inflammatory-lab-burden",
}
_DAILY_ALIASES = {
    "stress": {"stress_score", "daily_stress_score", "压力评分"},
    "recovery": {"recovery_score", "daily_recovery_score", "恢复评分"},
}
_INFLAMMATION_ALIASES = {
    "crp", "hscrp", "hs-crp", "c反应蛋白", "超敏c反应蛋白", "wbc", "白细胞",
    "neutrophils", "中性粒细胞", "nlr", "il6", "il-6", "ferritin", "铁蛋白",
}

_ZH_HANS = {
    "report.score.method.stress.direct_daily": "使用已同步的日常压力评分原始值；报告字段不会单独推算压力变化。",
    "report.score.method.recovery.direct_daily": "使用已同步的日常恢复评分原始值；报告字段不会单独推算恢复变化。",
    "report.score.method.inflammation.confirmed_labs": "仅使用本次报告中已确认的炎症相关指标及其正常/异常状态计算负担比例。",
    "report.score.input.daily_stress": "日常压力评分",
    "report.score.input.daily_recovery": "日常恢复评分",
    "report.score.input.confirmed_inflammation": "已确认炎症相关报告指标",
    "report.score.failure.missing_daily_stress": "缺少可用的日常压力评分，暂不生成压力变化。",
    "report.score.failure.missing_daily_recovery": "缺少可用的日常恢复评分，暂不生成恢复变化。",
    "report.score.failure.missing_inflammation_labs": "本次报告没有已确认的炎症相关指标，暂不生成炎症变化。",
    "report.score.failure.calculation_failed": "评分计算暂时失败，可稍后重试。",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def localized_text(key: str, params: dict | None = None, *, locale: str = "zh-Hans") -> dict:
    params = params or {}
    # zh-Hans is the first supported catalog. Unknown locales fail safely to it
    # while retaining the requested locale in no internal identifier.
    template = _ZH_HANS.get(key, "该信息暂不可用。")
    try:
        rendered = template.format(**params)
    except (KeyError, ValueError):
        rendered = template
    return {
        "key": key,
        "params": params,
        "text": rendered,
        "locale": "zh-Hans",
        "catalog_version": SCORE_CATALOG_VERSION,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _daily_evidence(db: Session, workflow: HealthReportWorkflow, cutoff: datetime) -> list[dict]:
    start = cutoff - timedelta(days=30)
    rows = db.execute(
        select(UserIndicatorValue)
        .where(
            UserIndicatorValue.user_id == workflow.user_id,
            UserIndicatorValue.measured_at >= start,
            UserIndicatorValue.measured_at <= cutoff,
            UserIndicatorValue.value_kind == "numeric",
        )
        .order_by(UserIndicatorValue.measured_at, UserIndicatorValue.id)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "indicator_name": row.indicator_name,
            "source_metric": row.source_metric,
            "value": row.value,
            "unit": row.unit,
            "measured_at": row.measured_at.isoformat(),
            "source": row.source,
        }
        for row in rows
    ]


def _report_evidence(db: Session, workflow: HealthReportWorkflow) -> list[dict]:
    rows = db.execute(
        select(ConfirmedHealthObservation)
        .where(
            ConfirmedHealthObservation.workflow_id == workflow.id,
            ConfirmedHealthObservation.user_id == workflow.user_id,
            ConfirmedHealthObservation.subject_user_id == workflow.subject_user_id,
            ConfirmedHealthObservation.status == "active",
        )
        .order_by(ConfirmedHealthObservation.id)
    ).scalars().all()
    return [
        {
            "id": row.id,
            "canonical_code": row.canonical_code,
            "canonical_name": row.canonical_name,
            "value_numeric": str(row.value_numeric) if row.value_numeric is not None else None,
            "value_text": row.value_text,
            "unit": row.unit,
            "abnormal_state": row.abnormal_state,
            "effective_at": row.effective_at.isoformat(),
            "version": row.version,
        }
        for row in rows
    ]


def enqueue_score_job(db: Session, *, workflow: HealthReportWorkflow) -> HealthReportScoreJob:
    """Insert the outbox and all score-kind items inside the confirmation transaction."""

    cutoff = workflow.confirmed_at or _utcnow()
    common = {
        "workflow_id": workflow.id,
        "confirmation_client_event_id": workflow.confirmation_client_event_id,
        "evidence_cutoff_at": cutoff.isoformat(),
        "daily": _daily_evidence(db, workflow, cutoff),
        "report_observations": _report_evidence(db, workflow),
    }
    manifest_digest = _digest(common)
    existing = db.execute(
        select(HealthReportScoreJob).where(
            HealthReportScoreJob.workflow_id == workflow.id,
            HealthReportScoreJob.user_id == workflow.user_id,
            HealthReportScoreJob.subject_user_id == workflow.subject_user_id,
            HealthReportScoreJob.algorithm_bundle_version == SCORE_BUNDLE_VERSION,
            HealthReportScoreJob.input_manifest_digest == manifest_digest,
        )
    ).scalars().first()
    if existing:
        return existing
    revision = int(
        db.scalar(
            select(func.coalesce(func.max(HealthReportScoreJob.input_revision), 0)).where(
                HealthReportScoreJob.workflow_id == workflow.id,
                HealthReportScoreJob.user_id == workflow.user_id,
                HealthReportScoreJob.subject_user_id == workflow.subject_user_id,
            )
        )
        or 0
    ) + 1
    prior = db.execute(
        select(HealthReportScoreJob)
        .where(
            HealthReportScoreJob.workflow_id == workflow.id,
            HealthReportScoreJob.user_id == workflow.user_id,
            HealthReportScoreJob.subject_user_id == workflow.subject_user_id,
        )
        .order_by(HealthReportScoreJob.input_revision.desc())
    ).scalars().first()
    job = HealthReportScoreJob(
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        subject_user_id=workflow.subject_user_id,
        job_key=f"score:{workflow.id}:{SCORE_BUNDLE_VERSION}:{manifest_digest[:24]}",
        input_revision=revision,
        algorithm_bundle_version=SCORE_BUNDLE_VERSION,
        input_manifest_digest=manifest_digest,
        evidence_cutoff_at=cutoff,
        supersedes_job_id=prior.id if prior else None,
        status="pending",
        attempt_count=0,
        max_attempts=3,
        next_attempt_at=cutoff,
    )
    db.add(job)
    db.flush()
    for kind in SCORE_KINDS:
        input_basis = []
        if kind in {"stress", "recovery"}:
            input_basis = [
                {
                    "code": f"daily_{kind}",
                    "label_key": f"report.score.input.daily_{kind}",
                    "source_refs": [f"user_indicator_value:{row['id']}" for row in common["daily"]],
                }
            ]
        else:
            input_basis = [
                {
                    "code": "confirmed_inflammation",
                    "label_key": "report.score.input.confirmed_inflammation",
                    "source_refs": [f"confirmed_health_observation:{row['id']}" for row in common["report_observations"]],
                }
            ]
        db.add(
            HealthReportScoreJobItem(
                job_id=job.id,
                workflow_id=workflow.id,
                user_id=workflow.user_id,
                subject_user_id=workflow.subject_user_id,
                score_kind=kind,
                policy_id=_POLICY_IDS[kind],
                policy_version="v1",
                status="pending",
                attempt_count=0,
                input_manifest=common,
                missing_inputs={},
                retryable=False,
                failure_message_params={},
                method_summary_key=_METHOD_KEYS[kind],
                method_summary_params={},
                catalog_version=SCORE_CATALOG_VERSION,
                input_basis=input_basis,
            )
        )
    db.flush()
    return job


def claim_score_job(db: Session, *, now: datetime | None = None) -> tuple[int, str] | None:
    now = now or _utcnow()
    job = db.execute(
        select(HealthReportScoreJob)
        .where(
            or_(
                (
                    (HealthReportScoreJob.status == "pending")
                    & or_(HealthReportScoreJob.next_attempt_at.is_(None), HealthReportScoreJob.next_attempt_at <= now)
                ),
                (
                    (HealthReportScoreJob.status == "running")
                    & (HealthReportScoreJob.lease_expires_at < now)
                ),
            ),
            HealthReportScoreJob.attempt_count < HealthReportScoreJob.max_attempts,
        )
        .order_by(HealthReportScoreJob.next_attempt_at, HealthReportScoreJob.id)
        .with_for_update(skip_locked=True)
    ).scalars().first()
    if not job:
        return None
    token = uuid.uuid4().hex
    job.status = "running"
    job.lease_token = token
    job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    job.attempt_count += 1
    job.started_at = job.started_at or now
    db.commit()
    return job.id, token


def _matches_alias(row: dict, aliases: set[str]) -> bool:
    values = {str(row.get("indicator_name") or "").strip().casefold(), str(row.get("source_metric") or "").strip().casefold()}
    return bool(values & {alias.casefold() for alias in aliases})


def _outcome(before: Decimal | None, after: Decimal, *, lower_is_better: bool) -> str:
    if before is None:
        return "unknown"
    if before == after:
        return "unchanged"
    improved = after < before if lower_is_better else after > before
    return "improved" if improved else "worsened"


def _calculate_item(db: Session, item: HealthReportScoreJobItem) -> None:
    manifest = item.input_manifest or {}
    before: Decimal | None = None
    after: Decimal | None = None
    confidence = Decimal("1.0000")
    direction = "lower_is_better"
    algorithm_id = item.policy_id
    evidence: dict[str, Any] = {}
    missing_key: str | None = None
    if item.score_kind in {"stress", "recovery"}:
        rows = [row for row in manifest.get("daily", []) if _matches_alias(row, _DAILY_ALIASES[item.score_kind])]
        rows.sort(key=lambda row: (row.get("measured_at") or "", row.get("id") or 0))
        valid = [Decimal(str(row["value"])) for row in rows if 0 <= Decimal(str(row["value"])) <= 100]
        if not valid:
            missing_key = f"report.score.failure.missing_daily_{item.score_kind}"
        else:
            after = valid[-1]
            before = valid[-2] if len(valid) > 1 else None
            direction = "lower_is_better" if item.score_kind == "stress" else "higher_is_better"
            evidence = {"daily_source_ids": [row["id"] for row in rows]}
    else:
        rows = []
        for row in manifest.get("report_observations", []):
            identity = str(row.get("canonical_code") or row.get("canonical_name") or "").strip().casefold().replace(" ", "")
            if identity in {alias.casefold().replace(" ", "") for alias in _INFLAMMATION_ALIASES} and row.get("abnormal_state") in {"normal", "abnormal"}:
                rows.append(row)
        if not rows:
            missing_key = "report.score.failure.missing_inflammation_labs"
        else:
            after = (Decimal(sum(row["abnormal_state"] == "abnormal" for row in rows)) / Decimal(len(rows)) * Decimal("100")).quantize(Decimal("0.001"))
            previous = db.execute(
                select(HealthScoreSnapshot)
                .where(
                    HealthScoreSnapshot.user_id == item.user_id,
                    HealthScoreSnapshot.subject_user_id == item.subject_user_id,
                    HealthScoreSnapshot.score_kind == "inflammation",
                    HealthScoreSnapshot.calculation_status == "completed",
                    HealthScoreSnapshot.source_report_workflow_id != item.workflow_id,
                )
                .order_by(HealthScoreSnapshot.computed_at.desc(), HealthScoreSnapshot.id.desc())
            ).scalars().first()
            before = previous.after_value if previous else None
            confidence = (Decimal(len(rows)) / Decimal(max(len(rows), 3))).quantize(Decimal("0.0001"))
            evidence = {"confirmed_observation_ids": [row["id"] for row in rows]}
    if missing_key:
        item.status = "unavailable"
        item.missing_inputs = {"message_key": missing_key}
        item.failure_code = "missing_required_inputs"
        item.failure_message_key = missing_key
        item.retryable = False
        item.computed_at = _utcnow()
        return
    assert after is not None
    algorithm_version = f"{item.policy_id}:{item.policy_version}"
    snapshot = db.execute(
        select(HealthScoreSnapshot).where(
            HealthScoreSnapshot.user_id == item.user_id,
            HealthScoreSnapshot.subject_user_id == item.subject_user_id,
            HealthScoreSnapshot.source_report_workflow_id == item.workflow_id,
            HealthScoreSnapshot.score_kind == item.score_kind,
            HealthScoreSnapshot.algorithm_version == algorithm_version,
        )
    ).scalars().first()
    if not snapshot:
        snapshot = HealthScoreSnapshot(
            user_id=item.user_id,
            subject_user_id=item.subject_user_id,
            source_report_workflow_id=item.workflow_id,
            idempotency_key=f"score-item:{item.id}:{algorithm_version}"[:96],
            score_kind=item.score_kind,
            algorithm_id=algorithm_id,
            algorithm_version=algorithm_version,
            before_value=before,
            after_value=after,
            before_confidence=confidence if before is not None else None,
            after_confidence=confidence,
            score_direction=direction,
            semantic_outcome=_outcome(before, after, lower_is_better=direction == "lower_is_better"),
            calculation_status="completed",
            evidence=evidence,
            missing_inputs={},
            computed_at=_utcnow(),
        )
        db.add(snapshot)
        db.flush()
    link = db.execute(
        select(HealthReportScoreSnapshotLink).where(
            HealthReportScoreSnapshotLink.job_item_id == item.id,
            HealthReportScoreSnapshotLink.user_id == item.user_id,
            HealthReportScoreSnapshotLink.subject_user_id == item.subject_user_id,
        )
    ).scalars().first()
    if not link:
        db.add(
            HealthReportScoreSnapshotLink(
                job_item_id=item.id,
                snapshot_id=snapshot.id,
                workflow_id=item.workflow_id,
                user_id=item.user_id,
                subject_user_id=item.subject_user_id,
            )
        )
    item.status = "completed"
    item.attempt_count += 1
    item.failure_code = None
    item.failure_message_key = None
    item.retryable = False
    item.computed_at = _utcnow()


def execute_claimed_score_job(db: Session, *, job_id: int, lease_token: str) -> HealthReportScoreJob:
    job = db.execute(
        select(HealthReportScoreJob)
        .where(HealthReportScoreJob.id == job_id, HealthReportScoreJob.lease_token == lease_token)
        .with_for_update()
    ).scalars().first()
    if not job or job.status != "running":
        raise RuntimeError("score job lease is not owned by this worker")
    items = list(
        db.execute(
            select(HealthReportScoreJobItem)
            .where(HealthReportScoreJobItem.job_id == job.id)
            .order_by(HealthReportScoreJobItem.id)
        ).scalars().all()
    )
    for item in items:
        if item.status == "completed":
            continue
        try:
            item.status = "running"
            _calculate_item(db, item)
        except Exception:
            item.status = "failed"
            item.attempt_count += 1
            item.failure_code = "score_calculation_failed"
            item.failure_message_key = "report.score.failure.calculation_failed"
            item.retryable = True
            item.computed_at = _utcnow()
    statuses = {item.status for item in items}
    workflow = db.get(HealthReportWorkflow, job.workflow_id)
    if statuses == {"completed"}:
        job.status = "completed"
        if workflow:
            workflow.status = "completed"
    elif "completed" in statuses:
        job.status = "partial_failed"
    else:
        job.status = "failed"
    job.finished_at = _utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    db.commit()
    db.refresh(job)
    return job


def retry_score_job(db: Session, *, workflow_id: int, user_id: int, subject_user_id: int) -> HealthReportScoreJob:
    job = db.execute(
        select(HealthReportScoreJob)
        .where(
            HealthReportScoreJob.workflow_id == workflow_id,
            HealthReportScoreJob.user_id == user_id,
            HealthReportScoreJob.subject_user_id == subject_user_id,
        )
        .order_by(HealthReportScoreJob.input_revision.desc())
        .with_for_update()
    ).scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Score job not found")
    retryable_items = list(
        db.execute(
            select(HealthReportScoreJobItem).where(
                HealthReportScoreJobItem.job_id == job.id,
                HealthReportScoreJobItem.status == "failed",
                HealthReportScoreJobItem.retryable.is_(True),
            )
        ).scalars().all()
    )
    if not retryable_items:
        return job
    for item in retryable_items:
        item.status = "pending"
    # A manual retry is an explicit operator/user decision after the automatic
    # budget was exhausted. Preserve the audited attempt count and grant one
    # additional claim instead of resetting history or leaving an unclaimable
    # ``pending`` job behind.
    if job.attempt_count >= job.max_attempts:
        job.max_attempts = job.attempt_count + 1
    job.status = "pending"
    job.next_attempt_at = _utcnow()
    job.lease_token = None
    job.lease_expires_at = None
    job.finished_at = None
    db.commit()
    db.refresh(job)
    return job


def score_item_presentations(
    db: Session, *, workflow_id: int, user_id: int, subject_user_id: int, locale: str
) -> dict[str, dict]:
    items = list(
        db.execute(
            select(HealthReportScoreJobItem)
            .where(
                HealthReportScoreJobItem.workflow_id == workflow_id,
                HealthReportScoreJobItem.user_id == user_id,
                HealthReportScoreJobItem.subject_user_id == subject_user_id,
            )
            .order_by(HealthReportScoreJobItem.id.desc())
        ).scalars().all()
    )
    result: dict[str, dict] = {}
    for item in items:
        if item.score_kind in result:
            continue
        result[item.score_kind] = {
            "job_item_status": item.status,
            "method_summary": localized_text(item.method_summary_key, item.method_summary_params, locale=locale),
            "input_basis": [
                {
                    **basis,
                    "label": localized_text(str(basis.get("label_key") or ""), locale=locale),
                }
                for basis in (item.input_basis or [])
            ],
            "failure": (
                {
                    "code": item.failure_code,
                    "retryable": item.retryable,
                    "message": localized_text(item.failure_message_key, item.failure_message_params, locale=locale),
                }
                if item.failure_message_key
                else None
            ),
        }
    return result
