"""Tests for scheduler + brain resilience (M3, M5, M6, L3, L6, M7)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def isolated_b2(tmp_data_dir, monkeypatch):
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auto"))
    for stub in ["ccxt", "openai"]:
        sys.modules.setdefault(stub, MagicMock())
    import journal
    importlib.reload(journal)
    import scheduler
    importlib.reload(scheduler)
    import brain
    importlib.reload(brain)
    yield {"scheduler": scheduler, "journal": journal, "brain": brain}


# ---- M6: runtime config reload --------------------------------------------

class TestRuntimeConfigReload:
    """M6: env vars re-read each cycle."""

    def test_reload_picks_up_new_capital(self, isolated_b2, monkeypatch):
        s = isolated_b2["scheduler"]
        monkeypatch.setenv("AUTO_CAPITAL", "50000")
        cfg = s._runtime()
        assert cfg.capital == 50000.0

    def test_reload_picks_up_daily_loss_cap(self, isolated_b2, monkeypatch):
        s = isolated_b2["scheduler"]
        monkeypatch.setenv("AUTO_DAILY_LOSS_CAP_PCT", "0.10")
        cfg = s._runtime()
        assert cfg.daily_loss_cap_pct == 0.10

    def test_reload_uses_defaults(self, isolated_b2, monkeypatch):
        monkeypatch.delenv("AUTO_CAPITAL", raising=False)
        monkeypatch.delenv("AUTO_DAILY_LOSS_CAP_PCT", raising=False)
        s = isolated_b2["scheduler"]
        cfg = s._runtime()
        assert cfg.capital == 10000.0  # default
        assert cfg.daily_loss_cap_pct == 0.03  # default

    def test_runtime_config_snapshot_isolated(self, isolated_b2, monkeypatch):
        """Mutating one snapshot doesn't affect another."""
        s = isolated_b2["scheduler"]
        c1 = s._runtime()
        c2 = s._runtime()
        c1.capital = 999.0
        assert c2.capital != 999.0


# ---- M5: entry freshness check -------------------------------------------

class TestEntryFreshness:
    """M5: LLM entry too far from current_price → skip."""

    def _setup_scheduler_state(self, s, llm_entry: float, current_price: float):
        """Patch _run_confluence, _run_regime, and brain.call_brain."""
        s.journal.ensure_dirs()
        conf = {"total_score": 3, "timeframes": {}}
        reg = {"regime": "TRENDING_UP", "close": current_price,
               "indicators": {"atr_14": 100}, "technical_indicators": {}}
        llm_dec = {"action": "long", "entry": llm_entry,
                   "stop_loss": current_price * 0.985,
                   "take_profit": current_price * 1.030,
                   "position_size_pct": 10, "confidence": 0.8,
                   "reasoning": "test reasoning with at least 50 chars"}
        return patch.multiple(s,
            _run_confluence=MagicMock(return_value=conf),
            _run_regime=MagicMock(return_value=reg),
            _brain_call=MagicMock(return_value=llm_dec),
        )

    def test_entry_within_5pct_accepted(self, isolated_b2, monkeypatch):
        s = isolated_b2["scheduler"]
        s.journal.ensure_dirs()
        current_price = 100.0
        llm_entry = 102.0  # 2% drift
        conf = {"total_score": 3, "timeframes": {}}
        reg = {"regime": "TRENDING_UP", "close": current_price,
               "indicators": {"atr_14": 100}, "technical_indicators": {}}
        llm_dec = {"action": "long", "entry": llm_entry,
                   "stop_loss": 98.5, "take_profit": 103.0,
                   "position_size_pct": 10, "confidence": 0.8,
                   "reasoning": "test reasoning with at least 50 chars"}

        # Patch journal.append_decision to capture calls
        appended = []
        def fake_append(decision_type, payload):
            appended.append((decision_type, payload))
        with patch.object(s, "_run_confluence", return_value=conf), \
             patch.object(s, "_run_regime", return_value=reg), \
             patch.object(s._brain, "call_brain", return_value=llm_dec), \
             patch.object(s, "_place_bracket_via_script",
                          return_value={"ok": False, "error": "skip bracket for test"}), \
             patch.object(s.journal, "append_decision", side_effect=fake_append):
            s.run_once_symbol("BTC-USDT")
        # Skip happened due to place_failed, not stale_llm_entry
        skip_reasons = [p.get("reason") for _, p in appended if p.get("reason")]
        assert "stale_llm_entry" not in skip_reasons

    def test_entry_too_far_skipped(self, isolated_b2):
        s = isolated_b2["scheduler"]
        s.journal.ensure_dirs()
        current_price = 100.0
        llm_entry = 200.0  # 100% drift — way over 5%
        conf = {"total_score": 3, "timeframes": {}}
        reg = {"regime": "TRENDING_UP", "close": current_price,
               "indicators": {"atr_14": 100}, "technical_indicators": {}}
        llm_dec = {"action": "long", "entry": llm_entry,
                   "stop_loss": 98.5, "take_profit": 103.0,
                   "position_size_pct": 10, "confidence": 0.8,
                   "reasoning": "test reasoning with at least 50 chars"}

        appended = []
        def fake_append(decision_type, payload):
            appended.append((decision_type, payload))
        with patch.object(s, "_run_confluence", return_value=conf), \
             patch.object(s, "_run_regime", return_value=reg), \
             patch.object(s._brain, "call_brain", return_value=llm_dec), \
             patch.object(s.journal, "append_decision", side_effect=fake_append):
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [p.get("reason") for dt, p in appended
                        if dt == "skip" and p.get("reason") == "stale_llm_entry"]
        assert "stale_llm_entry" in skip_reasons


# ---- M3: specific exception types -----------------------------------------

class TestSpecificExceptions:
    """M3: scheduler distinguishes timeout/network errors from unexpected."""

    def test_confluence_timeout_logged_as_confluence_error(self, isolated_b2):
        import subprocess
        s = isolated_b2["scheduler"]
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence",
                          side_effect=subprocess.TimeoutExpired("cmd", 180)), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.JournalCorruptError = s.journal.JournalCorruptError
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason") == "confluence_error"
        ]
        assert "confluence_error" in skip_reasons

    def test_confluence_json_decode_logged_as_confluence_error(self, isolated_b2):
        s = isolated_b2["scheduler"]
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence",
                          side_effect=json.JSONDecodeError("test", "doc", 0)), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.JournalCorruptError = s.journal.JournalCorruptError
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason") == "confluence_error"
        ]
        assert "confluence_error" in skip_reasons

    def test_unexpected_confluence_exception_logged_as_error(self, isolated_b2):
        """Regression: bare except Exception now logs as 'error' not 'skip'."""
        s = isolated_b2["scheduler"]
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence",
                          side_effect=ValueError("weird internal error")), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.JournalCorruptError = s.journal.JournalCorruptError
            s.run_once_symbol("BTC-USDT")
        # ValueError is not in (TimeoutExpired, RuntimeError, JSONDecodeError),
        # so it falls through to the catch-all "error" decision.
        error_decs = [
            c.args[1] for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "error" and c.args[1].get("where") == "confluence_unexpected"
        ]
        assert len(error_decs) == 1


# ---- L3: brain max_tokens parameter ---------------------------------------

class TestBrainMaxTokensParam:
    """L3: max_tokens now overridable per call."""

    def test_call_brain_accepts_max_tokens(self, isolated_b2):
        b = isolated_b2["brain"]
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"action":"hold","symbol":"BTC-USDT","reasoning":"r","confidence":0.5}'))]
        )
        with patch.object(b, "_get_client", return_value=client):
            b.call_brain("sys", "user", max_tokens=200)
        # max_tokens=200 should appear in the kwargs
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 200

    def test_call_brain_default_max_tokens(self, isolated_b2):
        b = isolated_b2["brain"]
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"action":"hold","symbol":"BTC-USDT","reasoning":"r","confidence":0.5}'))]
        )
        with patch.object(b, "_get_client", return_value=client):
            b.call_brain("sys", "user")
        call_kwargs = client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == b.DEFAULT_MAX_TOKENS


# ---- L6: LLM retry with exponential backoff ------------------------------

class TestLLMRetry:
    """L6: transient errors retried with exponential backoff."""

    def test_transient_error_retried(self, isolated_b2):
        b = isolated_b2["brain"]
        client = MagicMock()
        # First call: ConnectionError. Second call: success.
        success_resp = MagicMock(choices=[MagicMock(message=MagicMock(
            content='{"action":"hold","symbol":"BTC-USDT","reasoning":"r","confidence":0.5}'))])
        client.chat.completions.create.side_effect = [
            ConnectionError("network down"),
            success_resp,
        ]
        with patch.object(b, "_get_client", return_value=client), \
             patch.object(b.time, "sleep") as mock_sleep:
            result = b.call_brain("sys", "user")
        # Should have retried with 1s backoff
        assert mock_sleep.called
        assert mock_sleep.call_args.args[0] == 1
        assert result["action"] == "hold"

    def test_three_transient_failures_raises(self, isolated_b2):
        b = isolated_b2["brain"]
        client = MagicMock()
        client.chat.completions.create.side_effect = ConnectionError("perma-down")
        with patch.object(b, "_get_client", return_value=client), \
             patch.object(b.time, "sleep"):
            with pytest.raises(b.BrainError, match="after 3 attempts"):
                b.call_brain("sys", "user")

    def test_auth_error_no_retry(self, isolated_b2):
        """Auth errors propagate immediately without retry."""
        b = isolated_b2["brain"]
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("Invalid API key (401)")
        with patch.object(b, "_get_client", return_value=client):
            with pytest.raises(b.BrainError, match="auth/config error"):
                b.call_brain("sys", "user")
        assert client.chat.completions.create.call_count == 1


# ---- M4: regime error handling --------------------------------------------

class TestRegimeErrorHandling:
    """M4: indicator computation failures fall back to safe defaults."""

    def test_detect_regime_with_bad_data_falls_back(self, isolated_b2):
        """When compute_choppiness raises, regime still returns valid dict."""
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "regime"))
        from regime import detect_regime

        # Build mock df
        import pandas as pd
        import numpy as np
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        df = pd.DataFrame({
            "Open": 100 + np.cumsum(np.random.randn(100)),
            "High": 101 + np.cumsum(np.random.randn(100)),
            "Low": 99 + np.cumsum(np.random.randn(100)),
            "Close": 100 + np.cumsum(np.random.randn(100)),
            "Volume": [1000] * 100,
        }, index=dates)

        with patch("regime.compute_choppiness",
                    side_effect=ValueError("broken")), \
             patch("regime.fetch_daily", return_value=df):
            result = detect_regime("BTC-USDT", period="2y")
        # Must not raise; returns valid dict
        assert "regime" in result
        assert result["regime"] in {"TRENDING_UP", "TRENDING_DOWN", "RANGING",
                                     "MIXED", "CHOPPY", "HIGH_VOLATILITY"}
        # choppy fields should be defaults
        assert result["indicators"]["range_to_net_ratio"] == 0.0
        assert result["indicators"]["direction_changes_10d"] == 0


# ---- M7: telegram offset guard -------------------------------------------

class TestTelegramOffsetGuard:
    """M7: skip updates without update_id to avoid infinite loops."""

    def test_offset_unchanged_on_missing_update_id(self):
        """Inline reproduction of telegram poll loop offset logic (M7)."""
        # Mirror of telegram.py: skip updates without update_id to avoid
        # offset getting stuck when API returns malformed payloads.
        offset = 100
        updates = [
            {"update_id": 105, "message": {"text": "/help"}},
            {"message": {"text": "/status"}},  # NO update_id
            {"update_id": 107, "message": {"text": "/positions"}},
        ]
        new_offset = offset
        for update in updates:
            if "update_id" not in update:
                continue  # M7: skip malformed update
            new_offset = max(new_offset, int(update["update_id"]) + 1)
        # Skipped the one without update_id, processed 105 and 107
        assert new_offset == 108
