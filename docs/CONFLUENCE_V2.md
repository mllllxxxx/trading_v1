# Confluence Engine V2 — 8-Category Weighted System

The confluence engine has been expanded from a simple 5-TF EMA count to a multi-dimensional 8-category weighted scoring system. This document describes the output schema, category weights, and position sizing lookups.

## 1. Categories & Weights

The engine evaluates 8 independent categories (mapping to soft rules S0-S7):

| Category | Mapping | Weight | Description |
| --- | --- | --- | --- |
| `S0_mtf` | Multi-Timeframe Alignment | 1.3x | Directional consensus across 15m, 1h, 4h, 1d, 1w timeframes. |
| `S1_trend` | Moving Averages | 1.2x | EMA9 / EMA21 / EMA50 alignment on the daily timeframe. |
| `S2_struct` | Support / Resistance | 1.1x | Proximity of current price to swing support/resistance levels. |
| `S3_volume` | Volume Spread Analysis | 1.0x | Relative volume ratio vs SMA20 and spread analysis. |
| `S4_candle` | Candlestick Patterns | 0.8x | Presence of bullish/bearish reversal patterns (e.g. Engulfing, Morning Star, Hammer). |
| `S5_ichimoku` | Ichimoku Cloud | 1.1x | Price position relative to cloud, Tenkan/Kijun cross, and Chikou span. |
| `S6_oscill` | Oscillators | 0.9x | RSI zone consensus and MACD histogram momentum direction. |
| `S7_sentiment` | Sentiment | 0.7x | Macro news / event sentiment score (currently default 0 placeholder). |

Each category scorer returns a stateless decision dict:
* `score`: `+1` (bullish), `-1` (bearish), or `0` (neutral).
* `signal`: Short string describing the active signal.
* `detail`: Dictionary containing raw metrics (e.g. specific MA values, distance to support/resistance, RSI values).

## 2. Dynamic Sizing Lookup

The bot sizing per trade is dynamically scaled based on the number of aligned categories (where `|score| == 1`):

* **1-2 Categories**: 5% of total capital (probe size)
* **3-4 Categories**: 10% of total capital (normal size)
* **5-6 Categories**: 15% of total capital (high confidence size)
* **7-8 Categories**: 20% of total capital (max size)

This recommended size is output under `suggested_position_size_pct` and parsed by the bot scheduler and LLM user prompts.

## 3. Schema Specification

The returned JSON from `compute_confluence()` contains all legacy Phase B keys to ensure full backward compatibility, plus new category details:

```json
{
  "symbol": "BTC-USDT",
  "timestamp": "2026-06-25T20:46:57.720345+00:00",
  "timeframes": { ... },
  "total_score": -4,
  "weighted_score": -4.4,
  "bullish_tfs": 0,
  "bearish_tfs": 4,
  "aligned_tfs": ["15m", "1h", "4h", "1d"],
  "direction_bias": "short",
  "action": { "action": "STRONG SELL", "color": "RED", ... },
  
  "confluence_breakdown": {
    "S0_mtf": { "score": -1, "weight": 1.3, "signal": "bias_short_3tier", "detail": { } },
    "S1_trend": { "score": -1, "weight": 1.2, "signal": "ema_bearish_aligned", "detail": { } },
    "S2_struct": { "score": 0, "weight": 1.1, "signal": "structure_mid_range", "detail": { } },
    ...
  },
  "aligned_categories_count": 6,
  "category_weighted_score": -4.3,
  "suggested_position_size_pct": 15
}
```
