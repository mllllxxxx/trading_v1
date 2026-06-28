"""Auto-trade scheduler.

Periodically (every SCHED_INTERVAL seconds):
  1. Check kill switch
  2. Compute regime + confluence
  3. Check safety guards (open count, daily loss, capital)
  4. If conditions met -> place bracket order via okx_bracket
  5. Log everything to journal

All hard guards must pass. NO trade on mixed regime or weak confluence.

TRADE MODE (env, default "spot"):
  spot    — original OKX spot, uses brackets/okx_bracket.py
  futures — OKX USDT-margined SWAP, uses brackets/okx_futures_bracket.py
            (Tuần 1, 2026-06-23: enabled but not yet exercised end-to-end)
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Import sibling journal module
sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # type: ignore
import skills as _skills  # type: ignore
import validator as _validator  # type: ignore
import brain as _brain  # type: ignore
import prompts as _prompts  # type: ignore
import alerts as _alerts  # type: ignore

# Futures layer (lazy: imported only when TRADE_MODE=futures to avoid ccxt dep
# on bare spot deployments)
try:
    import universe as _universe  # type: ignore
except ImportError:
    _universe = None
try:
    import llm_override_tracker as _override  # type: ignore
except ImportError:
    _override = None

AUTO_DIR = Path(__file__).resolve().parent
BRACKETS_DIR = AUTO_DIR.parent / "brackets"
CONFLUENCE_PY = AUTO_DIR.parent / "confluence" / "confluence.py"
REGIME_PY = AUTO_DIR.parent / "regime" / "regime.py"
OKX_BRACKET_PY = BRACKETS_DIR / "okx_bracket.py"
OKX_FUTURES_BRACKET_PY = BRACKETS_DIR / "okx_futures_bracket.py"


# ---------------------------------------------------------------------------
# Trade mode (spot | futures) — added 2026-06-23 for futures support
# ---------------------------------------------------------------------------

TRADE_MODE = os.getenv("TRADE_MODE", "spot").strip().lower()
if TRADE_MODE not in ("spot", "futures"):
    raise SystemExit(f"TRADE_MODE must be 'spot' or 'futures', got '{TRADE_MODE}'")


def _is_futures() -> bool:
    return TRADE_MODE == "futures"


def _load_bracket_module():
    """Load the right bracket module based on TRADE_MODE.

    Returns the imported module (cached at module import via _okx_bracket for spot).
    For futures, dynamically imports okx_futures_bracket on first call.
    """
    if _is_futures():
        spec = importlib.util.spec_from_file_location(
            "okx_futures_bracket", OKX_FUTURES_BRACKET_PY
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load okx_futures_bracket from {OKX_FUTURES_BRACKET_PY}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    return _okx_bracket


def _resolve_symbols() -> list[dict[str, str]]:
    """Return list of {swap, spot} dicts for the configured universe.

    In spot mode: returns [{spot: sym}] for each entry in SYMBOLS env.
    In futures mode: calls universe.load_universe() and returns both formats.
    """
    if not _is_futures():
        return [{"spot": s, "swap": s} for s in SYMBOLS]

    if _universe is None:
        raise RuntimeError("TRADE_MODE=futures but universe module not importable")

    snap = _universe.load_universe()
    return [
        {"spot": meta.spot_symbol, "swap": meta.swap_symbol, "base": meta.base}
        for meta in snap.symbols
    ]


def _load_okx_bracket():
    """C1: Load okx_bracket module once at module import so the Phase 1
    fallback path can call compute_bracket() without relying on a name
    (`mod`) only bound inside _place_bracket_via_script. Previously, if LLM
    was unavailable the fallback raised NameError every cycle.
    """
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("okx_bracket", OKX_BRACKET_PY)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"cannot load okx_bracket from {OKX_BRACKET_PY}")
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)  # type: ignore
    return _mod


_okx_bracket = _load_okx_bracket()

# Track last regime per symbol for change detection (Telegram alerts).
_REGIME_STATE: dict[str, str] = {}

# Auto-trade parameters
# Phase B-multi: support multiple symbols (comma-separated)
SYMBOLS_STR = os.getenv("AUTO_SYMBOLS", os.getenv("AUTO_SYMBOL", "BTC-USDT"))
SYMBOLS = [s.strip() for s in SYMBOLS_STR.split(",") if s.strip()]
SCHED_INTERVAL = int(os.getenv("AUTO_INTERVAL_S", "300"))  # 5 min default
MIN_CONFLUENCE = int(os.getenv("AUTO_MIN_CONFLUENCE", "2"))  # need +2 or better
ALLOWED_REGIMES = {"TRENDING_UP", "TRENDING_DOWN"}
MAX_OPEN_POSITIONS = int(os.getenv("AUTO_MAX_POSITIONS", "3"))
DAILY_LOSS_CAP_PCT = float(os.getenv("AUTO_DAILY_LOSS_CAP_PCT", "0.03"))
CAPITAL = float(os.getenv("AUTO_CAPITAL", "10000"))
# C1: Drawdown-based risk multiplier tiers (drawdown_pct -> risk_multiplier).
# Each tier halves risk to shrink exposure as losses accumulate.
# Format: list of (max_drawdown_pct, multiplier). Sorted by drawdown ascending.
DRAWDOWN_TIERS = [
    (0.05, 1.0),
    (0.10, 0.5),
    (0.15, 0.25),
    (1.00, 0.0),  # >= 15% drawdown → halt trading entirely
]


class _RuntimeConfig:
    """M6: Mutable runtime config re-read from env on demand.

    Operators can change AUTO_CAPITAL, AUTO_DAILY_LOSS_CAP_PCT, etc. without
    restarting the bot. The next scheduler cycle picks up the new value.
    """

    __slots__ = ("interval_s", "min_confluence", "max_positions",
                 "daily_loss_cap_pct", "capital", "cooldown_minutes")

    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.interval_s = int(os.getenv("AUTO_INTERVAL_S", "300"))
        self.min_confluence = int(os.getenv("AUTO_MIN_CONFLUENCE", "2"))
        self.max_positions = int(os.getenv("AUTO_MAX_POSITIONS", "3"))
        self.daily_loss_cap_pct = float(os.getenv("AUTO_DAILY_LOSS_CAP_PCT", "0.03"))
        self.capital = float(os.getenv("AUTO_CAPITAL", "10000"))
        # 0 disables cooldown.
        self.cooldown_minutes = float(os.getenv("AUTO_COOLDOWN_MINUTES", "30"))


def _runtime() -> _RuntimeConfig:
    """Return a fresh RuntimeConfig snapshot. Cheap; safe to call per-cycle."""
    return _RuntimeConfig()


# M5: Maximum allowed distance between LLM-proposed entry and current_price.
# 5% is generous for crypto 24/7; tighter would reject too many valid setups
# during high-volatility regime transitions.
ENTRY_FRESHNESS_MAX_PCT = float(os.getenv("AUTO_ENTRY_FRESHNESS_MAX_PCT", "0.05"))


def _run_python_script(script_path: Path, *args: str) -> tuple[int, str, str]:
    """Run a sibling Python script as subprocess, return (rc, stdout, stderr)."""
    cmd = [sys.executable, str(script_path), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout, proc.stderr


def _run_confluence(symbol: str) -> dict[str, Any]:
    rc, out, err = _run_python_script(CONFLUENCE_PY, "--symbol", symbol, "--json")
    if rc != 0:
        raise RuntimeError(f"confluence failed: {err}")
    return json.loads(out)


def _run_regime(symbol: str) -> dict[str, Any]:
    rc, out, err = _run_python_script(REGIME_PY, "--symbol", symbol, "--json")
    if rc != 0:
        raise RuntimeError(f"regime failed: {err}")
    return json.loads(out)


def _compute_bracket_params(regime: dict[str, Any], confluence: dict[str, Any],
                            current_price: float, is_long: bool) -> dict[str, Any]:
    """Choose SL/TP based on regime and recent volatility.

    H5: Was hardcoded 1.5% SL / 3% TP, which gets hunted in HIGH_VOLATILITY
    regimes and is too tight relative to ATR. Now we use max(1.5%, 1.5xATR%)
    so that the stop is at least as wide as the daily range, and we keep the
    1:2 R:R baseline when ATR is unavailable.
    """
    atr_14 = float(regime.get("indicators", {}).get("atr_14") or 0)
    if atr_14 > 0 and current_price > 0:
        atr_pct = atr_14 / current_price * 100.0
        stop_pct = max(1.5, atr_pct * 1.5)  # at least 1.5%, else 1.5x ATR
        reward_pct = stop_pct * 2.0          # keep 1:2 R:R
    else:
        stop_pct = 1.5
        reward_pct = 3.0
    if is_long:
        sl = round(current_price * (1 - stop_pct / 100), 2)
        tp = round(current_price * (1 + reward_pct / 100), 2)
    else:
        sl = round(current_price * (1 + stop_pct / 100), 2)
        tp = round(current_price * (1 - reward_pct / 100), 2)
    return {"stop_loss": sl, "take_profit": tp,
            "side": "buy" if is_long else "sell",
            "stop_pct": stop_pct, "reward_pct": reward_pct}


def _clamp_size_pct(size_pct: float, hard_max: float = 20.0) -> float:
    """H6: Clamp LLM-returned size_pct to [0, hard_max].

    Prevents a runaway LLM (or hallucination) from oversizing the position
    past the 20% capital cap before validator sees it. Returns 0 for NaN
    or unparseable input (fail safe — better to skip than over-size).
    """
    try:
        v = float(size_pct)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or v < 0:
        return 0.0
    if v > hard_max:
        return hard_max
    return v


# C3: Classify LLM errors explicitly so silent fallback is impossible.
_API_KEY_MISSING = "DEEPSEEK_API_KEY not set"


def _classify_llm_error(err: str | None) -> str:
    """Return one of: 'ok', 'no_key', 'api_error', 'unexpected'.

    Only 'no_key' allows the rules-only fallback (backward-compat with
    setups that never wired DeepSeek). Any real API error must abort the
    cycle so we never trade without LLM oversight.
    """
    if not err:
        return "ok"
    if _API_KEY_MISSING in err:
        return "no_key"
    return "api_error"


def _place_bracket_via_script(symbol: str, side: str, entry: float,
                                stop_loss: float, take_profit: float,
                                capital: float,
                                risk_pct: float | None = None) -> dict[str, Any]:
    """Invoke bracket module in-process to avoid OKX env duplication.

    Dispatches based on ``TRADE_MODE``: spot uses ``okx_bracket``,
    futures uses ``okx_futures_bracket``.

    risk_pct: per-trade risk override (e.g., 0.005 to halve risk during
              drawdown). When None, bracket module uses its default.
    """
    mod = _load_bracket_module()
    if _is_futures():
        # Futures: leverage is set per-symbol, symbol must be SWAP form.
        # We pass leverage=None so module uses SymbolMeta default.
        # Risk-pct override semantics: same (shrink, not enlarge).
        proposal = mod.compute_bracket_futures(
            symbol, side, entry, stop_loss, take_profit, capital, risk_pct=risk_pct,
        )
        violations = mod.validate_futures(proposal)
        if violations:
            return {"ok": False, "proposal": proposal, "violations": violations}
    else:
        proposal = mod.compute_bracket(
            symbol, side, entry, stop_loss, take_profit, capital, risk_pct=risk_pct,
        )
        violations = mod.validate(proposal)
        if violations:
            return {"ok": False, "proposal": proposal, "violations": violations}
    # Place live (testnet). ccxt loads from .env in user home, same as host.
    cfg = mod.load_okx_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "OKX_API_KEY not set"}
    if not cfg["testnet"]:
        # Tuần 3/4: live trading is allowed once VPS smoke passes. For now this
        # is a safety net — flip OKX_TESTNET=false after `scripts/deploy_oracle.sh`
        # runs and you've confirmed 24h of clean paper on VPS.
        return {"ok": False, "error": "Refusing to place on LIVE - testnet only"}
    try:
        if _is_futures():
            orders = mod.place_orders_futures(proposal, cfg, dry_run=False)
        else:
            orders = mod.place_orders_spot(proposal, cfg, dry_run=False)
        if _is_futures() and not orders.get("ok"):
            return {"ok": False, "proposal": proposal, "error": orders.get("error", "unknown")}
        return {"ok": True, "proposal": proposal, "orders": orders}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _daily_pnl_usd(closed: list[dict[str, Any]]) -> float:
    """Sum of PnL for trades closed today (local time)."""
    today = time.strftime("%Y-%m-%d")
    total = 0.0
    for t in closed:
        ts = t.get("closed_at", "")[:10]
        if ts == today:
            total += float(t.get("pnl_usd", 0))
    return total


def _drawdown_multiplier(current_capital: float, peak_capital: float) -> tuple[float, float]:
    """C1: Return (multiplier, drawdown_pct) based on drawdown tiers.

    Tiers (default, env-overridable later):
      <  5% DD: 1.00x risk
      < 10% DD: 0.50x risk
      < 15% DD: 0.25x risk
      >= 15% DD: 0.00x (halt)
    """
    if peak_capital <= 0 or current_capital <= 0:
        return (1.0, 0.0)
    dd = max(0.0, (peak_capital - current_capital) / peak_capital)
    for max_dd, mult in DRAWDOWN_TIERS:
        if dd < max_dd:
            return (mult, dd)
    return (0.0, dd)


def run_once_symbol(current_symbol: str) -> None:
    """One scheduler cycle for a single symbol. Decides whether to open a position.

    ``current_symbol`` is the SWAP symbol in futures mode (e.g. ``BTC-USDT-SWAP``)
    or the spot symbol in spot mode (e.g. ``BTC-USDT``). Confluence + regime are
    always called with the spot symbol (those scripts use yfinance which expects
    ``BTC-USD`` style). The bracket module dispatches based on ``TRADE_MODE``.
    """
    # M6: Reload env vars each cycle so operator can change AUTO_CAPITAL etc.
    cfg = _runtime()
    # Resolve spot ↔ swap pair
    if _is_futures() and current_symbol.endswith("-USDT-SWAP"):
        spot_symbol = current_symbol.replace("-USDT-SWAP", "-USDT")
    elif _is_futures() and not current_symbol.endswith("-USDT-SWAP"):
        spot_symbol = current_symbol  # already spot
    else:
        spot_symbol = current_symbol
    # H4: If positions.json is corrupt, journal raises JournalCorruptError.
    # Treat as halt — better to skip a cycle than to open a duplicate while
    # OKX still holds the original.
    try:
        positions = journal.read_positions()
    except journal.JournalCorruptError as exc:
        journal.append_decision("skip", {"reason": "corrupt_journal",
                                          "symbol": current_symbol,
                                          "error": str(exc)})
        return

    # C2: Cool-down after a losing trade (gap fill — prevent revenge trading).
    # Stored in stats.json; cleared automatically when expired.
    in_cd, cd_reason, cd_remaining = journal.is_in_cooldown()
    if in_cd:
        journal.append_decision("skip", {
            "reason": "cooldown_active",
            "symbol": current_symbol,
            "remaining_s": cd_remaining,
            "trigger": cd_reason or "",
        })
        return

    if any(p["symbol"] == current_symbol for p in positions):
        return  # already open for this symbol, skip silently

    if journal.is_killed():
        journal.append_decision("skip", {"reason": "kill_switch_active",
                                          "symbol": current_symbol})
        return

    # H5: Auto kill on 3+ consecutive losses (global, not per-symbol)
    if journal.check_loss_streak_kill():
        journal.append_decision("skip", {"reason": "h5_loss_streak_kill",
                                          "symbol": current_symbol})
        return

    # 1. Open position guard
    if len(positions) >= cfg.max_positions:
        journal.append_decision("skip", {"reason": "max_open_positions",
                                          "open_count": len(positions)})
        return

    # 2. Daily loss cap (need closed log for daily_pnl)
    try:
        closed = journal.read_closed_trades()
    except (OSError, json.JSONDecodeError) as exc:
        journal.append_decision("skip", {"reason": "closed_trades_read_error",
                                          "error": str(exc)})
        return
    daily_pnl = _daily_pnl_usd(closed)
    if daily_pnl <= -(cfg.capital * cfg.daily_loss_cap_pct):
        journal.append_decision("skip", {"reason": "daily_loss_cap",
                                          "daily_pnl": daily_pnl,
                                          "cap_usd": -cfg.capital * cfg.daily_loss_cap_pct})
        return

    # 3. Confluence (C2: guard missing keys)
    try:
        conf = _run_confluence(spot_symbol)
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as exc:
        journal.append_decision("skip", {"reason": "confluence_error", "error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001  # M3: unexpected — log + continue
        journal.append_decision("error", {"where": "confluence_unexpected",
                                            "error": str(exc)})
        return
    score_raw = conf.get("total_score")
    if score_raw is None:
        journal.append_decision("skip", {"reason": "confluence_missing_total_score",
                                          "symbol": current_symbol})
        return
    try:
        score = int(score_raw)
    except (TypeError, ValueError) as exc:
        journal.append_decision("skip", {"reason": "confluence_bad_score",
                                          "score": score_raw, "error": str(exc),
                                          "symbol": current_symbol})
        return
    if score < cfg.min_confluence:
        journal.append_decision("skip", {"reason": "weak_confluence", "score": score,
                                          "min_required": cfg.min_confluence,
                                          "symbol": current_symbol})
        return
    if score <= -cfg.min_confluence:
        journal.append_decision("skip", {"reason": "bearish_confluence", "score": score,
                                          "symbol": current_symbol})
        return

    # 4. Regime (C2: guard missing keys)
    try:
        reg = _run_regime(spot_symbol)
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as exc:
        journal.append_decision("skip", {"reason": "regime_error", "error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001  # M3: unexpected
        journal.append_decision("error", {"where": "regime_unexpected",
                                            "error": str(exc)})
        return
    regime_name = reg.get("regime")
    if not regime_name:
        journal.append_decision("skip", {"reason": "regime_missing",
                                          "symbol": current_symbol})
        return
    # Detect regime change for Telegram alert (only fire on actual flip).
    prev_regime = _REGIME_STATE.get(current_symbol)
    if prev_regime and prev_regime != regime_name:
        _alerts.emit("regime_change", {
            "symbol": current_symbol,
            "old_regime": prev_regime,
            "new_regime": regime_name,
        })
    _REGIME_STATE[current_symbol] = regime_name
    if regime_name == "CHOPPY":
        journal.append_decision("skip", {"reason": "choppy_market_no_trade",
                                          "choppiness_index": reg.get("indicators", {}).get("choppiness_index"),
                                          "direction_changes_10d": reg.get("indicators", {}).get("direction_changes_10d")})
        return
    if regime_name not in ALLOWED_REGIMES:
        journal.append_decision("skip", {"reason": "bad_regime", "regime": regime_name,
                                          "allowed": list(ALLOWED_REGIMES)})
        return

    # T1A: Regime-conflict short-circuit. When 1d and 1w trends point in opposite
    # directions, the LLM brain correctly detects this and returns no_trade/hold
    # anyway. Skipping the LLM call here saves ~80% of wasted API spend during
    # transitional/CHOPPY regimes (currently the dominant market state).
    conf_tfs = conf.get("timeframes", {})
    trend_1d = conf_tfs.get("1d", {}).get("trend", "?")
    trend_1w = conf_tfs.get("1w", {}).get("trend", "?")
    if (trend_1d in ("UP", "DOWN") and trend_1w in ("UP", "DOWN")
            and trend_1d != trend_1w):
        journal.append_decision("skip", {
            "reason": "regime_conflict_higher_tf",
            "symbol": current_symbol,
            "trend_1d": trend_1d,
            "trend_1w": trend_1w,
            "msg": "Higher-TF trends conflict (1d vs 1w); LLM call skipped to save tokens.",
        })
        return

    # 5. Direction + price (C2: guard missing close; C4: guard zero price)
    is_long = score > 0
    close_raw = reg.get("close")
    if close_raw is None:
        journal.append_decision("skip", {"reason": "regime_missing_close",
                                          "symbol": current_symbol})
        return
    try:
        current_price = float(close_raw)
    except (TypeError, ValueError) as exc:
        journal.append_decision("skip", {"reason": "regime_bad_close",
                                          "close": close_raw, "error": str(exc),
                                          "symbol": current_symbol})
        return
    if current_price <= 0:  # C4: ZeroDivisionError guard
        journal.append_decision("skip", {"reason": "non_positive_price",
                                          "current_price": current_price,
                                          "symbol": current_symbol})
        return
    params = _compute_bracket_params(reg, conf, current_price, is_long)

    # H3: Correlation check from confluence-based direction (was hardcoded True).
    # Caps at 2 same-direction positions regardless of LLM direction.
    is_long_proposed = is_long
    proposed_side = "buy" if is_long_proposed else "sell"
    same_dir_count = sum(1 for p in positions if p.get("side") == proposed_side)
    if same_dir_count >= 2:
        journal.append_decision("skip", {
            "reason": "max_correlated_positions",
            "msg": f"Already have {same_dir_count} {proposed_side} positions. "
                   f"Skill 'position_correlation' caps at 2 to avoid correlated risk.",
            "symbol": current_symbol,
            "proposed_side": proposed_side,
        })
        return

    # Position sizing: S7/H9 lookups based on aligned categories count
    size_pct = conf.get("suggested_position_size_pct")
    if size_pct is None:
        bullish_tfs = 0
        bearish_tfs = 0
        for tf_label in ["15m", "1h", "4h", "1d", "1w"]:
            tf = conf.get("timeframes", {}).get(tf_label, {})
            if tf.get("trend") == "UP" and tf.get("momentum") == "UP":
                bullish_tfs += 1
            elif tf.get("trend") == "DOWN" and tf.get("momentum") == "DOWN":
                bearish_tfs += 1
        aligned_tfs = max(bullish_tfs, bearish_tfs)
        if aligned_tfs == 1:
            size_pct = 5
        elif aligned_tfs in (2, 3):
            size_pct = 10
        elif aligned_tfs == 4:
            size_pct = 15
        else:  # 5/5
            size_pct = 20

    # Market context for validator (H1, H2, H4, etc.)
    rsi_1d = conf.get("timeframes", {}).get("1d", {}).get("rsi")
    market_ctx = {
        "rsi_1d": rsi_1d,
        "atr_14": reg.get("indicators", {}).get("atr_14"),
        "current_price": current_price,
        "news_blackout": reg.get("technical_indicators", {}).get("news_blackout", {}),
    }

    # 5a. Phase 2: call LLM brain to get a refined decision
    llm_decision = None
    llm_error = None
    # T3F: Daily cost cap gate. If today's LLM spend >= cap, skip LLM call
    # and fall back to rules-only path below. The cost is still tracked for
    # the day; auto-resets at local midnight via _load_cost_state().
    cost_status = journal.daily_cost_status()
    cap_reached = bool(cost_status.get("cap_reached", False))
    if cap_reached:
        journal.append_decision("skip", {
            "reason": "daily_llm_cost_cap",
            "symbol": current_symbol,
            "cost_usd": round(float(cost_status.get("cost_usd", 0.0)), 6),
            "cap_usd": float(cost_status.get("cap_usd", 0.0)),
            "calls_today": int(cost_status.get("calls", 0)),
            "msg": "Daily LLM cost cap reached; using rules-only fallback.",
        })
        # Do NOT call LLM; fall through to the Phase 1 rules-only path.
    else:
        try:
            system_prompt = _prompts.build_system_prompt()
            user_prompt = _prompts.build_user_prompt(
                symbol=current_symbol,
                current_price=current_price,
                regime=reg,
                confluence=conf,
                open_positions=positions,
                recent_trades=closed,
                capital=cfg.capital,
                daily_pnl=daily_pnl,
            )
            llm_decision = _brain.call_brain(system_prompt, user_prompt)
            journal.append_decision("llm", {
                "model": llm_decision.get("_model", "?"),
                "latency_s": llm_decision.get("_latency_s", 0),
                "action": llm_decision.get("action"),
                "entry": llm_decision.get("entry"),
                "stop_loss": llm_decision.get("stop_loss"),
                "take_profit": llm_decision.get("take_profit"),
                "position_size_pct": llm_decision.get("position_size_pct"),
                "reasoning": llm_decision.get("reasoning", "")[:300],
                "cost_usd": llm_decision.get("_cost_usd"),
                "input_tokens": llm_decision.get("_input_tokens"),
                "output_tokens": llm_decision.get("_output_tokens"),
                "daily_cost_usd": llm_decision.get("_daily_cost_usd"),
            })
            _alerts.emit("decision", {
                "symbol": current_symbol,
                "action": llm_decision.get("action"),
                "entry": llm_decision.get("entry"),
                "stop_loss": llm_decision.get("stop_loss"),
                "take_profit": llm_decision.get("take_profit"),
                "confidence": llm_decision.get("confidence"),
                "reasoning": llm_decision.get("reasoning", "")[:300],
            })
        except _brain.BrainError as exc:
            llm_error = str(exc)
            journal.append_decision("llm_error", {"error": llm_error})
        except Exception as exc:  # noqa: BLE001
            llm_error = f"unexpected: {exc}"
            journal.append_decision("llm_error", {"error": llm_error})

    # 5b. Phase 3: handle LLM decision
    if llm_decision is None:
        # C3: Only allow rules-only fallback when DeepSeek API key is missing
        # (legacy config). Any real API error (timeout, parse, rate limit, ...)
        # must abort the cycle — silently trading without LLM oversight was
        # the source of H1-equivalent risk in the previous logic.
        llm_class = _classify_llm_error(llm_error)
        if llm_class == "api_error":
            journal.append_decision("skip", {"reason": "llm_unavailable",
                                              "error": llm_error,
                                              "policy": "abort_no_llm_oversight"})
            return
        # else 'no_key' or 'ok' (no_key): continue with rules-only fallback
    else:
        action = str(llm_decision.get("action", "hold")).lower()
        # Treat hold and no_trade the same: no position entry
        if action in ("hold", "no_trade"):
            rq_ok, rq_msg = _validator.check_reasoning_quality(
                llm_decision.get("reasoning", ""))
            journal.append_decision(f"llm_override_{action}", {
                "reasoning_chars": len(llm_decision.get("reasoning", "").strip()),
                "reasoning_quality": {"ok": rq_ok, "msg": rq_msg},
                "reasoning_text": llm_decision.get("reasoning", "")[:200],
                "confidence": llm_decision.get("confidence"),
            })
            return

        if action not in ("long", "short"):
            journal.append_decision("skip", {"reason": "llm_invalid_action",
                                              "action": action})
            return

        # H6: Clamp LLM position_size_pct to [0, 20] before computing units.
        size_pct = _clamp_size_pct(llm_decision.get("position_size_pct", 0))
        # C4: current_price already guarded >0 above, but be explicit:
        if current_price <= 0:
            journal.append_decision("skip", {"reason": "non_positive_price",
                                              "symbol": current_symbol})
            return
        # M5: Freshness check BEFORE validator. If LLM entry is too far from
        # current_price, reject before computing R:R (which would also fail
        # but with a confusing error message). Drift >5% suggests stale LLM
        # data or hallucination.
        llm_entry_raw = llm_decision.get("entry")
        if llm_entry_raw is not None:
            try:
                llm_entry_val = float(llm_entry_raw)
                drift = abs(llm_entry_val - current_price) / current_price
                if drift > ENTRY_FRESHNESS_MAX_PCT:
                    journal.append_decision("skip", {
                        "reason": "stale_llm_entry",
                        "llm_entry": llm_entry_val,
                        "current_price": current_price,
                        "drift_pct": round(drift * 100, 2),
                        "max_pct": ENTRY_FRESHNESS_MAX_PCT * 100,
                        "symbol": current_symbol,
                    })
                    return
            except (TypeError, ValueError):
                pass  # bad entry → use current_price below
        position_size_units = (cfg.capital * size_pct / 100) / current_price
        llm_proposal = {
            "side": "buy" if action == "long" else "sell",
            "entry": float(llm_decision.get("entry", current_price)),
            "stop_loss": float(llm_decision.get("stop_loss", 0)),
            "take_profit": float(llm_decision.get("take_profit", 0)),
            "position_size": position_size_units,
            "capital": cfg.capital,
        }
        vresult = _validator.validate_proposal(llm_proposal,
                                                 llm_context=llm_decision,
                                                 market_context=market_ctx)
        journal.append_decision("validator", {
            "ok": vresult["ok"],
            "rr_ratio": vresult["rr_ratio"],
            "position_pct": vresult["position_pct"],
            "violations": vresult["violations"],
            "llm_phase": "phase2_with_llm",
            "source": "llm",
            "reasoning_check": vresult.get("reasoning_check", {}),
        })
        if not vresult["ok"]:
            journal.append_decision("skip", {"reason": "validator_reject",
                                              "violations": vresult["violations"],
                                              "source": "llm"})
            return

        # LLM output passes validator -> use LLM's SL/TP/size
        params = {
            "side": llm_proposal["side"],
            "stop_loss": llm_proposal["stop_loss"],
            "take_profit": llm_proposal["take_profit"],
        }
        journal.append_decision("llm_decision_used", {
            "action": action,
            "entry": llm_proposal["entry"],
            "stop_loss": llm_proposal["stop_loss"],
            "take_profit": llm_proposal["take_profit"],
            "position_size": position_size_units,
        })

    # 5c. Phase 1 fallback: validate auto-computed proposal (only reached if LLM unavailable)
    if llm_decision is None:
        proposal_for_validator = {
            "side": params["side"],
            "entry": current_price,
            "stop_loss": params["stop_loss"],
            "take_profit": params["take_profit"],
            "position_size": 0,
            "capital": cfg.capital,
        }
        # C1: was `mod.compute_bracket(...)` where `mod` was never bound in this
        # scope (only inside _place_bracket_via_script), causing NameError every
        # LLM-unavailable cycle. Use the module-level `_okx_bracket` instead.
        # compute_bracket() validates SL/TP direction + sizes; we discard the
        # result since position_size is recomputed below from size_pct.
        _ = _okx_bracket.compute_bracket(
            current_symbol, params["side"], current_price,
            params["stop_loss"], params["take_profit"], cfg.capital,
        )
        proposal_for_validator["position_size"] = (cfg.capital * size_pct / 100) / current_price
        vresult = _validator.validate_proposal(proposal_for_validator,
                                                  market_context=market_ctx)
        journal.append_decision("validator", {
            "ok": vresult["ok"],
            "rr_ratio": vresult["rr_ratio"],
            "position_pct": vresult["position_pct"],
            "violations": vresult["violations"],
            "llm_phase": "phase1_no_llm",
            "source": "rules",
        })
        if not vresult["ok"]:
            journal.append_decision("skip", {"reason": "validator_reject",
                                              "violations": vresult["violations"]})
            return

    # 6. Place bracket
    # If LLM provided explicit entry/SL/TP, use them; else use current price for entry
    entry_to_use = current_price
    if llm_decision is not None and llm_decision.get("entry"):
        try:
            llm_entry = float(llm_decision.get("entry"))
            # M5: Reject LLM entries too far from current_price (likely stale data
            # or hallucination). 5% threshold is generous for crypto 24/7.
            if current_price > 0:
                drift = abs(llm_entry - current_price) / current_price
                if drift > ENTRY_FRESHNESS_MAX_PCT:
                    journal.append_decision("skip", {
                        "reason": "stale_llm_entry",
                        "llm_entry": llm_entry,
                        "current_price": current_price,
                        "drift_pct": round(drift * 100, 2),
                        "max_pct": ENTRY_FRESHNESS_MAX_PCT * 100,
                        "symbol": current_symbol,
                    })
                    return
            entry_to_use = llm_entry
        except (TypeError, ValueError):
            entry_to_use = current_price

    # C1: Compute drawdown-based risk multiplier from current/peak capital.
    # If drawdown is too deep, skip the trade entirely (multiplier = 0).
    try:
        _stats = journal.read_stats()
        _dd_mult, _dd_pct = _drawdown_multiplier(
            float(_stats.get("current_capital", cfg.capital)),
            float(_stats.get("peak_capital", cfg.capital)),
        )
    except Exception:  # noqa: BLE001
        _dd_mult, _dd_pct = 1.0, 0.0
    if _dd_mult <= 0:
        journal.append_decision("skip", {
            "reason": "drawdown_halt",
            "symbol": current_symbol,
            "drawdown_pct": round(_dd_pct * 100, 2),
            "msg": "Drawdown exceeds safe threshold; trading halted.",
        })
        return
    # BRACKET_RISK_PCT default is 0.01 (1%). Scale by _dd_mult.
    _risk_pct_override = _okx_bracket.RISK_PCT * _dd_mult

    result = _place_bracket_via_script(
        symbol=current_symbol,
        side=params["side"],
        entry=entry_to_use,
        stop_loss=params["stop_loss"],
        take_profit=params["take_profit"],
        capital=cfg.capital,
        risk_pct=_risk_pct_override,
    )
    journal.append_decision("drawdown_risk", {
        "symbol": current_symbol,
        "drawdown_pct": round(_dd_pct * 100, 2),
        "multiplier": _dd_mult,
        "effective_risk_pct": round(_risk_pct_override * 100, 4),
    })

    if not result.get("ok"):
        journal.append_decision("skip", {"reason": "place_failed",
                                          "violations": result.get("violations", []),
                                          "error": result.get("error", "")})
        return

    # 7. Record position
    proposal = result["proposal"]
    orders = result["orders"]
    
    # Handle futures vs spot order/position formats
    if _is_futures():
        algo_id = orders.get("algo_order_id", "")
        orders_dict = {
            "entry_id": algo_id,
            "tp_id": algo_id,
            "sl_id": algo_id,
            "algo_order_id": algo_id,
        }
    else:
        orders_dict = {
            "entry_id": orders["entry_order"].get("id", "") if "entry_order" in orders else "",
            "tp_id": orders["tp_order"].get("id", "") if "tp_order" in orders else "",
            "sl_id": orders["sl_order"].get("id", "") if "sl_order" in orders else "",
        }

    position = {
        "symbol": current_symbol,
        "side": params["side"],
        "entry": proposal["entry"],
        "stop_loss": proposal["stop_loss"],
        "take_profit": proposal["take_profit"],
        "position_size": proposal.get("position_size") or proposal.get("position_size_base", 0.0),
        "notional": proposal["position_notional"],
        "risk_usd": proposal["actual_risk_usd"],
        "rr_ratio": proposal["rr_ratio"],
        "confluence_score": score,
        "regime": regime_name,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "orders": orders_dict,
        "status": "open",
    }
    # Phase 4: persist LLM reasoning + skills for later trade analytics
    if llm_decision is not None:
        position["llm_reasoning"] = llm_decision.get("reasoning", "")
        position["skills_applied"] = llm_decision.get("reasoning", "")
    journal.add_position(position)
    journal.append_decision("open", {"symbol": current_symbol, "side": params["side"],
                                       "entry": proposal["entry"],
                                       "stop_loss": proposal["stop_loss"],
                                       "take_profit": proposal["take_profit"],
                                       "rr_ratio": proposal["rr_ratio"],
                                       "confluence_score": score,
                                       "regime": regime_name,
                                       "order_ids": position["orders"]})
    _alerts.emit("trade_opened", {
        "symbol": current_symbol,
        "side": params["side"],
        "entry": proposal["entry"],
        "stop_loss": proposal["stop_loss"],
        "take_profit": proposal["take_profit"],
        "rr_ratio": proposal["rr_ratio"],
        "confluence_score": score,
        "regime": regime_name,
        "position_size": proposal["position_size"],
    })


def main_loop() -> None:
    journal.ensure_dirs()
    journal.append_decision("start", {
        "interval_s": SCHED_INTERVAL,
        "trade_mode": TRADE_MODE,
        "symbols": SYMBOLS,
        "min_confluence": MIN_CONFLUENCE,
        "max_positions": MAX_OPEN_POSITIONS,
        "daily_loss_cap_pct": DAILY_LOSS_CAP_PCT,
        "capital": CAPITAL,
    })
    while True:
        # Resolve symbol list based on TRADE_MODE.
        # In spot mode: use SYMBOLS env directly.
        # In futures mode: pull from universe loader (top 10 by volume).
        if _is_futures():
            try:
                resolved = _resolve_symbols()
                trade_symbols = [s["swap"] for s in resolved]
            except Exception as exc:  # noqa: BLE001
                journal.append_decision("error",
                                          {"where": "universe_loader",
                                           "error": str(exc)})
                _alerts.emit("error", {"where": "universe_loader", "error": str(exc)})
                time.sleep(SCHED_INTERVAL)
                continue
        else:
            trade_symbols = SYMBOLS

        # Phase B-multi: iterate through all symbols
        for sym in trade_symbols:
            try:
                run_once_symbol(sym)
            except Exception as exc:  # noqa: BLE001
                journal.append_decision("error",
                                          {"where": f"scheduler/{sym}",
                                           "error": str(exc)})
                _alerts.emit("error", {"where": f"scheduler/{sym}", "error": str(exc)})
        time.sleep(SCHED_INTERVAL)


if __name__ == "__main__":
    main_loop()
