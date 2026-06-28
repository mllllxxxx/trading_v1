"""Trade proposal validator.

Checks a trade proposal against hard rules (from skills.json + skill document).
Returns (ok, violations_list).

Hard rules enforced (from trading-rules SKILL.md):
  H1: Volatility cap (ATR*3 > price*5%)
  H3: Position <= 20% capital
  H4: RSI extreme (>=85 no long, <=15 no short)
  H6: Confidence < 0.40 -> no_trade

Futures-specific (NEW in Tuần 1, 2026-06-23):
  H5: Per-symbol leverage cap (BTC=10, alts=2-3)
  H7: Liquidation distance >= per-symbol buffer (BTC=10%, alts=25%)
  H8: Funding blackout: refuse new position +/-5min around funding time

LLM-specific:
  - reasoning must have >= 50 chars + mention >= 1 soft skill
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import skills as _skills

log = logging.getLogger(__name__)

REASONING_MIN_CHARS = 50
REASONING_REQUIRE_SKILL_MENTION = True
RSI_OVERBOUGHT = 85.0
RSI_OVERSOLD = 15.0
MIN_CONFIDENCE = 0.40
VOLATILITY_CAP_ATR_MULT = 3.0
VOLATILITY_CAP_PRICE_PCT = 0.05

# H5/H7/H8 config (overridable via env)
MAX_LEVERAGE_BTC = int(os.getenv("MAX_LEVERAGE_BTC", "10"))
MAX_LEVERAGE_ALT = int(os.getenv("MAX_LEVERAGE_ALT", "3"))
# 10x BTC liq sits ~9.5% from entry (1/lev - MMR). 0.08 (8%) keeps trades
# just feasible; tighten with caution (lower buffer = closer to liquidation).
LIQ_BUFFER_BTC = float(os.getenv("LIQ_BUFFER_BTC", "0.08"))
LIQ_BUFFER_ALT = float(os.getenv("LIQ_BUFFER_ALT", "0.25"))     # 25% — fits 3x lev
FUNDING_BLACKOUT_MIN = int(os.getenv("FUNDING_BLACKOUT_MIN", "5"))


# ---------------------------------------------------------------------------
# H5 / H7 / H8 — futures-specific
# ---------------------------------------------------------------------------

# Bases that get BTC-tier leverage/buffer (only BTC for now).
_BTC_BASES = frozenset({"BTC"})


def _is_btc(base: str) -> bool:
    return base.upper() in _BTC_BASES


def check_leverage(symbol: str, leverage: int) -> tuple[bool, str]:
    """H5: per-symbol leverage cap.

    BTC: 10x. Alts: 3x. Symbol inferred from ``-USDT-SWAP`` suffix.
    """
    if leverage <= 0:
        return False, f"H5 leverage: must be > 0, got {leverage}"
    cap = MAX_LEVERAGE_BTC if _is_btc(_base_of(symbol)) else MAX_LEVERAGE_ALT
    if leverage > cap:
        tier = "BTC" if _is_btc(_base_of(symbol)) else "ALT"
        return False, f"H5 leverage: {leverage}x > {cap}x max for {tier} ({symbol})"
    return True, "OK"


def check_liquidation_buffer(
    entry: float,
    liq_price: float,
    symbol: str,
) -> tuple[bool, str]:
    """H7: distance from entry to liquidation price >= per-symbol buffer.

    At 10x leverage the liq sits ~10% from entry, so 30% buffer is unreachable.
    Per-symbol config:
      BTC: 10% (matches 10x leverage)
      ALT: 25% (matches 3x leverage, allows ~5% SL with buffer to spare)
    """
    if entry <= 0:
        return False, "H7: entry must be > 0"
    if liq_price <= 0:
        return False, "H7: liq_price must be > 0"
    distance_pct = abs(entry - liq_price) / entry
    required = LIQ_BUFFER_BTC if _is_btc(_base_of(symbol)) else LIQ_BUFFER_ALT
    if distance_pct < required:
        return False, (
            f"H7 liq buffer: {distance_pct:.2%} < {required:.2%} required "
            f"(entry={entry}, liq={liq_price:.2f}, {symbol})"
        )
    return True, "OK"


def check_funding_blackout(
    symbol: str,
    now_ms: int | None = None,
    blackout_min: int = FUNDING_BLACKOUT_MIN,
) -> tuple[bool, str]:
    """H8: refuse new position within ±blackout_min of next funding time.

    Fetches funding schedule from OKX. Fails OPEN on network error (don't block
    trades on transient errors — alert instead via journal).
    """
    try:
        from brackets.okx_futures_bracket import fetch_funding_rate, load_okx_config
    except ImportError:
        return True, "OK (module not importable, skipping)"
    try:
        cfg = load_okx_config()
        fr = fetch_funding_rate(cfg, symbol)
    except Exception as exc:  # noqa: BLE001
        log.warning("H8 funding check: API failed, allowing trade: %s", exc)
        return True, f"OK (API fail-open: {exc})"

    if now_ms is None:
        now_ms = int(time.time() * 1000)
    next_funding = fr["nextFundingTime"]
    diff_ms = next_funding - now_ms
    window_ms = blackout_min * 60 * 1000
    if -window_ms <= diff_ms <= window_ms:
        return False, (
            f"H8 funding blackout: next funding in {diff_ms / 1000 / 60:.1f} min "
            f"({symbol}, window=±{blackout_min}min)"
        )
    return True, "OK"


def _base_of(symbol: str) -> str:
    """Extract base from 'BTC-USDT-SWAP' -> 'BTC'. Handles 'BTC-USDT' too."""
    s = symbol.upper().strip()
    if "-" in s:
        return s.split("-", 1)[0]
    return s


def _rr_and_pct(proposal: dict[str, Any]) -> tuple[float, float]:
    side_raw = str(proposal.get("side", "")).lower()
    is_long = side_raw in ("buy", "long")
    is_short = side_raw in ("sell", "short")
    if not (is_long or is_short):
        return 0.0, 0.0
    entry = float(proposal.get("entry", 0))
    sl = float(proposal.get("stop_loss", 0))
    tp = float(proposal.get("take_profit", 0))
    size = float(proposal.get("position_size", 0))
    capital = float(proposal.get("capital", 0))
    if entry <= 0 or sl <= 0 or tp <= 0 or size <= 0 or capital <= 0:
        return 0.0, 0.0
    if is_long:
        reward = tp - entry
        risk = entry - sl
    else:
        reward = entry - tp
        risk = sl - entry
    if risk <= 0:
        return 0.0, 0.0
    rr = reward / risk
    notional = size * entry
    pct = notional / capital * 100
    return rr, pct


def validate_hard_rules(proposal: dict[str, Any],
                          llm_context: dict[str, Any] | None = None,
                          market_context: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """Apply hard rules. Returns (ok, violations).

    market_context (optional): {rsi_1d, atr_14, current_price} for H1 + H4 checks.
    """
    hard = _skills.get_hard_skills()
    violations: list[str] = []

    # H1: Volatility cap - ATR(14) * 3 > current_price * 5%
    if market_context:
        atr_14 = market_context.get("atr_14")
        current_price = market_context.get("current_price")
        if atr_14 is not None and current_price is not None and current_price > 0:
            if atr_14 * VOLATILITY_CAP_ATR_MULT > current_price * VOLATILITY_CAP_PRICE_PCT:
                violations.append(
                    f"H1 volatility: ATR(14)={atr_14:.2f}*3={atr_14*3:.2f} > "
                    f"price={current_price:.2f}*5%={current_price*0.05:.2f}"
                )

    # H2: News blackout - within +/- 30min of major event
    if market_context:
        nb = market_context.get("news_blackout")
        if nb and nb.get("in_blackout"):
            ev = nb.get("nearest_event", {})
            violations.append(
                f"H2 news blackout: {ev.get('name', '?')} in "
                f"{abs(ev.get('minutes_until', 0))} min (impact={ev.get('impact', '?')})"
            )

    # Core R:R + position size
    rr, pct = _rr_and_pct(proposal)
    if rr == 0.0:
        violations.append("Invalid SL/TP or price values (risk <= 0)")
    else:
        rr_min = float(hard.get("rr_minimum", 1.2))
        if rr < rr_min:
            violations.append(f"R:R = 1:{rr:.2f} < 1:{rr_min} (minimum)")

    if hard.get("stop_loss_required", True) and not proposal.get("stop_loss"):
        violations.append("Stop loss required but missing")
    if hard.get("take_profit_required", True) and not proposal.get("take_profit"):
        violations.append("Take profit required but missing")

    if pct > 0:
        max_pct = float(hard.get("max_position_pct", 0.20)) * 100
        if pct > max_pct:
            violations.append(f"Position = {pct:.1f}% > {max_pct:.0f}% (max notional)")

    # H4: RSI extreme direction restrict
    if market_context and llm_context:
        action = str(llm_context.get("action", "")).lower()
        rsi_1d = market_context.get("rsi_1d")
        if rsi_1d is not None:
            if action == "long" and rsi_1d >= RSI_OVERBOUGHT:
                violations.append(
                    f"H4 RSI: 1d RSI={rsi_1d:.1f} >= {RSI_OVERBOUGHT} (overbought) -> no long"
                )
            if action == "short" and rsi_1d <= RSI_OVERSOLD:
                violations.append(
                    f"H4 RSI: 1d RSI={rsi_1d:.1f} <= {RSI_OVERSOLD} (oversold) -> no short"
                )

    # H6: Confidence threshold (only when LLM context provided)
    if llm_context:
        confidence = llm_context.get("confidence")
        if confidence is not None and confidence < MIN_CONFIDENCE:
            violations.append(
                f"H6 confidence: {confidence:.2f} < {MIN_CONFIDENCE} (minimum)"
            )

    return (len(violations) == 0), violations


def check_reasoning_quality(reasoning: str) -> tuple[bool, str]:
    if not reasoning or not reasoning.strip():
        return False, "Empty reasoning"
    text = reasoning.strip()
    if len(text) < REASONING_MIN_CHARS:
        return False, f"Reasoning too short ({len(text)} chars, need > {REASONING_MIN_CHARS})"
    if REASONING_REQUIRE_SKILL_MENTION:
        soft_skills = _skills.get_soft_skills()
        text_lower = text.lower()
        keywords = []
        for skill_id, desc in soft_skills.items():
            for word in desc.lower().split():
                if len(word) > 4 and word in text_lower:
                    keywords.append(skill_id)
                    break
        if not keywords:
            return False, "Reasoning does not mention any soft skill"
    return True, "OK"


def validate_proposal(proposal: dict[str, Any],
                       llm_context: dict[str, Any] | None = None,
                       market_context: dict[str, Any] | None = None) -> dict[str, Any]:
    ok, violations = validate_hard_rules(proposal, llm_context, market_context)
    rr, pct = _rr_and_pct(proposal)
    result = {
        "ok": ok,
        "violations": violations,
        "rr_ratio": round(rr, 2) if rr > 0 else 0,
        "position_pct": round(pct, 2),
    }
    if llm_context is not None and not ok:
        reasoning = llm_context.get("reasoning", "")
        rq_ok, rq_msg = check_reasoning_quality(reasoning)
        result["reasoning_check"] = {"ok": rq_ok, "msg": rq_msg,
                                       "reasoning_chars": len(reasoning.strip())}
    return result


def validate_futures_hard_rules(proposal: dict[str, Any]) -> tuple[bool, list[str]]:
    """Apply futures-specific hard rules H5, H7, H8.

    Expects ``proposal`` from ``okx_futures_bracket.compute_bracket_futures``
    which already includes:
      - ``symbol``: SWAP symbol (e.g. "BTC-USDT-SWAP")
      - ``leverage``: requested leverage
      - ``entry``: entry price
      - ``liq_price``: computed liquidation price
      - ``side``: "buy" | "sell"

    H5 (leverage) and H7 (liquidation buffer) use the same proposal fields.
    H8 (funding blackout) calls OKX public API for the funding schedule.
    Returns (ok, violations) - same convention as ``validate_hard_rules``.
    """
    violations: list[str] = []
    symbol = str(proposal.get("symbol", ""))

    if not symbol:
        violations.append("H5/H7/H8: missing 'symbol' in proposal")
        return False, violations

    # H5: leverage cap
    leverage = int(proposal.get("leverage", 0))
    ok5, msg5 = check_leverage(symbol, leverage)
    if not ok5:
        violations.append(msg5)

    # H7: liquidation buffer
    entry = float(proposal.get("entry", 0))
    liq_price = float(proposal.get("liq_price", 0))
    if entry > 0 and liq_price > 0:
        ok7, msg7 = check_liquidation_buffer(entry, liq_price, symbol)
        if not ok7:
            violations.append(msg7)
    else:
        violations.append("H7: missing entry/liq_price in proposal")

    # H8: funding blackout
    ok8, msg8 = check_funding_blackout(symbol)
    if not ok8:
        violations.append(msg8)

    return (len(violations) == 0), violations


def validate_full_proposal(
    proposal: dict[str, Any],
    llm_context: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    is_futures: bool = False,
) -> dict[str, Any]:
    """One-shot validator: spot + (if applicable) futures rules.

    Returns dict with ``ok``, ``violations``, ``rr_ratio``, ``position_pct``,
    and (for futures) ``futures_violations`` broken out for downstream logging.
    """
    result = validate_proposal(proposal, llm_context, market_context)
    if is_futures:
        ok_f, violations_f = validate_futures_hard_rules(proposal)
        result["futures_ok"] = ok_f
        result["futures_violations"] = violations_f
        if not ok_f:
            result["ok"] = False
            result["violations"] = result["violations"] + violations_f
    return result

