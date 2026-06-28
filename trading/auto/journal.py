"""Trade journal: append-only decision log + current positions + closed trades.

File-based (no database). All paths under /data (or $VIBE_TRADING_HOME).

Files:
  decisions.jsonl      - every scheduler/monitor decision (append-only)
  positions.json       - currently open positions (replaced on update)
  closed_trades.jsonl  - every closed position with PnL (append-only)
  stats.json           - aggregate metrics (replaced on update)
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("VIBE_TRADING_HOME", "/data"))
JOURNAL_DIR = DATA_DIR / "journal"
DECISIONS_LOG = JOURNAL_DIR / "decisions.jsonl"
POSITIONS_FILE = JOURNAL_DIR / "positions.json"
CLOSED_LOG = JOURNAL_DIR / "closed_trades.jsonl"
STATS_FILE = JOURNAL_DIR / "stats.json"
KILL_SWITCH = DATA_DIR / "STOP"


class JournalCorruptError(RuntimeError):
    """Raised when a journal file cannot be parsed; signals caller to halt."""


# H1: Serializes all read-modify-write sections across threads so that
# scheduler + monitor never trample each other's positions/stats on disk.
# RLock (not Lock) because add_position/remove_position call read_positions
# then write_positions, both of which lock — a non-reentrant Lock would
# deadlock the same thread.
_FILE_LOCK = threading.RLock()

# Apply TZ env var (e.g., Asia/Ho_Chi_Minh) at import time so that
# time.localtime() / time.strftime() reflect the configured offset.
# Idempotent and safe to call multiple times.
if hasattr(time, "tzset"):
    try:
        time.tzset()
    except Exception:  # noqa: BLE001
        pass


def ensure_dirs() -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    if not POSITIONS_FILE.exists():
        POSITIONS_FILE.write_text("[]", encoding="utf-8")
    if not STATS_FILE.exists():
        STATS_FILE.write_text(json.dumps({
            "total_trades": 0, "wins": 0, "losses": 0,
            "total_pnl_usd": 0.0, "open_count": 0,
            "max_drawdown_usd": 0.0, "starting_capital": 10000.0,
            "current_capital": 10000.0,
        }, indent=2), encoding="utf-8")


def _now() -> str:
    """L1: Return strict ISO 8601 with timezone offset.

    Previously used time.strftime("%z") which returns '+0700' (no colon).
    datetime.fromisoformat() in Python 3.11+ accepts both, but downstream
    parsers (api_server, dashboard) sometimes break on the no-colon form.
    Now returns '2026-06-21T09:59:00+07:00' which round-trips with
    datetime.fromisoformat() across Python 3.10+.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append_decision(decision_type: str, payload: dict[str, Any]) -> None:
    """Append a decision event. decision_type: 'check', 'open', 'cancel', 'fill', 'skip'."""
    ensure_dirs()
    entry = {"ts": _now(), "type": decision_type, **payload}
    with _FILE_LOCK:
        with DECISIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_positions() -> list[dict[str, Any]]:
    """Read current open positions.

    H4: On JSON parse failure, backup the corrupt file with a timestamp suffix
    and raise JournalCorruptError instead of silently returning []. Returning []
    would let the scheduler think the book is flat and open a duplicate position
    while OKX still holds the original. Callers must treat corrupt-journal as a
    halt condition (better to skip a cycle than double-expose).
    """
    ensure_dirs()
    try:
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        backup = POSITIONS_FILE.with_suffix(
            f".corrupt.{int(time.time())}.bak")
        try:
            shutil.copy2(POSITIONS_FILE, backup)
        except OSError:
            pass
        raise JournalCorruptError(
            f"positions.json corrupt (backup at {backup}): {exc}"
        ) from exc
    except OSError:
        return []


def _log_corrupt_positions(exc: Exception) -> None:
    """Log a corrupt_positions event. Called by callers who already hold the lock
    or who need to surface the corruption to journal readers without re-acquiring.
    """
    append_decision("corrupt_journal", {
        "file": str(POSITIONS_FILE),
        "error": str(exc),
        "action": "halt_cycle",
    })


def write_positions(positions: list[dict[str, Any]]) -> None:
    ensure_dirs()
    with _FILE_LOCK:
        POSITIONS_FILE.write_text(json.dumps(positions, indent=2), encoding="utf-8")


def add_position(position: dict[str, Any]) -> None:
    with _FILE_LOCK:
        positions = read_positions()
        positions.append(position)
        write_positions(positions)
    append_decision("open", {"symbol": position["symbol"],
                              "side": position["side"],
                              "entry": position["entry"],
                              "stop_loss": position["stop_loss"],
                              "take_profit": position["take_profit"],
                              "position_size": position["position_size"],
                              "risk_usd": position["risk_usd"]})


def remove_position(symbol: str) -> dict[str, Any] | None:
    with _FILE_LOCK:
        positions = read_positions()
        for i, p in enumerate(positions):
            if p["symbol"] == symbol:
                removed = positions.pop(i)
                write_positions(positions)
                return removed
    return None


def update_position(symbol: str, updates: dict[str, Any]) -> None:
    with _FILE_LOCK:
        positions = read_positions()
        for p in positions:
            if p["symbol"] == symbol:
                p.update(updates)
                write_positions(positions)
                break



def append_closed_trade(trade: dict[str, Any]) -> None:
    ensure_dirs()
    with _FILE_LOCK:
        with CLOSED_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")
    append_decision("fill", {"symbol": trade["symbol"], "pnl_usd": trade["pnl_usd"],
                              "exit_price": trade["exit_price"], "exit_reason": trade["exit_reason"]})


def read_closed_trades() -> list[dict[str, Any]]:
    ensure_dirs()
    if not CLOSED_LOG.exists():
        return []
    out: list[dict[str, Any]] = []
    with CLOSED_LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def write_stats(stats: dict[str, Any]) -> None:
    ensure_dirs()
    with _FILE_LOCK:
        STATS_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def read_stats() -> dict[str, Any]:
    ensure_dirs()
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def update_stats_on_close(trade: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    """Recompute aggregate stats after a trade closes. Mutates and returns stats."""
    pnl = trade["pnl_usd"]
    stats["total_trades"] = stats.get("total_trades", 0) + 1
    if pnl > 0:
        stats["wins"] = stats.get("wins", 0) + 1
    else:
        stats["losses"] = stats.get("losses", 0) + 1
    stats["total_pnl_usd"] = stats.get("total_pnl_usd", 0.0) + pnl
    stats["current_capital"] = stats.get("starting_capital", 10000.0) + stats["total_pnl_usd"]
    if "peak_capital" not in stats:
        stats["peak_capital"] = stats["current_capital"]
    peak = stats["peak_capital"]
    if stats["current_capital"] > peak:
        stats["peak_capital"] = stats["current_capital"]
    dd = stats["peak_capital"] - stats["current_capital"]
    if dd > stats.get("max_drawdown_usd", 0.0):
        stats["max_drawdown_usd"] = dd
    wins = stats.get("wins", 0)
    total = stats.get("total_trades", 0)
    stats["winrate"] = round(wins / total * 100, 2) if total else 0.0
    # Phase 5: rebuild breakdowns + Sharpe each close (cheap because just closed trades re-read)
    closed = read_closed_trades()
    stats["breakdowns"] = _compute_breakdowns(closed)
    stats["sharpe"] = _compute_sharpe(closed, stats.get("starting_capital", 10000.0))
    stats["skill_usage"] = _compute_skill_usage(closed)
    return stats


def _compute_breakdowns(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Win rate by alpha, regime, confluence score, exit_reason."""
    out: dict[str, Any] = {
        "by_regime": {},
        "by_confluence_bucket": {},
        "by_exit_reason": {},
    }
    if not closed:
        return out
    for t in closed:
        pnl = float(t.get("pnl_usd", 0))
        win = pnl > 0
        regime = t.get("regime", "unknown")
        b = out["by_regime"].setdefault(regime, {"wins": 0, "losses": 0, "pnl": 0.0, "n": 0})
        b["wins" if win else "losses"] += 1
        b["pnl"] = round(b["pnl"] + pnl, 2)
        b["n"] += 1
        conf = t.get("confluence_score", 0)
        if conf >= 3:
            bucket = "+3_or_better"
        elif conf >= 1:
            bucket = "+1_to_+2"
        elif conf <= -3:
            bucket = "-3_or_worse"
        elif conf <= -1:
            bucket = "-1_to_-2"
        else:
            bucket = "neutral"
        b2 = out["by_confluence_bucket"].setdefault(bucket, {"wins": 0, "losses": 0, "n": 0})
        b2["wins" if win else "losses"] += 1
        b2["n"] += 1
        reason = t.get("exit_reason", "unknown")
        b3 = out["by_exit_reason"].setdefault(reason, {"n": 0, "pnl": 0.0})
        b3["n"] += 1
        b3["pnl"] = round(b3["pnl"] + pnl, 2)
    for grp in out.values():
        for k, v in grp.items():
            if isinstance(v, dict) and v.get("n", 0) > 0:
                v["winrate_pct"] = round(v.get("wins", 0) / v["n"] * 100, 1)
    return out


def _compute_sharpe(closed: list[dict[str, Any]], starting_capital: float) -> dict[str, Any]:
    """Annualized Sharpe ratio. Simplified: assume 252 trading days/year.

    trade_return = pnl_usd / capital_at_trade_time
    We approximate capital_at_trade_time as starting_capital + cumulative_pnl_before_this_trade.
    """
    if len(closed) < 2:
        return {"ratio": None, "annualized_ratio": None, "trade_count": len(closed)}
    returns: list[float] = []
    running_cap = float(starting_capital)
    for t in closed:
        pnl = float(t.get("pnl_usd", 0))
        if running_cap > 0:
            r = pnl / running_cap
            returns.append(r)
        running_cap += pnl
    if not returns:
        return {"ratio": None, "trade_count": 0}
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = var ** 0.5
    if std_r == 0:
        return {"ratio": 0.0, "annualized_ratio": 0.0, "trade_count": len(closed)}
    sharpe = mean_r / std_r
    return {
        "ratio": round(sharpe, 3),
        "annualized_ratio": round(sharpe * (252 ** 0.5), 3),
        "mean_return": round(mean_r * 100, 4),
        "std_return": round(std_r * 100, 4),
        "trade_count": len(closed),
    }


def _compute_skill_usage(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Track which soft skills LLM applied (extracted from reasoning text) and PnL."""
    out: dict[str, dict[str, int]] = {}
    if not closed:
        return out
    for t in closed:
        skills_text = t.get("skills_applied") or t.get("llm_reasoning", "")
        if not skills_text:
            continue
        text_lower = str(skills_text).lower()
        # Re-derive keyword list from skills.json on each call? Cheap enough.
        try:
            import skills  # type: ignore
            soft = skills.get_soft_skills()
        except Exception:
            soft = {}
        for skill_id in soft:
            if skill_id in text_lower:
                slot = out.setdefault(skill_id, {"applied": 0, "wins": 0, "losses": 0})
                slot["applied"] += 1
                pnl = float(t.get("pnl_usd", 0))
                if pnl > 0:
                    slot["wins"] += 1
                else:
                    slot["losses"] += 1
    for k, v in out.items():
        if v.get("applied", 0) > 0:
            v["winrate_pct"] = round(v["wins"] / v["applied"] * 100, 1)
    return out


def get_consecutive_losses(closed: list[dict[str, Any]] | None = None,
                            n: int = 3) -> dict[str, Any]:
    """H5: Check for N consecutive losses. If triggered, kill switch should activate.

    Args:
      closed: list of closed trade dicts (or None to read from file)
      n: number of consecutive losses that triggers (default 3)

    Returns: {
      'consecutive_losses': int (most recent run),
      'triggered': bool (>= n consecutive),
      'threshold': n,
      'last_3_results': [pnl_usd, ...]
    }
    """
    if closed is None:
        closed = read_closed_trades()
    if not closed:
        return {"consecutive_losses": 0, "triggered": False, "threshold": n,
                "last_3_results": []}
    # Take last N trades (most recent first)
    recent = closed[-n:]
    pnls = [float(t.get("pnl_usd", 0)) for t in recent]
    # Count consecutive losses from the most recent
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break
    return {
        "consecutive_losses": streak,
        "triggered": streak >= n,
        "threshold": n,
        "last_results": pnls,
    }


def check_loss_streak_kill() -> bool:
    """H5: If 3+ consecutive losses, auto-set kill switch and return True.

    Returns True if kill switch was newly set.
    """
    streak = get_consecutive_losses()
    if streak["triggered"] and not is_killed():
        KILL_SWITCH.touch()
        append_decision("h5_loss_streak_kill", {
            "consecutive_losses": streak["consecutive_losses"],
            "threshold": streak["threshold"],
            "last_results": streak["last_results"],
            "msg": "Auto kill switch activated - 3+ consecutive losses",
        })
        return True
    return False


def is_killed() -> bool:
    """Touch /data/STOP to halt the auto system."""
    return KILL_SWITCH.exists()


def clear_kill_switch() -> None:
    """L2: Catch OSError so /api/trader/resume doesn't 500 on race conditions."""
    try:
        if KILL_SWITCH.exists():
            KILL_SWITCH.unlink()
    except OSError:
        pass  # Race: another process already removed it, or permission denied.


# ============= Cooldown (gap C2: protect against revenge-trade after loss) =============
# Stored in stats.json under keys:
#   cooldown_until  - ISO timestamp; trades blocked until then
#   cooldown_reason - human-readable string
#
# Thread-safe via _FILE_LOCK + write_stats().

def _cooldown_from_stats(stats: dict[str, Any]) -> tuple[str | None, str | None]:
    return stats.get("cooldown_until"), stats.get("cooldown_reason")


def set_cooldown(minutes: float, reason: str = "") -> None:
    """Block new trade entries for `minutes` from now.

    Persists to stats.json so it survives monitor restart.
    """
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        from datetime import datetime, timedelta
        until = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        stats["cooldown_until"] = until
        stats["cooldown_reason"] = reason
        write_stats(stats)
    append_decision("cooldown_set", {"minutes": minutes, "until": until, "reason": reason})


def clear_cooldown() -> None:
    """Remove any active cooldown (e.g., after a profitable trade)."""
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        if "cooldown_until" in stats or "cooldown_reason" in stats:
            stats.pop("cooldown_until", None)
            stats.pop("cooldown_reason", None)
            write_stats(stats)
    append_decision("cooldown_cleared", {})


def is_in_cooldown() -> tuple[bool, str | None, int]:
    """Return (in_cooldown, reason, seconds_remaining).

    seconds_remaining is non-negative; 0 if cooldown expired.
    Auto-clears expired cooldowns (no separate cleanup pass needed).
    """
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        until_str, reason = _cooldown_from_stats(stats)
    if not until_str:
        return (False, None, 0)
    try:
        from datetime import datetime
        until = datetime.fromisoformat(until_str)
    except (ValueError, TypeError):
        return (False, None, 0)
    now = datetime.now()
    remaining_s = int((until - now).total_seconds())
    if remaining_s <= 0:
        # Expired — clean up so future reads are cheap.
        clear_cooldown()
        return (False, None, 0)
    return (True, reason, remaining_s)


# ============= LLM cost tracking (T3F: enforce daily cost cap) =============
# Stored in stats.json under "daily_llm_cost":
#   {date: "YYYY-MM-DD", cost_usd: float, calls: int,
#    alerted_50: bool, alerted_80: bool, alerted_100: bool,
#    monthly_cost_usd: float, monthly_date: "YYYY-MM"}
#
# Auto-resets daily at local midnight. Monthly is cumulative.

def _today_key() -> str:
    """Current local date key."""
    return time.strftime("%Y-%m-%d")


def _month_key() -> str:
    """Current local month key."""
    return time.strftime("%Y-%m")


def _load_cost_state() -> dict[str, Any]:
    """Read or initialize today's cost + monthly accumulator."""
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
    cost = stats.get("daily_llm_cost", {})
    if not isinstance(cost, dict):
        cost = {}
    today = _today_key()
    if cost.get("date") != today:
        # Roll over — carry monthly bucket across days.
        prev_month = cost.get("monthly_date")
        if prev_month == _month_key():
            monthly = float(cost.get("monthly_cost_usd", 0.0))
        else:
            monthly = 0.0
        cost = {
            "date": today,
            "cost_usd": 0.0,
            "calls": 0,
            "alerted_50": False,
            "alerted_80": False,
            "alerted_100": False,
            "monthly_cost_usd": round(monthly, 6),
            "monthly_date": _month_key(),
        }
        # Persist the reset so other threads see the new key.
        with _FILE_LOCK:
            stats["daily_llm_cost"] = cost
            write_stats(stats)
    return cost


def add_llm_cost(input_tokens: int, output_tokens: int) -> tuple[float, dict[str, Any]]:
    """Record cost for a single LLM call. Return (cost_usd, updated_state).

    Cost = input_tokens * AUTO_LLM_INPUT_PRICE_PER_M + output_tokens * AUTO_LLM_OUTPUT_PRICE_PER_M
    All in USD per million tokens (DeepSeek v4-flash: $0.14 in / $0.28 out).
    """
    price_in = float(os.getenv("AUTO_LLM_INPUT_PRICE_PER_M", "0.14")) / 1_000_000.0
    price_out = float(os.getenv("AUTO_LLM_OUTPUT_PRICE_PER_M", "0.28")) / 1_000_000.0
    cost = max(0, input_tokens) * price_in + max(0, output_tokens) * price_out
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        state = _load_cost_state()  # also writes reset if needed
        state["cost_usd"] = round(float(state.get("cost_usd", 0.0)) + cost, 6)
        state["calls"] = int(state.get("calls", 0)) + 1
        state["monthly_cost_usd"] = round(
            float(state.get("monthly_cost_usd", 0.0)) + cost, 6
        )
        stats["daily_llm_cost"] = state
        write_stats(stats)
    # Telegram alerts at 50% / 80% / 100% of daily cap (fire-once per day each).
    try:
        cap = float(os.getenv("AUTO_DAILY_LLM_COST_CAP_USD", "0.10"))
        if cap > 0 and cost > 0:
            new_total = float(state.get("cost_usd", 0.0))
            pct = (new_total / cap) * 100.0
            threshold_to_fire = None
            if pct >= 100 and not state.get("alerted_100", False):
                threshold_to_fire = 100
            elif pct >= 80 and not state.get("alerted_80", False):
                threshold_to_fire = 80
            elif pct >= 50 and not state.get("alerted_50", False):
                threshold_to_fire = 50
            if threshold_to_fire is not None:
                import alerts as _alerts  # type: ignore
                _alerts.emit("llm_cost_alert", {
                    "pct": threshold_to_fire,
                    "cost_usd": round(new_total, 6),
                    "cap_usd": cap,
                    "monthly_cost_usd": float(state.get("monthly_cost_usd", 0.0)),
                    "calls_today": int(state.get("calls", 0)),
                })
                mark_cost_alert_sent(threshold_to_fire)
    except Exception:  # noqa: BLE001
        pass  # alerts are best-effort; never break cost tracking
    return (cost, state)


def daily_cost_status() -> dict[str, Any]:
    """Return today's cost + cap + monthly accumulator.

    Used by scheduler (cap gate) and dashboard widget.
    """
    cap = float(os.getenv("AUTO_DAILY_LLM_COST_CAP_USD", "0.10"))
    state = _load_cost_state()
    cost = float(state.get("cost_usd", 0.0))
    return {
        "date": state.get("date", _today_key()),
        "cost_usd": cost,
        "calls": int(state.get("calls", 0)),
        "cap_usd": cap,
        "remaining_usd": max(0.0, round(cap - cost, 6)),
        "pct_of_cap": round((cost / cap * 100.0) if cap > 0 else 0.0, 2),
        "cap_reached": cap > 0 and cost >= cap,
        "monthly_cost_usd": float(state.get("monthly_cost_usd", 0.0)),
        "monthly_date": state.get("monthly_date", _month_key()),
        "alerted_50": bool(state.get("alerted_50", False)),
        "alerted_80": bool(state.get("alerted_80", False)),
        "alerted_100": bool(state.get("alerted_100", False)),
    }


def mark_cost_alert_sent(threshold: int) -> None:
    """Mark a threshold (50/80/100) as already-alerted-today so we don't spam."""
    key = f"alerted_{threshold}"
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        state = _load_cost_state()
        state[key] = True
        stats["daily_llm_cost"] = state
        write_stats(stats)
