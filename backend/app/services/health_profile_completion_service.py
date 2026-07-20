"""Server-authoritative health-profile completion and public redaction rules."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.health_trust import (
    HealthProfileCandidate,
    HealthProfileFact,
    HealthProfileSource,
)
from app.models.health_trust_expansion import (
    HealthProfileFactSourceVersion,
    HealthProfileGoal,
)


RESOLVED_RESPONSE_STATES = {
    "value",
    "none",
    "not_applicable",
    "prefer_not_to_answer",
}

# These weights describe information completeness, never health quality.
REQUIRED_PROFILE_FACT_WEIGHTS: dict[str, int] = {
    "basic.birth_date": 1,
    "basic.sex": 1,
    "basic.height": 1,
    "basic.weight": 1,
    "basic.blood_type": 1,
    "basic.region": 1,
    "basic.lifestyle": 1,
    "safety.medication_allergy": 1,
    "safety.other_allergy": 1,
    "safety.contraindication": 1,
    "safety.pregnancy_or_breastfeeding": 1,
    "safety.major_surgery": 1,
    "safety.important_condition": 1,
    "safety.clinician_restriction": 1,
    "goal.primary": 1,
}

_MEDICATION_ITEM_INPUT_KEYS = {
    "medication_name",
    "generic_name",
    "brand_name",
    "name",
    "strength",
    "dose_text",
    "dose_quantity",
    "dosage",
    "dose",
    "frequency",
    "schedule",
    "schedule_times",
    "reminder",
    "reminders",
    "reminder_time",
    "meal_relation",
    "instructions",
    "course_start",
    "course_end",
    "prescriber",
    "initial_quantity",
    "inventory_unit",
    "actions",
}
_MEDICATION_PUBLIC_FIELDS = (
    "medication_name",
    "purpose",
    "started_on",
    "is_still_taking",
    "source",
    "last_confirmed_at",
)
# Medication-scoped profile responses and revision snapshots may keep these
# audit/container fields.  Every other key is dropped, so newly introduced
# dose/schedule/reminder aliases fail closed instead of relying on a denylist.
_MEDICATION_SAFE_CONTAINER_FIELDS = {
    "response_state",
    "kind",
    "items",
    "algorithm_version",
    "value",
    "value_data",
    "fact_id",
    "fact_key",
    "category",
    "is_safety_critical",
    "confirmation_method",
    "status",
    "version",
    "confirmed_by_user_id",
    "confirmed_at",
    "candidate_id",
    "proposed_value",
    "review_status",
    "conflict_with_fact_id",
    "confidence",
    "action",
    "request",
    "request_action",
    "source_candidate_id",
    "confirmed_fact_id",
    "expected_version",
    "reason",
    "source_type",
    "source_ref",
    "plan_id",
    "plan_version",
    "source_plan_versions",
    "automatic_fact_created",
}


def _medication_item(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy medication snapshots to the six-field public contract."""
    medication_name = (
        value.get("medication_name")
        or value.get("brand_name")
        or value.get("generic_name")
        or value.get("name")
    )
    started_on = value.get("started_on") or value.get("course_start")
    is_still_taking = value.get("is_still_taking")
    if is_still_taking is None and "status" in value:
        is_still_taking = value.get("status") == "active"
    return {
        "medication_name": medication_name,
        "purpose": value.get("purpose"),
        "started_on": started_on,
        "is_still_taking": is_still_taking,
        "source": value.get("source"),
        "last_confirmed_at": value.get("last_confirmed_at") or value.get("confirmed_at"),
    }


def _safe_medication_public_value(value: Any) -> Any:
    if (
        value is None
        or isinstance(value, (str, int, float, bool))
        or hasattr(value, "isoformat")
    ):
        return value
    return None


def sanitize_medication_payload(value: Any, *, _item_context: bool = False) -> Any:
    """Apply the six-field medication allowlist to every profile surface."""
    if isinstance(value, list):
        return [
            sanitize_medication_payload(item, _item_context=_item_context)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    is_container = bool(
        {"items", "value_data", "proposed_value", "request", "source_plan_versions"}
        .intersection(value)
    )
    if _item_context or (
        _MEDICATION_ITEM_INPUT_KEYS.intersection(value) and not is_container
    ):
        normalized = _medication_item(value)
        return {
            key: _safe_medication_public_value(normalized.get(key))
            for key in _MEDICATION_PUBLIC_FIELDS
        }
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key not in _MEDICATION_SAFE_CONTAINER_FIELDS:
            continue
        sanitized[key] = sanitize_medication_payload(
            item,
            _item_context=key == "items",
        )
    return sanitized


def sanitize_profile_payload(
    value: Any,
    *,
    fact_key: str | None = None,
    category: str | None = None,
) -> Any:
    if category == "medication" or (fact_key or "").startswith("medication."):
        return sanitize_medication_payload(value)
    return value


def canonical_source_identity(source_type: str, source_ref: str) -> tuple[str, str]:
    """Collapse historical medication plan versions into one real source."""
    normalized_ref = source_ref.strip()
    if source_type == "medication":
        normalized_ref = re.sub(r":v\d+$", "", normalized_ref)
    return source_type, normalized_ref


def _independent_source_count(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    facts: list[HealthProfileFact],
    legacy_sources: Iterable[HealthProfileSource],
) -> int:
    fact_by_id = {fact.id: fact for fact in facts}
    if not fact_by_id:
        return 0
    version_rows = list(
        db.execute(
            select(HealthProfileFactSourceVersion).where(
                HealthProfileFactSourceVersion.user_id == user_id,
                HealthProfileFactSourceVersion.subject_user_id == subject_user_id,
                HealthProfileFactSourceVersion.fact_id.in_(fact_by_id),
            )
        ).scalars().all()
    )
    version_managed_fact_ids: set[int] = set()
    identities: set[tuple[str, str]] = set()
    for row in version_rows:
        fact = fact_by_id.get(row.fact_id)
        if fact is None:
            continue
        version_managed_fact_ids.add(row.fact_id)
        if row.fact_version != fact.version:
            continue
        identities.add(canonical_source_identity(row.source_type, row.source_identity))
    for source in legacy_sources:
        if source.fact_id not in fact_by_id or source.fact_id in version_managed_fact_ids:
            continue
        identities.add(canonical_source_identity(source.source_type, source.source_ref))
    return len(identities)


def build_profile_completion(
    db: Session,
    *,
    user_id: int,
    subject_user_id: int,
    facts: list[HealthProfileFact],
    candidates: list[HealthProfileCandidate],
    sources: list[HealthProfileSource],
    goals: list[HealthProfileGoal],
) -> tuple[dict[str, Any], str]:
    """Compute completion and the only primary action exposed to clients."""
    active_by_key = {fact.fact_key: fact for fact in facts}
    resolved_keys = {
        key
        for key, fact in active_by_key.items()
        if (fact.value_data or {}).get("response_state") in RESOLVED_RESPONSE_STATES
    }
    if any(goal.status != "archived" for goal in goals):
        resolved_keys.add("goal.primary")
    total_weight = sum(REQUIRED_PROFILE_FACT_WEIGHTS.values())
    resolved_weight = sum(
        weight
        for key, weight in REQUIRED_PROFILE_FACT_WEIGHTS.items()
        if key in resolved_keys
    )
    missing = [key for key in REQUIRED_PROFILE_FACT_WEIGHTS if key not in resolved_keys]
    completeness = round(100 * resolved_weight / total_weight) if total_weight else 100

    if candidates:
        safety_review = any(candidate.is_safety_critical for candidate in candidates)
        primary_action = {
            "kind": "review_updates",
            "item_count": len(candidates),
            "localization_key": "health_profile.primary_action.review_updates",
            "route": "profile_safety_editor" if safety_review else "profile_updates",
        }
    elif missing:
        primary_action = {
            "kind": "complete_profile",
            "item_count": len(missing),
            "localization_key": "health_profile.primary_action.complete_profile",
            "route": "profile_editor",
        }
    else:
        primary_action = {
            "kind": "edit_profile",
            "item_count": 0,
            "localization_key": "health_profile.primary_action.edit_profile",
            "route": "profile_editor",
        }

    return (
        {
            "completeness_percent": completeness,
            "resolved_required_weight": resolved_weight,
            "total_required_weight": total_weight,
            "missing_required_fact_keys": missing,
            "pending_update_count": len(candidates),
            "independent_source_count": _independent_source_count(
                db,
                user_id=user_id,
                subject_user_id=subject_user_id,
                facts=facts,
                legacy_sources=sources,
            ),
            "primary_action": primary_action,
        },
        "needs_attention" if candidates or missing else "updated",
    )
