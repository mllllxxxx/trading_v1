"""Load generated rulebook skills for legacy validator/prompt consumers.

Skills are generated from ``trading/rulebook/source`` for backward compatibility
with the existing validator/prompt code. Two categories:
  - hard: validator enforces strictly (REJECT on violation)
  - soft: LLM considers (override allowed with reasoning)

The canonical runtime input is ``trading/rulebook/compiled/skills.json``.
``trading/auto/skills.json`` is generated only for older code paths and review
compatibility.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import Any

AUTO_DIR = Path(__file__).resolve().parent
TRADING_DIR = AUTO_DIR.parent
SKILLS_FILE = AUTO_DIR / "skills.json"
COMPILED_SKILLS_FILE = TRADING_DIR / "rulebook" / "compiled" / "skills.json"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FAIL_CLOSED_MARKERS = ("paper", "live", "review", "prod", "production")
_TEST_FALLBACK_MARKERS = ("test", "pytest", "ci", "dev", "development", "local", "research")

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


class SkillsLoadError(RuntimeError):
    """Raised when generated rulebook skills cannot be safely loaded."""


def _validate_structure(data: dict[str, Any], *, require_generated: bool = True) -> bool:
    if not isinstance(data, dict):
        return False
    if require_generated:
        if data.get("_generated") is not True or data.get("_do_not_edit") is not True:
            return False
        if data.get("_source") != "trading/rulebook/source":
            return False
        if "DO NOT EDIT" not in str(data.get("_generated_notice", "")):
            return False
    if "hard" not in data or "soft" not in data:
        return False
    if not isinstance(data["hard"], dict) or not isinstance(data["soft"], dict):
        return False
    required_hard = {"rr_minimum", "max_position_pct", "max_leverage"}
    if not required_hard.issubset(data["hard"].keys()):
        return False
    return True


def _runtime_mode(mode: str | None = None) -> str:
    """Return the current autonomy/runtime mode hint."""
    candidates = [
        mode,
        os.getenv("TRADING_AUTONOMY_MODE"),
        os.getenv("AUTONOMY_MODE"),
        os.getenv("TRADING_PROFILE"),
        os.getenv("APP_ENV"),
        os.getenv("ENV"),
    ]
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip().lower()
    return "unspecified"


def _is_fail_closed_mode(mode: str) -> bool:
    """Return whether the mode must fail closed on missing policy."""
    if os.getenv("OKX_TESTNET", "true").strip().lower() not in _TRUE_VALUES:
        return True
    return any(marker in mode for marker in _FAIL_CLOSED_MARKERS)


def _is_test_fallback_mode(mode: str) -> bool:
    """Return whether explicit fixture fallback is allowed for this mode."""
    return any(marker in mode for marker in _TEST_FALLBACK_MARKERS)


def _explicit_test_fallback_allowed(
    mode: str,
    allow_test_fallback: bool | None,
) -> bool:
    if _is_fail_closed_mode(mode):
        return False
    if allow_test_fallback is not None:
        return bool(allow_test_fallback) and _is_test_fallback_mode(mode)
    env_value = os.getenv("RULEBOOK_ALLOW_TEST_FALLBACK", "").strip().lower()
    return env_value in _TRUE_VALUES and _is_test_fallback_mode(mode)


def _test_fixture_defaults() -> dict[str, Any]:
    data = copy.deepcopy(DEFAULTS)
    data["_test_fixture_fallback"] = True
    data["_source"] = "explicit_test_fixture"
    return data


def _raise_or_test_fallback(
    message: str,
    *,
    mode: str,
    allow_test_fallback: bool | None,
) -> dict[str, Any]:
    if _explicit_test_fallback_allowed(mode, allow_test_fallback):
        log.warning("%s; using explicit test fixture defaults", message)
        return _test_fixture_defaults()
    raise SkillsLoadError(message)


def load_compiled_rulebook(
    path: Path | None = None,
    *,
    mode: str | None = None,
    allow_test_fallback: bool | None = None,
) -> dict[str, Any]:
    """Load generated compiled rulebook skills.

    Missing or malformed skills raise ``SkillsLoadError`` by default. A tiny
    fixture fallback is available only when explicitly requested in test/dev
    modes, never in paper/live/review modes.
    """
    fp = path or COMPILED_SKILLS_FILE
    active_mode = _runtime_mode(mode)
    if not fp.exists():
        return _raise_or_test_fallback(
            f"compiled skills not found at {fp}",
            mode=active_mode,
            allow_test_fallback=allow_test_fallback,
        )
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return _raise_or_test_fallback(
            f"failed to parse compiled skills at {fp}: {exc}",
            mode=active_mode,
            allow_test_fallback=allow_test_fallback,
        )
    if not _validate_structure(data):
        return _raise_or_test_fallback(
            f"compiled skills structure invalid at {fp}",
            mode=active_mode,
            allow_test_fallback=allow_test_fallback,
        )
    return data


def load_skills(
    path: Path | None = None,
    *,
    mode: str | None = None,
    allow_test_fallback: bool | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for loading compiled rulebook skills."""
    return load_compiled_rulebook(
        path=path,
        mode=mode,
        allow_test_fallback=allow_test_fallback,
    )


def get_hard_skills() -> dict[str, Any]:
    return load_skills()["hard"]


def get_soft_skills() -> dict[str, Any]:
    return load_skills()["soft"]
