import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from confluence import (
    _score_s0_mtf,
    _score_s1_trend,
    _score_s2_structure,
    _score_s3_volume,
    _score_s4_candlestick,
    _score_s5_ichimoku,
    _score_s6_oscillators,
    _score_s7_sentiment,
    suggested_size_pct,
    compute_confluence
)

def test_s0_mtf_tie():
    timeframes = {
        "15m": {"score": 1, "weight": 0.8},
        "1h": {"score": 1, "weight": 1.0},
        "4h": {"score": -1, "weight": 1.3},
        "1d": {"score": -1, "weight": 1.3},
        "1w": {"score": 0, "weight": 1.3}
    }
    # Weighted: 1*0.8 + 1*1.0 - 1*1.3 - 1*1.3 = 0.8 + 1.0 - 2.6 = -0.8
    res = _score_s0_mtf(timeframes)
    assert res["score"] == 0
    assert res["signal"] == "bias_neutral"

def test_s0_mtf_long_bias():
    timeframes = {
        "15m": {"score": 1, "weight": 0.8},
        "1h": {"score": 1, "weight": 1.0},
        "4h": {"score": 1, "weight": 1.3},
        "1d": {"score": 0, "weight": 1.3},
        "1w": {"score": 0, "weight": 1.3}
    }
    # Weighted: 0.8 + 1.0 + 1.3 = 3.1 >= 1.5
    res = _score_s0_mtf(timeframes)
    assert res["score"] == 1
    assert res["signal"] == "bias_long_3tier"

def test_s1_trend_bullish():
    ti = {
        "moving_averages": {
            "alignment": "bullish_aligned",
            "golden_cross": True,
            "death_cross": False
        }
    }
    res = _score_s1_trend(ti)
    assert res["score"] == 1
    assert res["signal"] == "ema_bullish_aligned"

def test_s1_trend_bearish():
    ti = {
        "moving_averages": {
            "alignment": "bearish_aligned",
            "golden_cross": False,
            "death_cross": True
        }
    }
    res = _score_s1_trend(ti)
    assert res["score"] == -1
    assert res["signal"] == "ema_bearish_aligned"

def test_s1_trend_mixed():
    ti = {
        "moving_averages": {
            "alignment": "mixed",
            "golden_cross": False,
            "death_cross": False
        }
    }
    res = _score_s1_trend(ti)
    assert res["score"] == 0
    assert res["signal"] == "ema_mixed_or_choppy"

def test_s2_struct_at_support():
    df = pd.DataFrame({"Close": [100.0] * 20, "High": [105.0] * 20, "Low": [95.0] * 20})
    # ATR is calculated as 10.0. 1.5 * ATR = 15.0. 
    # nearest_support is at 90.0, current_price is 100.0. 100.0 - 90.0 = 10.0 <= 15.0 (Near support)
    ti = {
        "nearest": {
            "nearest_support": {"price": 90.0},
            "nearest_resistance": {"price": 130.0}
        }
    }
    res = _score_s2_structure(df, ti)
    assert res["score"] == 1
    assert res["signal"] == "near_support_bounce"

def test_s2_struct_at_resistance():
    df = pd.DataFrame({"Close": [100.0] * 20, "High": [105.0] * 20, "Low": [95.0] * 20})
    # ATR = 10.0. 1.5 * ATR = 15.0.
    # nearest_resistance is at 110.0, current_price is 100.0. 110.0 - 100.0 = 10.0 <= 15.0 (Near resistance)
    ti = {
        "nearest": {
            "nearest_support": {"price": 70.0},
            "nearest_resistance": {"price": 110.0}
        }
    }
    res = _score_s2_structure(df, ti)
    assert res["score"] == -1
    assert res["signal"] == "near_resistance_reversal"

def test_s2_struct_midrange():
    df = pd.DataFrame({"Close": [100.0] * 20, "High": [105.0] * 20, "Low": [95.0] * 20})
    ti = {
        "nearest": {
            "nearest_support": {"price": 50.0},
            "nearest_resistance": {"price": 150.0}
        }
    }
    res = _score_s2_structure(df, ti)
    assert res["score"] == 0
    assert res["signal"] == "structure_mid_range"

def test_s3_volume_elevated_bull():
    ti = {
        "vsa": {
            "volume_ratio": 1.5,
            "bar_type": "up_bar",
            "vsa": "normal",
            "spread": "wide"
        }
    }
    res = _score_s3_volume(ti)
    assert res["score"] == 1
    assert res["signal"] == "volume_elevated_bullish"

def test_s3_volume_climax():
    ti = {
        "vsa": {
            "volume_ratio": 2.5,
            "bar_type": "up_bar",
            "vsa": "stopping_volume",
            "spread": "wide"
        }
    }
    res = _score_s3_volume(ti)
    assert res["score"] == 0
    assert res["signal"] == "volume_climax_exhaustion"

def test_s4_candle_engulfing_at_support():
    ti = {
        "candlestick": {
            "direction": "bullish",
            "pattern": "engulfing_bull",
            "reliability": "high"
        }
    }
    res = _score_s4_candlestick(ti)
    assert res["score"] == 1
    assert res["signal"] == "bullish_engulfing_bull"

def test_s4_candle_no_pattern():
    ti = {
        "candlestick": {
            "direction": "neutral",
            "pattern": "none",
            "reliability": "low"
        }
    }
    res = _score_s4_candlestick(ti)
    assert res["score"] == 0
    assert res["signal"] == "candlestick_neutral"

def test_s5_ichimoku_above_cloud_bull():
    ti = {
        "ichimoku": {
            "signal": "STRONG_LONG",
            "price_vs_cloud": "above",
            "tk_cross": "bullish"
        }
    }
    res = _score_s5_ichimoku(ti)
    assert res["score"] == 1
    assert res["signal"] == "ichimoku_strong_long"

def test_s5_ichimoku_in_cloud():
    ti = {
        "ichimoku": {
            "signal": "HOLD_NO_TRADE",
            "price_vs_cloud": "inside",
            "tk_cross": "none"
        }
    }
    res = _score_s5_ichimoku(ti)
    assert res["score"] == 0
    assert res["signal"] == "ichimoku_inside_cloud_hold"

def test_s6_oscill_rsi_bull_macd_up():
    ti = {
        "oscillators": {
            "consensus": "both_bullish",
            "stochastic": {"zone": "neutral", "crossover": "none"}
        }
    }
    res = _score_s6_oscillators(ti, 60.0)
    assert res["score"] == 1
    assert res["signal"] == "oscillators_bullish"

def test_s6_oscill_rsi_neutral():
    ti = {
        "oscillators": {
            "consensus": "both_bullish",
            "stochastic": {"zone": "neutral", "crossover": "none"}
        }
    }
    res = _score_s6_oscillators(ti, 50.0)
    assert res["score"] == 0
    assert res["signal"] == "oscillators_neutral"

def test_s7_sentiment_no_news():
    res = _score_s7_sentiment(None)
    assert res["score"] == 0
    assert res["signal"] == "no_news_module"

def test_s7_sentiment_positive():
    res = _score_s7_sentiment({"bias": "bullish"})
    assert res["score"] == 1
    assert res["signal"] == "sentiment_bullish"

def test_suggested_size_pct():
    assert suggested_size_pct(1) == 5
    assert suggested_size_pct(2) == 5
    assert suggested_size_pct(3) == 10
    assert suggested_size_pct(4) == 10
    assert suggested_size_pct(5) == 15
    assert suggested_size_pct(6) == 15
    assert suggested_size_pct(7) == 20
    assert suggested_size_pct(8) == 20

def test_backward_compat_keys(monkeypatch):
    # Mock fetch_timeframe to return dummy data frames instead of downloading via yfinance
    dummy_df = pd.DataFrame({
        "Open": [100.0] * 210,
        "High": [105.0] * 210,
        "Low": [95.0] * 210,
        "Close": [100.0] * 210,
        "Volume": [1000.0] * 210
    })
    monkeypatch.setattr("confluence.fetch_timeframe", lambda symbol, interval, period: dummy_df)
    
    report = compute_confluence("BTC-USDT")
    
    # Assert Phase B keys
    assert "symbol" in report
    assert "timestamp" in report
    assert "timeframes" in report
    assert "total_score" in report
    assert "weighted_score" in report
    assert "bullish_tfs" in report
    assert "bearish_tfs" in report
    assert "aligned_tfs" in report
    assert "direction_bias" in report
    assert "action" in report
    
    # Assert Phase 2 keys
    assert "confluence_breakdown" in report
    assert "aligned_categories_count" in report
    assert "category_weighted_score" in report
    assert "suggested_position_size_pct" in report
    
    assert len(report["confluence_breakdown"]) == 8
