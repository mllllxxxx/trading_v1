"""Shared interpretation helpers for signed confluence scores."""

from __future__ import annotations


def classify_candidate_direction(score: float, min_confluence: float) -> str:
    """Classify signed confluence into long, short, or none."""
    if abs(float(score)) < float(min_confluence) or float(score) == 0.0:
        return "none"
    return "long" if float(score) > 0 else "short"


def classify_confluence_direction(
    score: float,
    min_abs: float,
) -> tuple[bool, str | None, str | None]:
    """Return whether confluence is actionable plus direction and order side."""
    direction = classify_candidate_direction(score, min_abs)
    if direction == "none":
        return (False, None, None)
    side = "buy" if direction == "long" else "sell"
    return (True, direction, side)
