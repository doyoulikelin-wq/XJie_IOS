"""Shared durable-state and exact-reupload policy for report OCR."""

from __future__ import annotations

from datetime import datetime, timedelta


REPORT_OCR_PENDING_TIMEOUT_SECONDS = 30 * 60
REPORT_OCR_PROVIDER_UNAVAILABLE_FAILURE_CODE = "report_ocr_provider_unavailable"

# These failures are produced by the durable report OCR workflow and must all
# expose the same user recovery: re-uploading the exact original rebinds the
# workflow and wakes OCR again. Keep presentation and mutation code on this
# single registry so a new failure cannot advertise an action it cannot perform.
REPORT_OCR_TECHNICAL_REUPLOAD_FAILURE_CODES = frozenset(
    {
        REPORT_OCR_PROVIDER_UNAVAILABLE_FAILURE_CODE,
        "report_ocr_retry_exhausted",
        "report_ocr_storage_unavailable",
        "report_ocr_stalled",
    }
)
REPORT_OCR_EXACT_REUPLOAD_FAILURE_CODES = frozenset(
    {*REPORT_OCR_TECHNICAL_REUPLOAD_FAILURE_CODES, "no_reviewable_candidates"}
)


def fresh_report_ocr_pending_metadata(*, now: datetime) -> dict[str, str]:
    """Return one persisted pending window shared by every retry entry point."""

    return {
        "ocr_state": "pending",
        "ocr_pending_since": now.isoformat(),
        "ocr_pending_deadline_at": (
            now + timedelta(seconds=REPORT_OCR_PENDING_TIMEOUT_SECONDS)
        ).isoformat(),
    }
