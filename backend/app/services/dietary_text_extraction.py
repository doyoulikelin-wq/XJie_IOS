"""Controlled text/voice/chat extraction for dietary pending drafts."""

from __future__ import annotations

import logging
import math
from typing import Any

from app.core.config import settings
from app.providers.factory import get_provider


logger = logging.getLogger(__name__)

TEXT_RECOGNITION_CONTRACT_VERSION = "meal-text-extraction.v1"
_PRODUCTION_ENVS = {"prod", "production", "staging"}
_ALLOWED_CATEGORIES = {
    "staple",
    "protein",
    "vegetable",
    "fruit",
    "dairy",
    "beverage",
    "other",
}
_ALLOWED_CONFIDENCE_FIELDS = {
    "food_items",
    "portion_text",
    "meal_type",
    "structure",
    "estimated_nutrition",
}


def _manual_result(
    *, recognition_version: str, recognition_error: str | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "food_items": [],
        "portion_text": None,
        "structure": {},
        "estimated_nutrition": {},
        "field_confidences": {},
        "recognition_confidence": None,
        "recognition_status": "failed_manual_entry_available",
        "recognition_version": recognition_version,
    }
    if recognition_error is not None:
        result["recognition_error"] = recognition_error
    return result


def _finite_confidence(value: Any, *, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed):
        return fallback
    return min(1.0, max(0.0, parsed))


def _estimated_nutrition(value: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded ranges and never promote model output to exact facts."""

    output: dict[str, Any] = {"is_estimate": True}
    for key, raw_range in value.items():
        if not key.endswith("_range") or not isinstance(raw_range, list):
            continue
        if len(raw_range) != 2:
            continue
        try:
            low = float(raw_range[0])
            high = float(raw_range[1])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(low) or not math.isfinite(high):
            continue
        low = max(0.0, min(low, 100_000.0))
        high = max(0.0, min(high, 100_000.0))
        if low > high:
            low, high = high, low
        output[key[:80]] = [low, high]
    return output if len(output) > 1 else {}


def extract_dietary_text_candidate(raw_text: str) -> dict[str, Any]:
    """Return bounded candidate fields; failure remains an editable manual draft.

    The caller must invoke this inside the tenant/client-event idempotency lock so
    a network replay cannot execute the provider twice.
    """

    try:
        provider = get_provider()
    except Exception as exc:  # provider construction must not discard the draft
        logger.warning(
            "Dietary text provider construction failed: %s", type(exc).__name__
        )
        return _manual_result(
            recognition_version=TEXT_RECOGNITION_CONTRACT_VERSION,
            recognition_error=type(exc).__name__,
        )
    version = f"{provider.provider_name}:{provider.text_model}"[:80]
    if (
        settings.APP_ENV.strip().lower() in _PRODUCTION_ENVS
        and provider.provider_name == "mock"
    ):
        return _manual_result(
            recognition_version=version,
            recognition_error="ProductionMockProviderRejected",
        )

    try:
        result = provider.analyze_meal_text(raw_text[:4000])
    except Exception as exc:  # recognition failure remains an editable draft
        logger.warning("Dietary text recognition failed: %s", type(exc).__name__)
        return _manual_result(
            recognition_version=version,
            recognition_error=type(exc).__name__,
        )
    if not result.recognized or not result.items:
        return _manual_result(
            recognition_version=version,
            recognition_error="TextNotRecognized",
        )

    food_items: list[dict[str, Any]] = []
    for index, item in enumerate(result.items[:64], start=1):
        name = item.name.strip()
        if not name or len(name) > 160:
            continue
        categories = [
            category
            for category in item.categories[:12]
            if category in _ALLOWED_CATEGORIES
        ]
        food_items.append(
            {
                "item_id": f"text-item-{index}",
                "name": name,
                "portion_text": item.portion_text[:160] if item.portion_text else None,
                "categories": categories,
                "confidence": _finite_confidence(item.confidence),
                "is_estimated": True,
            }
        )
    if not food_items:
        return _manual_result(
            recognition_version=version,
            recognition_error="TextItemsRejected",
        )

    category_counts: dict[str, int] = {}
    structure: dict[str, Any] = {"is_estimate": True}
    for item in food_items:
        for category in item["categories"]:
            category_counts[category] = category_counts.get(category, 0) + 1
            structure["vegetables" if category == "vegetable" else category] = "present"
    structure["category_counts"] = category_counts

    confidences = {
        key: _finite_confidence(value)
        for key, value in result.field_confidences.items()
        if key in _ALLOWED_CONFIDENCE_FIELDS
    }
    overall_confidence = _finite_confidence(result.confidence)
    confidences.setdefault("food_items", min(item["confidence"] for item in food_items))
    confidences.setdefault(
        "portion_text",
        overall_confidence
        if result.portion_text or any(item.get("portion_text") for item in food_items)
        else 0.0,
    )
    confidences.setdefault(
        "meal_type", overall_confidence if result.meal_type is not None else 0.0
    )
    confidences.setdefault("structure", overall_confidence if category_counts else 0.0)
    nutrition = _estimated_nutrition(result.estimated_nutrition)
    confidences.setdefault(
        "estimated_nutrition", overall_confidence if nutrition else 0.0
    )
    payload: dict[str, Any] = {
        "food_items": food_items,
        "portion_text": result.portion_text[:256] if result.portion_text else None,
        "structure": structure,
        "estimated_nutrition": nutrition,
        "field_confidences": confidences,
        "recognition_confidence": overall_confidence,
        "recognition_status": "completed",
        "recognition_version": version,
    }
    if result.meal_type is not None:
        payload["meal_type"] = result.meal_type
    return payload
