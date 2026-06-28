"""LLM prompt templates for the trading brain.

Two prompts:
  - SYSTEM: role, hard rules, soft skills, output JSON schema
  - USER: current market state + open positions + recent PnL

Both are deterministic functions of inputs. No LLM magic in prompt building.
"""
from __future__ import annotations

import json
from typing import Any

import skills as _skills


SYSTEM_PROMPT = """\
Trading decision assistant for paper trading on OKX testnet.

## ROLE
- Analyze market state and decide whether to open a new position.
- Output valid JSON: action, confidence, entry, SL, TP, position_size_pct, reasoning.
- Apply soft skills when relevant.
- Strictly obey hard rules (violation = REJECT).

## HARD RULES (validator-enforced; cannot override)
- R:R (reward:risk) must be >= 1:1.2.
- Position size must be <= 20% of capital.
- Stop loss and take profit are REQUIRED.
- H4: If 1d RSI >= 85, NO long. If 1d RSI <= 15, NO short.
- H6: Confidence MUST be >= 0.40 (else output "no_trade").

## SOFT SKILLS (consider when relevant)
{soft_skills}

## POSITION SIZING BY CONFLUENCE COUNT
Aligned timeframes (out of 5: 15m, 1h, 4h, 1d, 1w):
  1 TF aligned = 5% capital (probe)
  2-3 TFs aligned = 10% capital (normal)
  4 TFs aligned = 15% capital (high confidence)
  5/5 TFs aligned = 20% capital (max)
Use position_size_pct accordingly; never exceed 20%.

## OUTPUT FORMAT (JSON only, no surrounding text)
{{
  "action": "long" | "short" | "hold" | "no_trade",
  "symbol": "<SYMBOL>",
  "confidence": <0.0-1.0, required; <0.40 must be "no_trade">,
  "entry": <number>,
  "stop_loss": <number>,
  "take_profit": <number>,
  "position_size_pct": <0-20, per confluence>,
  "reasoning": "<3-5 sentences explaining decision; mention applied soft skills and confluence alignment>"
}}

## NOTES
- "hold" = no new position. Still provide reasoning.
- "no_trade" = low confidence (<0.40) or hard rule violation.
- entry = current price (limit order). SL/TP must be specific numbers.
- position_size_pct is capital percentage (0-20) keyed to confluence count.
- reasoning >= 50 chars; mention which skill(s) you applied.
"""


def build_system_prompt() -> str:
    soft = _skills.get_soft_skills()
    soft_lines = []
    for skill_id, desc in soft.items():
        soft_lines.append(f"- {skill_id}: {desc}")
    return SYSTEM_PROMPT.format(soft_skills="\n".join(soft_lines))


def build_user_prompt(
    symbol: str,
    current_price: float,
    regime: dict[str, Any],
    confluence: dict[str, Any],
    open_positions: list[dict[str, Any]],
    recent_trades: list[dict[str, Any]],
    capital: float,
    daily_pnl: float,
) -> str:
    tf_lines = []
    bullish_count = 0
    bearish_count = 0
    for label in ["15m", "1h", "4h", "1d", "1w"]:
        tf = confluence.get("timeframes", {}).get(label, {})
        if tf:
            tf_lines.append(
                f"  - {label}: trend={tf.get('trend', '?')} momentum={tf.get('momentum', '?')} "
                f"close={tf.get('close', '?')}"
            )
            if tf.get("trend") == "UP" and tf.get("momentum") == "UP":
                bullish_count += 1
            elif tf.get("trend") == "DOWN" and tf.get("momentum") == "DOWN":
                bearish_count += 1
    aligned_tfs = max(bullish_count, bearish_count)
    direction = "LONG" if bullish_count > bearish_count else (
                 "SHORT" if bearish_count > bearish_count else "NEUTRAL")

    pos_lines = []
    for p in open_positions:
        pos_lines.append(
            f"  - {p.get('symbol', symbol)} {p.get('side', '?').upper()} @ {p.get('entry', '?')}, "
            f"SL {p.get('stop_loss', '?')}, TP {p.get('take_profit', '?')}"
        )
    if not pos_lines:
        pos_lines.append("  (none)")

    trade_lines = []
    for t in recent_trades[-5:]:
        trade_lines.append(
            f"  - {t.get('closed_at', '?')[:10]}: {t.get('symbol', '?')} {t.get('side', '?').upper()} "
            f"{t.get('exit_reason', '?')}, PnL ${t.get('pnl_usd', 0):.2f}"
        )
    if not trade_lines:
        trade_lines.append("  (none)")

    rsi_1d = confluence.get("timeframes", {}).get("1d", {}).get("rsi", "?")
    ti = regime.get("technical_indicators", {})

    cb = confluence.get("confluence_breakdown", {})
    breakdown_lines = []
    if cb:
        for k, v in cb.items():
            name = k.replace("_", " ").upper()
            score_val = v.get("score", 0)
            weight_val = v.get("weight", 1.0)
            signal_val = v.get("signal", "unknown")
            score_str = f"{score_val:+d}"
            breakdown_lines.append(f"  * {name} ({weight_val}x): {score_str} ({signal_val})")
        breakdown_str = "\n".join(breakdown_lines)
    else:
        breakdown_str = "  (No 8-category breakdown available)"

    aligned_count = confluence.get("aligned_categories_count", 0)
    suggested_pct = confluence.get("suggested_position_size_pct", 5)

    return f"""\
## Market state
- Symbol: {symbol}
- Current price: ${current_price:.2f}
- Regime: {regime.get('regime', '?')} ({regime.get('regime_description', '')})
- S0 trend: {regime.get('trend', '?')} (the regime name mapped to MTF bias)
- Confluence (flat): {confluence.get('total_score', 0):+d}/5
- Confluence (weighted): {confluence.get('weighted_score', 0):+.2f}/6.2 (Direction 1.3x, Conf 1.0x, Entry 0.8x)
- Direction bias: {confluence.get('direction_bias', '?')} ({confluence.get('bullish_tfs', 0)}L / {confluence.get('bearish_tfs', 0)}S aligned)
- 1d RSI: {rsi_1d}
- ATR ratio (vs 50d avg): {regime.get('indicators', {}).get('atr_ratio', '?')}
- Choppiness: range/net ratio = {regime.get('indicators', {}).get('range_to_net_ratio', '?')}, direction changes (10d) = {regime.get('indicators', {}).get('direction_changes_10d', '?')} (>=5 choppy, AVOID trading)

- Confluence 8-category breakdown (NEW):
{breakdown_str}
- Aligned categories: {aligned_count}/8
- Category-weighted score: {confluence.get('category_weighted_score', 0.0):+.2f}/7.8

## Technical indicators (S2/S3/S4 from trading-rules skill)
- Support levels: {[s['price'] for s in ti.get('support_resistance', {}).get('support', [])[:3]]}
- Resistance levels: {[r['price'] for r in ti.get('support_resistance', {}).get('resistance', [])[:3]]}
- Fibonacci retracement: {ti.get('fibonacci_retracement', {})}
- VSA signal: {ti.get('vsa', {}).get('vsa', '?')} (volume: {ti.get('vsa', {}).get('volume', '?')}, spread: {ti.get('vsa', {}).get('spread', '?')})
- Candlestick: {ti.get('candlestick', {}).get('pattern', '?')} ({ti.get('candlestick', {}).get('direction', '?')}, reliability: {ti.get('candlestick', {}).get('reliability', '?')})

## Oscillators (S6)
- MACD: value={ti.get('oscillators', {}).get('macd', {}).get('value')}, vs signal={ti.get('oscillators', {}).get('macd', {}).get('macd_vs_signal')}, histogram={ti.get('oscillators', {}).get('macd', {}).get('histogram_direction')}
- Bollinger: bandwidth={ti.get('oscillators', {}).get('bollinger', {}).get('bandwidth')}, %B={ti.get('oscillators', {}).get('bollinger', {}).get('percent_b')}, state={ti.get('oscillators', {}).get('bollinger', {}).get('bandwidth_state')}, signal={ti.get('oscillators', {}).get('bollinger', {}).get('signal')}
- Stochastic: %K={ti.get('oscillators', {}).get('stochastic', {}).get('k')}, %D={ti.get('oscillators', {}).get('stochastic', {}).get('d')}, zone={ti.get('oscillators', {}).get('stochastic', {}).get('zone')}
- Consensus: {ti.get('oscillators', {}).get('consensus', '?')}

## Ichimoku Cloud (S5)
- Price vs Cloud: {ti.get('ichimoku', {}).get('price_vs_cloud', '?')}
- Cloud type: {ti.get('ichimoku', {}).get('cloud_type', '?')}
- TK cross: {ti.get('ichimoku', {}).get('tk_cross', '?')}
- Chikou vs price: {ti.get('ichimoku', {}).get('chikou_vs_price', '?')}
- Signal: {ti.get('ichimoku', {}).get('signal', '?')}

## Moving Averages (S1)
- MA alignment: {ti.get('moving_averages', {}).get('alignment', '?')}
- Golden cross: {ti.get('moving_averages', {}).get('golden_cross')}, Death cross: {ti.get('moving_averages', {}).get('death_cross')}
- Price vs MA200: {ti.get('moving_averages', {}).get('price_vs_ma200_pct')}%

## News blackout (H2)
- In blackout: {ti.get('news_blackout', {}).get('in_blackout', False)}
- Nearest event: {ti.get('news_blackout', {}).get('nearest_event', {}).get('name', 'none')} (in {ti.get('news_blackout', {}).get('nearest_event', {}).get('minutes_until', '?')} min)

## Strategy hints for this regime
{chr(10).join(f"  - {k}: {v}" for k, v in regime.get('regime_strategy_hints', {}).items()) if regime.get('regime_strategy_hints') else '  (no specific hints)'}

## Timeframes
{chr(10).join(tf_lines) if tf_lines else '  (no data)'}

## Open positions ({len(open_positions)})
{chr(10).join(pos_lines)}

## Recent closed trades (last 5)
{chr(10).join(trade_lines)}

## Account
- Capital: ${capital:.2f}
- Daily P&L: ${daily_pnl:+.2f}

## Position sizing by confluence (ap dung)
- 1-2 categories aligned = 5% capital (probe)
- 3-4 categories aligned = 10% capital (normal)
- 5-6 categories aligned = 15% capital (high confidence)
- 7-8 categories aligned = 20% capital (max)
- Hien tai: {aligned_count} categories aligned (suggested size: {suggested_pct}% capital)

## Self-verification checklist (TRA LOI trong reasoning)
1. Higher TF (1d, 1w) co cho tin hieu theo huong nao?
2. Co dang convincing yourself vi ly do khong phai market khong? (FOMO, revenge, etc)
3. Trade nay co nguoc huong Higher TF khong?

Dua tren tat ca thong tin tren, hay quyet dinh:
- "long" neu co setup long tot (entry gia current, SL/TP hop ly, size theo confluence)
- "short" neu co setup short tot
- "hold" neu khong nen trade (regime choppy, conflict, etc)
- "no_trade" neu confidence thap (<0.40) hoac hard rule bi vi pham

Ap dung soft skills khi phu hop, dac biet:
- Neu regime = CHOPPY hoac direction_changes >= 5, BAT BUOC "hold" hoac "no_trade"
- Neu range_to_net_ratio > 5, can nhac "hold"
- Neu 1d RSI > 75, tranh "long" (avoid_overbought_long)
- Neu 1d RSI < 25, tranh "short" (avoid_oversold_short)
- Neu ATR ratio > 1.5, giam position_size_pct xuong 50% (high_vol_caution)
- Neu Higher TF nguoc huong, "no_trade" (theo S0 MTF Rule #1)

Output CHI JSON, khong kem text giai thich ngoai JSON.
"""
