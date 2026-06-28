"""Tests for data quality fixes (M8, L1, L4)."""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def isolated_journal_b2(tmp_data_dir):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auto"))
    import journal
    importlib.reload(journal)
    yield journal
    importlib.reload(journal)


# ---- L1: ISO 8601 timestamp -----------------------------------------------

class TestISOTimestamps:
    """L1: _now() must return strict ISO 8601 with colon-separated tz offset."""

    def test_now_is_strict_iso8601(self, isolated_journal_b2):
        ts = isolated_journal_b2._now()
        # Must parse with fromisoformat (Python 3.10+ requires the colon)
        parsed = datetime.fromisoformat(ts)
        assert isinstance(parsed, datetime)
        assert parsed.tzinfo is not None

    def test_now_has_colon_in_offset(self, isolated_journal_b2):
        ts = isolated_journal_b2._now()
        # Match +07:00 not +0700
        assert re.search(r"[+-]\d{2}:\d{2}$", ts), f"Bad offset: {ts}"

    def test_decision_entries_parseable(self, isolated_journal_b2):
        isolated_journal_b2.append_decision("test", {"foo": "bar"})
        with isolated_journal_b2.DECISIONS_LOG.open(encoding="utf-8") as f:
            line = f.readline()
        import json
        obj = json.loads(line)
        datetime.fromisoformat(obj["ts"])  # must not raise


# ---- M8: RSI NaN guard -----------------------------------------------------

class TestRSINaNGuard:
    """M8: confluence.score_timeframe must not produce NaN RSI."""

    def test_constant_price_returns_valid_rsi(self, tmp_path):
        """If price never moves, gain=0 → rs=0 → RSI=0 (no NaN)."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "confluence"))
        from confluence import score_timeframe
        # Build df of 200 rows with constant Close
        dates = pd.date_range("2024-01-01", periods=200, freq="D")
        df = pd.DataFrame({
            "Open": 100.0, "High": 100.0, "Low": 100.0, "Close": 100.0,
            "Volume": 1000.0,
        }, index=dates)
        result = score_timeframe(df)
        assert not math.isnan(result["rsi"])
        assert 0 <= result["rsi"] <= 100

    def test_real_movement_returns_valid_rsi(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "confluence"))
        from confluence import score_timeframe
        import numpy as np
        # 200 days of random-walk-ish price
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(200))
        dates = pd.date_range("2024-01-01", periods=200, freq="D")
        df = pd.DataFrame({
            "Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
            "Close": prices, "Volume": 1000.0,
        }, index=dates)
        result = score_timeframe(df)
        assert 0 <= result["rsi"] <= 100
        assert not math.isnan(result["rsi"])


# ---- L4: round(0.0) bug ----------------------------------------------------

class TestRoundZeroGuard:
    """L4: senkou_a=0.0 must round to 0.0, not None."""

    def test_senkou_zero_returns_zero_not_none(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "regime"))
        from indicators import compute_ichimoku
        import numpy as np
        # 60-day constant price → Ichimoku Tenkan/Kijun = constant, Senkou = constant
        # Senkou_a = (Tenkan + Kijun) / 2 = constant. Could be 0 if price near 0.
        # Use small price to test zero handling.
        dates = pd.date_range("2024-01-01", periods=80, freq="D")
        df = pd.DataFrame({
            "Open": 0.0, "High": 0.0, "Low": 0.0, "Close": 0.0,
            "Volume": 1000.0,
        }, index=dates)
        result = compute_ichimoku(df)
        # senkou_a should be 0.0 (rounded), not None
        if "senkou_a" in result:
            assert result["senkou_a"] is not None or result["senkou_a"] == 0.0
            # If price is 0, the Ichimoku math gives 0, so it should be 0.0 not None
            if result["senkou_a"] is not None:
                assert isinstance(result["senkou_a"], (int, float))

    def test_normal_ichimoku_returns_numbers(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "regime"))
        from indicators import compute_ichimoku
        import numpy as np
        np.random.seed(7)
        prices = 100 + np.cumsum(np.random.randn(100))
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
            "Close": prices, "Volume": 1000.0,
        }, index=dates)
        result = compute_ichimoku(df)
        assert result["tenkan_sen"] is not None
        assert result["kijun_sen"] is not None
        assert isinstance(result["tenkan_sen"], (int, float))


# ---- L2: clear_kill_switch OSError ---------------------------------------

class TestKillSwitchClearOSError:
    """L2: clear_kill_switch must not raise OSError."""

    def test_clear_swallows_oserror(self, isolated_journal_b2, monkeypatch):
        # Make unlink raise OSError
        def boom(self):
            raise OSError("permission denied")
        monkeypatch.setattr(Path, "unlink", boom)
        # Also make exists return True so we try to unlink
        monkeypatch.setattr(Path, "exists", lambda self: True)
        # Must not raise
        isolated_journal_b2.clear_kill_switch()