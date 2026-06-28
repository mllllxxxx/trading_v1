#!/usr/bin/env python3
"""Market regime detector.

Classifies the current market regime for a symbol into one of:
  * TRENDING_UP   - sustained uptrend
  * TRENDING_DOWN - sustained downtrend
  * RANGING       - mean-reverting / sideways
  * HIGH_VOLATILITY - elevated volatility regime
  * MIXED         - signals conflict, sit out

Indicators:
  * Hurst exponent (R/S method)        - trending vs mean-reverting
  * ADX (Average Directional Index)   - trend strength
  * ATR ratio (current vs 50-day MA)   - volatility regime
  * EMA50 slope (5-day change)         - trend direction

For each regime we recommend which alphas from the Vibe-Trading zoo are
likely to work. The point: avoid using a momentum alpha in a ranging
market, or a mean-reversion alpha in a strong trend.

Usage:
  python regime.py --symbol BTC-USDT
  python regime.py --symbol ETH-USDT --period 1y --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Phase C: import indicators (S/R, VSA, candlestick)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicators  # type: ignore

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def okx_to_yf(symbol: str) -> str:
    if "-" not in symbol:
        raise ValueError(f"Bad symbol '{symbol}', expected e.g. BTC-USDT")
    base, quote = symbol.split("-", 1)
    return f"{base}-USD" if quote.upper() == "USDT" else symbol


def fetch_daily(symbol: str, period: str) -> pd.DataFrame:
    import yfinance as yf  # type: ignore
    yf_sym = okx_to_yf(symbol)
    df = yf.download(yf_sym, period=period, interval="1d",
                     progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data for {yf_sym} (period={period})")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna()


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def hurst_exponent(close: pd.Series, max_lag: int = 100) -> float:
    """Hurst via R/S (rescaled range). H > 0.5 = trending, < 0.5 = mean-revert."""
    ts = close.dropna().values
    n = len(ts)
    if n < max_lag * 2:
        max_lag = n // 4
    if max_lag < 8:
        return 0.5  # not enough data; default to random walk

    lags = np.unique(np.geomspace(4, max_lag, num=20).astype(int))
    log_lags = []
    log_rs = []
    for lag in lags:
        # walk through series in non-overlapping chunks of length `lag`
        n_chunks = n // lag
        if n_chunks < 2:
            continue
        rs_values = []
        for i in range(n_chunks):
            chunk = ts[i * lag:(i + 1) * lag]
            mean = chunk.mean()
            cumdev = np.cumsum(chunk - mean)
            R = cumdev.max() - cumdev.min()
            S = chunk.std(ddof=0)
            if S > 0:
                rs_values.append(R / S)
        if rs_values:
            log_lags.append(math.log(lag))
            log_rs.append(math.log(np.mean(rs_values)))

    if len(log_lags) < 3:
        return 0.5

    slope, _ = np.polyfit(log_lags, log_rs, 1)
    return float(max(0.0, min(1.0, slope)))


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = 14) -> float:
    """ADX (Average Directional Index) - trend strength 0-100."""
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    val = float(adx.iloc[-1])
    if math.isnan(val):
        return 0.0
    return val


def compute_atr_ratio(high: pd.Series, low: pd.Series, close: pd.Series,
                      period: int = 14, baseline: int = 50) -> tuple[float, float]:
    """ATR(14) / SMA(ATR(14), 50). > 1.5 = elevated vol, < 0.7 = quiet.

    Returns: (atr_ratio, atr_14_value)
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    baseline_atr = atr.rolling(baseline).mean()
    atr_14 = float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0
    if baseline_atr.iloc[-1] == 0 or pd.isna(baseline_atr.iloc[-1]):
        return 1.0, atr_14
    return float(atr.iloc[-1] / baseline_atr.iloc[-1]), atr_14


def compute_ema_slope(close: pd.Series, span: int = 50, lookback: int = 5) -> float:
    """Pct change of EMA(span) over the last `lookback` bars."""
    ema = close.ewm(span=span, adjust=False).mean()
    if len(ema) < lookback + span:
        return 0.0
    cur = float(ema.iloc[-1])
    prev = float(ema.iloc[-1 - lookback])
    if prev == 0:
        return 0.0
    return (cur - prev) / prev * 100.0


# ---------------------------------------------------------------------------
# Regime classification
# ---------------------------------------------------------------------------

REGIME_ALPHAS: dict[str, list[str]] = {
    "TRENDING_UP": [
        "academic_carhart_mom",
        "academic_mkt_rf",
        "alpha101_001", "alpha101_006",
    ],
    "TRENDING_DOWN": [
        "academic_carhart_mom",  # inverted for short
        "alpha101_001",
    ],
    "RANGING": [
        "alpha101_reversal_3",
        "alpha101_reversal_5",
        "academic_cma",
    ],
    "HIGH_VOLATILITY": [
        "academic_cma",  # defensive
    ],
    "MIXED": [
        "academic_hml",  # value
    ],
    "CHOPPY": [],  # NO TRADE - whipsaw kills stops
}

REGIME_DESCRIPTIONS: dict[str, str] = {
    "TRENDING_UP":    "Sustained uptrend - momentum alphas likely to work",
    "TRENDING_DOWN":  "Sustained downtrend - inverse momentum / short only",
    "RANGING":        "Sideways - mean-reversion alphas likely to work",
    "HIGH_VOLATILITY": "Elevated volatility - reduce size or use defensive alphas",
    "MIXED":          "Conflicting signals - sit out or use defensive alphas",
    "CHOPPY":         "Whipsaw market - NO TRADE (stops get hunted)",
}

# Strategy hints per regime - tells LLM which indicators to use
REGIME_STRATEGY_HINTS: dict[str, dict[str, str]] = {
    "TRENDING_UP": {
        "indicators": "MA cross (EMA 20/50), Ichimoku cloud, momentum oscillators",
        "approach": "Trade the trend, buy pullbacks, trail stop loss",
        "avoid": "Counter-trend reversals, mean-reversion setups",
    },
    "TRENDING_DOWN": {
        "indicators": "MA cross (EMA 20/50), Ichimoku cloud, momentum oscillators",
        "approach": "Short rallies, trail stop loss, or stay flat",
        "avoid": "Bottom-fishing, mean-reversion setups",
    },
    "RANGING": {
        "indicators": "Support/Resistance, Bollinger Bands, RSI (30/70)",
        "approach": "Mean-reversion - buy at support, sell at resistance",
        "avoid": "Breakout trades (false breakouts common), trend-following",
    },
    "HIGH_VOLATILITY": {
        "indicators": "ATR (widen stops), VSA (Volume Spread Analysis)",
        "approach": "Reduce position size 50%, widen stops, fewer trades",
        "avoid": "Tight stops (will get triggered), large positions",
    },
    "MIXED": {
        "indicators": "Wait for clearer signals",
        "approach": "Stay flat or use very small defensive positions",
        "avoid": "New entries, increasing exposure",
    },
    "CHOPPY": {
        "indicators": "No reliable indicator - market has no edge",
        "approach": "NO TRADE. Wait for trend to emerge or regime to clarify",
        "avoid": "All entries - this is a stop-hunting market",
    },
}


def compute_choppiness(close: pd.Series, period: int = 14) -> dict[str, float]:
    """Detect choppy market via two methods.

    Method 1: Direction changes in last N daily bars (>= 5 = whipsaw)
    Method 2: Range/net-change ratio (price oscillates a lot but ends where it started)

    Returns: {direction_changes, range_to_net_ratio, is_choppy}
    """
    if len(close) < period + 1:
        return {"direction_changes": 0, "range_to_net_ratio": 0.0, "is_choppy": False}

    # Method 1: count direction changes
    lookback = min(10, len(close) - 1)
    daily_returns = close.pct_change().iloc[-lookback:]
    direction_changes = int((daily_returns * daily_returns.shift(1) < 0).sum())

    # Method 2: range / net change
    window = close.iloc[-period:]
    price_range = float(window.max() - window.min())
    net_change = abs(float(window.iloc[-1] - window.iloc[0]))
    # Avoid div by zero
    if net_change < 1e-6:
        # Price ended at start, but range > 0 = perfectly choppy
        range_ratio = 100.0 if price_range > 1e-6 else 0.0
    else:
        # If range is 5x the net change, market oscillated a lot
        range_ratio = price_range / net_change

    # Choppy = either many direction changes OR high range/net ratio
    is_choppy = direction_changes >= 5 or range_ratio >= 5.0

    return {
        "direction_changes": direction_changes,
        "range_to_net_ratio": round(range_ratio, 2),
        "is_choppy": is_choppy,
    }


def classify(hurst: float, adx: float, atr_ratio: float,
             ema_slope: float, choppy_info: dict[str, Any] | None = None) -> str:
    """Priority: HIGH_VOLATILITY > CHOPPY > TRENDING > RANGING > MIXED.

    CHOPPY detection: either Choppiness Index > 61.8 or 5+ direction changes in 10 days.
    """
    if atr_ratio > 1.5:
        return "HIGH_VOLATILITY"
    if choppy_info and choppy_info.get("is_choppy", False):
        return "CHOPPY"
    if hurst > 0.55 and adx > 25:
        return "TRENDING_UP" if ema_slope > 0 else "TRENDING_DOWN"
    if hurst < 0.45:
        return "RANGING"
    return "MIXED"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def detect_regime(symbol: str, period: str = "2y") -> dict[str, Any]:
    """M4: Wrap individual indicator computations in try/except so one bad
    data point doesn't crash the whole regime detection. Falls back to
    sensible defaults (mixed regime, neutral indicators).
    """
    df = fetch_daily(symbol, period)
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    # M4: Suppress numpy warnings (polyfit on degenerate data) and fall back
    # to defaults if individual indicators raise.
    import warnings
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        try:
            hurst = hurst_exponent(close)
        except Exception:  # noqa: BLE001
            hurst = 0.5
        try:
            adx = compute_adx(high, low, close)
        except Exception:  # noqa: BLE001
            adx = 0.0
        try:
            atr_ratio, atr_14 = compute_atr_ratio(high, low, close)
        except Exception:  # noqa: BLE001
            atr_ratio, atr_14 = 1.0, 0.0
        try:
            ema_slope = compute_ema_slope(close)
        except Exception:  # noqa: BLE001
            ema_slope = 0.0
        try:
            choppy = compute_choppiness(close)
        except Exception:  # noqa: BLE001
            choppy = {"direction_changes": 0, "range_to_net_ratio": 0.0,
                      "is_choppy": False}

    regime = classify(hurst, adx, atr_ratio, ema_slope, choppy)

    # Phase B8: also output S0 trend (uptrend/downtrend/range/chop)
    if regime == "TRENDING_UP":
        trend = "uptrend"
    elif regime == "TRENDING_DOWN":
        trend = "downtrend"
    elif regime == "RANGING":
        trend = "range"
    elif regime == "CHOPPY":
        trend = "chop"
    elif regime == "HIGH_VOLATILITY":
        trend = "volatile"  # S0 doesn't have this directly
    else:
        trend = "mixed"

    # M4: technical_indicators also wrapped to never crash regime detection.
    try:
        tech = indicators.compute_indicators(df)
    except Exception:  # noqa: BLE001
        tech = {}

    return {
        "symbol": symbol,
        "period": period,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "close": round(float(close.iloc[-1]), 2),
        "indicators": {
            "hurst_exponent": round(hurst, 3),
            "adx": round(adx, 1),
            "atr_ratio": round(atr_ratio, 2),
            "atr_14": round(atr_14, 2),
            "ema50_slope_pct_5d": round(ema_slope, 2),
            "range_to_net_ratio": choppy["range_to_net_ratio"],
            "direction_changes_10d": choppy["direction_changes"],
        },
        "regime": regime,
        "trend": trend,
        "regime_description": REGIME_DESCRIPTIONS[regime],
        "regime_strategy_hints": REGIME_STRATEGY_HINTS.get(regime, {}),
        "recommended_alphas": REGIME_ALPHAS[regime],
        "technical_indicators": tech,
    }


def render_text(report: dict[str, Any]) -> str:
    ind = report["indicators"]
    regime = report["regime"]
    out = []
    out.append("=" * 60)
    out.append(f"MARKET REGIME  -  {report['symbol']}")
    out.append(f"Period: {report['period']}    Close: ${report['close']}")
    out.append("=" * 60)
    out.append("Indicators:")
    out.append(f"  Hurst exponent  : {ind['hurst_exponent']:.3f}  "
               f"({'>0.5 trending' if ind['hurst_exponent'] > 0.5 else '<0.5 mean-revert' if ind['hurst_exponent'] < 0.5 else '0.5 random walk'})")
    out.append(f"  ADX             : {ind['adx']:.1f}  "
               f"({'strong trend' if ind['adx'] > 25 else 'weak/no trend'})")
    out.append(f"  ATR ratio       : {ind['atr_ratio']:.2f}  "
               f"({'elevated' if ind['atr_ratio'] > 1.5 else 'low' if ind['atr_ratio'] < 0.7 else 'normal'})")
    out.append(f"  EMA50 slope(5d) : {ind['ema50_slope_pct_5d']:+.2f}%")
    out.append("-" * 60)
    out.append(f"REGIME: {regime}")
    out.append(f"  {report['regime_description']}")
    out.append("-" * 60)
    out.append("Recommended alphas (run `vibe-trading alpha bench` on these):")
    for a in report["recommended_alphas"]:
        out.append(f"  - {a}")
    out.append("=" * 60)
    out.append("")
    out.append("Usage tip:")
    out.append("  vibe-trading alpha bench --alpha " + report["recommended_alphas"][0] +
               " --universe equity_us --period 2020-2025")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Market regime detector with alpha recommendations"
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTC-USDT")
    parser.add_argument("--period", default="2y",
                        help="yfinance period (default 2y)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        report = detect_regime(args.symbol, args.period)
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
