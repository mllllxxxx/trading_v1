"""Skills loader: load + validate skills.json structure.

Skills are user-editable JSON. Two categories:
  - hard: validator enforces strictly (REJECT on violation)
  - soft: LLM considers (override allowed with reasoning)

If skills.json is missing or malformed, falls back to safe defaults.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

SKILLS_FILE = Path(__file__).resolve().parent / "skills.json"

DEFAULT_HARD = {
    "rr_minimum": 1.2,
    "max_position_pct": 0.20,
    "max_leverage": 3.0,
    "stop_loss_required": True,
    "take_profit_required": True,
}

DEFAULT_SOFT = {
    "avoid_overbought_long": "Khong long khi 1d RSI > 75 (overbought)",
    "avoid_oversold_short": "Khong short khi 1d RSI < 25 (oversold)",
    "high_vol_caution": "ATR ratio > 1.5 thi giam position size 50%",
    "major_news_avoid": "Tranh mo position 30 phut truoc/sau FOMC, CPI, NFP",
    "btc_dominance_rule": "BTC dominance > 60% thi uu tien BTC trade hon altcoin",
    "trend_persistence": "Trong trending regime, doi pullback de entry tot hon",
}

DEFAULTS: dict[str, Any] = {"hard": DEFAULT_HARD, "soft": DEFAULT_SOFT}

log = logging.getLogger(__name__)


def _validate_structure(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if "hard" not in data or "soft" not in data:
        return False
    if not isinstance(data["hard"], dict) or not isinstance(data["soft"], dict):
        return False
    required_hard = {"rr_minimum", "max_position_pct", "max_leverage"}
    if not required_hard.issubset(data["hard"].keys()):
        return False
    return True


def load_skills(path: Path | None = None) -> dict[str, Any]:
    """Load skills from JSON. Falls back to defaults on any error."""
    fp = path or SKILLS_FILE
    if not fp.exists():
        log.warning("skills.json not found at %s, using defaults", fp)
        return dict(DEFAULTS)
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("failed to parse skills.json (%s), using defaults", exc)
        return dict(DEFAULTS)
    if not _validate_structure(data):
        log.warning("skills.json structure invalid, using defaults")
        return dict(DEFAULTS)
    return data


def get_hard_skills() -> dict[str, Any]:
    return load_skills().get("hard", DEFAULT_HARD)


def get_soft_skills() -> dict[str, Any]:
    return load_skills().get("soft", DEFAULT_SOFT)
