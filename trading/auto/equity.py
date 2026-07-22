"""Runtime equity helpers for capped demo-account studies."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Mapping


def equity_cap_usd() -> float | None:
    """Return the configured simulated equity cap, if any."""
    return _positive_env_float("TRADING_EQUITY_CAP_USD") or _positive_env_float("AUTO_EQUITY_CAP_USD")


def runtime_equity(default: float = 10_000.0) -> float:
    """Return the equity runtime modules should use for new decisions."""
    cap = equity_cap_usd()
    if cap is not None:
        return cap
    return _positive_env_float("AUTO_CAPITAL") or default


def risk_profile_name() -> str:
    """Return the selected non-secret risk profile name."""
    return os.getenv("TRADING_RISK_PROFILE", "default").strip() or "default"


def pnl_baseline_usd() -> float:
    """Return the PnL baseline for the active capped-equity study."""
    env_baseline = _number(os.getenv("TRADING_EQUITY_CAP_PNL_BASELINE_USD"))
    if env_baseline is not None:
        return env_baseline
    return _pnl_baseline_from_file()


def apply_equity_cap(account_state: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay a simulated equity cap on a dashboard account-state payload."""
    cap = equity_cap_usd()
    account = dict(account_state)
    if cap is None:
        return account

    actual_current = _number(account.get("current_capital_usd"))
    actual_available = _number(account.get("available_balance_usd"))
    actual_total_pnl = _number(account.get("total_pnl_usd"))
    realized = _number(account.get("journal_realized_pnl_usd")) or 0.0
    unrealized = _number(account.get("unrealized_pnl_usd")) or 0.0
    pre_cap_total_pnl = realized + unrealized
    baseline = pnl_baseline_usd()
    simulated_total_pnl = pre_cap_total_pnl - baseline
    simulated_current = cap + simulated_total_pnl
    source = str(account.get("source") or "account")
    errors = [str(item) for item in account.get("errors") or [] if item]
    if "equity_cap_active" not in errors:
        errors.append("equity_cap_active")

    account.update(
        {
            "source": f"{source}_capped",
            "risk_profile": risk_profile_name(),
            "simulation_equity_cap_usd": round(cap, 2),
            "equity_cap_pnl_baseline_usd": round(baseline, 2),
            "pre_cap_total_pnl_usd": round(pre_cap_total_pnl, 2),
            "starting_capital_usd": round(cap, 2),
            "current_capital_usd": round(simulated_current, 2),
            "total_pnl_usd": round(simulated_total_pnl, 2),
            "available_balance_usd": (
                round(min(actual_available, max(simulated_current, 0.0)), 2)
                if actual_available is not None
                else round(max(simulated_current, 0.0), 2)
            ),
            "actual_current_capital_usd": round(actual_current, 2) if actual_current is not None else None,
            "actual_available_balance_usd": round(actual_available, 2) if actual_available is not None else None,
            "actual_total_pnl_usd": round(actual_total_pnl, 2) if actual_total_pnl is not None else None,
            "errors": errors,
        }
    )
    return account


def _pnl_baseline_from_file() -> float:
    profile = risk_profile_name()
    path = Path(os.getenv("VIBE_TRADING_HOME", "/data")) / "journal" / "equity_study_baseline.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0.0
    if not isinstance(payload, Mapping):
        return 0.0
    if str(payload.get("risk_profile") or "") != profile:
        return 0.0
    cap = equity_cap_usd()
    file_cap = _number(payload.get("equity_cap_usd"))
    if cap is not None and file_cap is not None and round(file_cap, 2) != round(cap, 2):
        return 0.0
    return _number(payload.get("baseline_total_pnl_usd")) or 0.0


def _positive_env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None
