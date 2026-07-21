"""Database-authoritative Beijing daily diet summaries and retries."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from app.db.session import SessionLocal
from app.providers.factory import get_provider
from app.services import dietary_records_service as dietary_service
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


def _effective_now(now_iso: str | None) -> datetime:
    if now_iso is None:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_iso must include timezone")
    return value.astimezone(timezone.utc)


def _provider_error_code(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "provider_timeout"
    if isinstance(exc, ValueError):
        return "provider_invalid_output"
    return "provider_error"


def _next_retry_is_due(evidence: dict[str, Any], now: datetime) -> bool:
    raw = evidence.get("next_retry_at")
    if not isinstance(raw, str):
        return False
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if value.tzinfo is None or value.utcoffset() is None:
        return False
    return value.astimezone(timezone.utc) <= now


def _run_model_attempt(
    *,
    prepared: dict[str, Any],
    provider: Any,
    now: datetime,
    increment_retry_attempt: bool,
) -> str:
    summary = prepared["summary"]
    try:
        result = provider.summarize_daily_diet(prepared["model_payload"])
    except Exception as exc:
        with SessionLocal() as db:
            state = dietary_service.record_daily_summary_failure(
                db,
                summary_id=int(summary["summary_id"]),
                expected_record_version=int(prepared["record_version"]),
                expected_input_fingerprint=prepared["model_input_fingerprint"],
                error_code=_provider_error_code(exc),
                now=now,
                increment_retry_attempt=increment_retry_attempt,
            )
            db.commit()
        return state

    with SessionLocal() as db:
        finalized = dietary_service.finalize_daily_summary(
            db,
            summary_id=int(summary["summary_id"]),
            expected_record_version=int(prepared["record_version"]),
            expected_input_fingerprint=prepared["model_input_fingerprint"],
            result=result,
            now=now,
        )
        if finalized:
            db.commit()
            return "ai_completed"
        db.rollback()
        return "stale"


def _summary_counts(discovered: int) -> dict[str, int]:
    return {
        "discovered": discovered,
        "processed": 0,
        "ai_completed": 0,
        "fallback_retryable": 0,
        "fallback_exhausted": 0,
        "stale": 0,
        "skipped": 0,
        "failed": 0,
    }


@celery_app.task(name="generate_beijing_daily_diet_summaries")
def generate_beijing_daily_diet_summaries(
    max_users: int = 100,
    now_iso: str | None = None,
) -> dict[str, int]:
    """Generate summaries only for confirmed records on Beijing yesterday."""

    effective_now = _effective_now(now_iso)
    target_date = dietary_service.beijing_target_date(effective_now)
    with SessionLocal() as discovery_db:
        candidates = dietary_service.discover_beijing_summary_candidates(
            discovery_db,
            target_date=target_date,
            limit=max_users,
        )
    counts = _summary_counts(len(candidates))
    provider = get_provider()
    for user_id, subject_user_id in candidates:
        try:
            with SessionLocal() as db:
                prepared = dietary_service.prepare_daily_summary_attempt(
                    db,
                    user_id=user_id,
                    subject_user_id=subject_user_id,
                    target_date=target_date,
                    now=effective_now,
                )
                if prepared is None:
                    db.rollback()
                    counts["skipped"] += 1
                    continue
                db.commit()
            evidence = prepared["summary"].get("evidence") or {}
            if (
                evidence.get("generation_status") != "fallback_retryable"
                or not _next_retry_is_due(evidence, effective_now)
            ):
                counts["skipped"] += 1
                continue
            state = _run_model_attempt(
                prepared=prepared,
                provider=provider,
                now=effective_now,
                increment_retry_attempt=False,
            )
            counts["processed"] += 1
            counts[state] += 1
        except Exception:
            logger.exception(
                "Beijing daily diet summary failed for user_id=%s subject_user_id=%s",
                user_id,
                subject_user_id,
            )
            counts["failed"] += 1
    return counts


@celery_app.task(name="retry_daily_diet_summaries")
def retry_daily_diet_summaries(
    max_summaries: int = 100,
    now_iso: str | None = None,
) -> dict[str, int]:
    """Retry only durable fallback summaries whose next attempt is due."""

    effective_now = _effective_now(now_iso)
    with SessionLocal() as discovery_db:
        summary_ids = dietary_service.discover_due_summary_retry_ids(
            discovery_db,
            now=effective_now,
            limit=max_summaries,
        )
    counts = _summary_counts(len(summary_ids))
    provider = get_provider()
    for summary_id in summary_ids:
        try:
            with SessionLocal() as db:
                prepared = dietary_service.prepare_daily_summary_retry(
                    db,
                    summary_id=summary_id,
                    now=effective_now,
                )
                if prepared is None:
                    db.rollback()
                    counts["skipped"] += 1
                    continue
                db.commit()
            state = _run_model_attempt(
                prepared=prepared,
                provider=provider,
                now=effective_now,
                increment_retry_attempt=True,
            )
            counts["processed"] += 1
            counts[state] += 1
        except Exception:
            logger.exception(
                "daily diet summary retry failed for summary_id=%s", summary_id
            )
            counts["failed"] += 1
    return counts


@celery_app.task(name="process_due_dietary_days")
def process_due_dietary_days(
    max_days: int = 100,
    now_iso: str | None = None,
) -> dict[str, int]:
    """Discover, claim, and close due days in isolated transactions.

    Beat delivery is intentionally at-least-once.  PostgreSQL row claims and
    the day/summary database invariants make the resulting transition
    effectively once for each dietary-day record version.
    """

    effective_now = _effective_now(now_iso)
    bounded_max_days = max(1, min(max_days, 500))
    with SessionLocal() as discovery_db:
        day_ids = dietary_service.discover_due_dietary_day_ids(
            discovery_db,
            now=effective_now,
            limit=bounded_max_days,
        )

    counts = {
        "discovered": len(day_ids),
        "processed": 0,
        "ready": 0,
        "waiting_confirmation": 0,
        "incomplete": 0,
        "skipped": 0,
        "failed": 0,
    }
    for day_id in day_ids:
        try:
            with SessionLocal() as db:
                result = dietary_service.auto_complete_due_day_by_id(
                    db,
                    day_id=day_id,
                    now=effective_now,
                )
                if result is None:
                    db.rollback()
                    counts["skipped"] += 1
                    continue
                db.commit()
            state = str(result["state"])
            counts["processed"] += 1
            if state in {"ready", "waiting_confirmation", "incomplete"}:
                counts[state] += 1
        except Exception:
            logger.exception("dietary day completion failed for day_id=%s", day_id)
            counts["failed"] += 1
    return counts
