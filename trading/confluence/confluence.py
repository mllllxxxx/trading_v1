#!/usr/bin/env python3
"""Multi-timeframe confluence scorer.

Fetches OHLCV for a symbol across 5 timeframes (15m, 1h, 4h, 1d, 1w) and
computes a confluence score. The idea: trade only when the majority of
timeframes agree on direction, which is the classic prop-trader technique
that filters out ~70% of losing entries.

For each timeframe we compute:
  * Trend  : EMA50 > EMA200 ? UP : DOWN
  * Momentum: close > EMA20 ? UP : DOWN
If both agree: +1 (for UP) or -1 (for DOWN). If conflict: 0.

Aggregate across 5 timeframes:
  +4..+5 -> STRONG BUY
  +2..+3 -> MODERATE BUY
  -1..+1 -> NO TRADE  (conflict, mixed, or all neutral)
  -2..-3 -> MODERATE SELL
  -4..-5 -> STRONG SELL

Usage:
  python confluence.py --symbol BTC-USDT
  python confluence.py --symbol ETH-USDT --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Lazy imports so the help text is fast and unit tests can stub modules.


def okx_to_yf(symbol: str) -> str:
    """BTC-USDT -> BTC-USD. yfinance uses -USD, OKX uses -USDT."""
    if "-" not in symbol:
        raise ValueError(f"Bad symbol '{symbol}', expected e.g. BTC-USDT")
    base, quote = symbol.split("-", 1)
    if quote.upper() == "USDT":
        return f"{base}-USD"
    return symbol


def fetch_timeframe(symbol: str, interval: str, period: str) -> "pd.DataFrame":
    """Fetch OHLCV via yfinance. Resample 1h -> 4h if needed."""
    import pandas as pd  # type: ignore
    import yfinance as yf  # type: ignore

    yf_symbol = okx_to_yf(symbol)
    df = yf.download(yf_symbol, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()
    # yfinance returns MultiIndex columns when there's only 1 ticker; flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if interval == "1h" and period.endswith("d") is False:
        # Resample 1h -> 4h
        df = df.resample("4h").agg({
            "Open": "first", "High": "max",
            "Low": "min", "Close": "last", "Volume": "sum",
        }).dropna()

    return df


def score_timeframe(df: "pd.DataFrame") -> dict[str, Any]:
    """Score a single timeframe. Returns dict with direction, components."""
    import pandas as pd  # type: ignore

    if df is None or df.empty or len(df) < 60:
        return {
            "direction": 0,
            "score": 0,
            "trend": "?",
            "momentum": "?",
            "rsi": None,
            "close": None,
            "reason": "insufficient data",
        }

    close = df["Close"].astype(float)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    last_close = float(close.iloc[-1])
    last_ema20 = float(ema20.iloc[-1])
    last_ema50 = float(ema50.iloc[-1])
    last_ema200 = float(ema200.iloc[-1])

    trend = "UP" if last_ema50 > last_ema200 else "DOWN"
    momentum = "UP" if last_close > last_ema20 else "DOWN"

    # Optional: RSI for context
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi_val = float((100 - 100 / (1 + rs)).iloc[-1])
    # M8: Guard NaN RSI — can happen if both gain and loss series are all-zero
    # (price didn't move at all) which gives 0/0 → NaN.
    if math.isnan(rsi_val):
        rsi_val = 50.0  # neutral default

    if trend == "UP" and momentum == "UP":
        direction = 1
        reason = "Trend UP + Momentum UP (confluence)"
    elif trend == "DOWN" and momentum == "DOWN":
        direction = -1
        reason = "Trend DOWN + Momentum DOWN (confluence)"
    else:
        direction = 0
        reason = f"Conflict: Trend {trend}, Momentum {momentum}"

    # Score per TF: 1 if up, -1 if down, 0 if conflict
    score = direction

    return {
        "direction": direction,
        "score": score,
        "trend": trend,
        "momentum": momentum,
        "rsi": round(rsi_val, 1),
        "close": round(last_close, 2),
        "ema20": round(last_ema20, 2),
        "ema50": round(last_ema50, 2),
        "ema200": round(last_ema200, 2),
        "reason": reason,
    }


def determine_action(total: int) -> dict[str, Any]:
    if total >= 4:
        return {"action": "STRONG BUY", "color": "GREEN", "emoji": "[++]",
                "advice": f"{total}/5 TFs bullish - high conviction long setup"}
    if total >= 2:
        return {"action": "MODERATE BUY", "color": "YELLOW", "emoji": "[+]",
                "advice": f"{total}/5 TFs bullish - decent long, smaller size"}
    if total <= -4:
        return {"action": "STRONG SELL", "color": "RED", "emoji": "[--]",
                "advice": f"{abs(total)}/5 TFs bearish - high conviction short setup"}
    if total <= -2:
        return {"action": "MODERATE SELL", "color": "YELLOW", "emoji": "[-]",
                "advice": f"{abs(total)}/5 TFs bearish - decent short, smaller size"}
    return {"action": "NO TRADE", "color": "GREY", "emoji": "[ ]",
            "advice": f"Score {total} - mixed/conflict signals, sit out"}


# Timeframes: (label, yf_interval, yf_period)
TIMEFRAMES = [
    ("15m", "15m", "30d"),
    ("1h",  "1h",  "60d"),
    ("4h",  "1h",  "180d"),  # resampled to 4h
    ("1d",  "1d",  "2y"),
    ("1w",  "1wk", "10y"),
]


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if df is None or df.empty or len(df) < period + 1:
        return 0.0
    try:
        import pandas as pd
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        close = df["Close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return float(atr.iloc[-1])
    except Exception:
        return 0.0

def _score_s0_mtf(timeframes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # S0: MTF alignment - direction bias across 5 timeframes
    weighted_total = 0.0
    for tf in timeframes.values():
        weighted_total += tf.get("score", 0) * tf.get("weight", 1.0)
        
    if weighted_total >= 1.5:
        score = 1
        signal = "bias_long_3tier"
    elif weighted_total <= -1.5:
        score = -1
        signal = "bias_short_3tier"
    else:
        score = 0
        signal = "bias_neutral"
        
    return {
        "score": score,
        "weight": 1.3,
        "signal": signal,
        "detail": {
            "weighted_score": round(weighted_total, 2),
            "bullish": sum(1 for v in timeframes.values() if v.get("score") == 1),
            "bearish": sum(1 for v in timeframes.values() if v.get("score") == -1)
        }
    }

def _score_s1_trend(ti: dict[str, Any]) -> dict[str, Any]:
    # S1: Trend/MA alignment
    ma = ti.get("moving_averages", {})
    align = ma.get("alignment", "mixed")
    if align == "bullish_aligned":
        score = 1
        signal = "ema_bullish_aligned"
    elif align == "bearish_aligned":
        score = -1
        signal = "ema_bearish_aligned"
    else:
        score = 0
        signal = "ema_mixed_or_choppy"
    return {
        "score": score,
        "weight": 1.2,
        "signal": signal,
        "detail": {
            "alignment": align,
            "golden_cross": ma.get("golden_cross", False),
            "death_cross": ma.get("death_cross", False)
        }
    }

def _score_s2_structure(df_1d: pd.DataFrame | None, ti: dict[str, Any]) -> dict[str, Any]:
    # S2: Support / Resistance + Fibonacci
    current_price = 0.0
    if df_1d is not None and not df_1d.empty:
        current_price = float(df_1d["Close"].iloc[-1])
        
    atr = _atr(df_1d, 14)
    threshold = atr * 1.5 if atr > 0 else current_price * 0.015
    
    nearest = ti.get("nearest", {})
    sup = nearest.get("nearest_support")
    res = nearest.get("nearest_resistance")
    
    sup_price = sup.get("price") if sup else None
    res_price = res.get("price") if res else None
    
    score = 0
    signal = "structure_mid_range"
    dist_sup = None
    dist_res = None
    
    if sup_price is not None:
        dist_sup = current_price - sup_price
        if dist_sup <= threshold:
            score = 1
            signal = "near_support_bounce"
            
    if res_price is not None:
        dist_res = res_price - current_price
        if dist_res <= threshold:
            if score == 1:
                score = 0
                signal = "near_both_sr_tight"
            else:
                score = -1
                signal = "near_resistance_reversal"
                
    return {
        "score": score,
        "weight": 1.1,
        "signal": signal,
        "detail": {
            "nearest_support": sup_price,
            "nearest_resistance": res_price,
            "distance_support": round(dist_sup, 2) if dist_sup is not None else None,
            "distance_resistance": round(dist_res, 2) if dist_res is not None else None,
            "atr_14": round(atr, 2)
        }
    }

def _score_s3_volume(ti: dict[str, Any]) -> dict[str, Any]:
    # S3: Volume Spread Analysis (VSA)
    vsa = ti.get("vsa", {})
    vsa_type = vsa.get("vsa", "normal")
    vol_ratio = vsa.get("volume_ratio", 1.0)
    bar_type = vsa.get("bar_type", "neutral")
    
    score = 0
    signal = "volume_normal"
    
    if vol_ratio > 2.2:
        score = 0
        signal = "volume_climax_exhaustion"
    elif vol_ratio > 1.2:
        if bar_type == "up_bar":
            score = 1
            signal = "volume_elevated_bullish"
        elif bar_type == "down_bar":
            score = -1
            signal = "volume_elevated_bearish"
    elif vsa_type == "no_demand":
        score = 0
        signal = "volume_no_demand"
        
    return {
        "score": score,
        "weight": 1.0,
        "signal": signal,
        "detail": {
            "vsa_pattern": vsa_type,
            "volume_ratio": vol_ratio,
            "bar_type": bar_type,
            "spread": vsa.get("spread", "normal")
        }
    }

def _score_s4_candlestick(ti: dict[str, Any]) -> dict[str, Any]:
    # S4: Candlestick patterns
    candle = ti.get("candlestick", {})
    direction = candle.get("direction", "neutral")
    pattern = candle.get("pattern", "none")
    reliability = candle.get("reliability", "low")
    
    score = 0
    signal = "candlestick_neutral"
    
    if direction == "bullish":
        if reliability in ("high", "medium") or pattern in ("hammer", "engulfing_bull", "morning_star"):
            score = 1
            signal = f"bullish_{pattern}"
    elif direction == "bearish":
        if reliability in ("high", "medium") or pattern in ("shooting_star", "engulfing_bear", "evening_star"):
            score = -1
            signal = f"bearish_{pattern}"
            
    return {
        "score": score,
        "weight": 0.8,
        "signal": signal,
        "detail": {
            "pattern": pattern,
            "direction": direction,
            "reliability": reliability
        }
    }

def _score_s5_ichimoku(ti: dict[str, Any]) -> dict[str, Any]:
    # S5: Ichimoku Cloud
    ichimoku = ti.get("ichimoku", {})
    sig = ichimoku.get("signal", "neutral")
    
    score = 0
    signal = "ichimoku_neutral"
    
    if sig == "STRONG_LONG":
        score = 1
        signal = "ichimoku_strong_long"
    elif sig == "STRONG_SHORT":
        score = -1
        signal = "ichimoku_strong_short"
    elif sig == "HOLD_NO_TRADE":
        signal = "ichimoku_inside_cloud_hold"
    elif sig == "caution_long":
        signal = "ichimoku_caution_long"
    elif sig == "caution_short":
        signal = "ichimoku_caution_short"
        
    return {
        "score": score,
        "weight": 1.1,
        "signal": signal,
        "detail": {
            "ichimoku_signal": sig,
            "price_vs_cloud": ichimoku.get("price_vs_cloud", "unknown"),
            "tk_cross": ichimoku.get("tk_cross", "none")
        }
    }

def _score_s6_oscillators(ti: dict[str, Any], rsi_1d: float | None) -> dict[str, Any]:
    # S6: Oscillators
    oscill = ti.get("oscillators", {})
    consensus = oscill.get("consensus", "neutral")
    stoch = oscill.get("stochastic", {})
    stoch_zone = stoch.get("zone", "neutral")
    
    score = 0
    signal = "oscillators_neutral"
    
    rsi = rsi_1d if rsi_1d is not None else 50.0
    
    if rsi >= 55.0 and consensus == "both_bullish":
        score = 1
        signal = "oscillators_bullish"
    elif rsi <= 45.0 and consensus == "both_bearish":
        score = -1
        signal = "oscillators_bearish"
        
    return {
        "score": score,
        "weight": 0.9,
        "signal": signal,
        "detail": {
            "rsi_1d": rsi,
            "oscillator_consensus": consensus,
            "stochastic_zone": stoch_zone,
            "stochastic_crossover": stoch.get("crossover", "none")
        }
    }

def _score_s7_sentiment(news_signal: dict | None = None) -> dict[str, Any]:
    # S7: Sentiment
    score = 0
    signal = "no_news_module"
    bias = "neutral"
    
    if news_signal is not None:
        bias = str(news_signal.get("bias", "neutral")).lower()
        if bias in ("bullish", "positive", "long", "up"):
            score = 1
            signal = "sentiment_bullish"
        elif bias in ("bearish", "negative", "short", "down"):
            score = -1
            signal = "sentiment_bearish"
        else:
            signal = "sentiment_neutral"
            
    return {
        "score": score,
        "weight": 0.7,
        "signal": signal,
        "detail": {
            "bias": bias
        }
    }

def suggested_size_pct(aligned_count: int) -> int:
    if aligned_count <= 2:
        return 5
    elif aligned_count <= 4:
        return 10
    elif aligned_count <= 6:
        return 15
    else:
        return 20

def compute_confluence(symbol: str, news_signal: dict | None = None) -> dict[str, Any]:
    """Run the full MTF confluence analysis. Returns dict for the report.

    Phase B6: 3-tier MTF (Direction / Confirmation / Entry)
    Phase B7: weighted scoring (Direction 1.3x, Confirmation 1.0x, Entry 0.8x)
    """
    # Phase B6: 3-tier mapping for crypto 24/7 (per skill: Direction=4H, Conf=1H, Entry=15m)
    TF_TIER = {
        "1w":  "direction",   # higher TF - bias
        "1d":  "direction",
        "4h":  "direction",
        "1h":  "confirmation",
        "15m": "entry",
    }
    # Phase B7: weights per tier
    TF_WEIGHT = {
        "direction":   1.3,   # S0 says MTF alignment is strongest
        "confirmation": 1.0,
        "entry":        0.8,
    }

    results: dict[str, Any] = {}
    total = 0
    weighted_total = 0.0
    bullish_tfs = 0
    bearish_tfs = 0
    aligned_tfs_list: list[str] = []  # for tier breakdown
    
    df_1d = None
    for label, interval, period in TIMEFRAMES:
        try:
            df = fetch_timeframe(symbol, interval, period)
            score = score_timeframe(df)
            if label == "1d":
                df_1d = df
        except Exception as exc:  # noqa: BLE001
            score = {
                "direction": 0, "score": 0, "trend": "?", "momentum": "?",
                "rsi": None, "close": None, "reason": f"error: {exc}",
            }
        # Tag with tier
        score["tier"] = TF_TIER.get(label, "entry")
        score["weight"] = TF_WEIGHT[score["tier"]]
        results[label] = score
        total += score["score"]
        weighted_total += score["score"] * score["weight"]
        if score["score"] == 1:
            bullish_tfs += 1
            aligned_tfs_list.append(label)
        elif score["score"] == -1:
            bearish_tfs += 1
            aligned_tfs_list.append(label)
        time.sleep(0.3)

    # Direction bias: dominant side
    direction = "long" if bullish_tfs > bearish_tfs else (
                 "short" if bearish_tfs > bullish_tfs else "neutral")

    action = determine_action(total)
    
    # Calculate indicators if df_1d is present
    ti = {}
    if df_1d is not None and not df_1d.empty:
        import sys
        from pathlib import Path
        try:
            import indicators
        except ImportError:
            try:
                regime_dir = Path(__file__).resolve().parent.parent / "regime"
                if str(regime_dir) not in sys.path:
                    sys.path.insert(0, str(regime_dir))
                import indicators
            except Exception:
                indicators = None
        
        if indicators is not None:
            try:
                ti = indicators.compute_indicators(df_1d)
            except Exception:
                ti = {}
                
    # Score categories
    rsi_1d = results.get("1d", {}).get("rsi")
    breakdown = {
        "S0_mtf":       _score_s0_mtf(results),
        "S1_trend":     _score_s1_trend(ti),
        "S2_struct":    _score_s2_structure(df_1d, ti),
        "S3_volume":    _score_s3_volume(ti),
        "S4_candle":    _score_s4_candlestick(ti),
        "S5_ichimoku":  _score_s5_ichimoku(ti),
        "S6_oscill":    _score_s6_oscillators(ti, rsi_1d),
        "S7_sentiment": _score_s7_sentiment(news_signal),
    }
    
    aligned_count = sum(1 for v in breakdown.values() if v["score"] != 0)
    cat_weighted = sum(v["score"] * v["weight"] for v in breakdown.values())

    return {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timeframes": results,
        "total_score": total,
        "weighted_score": round(weighted_total, 2),
        "bullish_tfs": bullish_tfs,
        "bearish_tfs": bearish_tfs,
        "aligned_tfs": aligned_tfs_list,
        "direction_bias": direction,
        "action": action,
        "confluence_breakdown": breakdown,
        "aligned_categories_count": aligned_count,
        "category_weighted_score": round(cat_weighted, 2),
        "suggested_position_size_pct": suggested_size_pct(aligned_count),
    }


def render_text(report: dict[str, Any]) -> str:
    out = []
    out.append("=" * 60)
    out.append(f"MTF CONFLUENCE  -  {report['symbol']}  (3-tier weighted)")
    out.append(f"Timestamp: {report['timestamp']}")
    out.append("=" * 60)
    out.append(f"{'TF':<6} {'Tier':<13} {'Trend':<6} {'Mom':<5} {'RSI':<6} {'Close':<12} {'Score':<6}")
    out.append("-" * 60)
    for label, _, _ in TIMEFRAMES:
        s = report["timeframes"][label]
        rsi_s = f"{s['rsi']}" if s["rsi"] is not None else "?"
        close_s = f"{s['close']}" if s["close"] is not None else "?"
        score_s = {1: "+1", -1: "-1", 0: " 0"}.get(s["score"], "?")
        out.append(
            f"{label:<6} {s.get('tier', '?'):<13} {s['trend']:<6} {s['momentum']:<5} "
            f"{rsi_s:<6} {close_s:<12} {score_s:<6}"
        )
    out.append("-" * 60)
    out.append(f"Flat score:    {report['total_score']:+d}/5  (range -5..+5)")
    out.append(f"Weighted score: {report['weighted_score']:+.2f}/6.2  (Direction 1.3x, Conf 1.0x, Entry 0.8x)")
    out.append(f"Direction bias: {report['direction_bias']} ({report['bullish_tfs']}L / {report['bearish_tfs']}S aligned)")
    
    if "confluence_breakdown" in report:
        out.append("-" * 60)
        out.append("8-Category Confluence Breakdown:")
        out.append("-" * 60)
        for cat, val in report["confluence_breakdown"].items():
            score_str = f"{val['score']:+d}"
            weight_str = f"({val['weight']}x)"
            out.append(f"  {cat:<13} {weight_str:<7} score={score_str:<3} signal={val['signal']}")
        out.append("-" * 60)
        out.append(f"Aligned Categories:       {report['aligned_categories_count']}/8")
        out.append(f"Category-Weighted Score:  {report['category_weighted_score']:+.2f}/7.8")
        out.append(f"Suggested Position Size:  {report['suggested_position_size_pct']}% capital")
        
    a = report["action"]
    out.append("=" * 60)
    out.append(f"{a['emoji']} {a['action']}")
    out.append(f"   {a['advice']}")
    out.append("=" * 60)
    out.append("")
    out.append("Per-TF detail:")
    for label, _, _ in TIMEFRAMES:
        s = report["timeframes"][label]
        out.append(f"  {label}: {s['reason']}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Multi-timeframe confluence scorer (15m, 1h, 4h, 1d, 1w)"
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTC-USDT")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        report = compute_confluence(args.symbol)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
