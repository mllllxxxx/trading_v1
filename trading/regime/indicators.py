"""Technical indicators: S/R levels, Fibonacci, VSA, Candlestick patterns,
Oscillators (MACD, BB, Stochastic), Ichimoku Cloud, Moving Averages,
Economic calendar (H2 news blackout).

Inspired by trading-rules skill:
  S1: Moving Averages (alignment, golden/death cross)
  S2: Support/Resistance + Fibonacci retracement
  S3: Volume Spread Analysis (VSA)
  S4: Candlestick patterns (single + multi-bar)
  S5: Ichimoku Cloud (6 components)
  S6: Oscillators (RSI/MACD/BB/Stochastic)
  H2: News blackout (economic calendar)

All functions take pandas DataFrame with columns: Open, High, Low, Close, Volume.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Path to economic calendar (pre-loaded JSON)
CALENDAR_FILE = Path(__file__).resolve().parent / "economic_calendar.json"
NEWS_BLACKOUT_MINUTES = 30  # +/- 30 min around major events


# ---------------------------------------------------------------------------
# S2: Support / Resistance + Fibonacci
# ---------------------------------------------------------------------------

def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> dict[str, list[float]]:
    """Find swing highs and lows using local extrema.

    Swing high: bar whose High > all neighbors within lookback bars
    Swing low: bar whose Low < all neighbors within lookback bars
    """
    if df is None or len(df) < lookback * 2 + 1:
        return {"swing_highs": [], "swing_lows": []}

    highs = df["High"].values
    lows = df["Low"].values

    swing_highs = []
    swing_lows = []
    for i in range(lookback, len(df) - lookback):
        window_highs = highs[i - lookback:i + lookback + 1]
        window_lows = lows[i - lookback:i + lookback + 1]
        if highs[i] == window_highs.max():
            swing_highs.append(float(highs[i]))
        if lows[i] == window_lows.min():
            swing_lows.append(float(lows[i]))

    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


def find_sr_levels(df: pd.DataFrame, lookback: int = 5,
                    tolerance_pct: float = 0.01) -> dict[str, list[dict[str, Any]]]:
    """Cluster nearby swing points into S/R levels.

    Returns: {resistance: [{price, strength}], support: [{price, strength}]}
    strength = number of original swing points that fell into this cluster
    """
    swings = find_swing_points(df, lookback)
    resistance = _cluster_levels(swings["swing_highs"], tolerance_pct)
    support = _cluster_levels(swings["swing_lows"], tolerance_pct)
    return {"resistance": resistance, "support": support}


def _cluster_levels(prices: list[float], tolerance_pct: float) -> list[dict[str, Any]]:
    if not prices:
        return []
    sorted_p = sorted(prices)
    clusters: list[list[float]] = [[sorted_p[0]]]
    for p in sorted_p[1:]:
        if abs(p - clusters[-1][-1]) / clusters[-1][-1] <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [
        {"price": round(sum(c) / len(c), 2), "strength": len(c)}
        for c in clusters
    ]


def fibonacci_retracement(high: float, low: float) -> dict[str, float]:
    """Compute Fibonacci retracement levels from a swing high-low pair.

    Returns: {0.382, 0.5, 0.618, 0.786} levels.
    """
    diff = high - low
    if diff <= 0:
        return {}
    return {
        "0.382": round(high - diff * 0.382, 2),
        "0.5":   round(high - diff * 0.5, 2),
        "0.618": round(high - diff * 0.618, 2),
        "0.786": round(high - diff * 0.786, 2),
    }


def nearest_sr(df: pd.DataFrame, current_price: float) -> dict[str, Any]:
    """Find nearest support and resistance for current price."""
    levels = find_sr_levels(df)
    sup = min(levels["support"], key=lambda x: abs(x["price"] - current_price),
              default=None) if levels["support"] else None
    res = min(levels["resistance"], key=lambda x: abs(x["price"] - current_price),
              default=None) if levels["resistance"] else None
    return {
        "nearest_support": sup,
        "nearest_resistance": res,
        "price_position_pct": round((current_price - sup["price"]) /
                                      (res["price"] - sup["price"]) * 100, 1)
        if sup and res and res["price"] != sup["price"] else None,
    }


# ---------------------------------------------------------------------------
# S3: Volume Spread Analysis (VSA)
# ---------------------------------------------------------------------------

def vsa_signal(df: pd.DataFrame, lookback: int = 20) -> dict[str, Any]:
    """Classify last bar using VSA principles (Wyckoff-inspired).

    Returns: {
      'vsa': 'buying_climax' | 'selling_climax' | 'stopping_volume' |
             'absorption' | 'no_demand' | 'normal' | 'thin_market',
      'spread': 'wide' | 'narrow',
      'volume': 'high' | 'low' | 'normal',
      'close_position': 'high' | 'mid' | 'low',
      'volume_ratio': current_vol / sma20_vol
    }
    """
    if df is None or len(df) < lookback + 5:
        return {"vsa": "unknown", "spread": "?", "volume": "?", "close_position": "?"}

    last = df.iloc[-1]
    open_p = float(last["Open"])
    high = float(last["High"])
    low = float(last["Low"])
    close = float(last["Close"])
    vol = float(last["Volume"])

    sma_vol = float(df["Volume"].iloc[-lookback:].mean())
    vol_ratio = vol / sma_vol if sma_vol > 0 else 1.0

    spread = high - low
    sma_spread = float((df["High"] - df["Low"]).iloc[-lookback:].mean())
    spread_ratio = spread / sma_spread if sma_spread > 0 else 1.0
    is_wide = spread_ratio > 1.2
    is_narrow = spread_ratio < 0.8

    is_high_vol = vol_ratio > 1.5
    is_low_vol = vol_ratio < 0.5

    if close > open_p:
        bar_type = "up_bar"
    elif close < open_p:
        bar_type = "down_bar"
    else:
        bar_type = "doji_bar"

    if is_wide and is_high_vol:
        if bar_type == "up_bar" and close <= (high + low) / 2:
            vsa = "buying_climax"  # wide + high vol + close low = exhaustion
        elif bar_type == "down_bar" and close >= (high + low) / 2:
            vsa = "selling_climax"  # wide + high vol + close high = strength (?)
        else:
            vsa = "stopping_volume"  # high vol + wide spread, no clear direction
    elif is_narrow and is_high_vol:
        vsa = "absorption"  # narrow + high vol = effort vs result conflict
    elif is_narrow and is_low_vol:
        vsa = "no_demand"
    elif is_low_vol:
        vsa = "thin_market"
    else:
        vsa = "normal"

    close_pos = "high" if close > (high + low) / 2 + (high - low) * 0.1 else \
                "low" if close < (high + low) / 2 - (high - low) * 0.1 else "mid"

    return {
        "vsa": vsa,
        "spread": "wide" if is_wide else ("narrow" if is_narrow else "normal"),
        "volume": "high" if is_high_vol else ("low" if is_low_vol else "normal"),
        "bar_type": bar_type,
        "close_position": close_pos,
        "volume_ratio": round(vol_ratio, 2),
    }


# ---------------------------------------------------------------------------
# S4: Candlestick patterns
# ---------------------------------------------------------------------------

def detect_candlestick(df: pd.DataFrame) -> dict[str, Any]:
    """Detect candlestick patterns on the last bar.

    Returns: {
      'pattern': 'doji' | 'hammer' | 'shooting_star' | 'marubozu' |
                 'spinning_top' | 'pin_bar' | 'engulfing_bull' | 'engulfing_bear' |
                 'morning_star' | 'evening_star' | 'three_soldiers' | 'three_crows' |
                 'inside_bar' | 'outside_bar' | 'none',
      'reliability': 'high' | 'medium' | 'low',
      'direction': 'bullish' | 'bearish' | 'neutral'
    }
    """
    if df is None or len(df) < 3:
        return {"pattern": "none", "reliability": "low", "direction": "neutral"}

    last = df.iloc[-1]
    o = float(last["Open"])
    h = float(last["High"])
    low_price = float(last["Low"])
    c = float(last["Close"])
    body = abs(c - o)
    upper_wick = h - max(c, o)
    lower_wick = min(c, o) - low_price
    total_range = h - low_price

    if total_range < 1e-9:
        return {"pattern": "doji", "reliability": "low", "direction": "neutral"}

    # Single bar patterns
    pattern = "none"
    direction = "neutral"
    reliability = "low"

    body_pct = body / total_range
    upper_pct = upper_wick / total_range
    lower_pct = lower_wick / total_range

    if body_pct < 0.1:
        pattern = "doji"
        direction = "neutral"
        reliability = "low"
    elif lower_pct > 0.6 and body_pct < 0.3:
        pattern = "hammer"
        direction = "bullish"
        reliability = "medium"
    elif upper_pct > 0.6 and body_pct < 0.3:
        pattern = "shooting_star"
        direction = "bearish"
        reliability = "medium"
    elif body_pct > 0.9:
        pattern = "marubozu"
        direction = "bullish" if c > o else "bearish"
        reliability = "high"
    elif body_pct < 0.3 and upper_pct > 0.3 and lower_pct > 0.3:
        pattern = "spinning_top"
        direction = "neutral"
        reliability = "low"
    elif (upper_pct >= 0.6 or lower_pct >= 0.6) and body_pct < 0.4:
        pattern = "pin_bar"
        direction = "bullish" if lower_pct > upper_pct else "bearish"
        reliability = "medium"

    # Multi-bar: engulfing (2 bars)
    if pattern == "none" and len(df) >= 2:
        prev = df.iloc[-2]
        po, pc = float(prev["Open"]), float(prev["Close"])
        prev_body = abs(pc - po)
        if (c > o) != (pc > po) and body > prev_body * 1.05:
            if c > o:
                pattern = "engulfing_bull"
                direction = "bullish"
                reliability = "high"
            else:
                pattern = "engulfing_bear"
                direction = "bearish"
                reliability = "high"

    # Multi-bar: morning/evening star (3 bars)
    if pattern == "none" and len(df) >= 3:
        b1 = df.iloc[-3]
        b2 = df.iloc[-2]
        b1o, b1c = float(b1["Open"]), float(b1["Close"])
        b2o, b2c = float(b2["Open"]), float(b2["Close"])
        b2_body = abs(b2c - b2o)
        if b2_body < abs(b1c - b1o) * 0.3 and body > b2_body * 2:
            if b1c < b1o and c > o:  # bearish + doji + bullish
                pattern = "morning_star"
                direction = "bullish"
                reliability = "high"
            elif b1c > b1o and c < o:
                pattern = "evening_star"
                direction = "bearish"
                reliability = "high"

    # Multi-bar: 3 soldiers/crows
    if pattern == "none" and len(df) >= 3:
        last3 = df.iloc[-3:]
        all_up = all(float(r["Close"]) > float(r["Open"]) for _, r in last3.iterrows())
        all_down = all(float(r["Close"]) < float(r["Open"]) for _, r in last3.iterrows())
        if all_up:
            pattern = "three_soldiers"
            direction = "bullish"
            reliability = "medium"
        elif all_down:
            pattern = "three_crows"
            direction = "bearish"
            reliability = "medium"

    # Inside/outside bar
    if pattern == "none" and len(df) >= 2:
        prev = df.iloc[-2]
        if h <= float(prev["High"]) and low_price >= float(prev["Low"]):
            pattern = "inside_bar"
            direction = "neutral"
            reliability = "low"
        elif h > float(prev["High"]) and low_price < float(prev["Low"]):
            pattern = "outside_bar"
            direction = "neutral"
            reliability = "low"

    return {
        "pattern": pattern,
        "reliability": reliability,
        "direction": direction,
        "body_pct": round(body_pct * 100, 1),
        "upper_wick_pct": round(upper_pct * 100, 1),
        "lower_wick_pct": round(lower_pct * 100, 1),
    }


# ---------------------------------------------------------------------------
# H2: News blackout (economic calendar)
# ---------------------------------------------------------------------------

def check_news_blackout(now_utc: datetime | None = None) -> dict[str, Any]:
    """H2: Check if current time is within +/- 30 min of a major economic event.

    Reads pre-loaded calendar from economic_calendar.json.
    Returns: {in_blackout, next_event, minutes_until, event_name}
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if not CALENDAR_FILE.exists():
        return {"in_blackout": False, "calendar_loaded": False}

    try:
        with CALENDAR_FILE.open() as f:
            cal = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"in_blackout": False, "calendar_loaded": False}

    events = cal.get("events", [])
    in_blackout = False
    nearest_event = None
    nearest_minutes = None

    for ev in events:
        try:
            ev_dt = datetime.strptime(
                f"{ev['date']} {ev['time_utc']}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        diff_minutes = (ev_dt - now_utc).total_seconds() / 60
        if abs(diff_minutes) <= NEWS_BLACKOUT_MINUTES:
            in_blackout = True
            nearest_event = ev
            nearest_minutes = int(diff_minutes)
            break
        if nearest_minutes is None or abs(diff_minutes) < abs(nearest_minutes):
            nearest_minutes = int(diff_minutes)
            nearest_event = ev

    result = {
        "in_blackout": in_blackout,
        "calendar_loaded": True,
        "news_blackout_minutes": NEWS_BLACKOUT_MINUTES,
    }
    if nearest_event:
        result["nearest_event"] = {
            "name": nearest_event.get("name", "?"),
            "date": nearest_event.get("date", "?"),
            "time_utc": nearest_event.get("time_utc", "?"),
            "impact": nearest_event.get("impact", "?"),
            "minutes_until": nearest_minutes,
        }
    return result


# ---------------------------------------------------------------------------
# Driver: full indicator analysis
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """One-shot: S/R + VSA + Candlestick + Oscillators + Ichimoku. Returns dict for LLM brain + dashboard."""
    if df is None or df.empty:
        return {}
    sr = find_sr_levels(df)
    fib = fibonacci_retracement(float(df["High"].max()), float(df["Low"].min()))
    current = float(df["Close"].iloc[-1])
    nearest = nearest_sr(df, current)
    return {
        "support_resistance": sr,
        "nearest": nearest,
        "fibonacci_retracement": fib,
        "vsa": vsa_signal(df),
        "candlestick": detect_candlestick(df),
        "oscillators": compute_oscillators(df),
        "ichimoku": compute_ichimoku(df),
        "moving_averages": compute_moving_averages(df),
        "news_blackout": check_news_blackout(),
    }


# ---------------------------------------------------------------------------
# S6: Oscillators - MACD, Bollinger Bands, Stochastic
# ---------------------------------------------------------------------------

def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> dict[str, Any]:
    """MACD (Moving Average Convergence Divergence).

    Returns: {value, signal, histogram, macd_vs_signal, macd_vs_zero,
              histogram_direction, divergence}
    """
    if close is None or len(close) < slow + signal:
        return {"value": None, "signal": None, "histogram": None}

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    last_macd = float(macd_line.iloc[-1])
    last_signal = float(signal_line.iloc[-1])
    last_hist = float(histogram.iloc[-1])

    # Direction: histogram increasing or decreasing
    if len(histogram) >= 2:
        hist_direction = "rising" if histogram.iloc[-1] > histogram.iloc[-2] else (
                         "falling" if histogram.iloc[-1] < histogram.iloc[-2] else "flat")
    else:
        hist_direction = "flat"

    return {
        "value": round(last_macd, 2),
        "signal": round(last_signal, 2),
        "histogram": round(last_hist, 2),
        "macd_vs_signal": "above" if last_macd > last_signal else "below",
        "macd_vs_zero": "above" if last_macd > 0 else "below",
        "histogram_direction": hist_direction,
    }


def compute_bollinger(close: pd.Series, period: int = 20,
                       std_dev: float = 2.0) -> dict[str, Any]:
    """Bollinger Bands (20/2 default).

    Returns: {upper, middle, lower, bandwidth, percent_b, signal}
    """
    if close is None or len(close) < period:
        return {"upper": None, "middle": None, "lower": None}

    sma = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = sma + std_dev * std
    lower = sma - std_dev * std

    last_close = float(close.iloc[-1])
    last_upper = float(upper.iloc[-1])
    last_middle = float(sma.iloc[-1])
    last_lower = float(lower.iloc[-1])

    bandwidth = (last_upper - last_lower) / last_middle if last_middle > 0 else 0
    range_b = last_upper - last_lower
    percent_b = (last_close - last_lower) / range_b if range_b > 0 else 0.5

    # Signal classification
    if percent_b > 1.0:
        signal = "above_upper"
    elif percent_b > 0.8:
        signal = "near_upper"
    elif percent_b < 0.0:
        signal = "below_lower"
    elif percent_b < 0.2:
        signal = "near_lower"
    else:
        signal = "within_bands"

    # Bandwidth state
    if bandwidth < 0.10:
        bw_state = "squeeze"
    elif bandwidth > 0.40:
        bw_state = "wide"
    else:
        bw_state = "normal"

    return {
        "upper": round(last_upper, 2),
        "middle": round(last_middle, 2),
        "lower": round(last_lower, 2),
        "bandwidth": round(bandwidth, 4),
        "percent_b": round(percent_b, 2),
        "signal": signal,
        "bandwidth_state": bw_state,
    }


def compute_stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                       k_period: int = 14, d_period: int = 3) -> dict[str, Any]:
    """Stochastic Oscillator (14/3/3 default).

    Returns: {k, d, zone, crossover}
    """
    if close is None or len(close) < k_period + d_period:
        return {"k": None, "d": None, "zone": "unknown"}

    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, 1e-10)
    d = k.rolling(d_period).mean()

    last_k = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50.0
    last_d = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50.0

    if last_k > 80:
        zone = "overbought"
    elif last_k < 20:
        zone = "oversold"
    else:
        zone = "neutral"

    # Crossover detection
    crossover = "none"
    if len(k) >= 2 and len(d) >= 2:
        prev_k, prev_d = float(k.iloc[-2]), float(d.iloc[-2])
        if prev_k <= prev_d and last_k > last_d:
            crossover = "bull_cross"
        elif prev_k >= prev_d and last_k < last_d:
            crossover = "bear_cross"

    return {
        "k": round(last_k, 2),
        "d": round(last_d, 2),
        "zone": zone,
        "crossover": crossover,
    }


def compute_oscillators(df: pd.DataFrame) -> dict[str, Any]:
    """S6: All oscillators (RSI is computed in confluence, not here)."""
    if df is None or df.empty:
        return {}
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    macd = compute_macd(close)
    bb = compute_bollinger(close)
    stoch = compute_stochastic(high, low, close)

    # Momentum matrix
    macd_bullish = macd.get("macd_vs_signal") == "above"
    bb_bullish = bb.get("percent_b", 0.5) > 0.5
    if macd_bullish and bb_bullish:
        consensus = "both_bullish"
    elif not macd_bullish and not bb_bullish:
        consensus = "both_bearish"
    elif macd_bullish != bb_bullish:
        consensus = "conflicted"
    else:
        consensus = "neutral"

    return {
        "macd": macd,
        "bollinger": bb,
        "stochastic": stoch,
        "consensus": consensus,
    }


# ---------------------------------------------------------------------------
# S1: Moving Averages (alignment, golden/death cross detection)
# ---------------------------------------------------------------------------

def compute_moving_averages(close_or_df) -> dict[str, Any]:
    """S1: MA alignment + golden/death cross detection.

    Accepts either a Series of close prices OR a DataFrame with 'Close' column.
    Returns: {ma9, ma21, ma50, ma200, alignment, golden_cross, death_cross,
              price_vs_ma200_pct}
    """
    if isinstance(close_or_df, pd.DataFrame):
        close = close_or_df["Close"].astype(float)
    else:
        close = close_or_df.astype(float)

    if close is None or len(close) < 210:
        return {"ma9": None, "ma21": None, "ma50": None, "ma200": None,
                "alignment": "insufficient_data"}

    ma9 = close.ewm(span=9, adjust=False).mean()
    ma21 = close.ewm(span=21, adjust=False).mean()
    ma50 = close.ewm(span=50, adjust=False).mean()
    ma200 = close.ewm(span=200, adjust=False).mean()

    last_close = float(close.iloc[-1])
    last_ma9 = float(ma9.iloc[-1])
    last_ma21 = float(ma21.iloc[-1])
    last_ma50 = float(ma50.iloc[-1])
    last_ma200 = float(ma200.iloc[-1])

    # Alignment
    bullish_align = last_ma9 > last_ma21 > last_ma50
    bearish_align = last_ma9 < last_ma21 < last_ma50
    if bullish_align:
        alignment = "bullish_aligned"
    elif bearish_align:
        alignment = "bearish_aligned"
    elif abs(last_ma9 - last_ma21) / last_ma21 < 0.005:
        alignment = "flat_chop"
    else:
        alignment = "mixed"

    # Golden/Death cross (MA50 vs MA200)
    if len(ma50) >= 2 and len(ma200) >= 2:
        prev_ma50 = float(ma50.iloc[-2])
        prev_ma200 = float(ma200.iloc[-2])
        if prev_ma50 <= prev_ma200 and last_ma50 > last_ma200:
            golden = True
            death = False
        elif prev_ma50 >= prev_ma200 and last_ma50 < last_ma200:
            golden = False
            death = True
        else:
            golden = last_ma50 > last_ma200
            death = last_ma50 < last_ma200
    else:
        golden = death = False

    return {
        "ma9": round(last_ma9, 2),
        "ma21": round(last_ma21, 2),
        "ma50": round(last_ma50, 2),
        "ma200": round(last_ma200, 2),
        "alignment": alignment,
        "golden_cross": golden,
        "death_cross": death,
        "price_vs_ma200_pct": round((last_close - last_ma200) / last_ma200 * 100, 2),
    }


# ---------------------------------------------------------------------------
# S5: Ichimoku Cloud (6 components)
# ---------------------------------------------------------------------------

def compute_ichimoku(df: pd.DataFrame,
                      tenkan: int = 9, kijun: int = 26,
                      senkou_b: int = 52, displacement: int = 26) -> dict[str, Any]:
    """Ichimoku Cloud (5 lines + cloud).

    Returns: {tenkan_sen, kijun_sen, senkou_a, senkou_b, chikou_span,
              price_vs_cloud, cloud_type, cloud_thickness,
              tk_cross, chikou_vs_price, signal}
    """
    if df is None or len(df) < senkou_b + displacement:
        return {"signal": "insufficient_data"}

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    # Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2

    # Kijun-sen (Base Line): (26-period high + 26-period low) / 2
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2

    # Senkou Span A: (Tenkan + Kijun) / 2, displaced forward 26 periods
    senkou_a_raw = (tenkan_sen + kijun_sen) / 2
    senkou_a = senkou_a_raw.shift(displacement)

    # Senkou Span B: (52-period high + 52-period low) / 2, displaced forward 26
    senkou_b = ((high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2).shift(displacement)

    # Chikou Span: Close displaced backward 26 periods
    chikou_span = close.shift(-displacement)

    # Current values
    last_close = float(close.iloc[-1])
    last_tenkan = float(tenkan_sen.iloc[-1])
    last_kijun = float(kijun_sen.iloc[-1])
    last_senkou_a = float(senkou_a.iloc[-1]) if not pd.isna(senkou_a.iloc[-1]) else None
    last_senkou_b = float(senkou_b.iloc[-1]) if not pd.isna(senkou_b.iloc[-1]) else None

    # Price vs Cloud
    if last_senkou_a is not None and last_senkou_b is not None:
        cloud_top = max(last_senkou_a, last_senkou_b)
        cloud_bottom = min(last_senkou_a, last_senkou_b)
        if last_close > cloud_top:
            price_vs_cloud = "above"
        elif last_close < cloud_bottom:
            price_vs_cloud = "below"
        else:
            price_vs_cloud = "inside"
        cloud_type = "bullish" if last_senkou_a > last_senkou_b else "bearish"
        cloud_thickness = abs(last_senkou_a - last_senkou_b)
        # Thick if > 0.5 * ATR(14) approximation
        atr_14 = (high - low).rolling(14).mean().iloc[-1]
        cloud_thick = cloud_thickness > 0.5 * float(atr_14)
    else:
        price_vs_cloud = "unknown"
        cloud_type = "unknown"
        cloud_thickness = 0
        cloud_thick = False

    # TK cross
    if last_tenkan > last_kijun:
        tk_cross = "bullish"
    elif last_tenkan < last_kijun:
        tk_cross = "bearish"
    else:
        tk_cross = "none"

    # Chikou vs price 26 bars ago
    if len(close) > displacement:
        price_26_ago = float(close.iloc[-(displacement + 1)])
        chikou_now = float(close.iloc[-1])
        chikou_vs_price = "above" if chikou_now > price_26_ago else "below"
    else:
        chikou_vs_price = "unknown"

    # Decision matrix (simplified)
    if price_vs_cloud == "above" and tk_cross == "bullish" and chikou_vs_price == "above":
        signal = "STRONG_LONG"
    elif price_vs_cloud == "below" and tk_cross == "bearish" and chikou_vs_price == "below":
        signal = "STRONG_SHORT"
    elif price_vs_cloud == "inside":
        signal = "HOLD_NO_TRADE"
    elif price_vs_cloud == "above" and tk_cross == "bearish":
        signal = "caution_long"
    elif price_vs_cloud == "below" and tk_cross == "bullish":
        signal = "caution_short"
    else:
        signal = "neutral"

    return {
        "tenkan_sen": round(last_tenkan, 2),
        "kijun_sen": round(last_kijun, 2),
        # L4: Use `is not None` instead of truthy check. round(0.0, 2) == 0.0
        # which is falsy → previously returned None for legitimate 0.0 values.
        "senkou_a": round(last_senkou_a, 2) if last_senkou_a is not None else None,
        "senkou_b": round(last_senkou_b, 2) if last_senkou_b is not None else None,
        "chikou_span": round(float(chikou_span.iloc[-1]), 2)
                     if not pd.isna(chikou_span.iloc[-1]) else None,
        "price_vs_cloud": price_vs_cloud,
        "cloud_type": cloud_type,
        "cloud_thickness": round(cloud_thickness, 2),
        "cloud_thick": cloud_thick,
        "tk_cross": tk_cross,
        "chikou_vs_price": chikou_vs_price,
        "signal": signal,
    }
