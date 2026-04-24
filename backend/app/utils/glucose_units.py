"""Glucose unit conversion + display helpers.

Backend stores all glucose values in mg/dL. User-facing strings should be
formatted via `format_glucose` according to the user's preferred unit.
"""

from __future__ import annotations

MGDL_PER_MMOL = 18.018


def mgdl_to_mmol(mgdl: float) -> float:
    """Convert mg/dL → mmol/L."""
    return mgdl / MGDL_PER_MMOL


def format_glucose(mgdl: float, unit: str = "mg_dl") -> str:
    """Format a mg/dL reading for display in the user's chosen unit.

    - "mg_dl"  → "126 mg/dL" (no decimals)
    - "mmol_l" → "7.0 mmol/L" (one decimal)
    """
    if unit == "mmol_l":
        return f"{mgdl_to_mmol(mgdl):.1f} mmol/L"
    return f"{mgdl:.0f} mg/dL"
