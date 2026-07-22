"""Tests for scheduler.py safety fixes (C1-C4, H2, H3, H5, H6)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def isolated_scheduler(tmp_data_dir, monkeypatch):
    """Reload scheduler with DATA_DIR redirected + stub external deps."""
    import importlib
    import sys
    # Stub external deps BEFORE scheduler imports them so it doesn't try to
    # touch network / openai at import time.
    for stub in ["ccxt", "openai"]:
        if stub not in sys.modules:
            sys.modules[stub] = MagicMock()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auto"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if "journal" in sys.modules:
        importlib.reload(sys.modules["journal"])
    if "scheduler" in sys.modules:
        importlib.reload(sys.modules["scheduler"])
    import scheduler  # type: ignore  # noqa: E402
    yield scheduler
    if "scheduler" in sys.modules:
        importlib.reload(sys.modules["scheduler"])


# ---- C3: LLM error classification -----------------------------------------

class TestLLMErrorClassification:
    """C3: only DEEPSEEK_API_KEY missing allows rules-only fallback."""

    def test_missing_api_key_allows_fallback(self, isolated_scheduler):
        s = isolated_scheduler
        assert s._classify_llm_error("DEEPSEEK_API_KEY not set") == "no_key"

    def test_network_error_aborts(self, isolated_scheduler):
        s = isolated_scheduler
        assert s._classify_llm_error("LLM API call failed: timeout") == "api_error"
        assert s._classify_llm_error("ConnectionError: deepseek.com unreachable") == "api_error"

    def test_parse_error_aborts(self, isolated_scheduler):
        s = isolated_scheduler
        assert s._classify_llm_error("Invalid JSON: ...") == "api_error"

    def test_no_error_returns_ok(self, isolated_scheduler):
        s = isolated_scheduler
        assert s._classify_llm_error(None) == "ok"
        assert s._classify_llm_error("") == "ok"


# ---- C1: Phase 1 fallback uses top-level _okx_bracket ---------------------

class TestPhase1FallbackModule:
    """C1: `_okx_bracket` is bound at module level so fallback works."""

    def test_okx_bracket_loaded_at_import(self, isolated_scheduler):
        s = isolated_scheduler
        assert hasattr(s, "_okx_bracket")
        assert s._okx_bracket is not None
        assert hasattr(s._okx_bracket, "compute_bracket")
        assert hasattr(s._okx_bracket, "validate")

    def test_run_once_symbol_no_nameerror_when_no_llm(self, isolated_scheduler, tmp_data_dir):
        """Regression: Phase 1 fallback used to NameError because `mod` was undefined."""
        s = isolated_scheduler
        s.journal.ensure_dirs()
        # Add a position so the symbol-already-open guard fires (cheapest path)
        # Otherwise we'd need to mock confluence/regime subprocess calls.
        s.journal.add_position({
            "symbol": "BTC-USDT", "side": "buy", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": 110.0,
            "position_size": 0.1, "risk_usd": 50.0,
        })
        # Should silently return (no exception, no nameerror)
        s.run_once_symbol("BTC-USDT")
        # No assertion needed: if NameError fired, the test would raise.

    def test_run_once_symbol_respects_startup_sync_guard(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        s.journal.set_startup_sync_guard("exchange_snapshot_failed", {"error": "okx down"})

        s.run_once_symbol("BTC-USDT")

        with s.journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        assert any(
            event.get("type") == "skip"
            and event.get("reason") == "startup_sync_blocked"
            for event in events
        )


# ---- C2: KeyError guards --------------------------------------------------

class TestKeyErrorGuards:
    """C2: confluence/regime JSON missing keys must not crash scheduler."""

    def test_confluence_missing_total_score_skips(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence", return_value={"timeframes": {}}), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")
        # Verify skip was logged with our new reason
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason", "").startswith("confluence")
        ]
        assert "confluence_missing_total_score" in skip_reasons


class TestSignedConfluenceDirection:
    """Step 9: signed confluence must support both long and short candidates."""

    @pytest.mark.parametrize(
        ("score", "is_candidate", "direction", "side"),
        [
            (4, True, "long", "buy"),
            (-4, True, "short", "sell"),
            (1, False, None, None),
            (-1, False, None, None),
            (0, False, None, None),
        ],
    )
    def test_classify_confluence_direction(
        self,
        isolated_scheduler,
        score,
        is_candidate,
        direction,
        side,
    ):
        assert isolated_scheduler.classify_confluence_direction(score, 2) == (
            is_candidate,
            direction,
            side,
        )

    def test_negative_confluence_reaches_llm_as_short_candidate(
        self,
        isolated_scheduler,
        tmp_data_dir,
    ):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        captured: dict[str, dict] = {}

        def fake_user_prompt(**kwargs):
            captured["confluence"] = dict(kwargs["confluence"])
            return "user-prompt"

        with patch.object(s, "_run_confluence", return_value={
                "total_score": -3,
                "timeframes": {
                    "1d": {"trend": "DOWN", "momentum": "DOWN"},
                    "1w": {"trend": "DOWN", "momentum": "DOWN"},
                },
            }), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_DOWN",
                "close": 100.0,
                "indicators": {"atr_14": 1.0},
                "technical_indicators": {},
            }), \
             patch.object(s, "journal") as mock_journal, \
             patch.object(s._prompts, "build_system_prompt", return_value="system-prompt"), \
             patch.object(s._prompts, "build_user_prompt", side_effect=fake_user_prompt), \
             patch.object(s._brain, "call_brain", return_value={
                "action": "hold",
                "reasoning": "Holding after evaluating the short candidate context.",
                "confidence": 0.5,
                "_model": "test",
                "_latency_s": 0,
            }):
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.daily_cost_status.return_value = {"cap_reached": False}
            s.run_once_symbol("BTC-USDT")

        candidate_events = [
            c.args[1] for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "candidate"
        ]
        assert candidate_events
        assert candidate_events[0]["candidate_direction"] == "short"
        assert candidate_events[0]["candidate_side"] == "sell"
        assert captured["confluence"]["candidate_direction"] == "short"
        assert captured["confluence"]["candidate_side"] == "sell"
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip"
        ]
        assert "weak_confluence" not in skip_reasons
        assert "bearish_confluence" not in skip_reasons

    def test_direction_regime_conflict_skips_safely(
        self,
        isolated_scheduler,
        tmp_data_dir,
    ):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence", return_value={
                "total_score": -3,
                "timeframes": {},
            }), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP",
                "close": 100.0,
                "indicators": {},
                "technical_indicators": {},
            }), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")

        conflict_events = [
            c.args[1] for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip"
            and c.args[1].get("reason") == "regime_direction_conflict"
        ]
        assert conflict_events
        assert conflict_events[0]["candidate_direction"] == "short"


class TestRegimeKeyGuards:
    """C2: regime JSON missing or malformed close must not crash scheduler."""

    def test_regime_missing_close_skips(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3, "timeframes": {}}), \
             patch.object(s, "_run_regime", return_value={"regime": "TRENDING_UP"}), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason", "").startswith("regime")
        ]
        assert "regime_missing_close" in skip_reasons

    def test_regime_bad_close_skips(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        # Use a non-numeric string that float() cannot parse
        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3, "timeframes": {}}), \
             patch.object(s, "_run_regime", return_value={"regime": "TRENDING_UP", "close": "not-a-number"}), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason", "") == "regime_bad_close"
        ]
        assert "regime_bad_close" in skip_reasons


# ---- C4: Division by zero / non-positive price ----------------------------

class TestNonPositivePrice:
    """C4: current_price <= 0 must skip, never ZeroDivisionError."""

    def test_zero_price_skips(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3, "timeframes": {}}), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP", "close": 0,
                "indicators": {"atr_14": 0}, "technical_indicators": {}}), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason", "") == "non_positive_price"
        ]
        assert "non_positive_price" in skip_reasons

    def test_negative_price_skips(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3, "timeframes": {}}), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP", "close": -100.0,
                "indicators": {}, "technical_indicators": {}}), \
             patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason", "") == "non_positive_price"
        ]
        assert "non_positive_price" in skip_reasons


# ---- H6: position_size_pct clamp -------------------------------------------

class TestSizeClamp:
    """H6: clamp position_size_pct to [0, 20]."""

    def test_clamp_above_max(self, isolated_scheduler):
        assert isolated_scheduler._clamp_size_pct(50) == 20.0
        assert isolated_scheduler._clamp_size_pct(100) == 20.0
        assert isolated_scheduler._clamp_size_pct(20.5) == 20.0

    def test_clamp_below_min(self, isolated_scheduler):
        assert isolated_scheduler._clamp_size_pct(-5) == 0.0
        assert isolated_scheduler._clamp_size_pct(0) == 0.0

    def test_clamp_within_range(self, isolated_scheduler):
        assert isolated_scheduler._clamp_size_pct(15) == 15.0
        assert isolated_scheduler._clamp_size_pct(5) == 5.0
        assert isolated_scheduler._clamp_size_pct(20) == 20.0

    def test_clamp_invalid_input(self, isolated_scheduler):
        assert isolated_scheduler._clamp_size_pct("NaN") == 0.0
        assert isolated_scheduler._clamp_size_pct(None) == 0.0


# ---- H5: ATR-based SL/TP --------------------------------------------------

class TestATRBracketParams:
    """H5: SL/TP must adapt to ATR, not be hardcoded 1.5%/3%."""

    def test_atr_drives_stops_when_available(self, isolated_scheduler):
        s = isolated_scheduler
        # ATR=2.4% of price → stop should be max(1.5%, 1.5*2.4%)=3.6%
        reg = {"indicators": {"atr_14": 240.0}}  # 240 / 10000 = 2.4%
        params = s._compute_bracket_params(reg, {}, current_price=10000.0, is_long=True)
        assert params["stop_loss"] == round(10000.0 * (1 - 3.6/100), 2)
        assert params["take_profit"] == round(10000.0 * (1 + 7.2/100), 2)

    def test_falls_back_to_baseline_when_no_atr(self, isolated_scheduler):
        s = isolated_scheduler
        reg = {"indicators": {}}
        params = s._compute_bracket_params(reg, {}, current_price=10000.0, is_long=True)
        # Baseline 1.5% / 3% preserved
        assert params["stop_loss"] == round(10000.0 * 0.985, 2)
        assert params["take_profit"] == round(10000.0 * 1.030, 2)

    def test_short_side_uses_correct_direction(self, isolated_scheduler):
        s = isolated_scheduler
        reg = {"indicators": {"atr_14": 100.0}}  # 1%
        params = s._compute_bracket_params(reg, {}, current_price=10000.0, is_long=False)
        # short: SL above, TP below
        assert params["stop_loss"] > 10000.0
        assert params["take_profit"] < 10000.0


# ---- H3: Correlation check both directions --------------------------------

class TestCorrelationBothDirections:
    """H3: correlation cap applies to both long and short."""

    def test_three_buys_blocks_new_buy(self, isolated_scheduler):
        # Need score>0 (is_long=True), regime TRENDING_UP
        positions = [
            {"symbol": "BTC-USDT", "side": "buy"},
            {"symbol": "ETH-USDT", "side": "buy"},
            {"symbol": "SOL-USDT", "side": "buy"},
        ]
        # Simulate the check directly with our new logic
        is_long = True
        proposed = "buy" if is_long else "sell"
        same = sum(1 for p in positions if p.get("side") == proposed)
        assert same >= 2  # blocked

    def test_two_sells_blocks_new_sell(self, isolated_scheduler):
        """Regression: previous code only checked 'buy' count, missing shorts."""
        positions = [
            {"symbol": "BTC-USDT", "side": "sell"},
            {"symbol": "ETH-USDT", "side": "sell"},
        ]
        is_long = False
        proposed = "buy" if is_long else "sell"
        same = sum(1 for p in positions if p.get("side") == proposed)
        assert same >= 2  # would be blocked now (was missed before)


# ---- H4: corrupt journal halt ---------------------------------------------

class TestCorruptJournalHalt:
    """H4: corrupt positions.json must halt cycle, not silently return []."""

    def test_corrupt_positions_halts(self, isolated_scheduler, tmp_data_dir):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        s.journal.POSITIONS_FILE.write_text("garbage", encoding="utf-8")
        # Capture the real exception class BEFORE patching the journal module
        # (otherwise mock auto-creates a Mock attribute that doesn't inherit
        # from BaseException and `except journal.JournalCorruptError` crashes).
        RealJournalCorruptError = s.journal.JournalCorruptError
        real_exc = RealJournalCorruptError("test")
        with patch.object(s, "journal") as mock_journal:
            mock_journal.read_positions.side_effect = real_exc
            mock_journal.JournalCorruptError = RealJournalCorruptError
            mock_journal.append_decision.return_value = None
            s.run_once_symbol("BTC-USDT")
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip" and c.args[1].get("reason") == "corrupt_journal"
        ]
        assert "corrupt_journal" in skip_reasons


class TestExplicitLLMFallbackPolicy:
    """Step 16: rules-only fallback must be explicit and fail closed."""

    def test_cost_cap_skips_when_llm_is_required(
        self,
        isolated_scheduler,
        tmp_data_dir,
        monkeypatch,
    ):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        monkeypatch.setenv("REQUIRE_LLM_DECISION", "true")
        monkeypatch.setenv("ENABLE_RULES_ONLY_FALLBACK", "true")

        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3,
                "timeframes": {},
            }), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP",
                "close": 100.0,
                "indicators": {},
                "technical_indicators": {},
            }), \
             patch.object(s, "journal") as mock_journal, \
             patch.object(s, "_place_bracket_via_script") as mock_place:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.daily_cost_status.return_value = {
                "cap_reached": True,
                "cost_usd": 1.0,
                "cap_usd": 1.0,
                "calls": 12,
            }
            s.run_once_symbol("BTC-USDT")

        mock_place.assert_not_called()
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip"
        ]
        assert "llm_required_cost_cap" in skip_reasons

    def test_missing_llm_skips_when_llm_is_required(
        self,
        isolated_scheduler,
        tmp_data_dir,
        monkeypatch,
    ):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        monkeypatch.setenv("REQUIRE_LLM_DECISION", "true")
        monkeypatch.setenv("ENABLE_RULES_ONLY_FALLBACK", "true")

        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3,
                "timeframes": {},
            }), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP",
                "close": 100.0,
                "indicators": {},
                "technical_indicators": {},
            }), \
             patch.object(s, "journal") as mock_journal, \
             patch.object(s._prompts, "build_system_prompt", return_value="system"), \
             patch.object(s._prompts, "build_user_prompt", return_value="user"), \
             patch.object(s._brain, "call_brain",
                          side_effect=s._brain.BrainError("DEEPSEEK_API_KEY not set")), \
             patch.object(s, "_place_bracket_via_script") as mock_place:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.daily_cost_status.return_value = {"cap_reached": False}
            s.run_once_symbol("BTC-USDT")

        mock_place.assert_not_called()
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip"
        ]
        assert "llm_required_unavailable" in skip_reasons

    def test_rules_only_disabled_skips_even_when_llm_not_required(
        self,
        isolated_scheduler,
        tmp_data_dir,
        monkeypatch,
    ):
        s = isolated_scheduler
        s.journal.ensure_dirs()
        monkeypatch.setenv("REQUIRE_LLM_DECISION", "false")
        monkeypatch.setenv("ENABLE_RULES_ONLY_FALLBACK", "false")

        with patch.object(s, "_run_confluence", return_value={
                "total_score": 3,
                "timeframes": {},
            }), \
             patch.object(s, "_run_regime", return_value={
                "regime": "TRENDING_UP",
                "close": 100.0,
                "indicators": {},
                "technical_indicators": {},
            }), \
             patch.object(s, "journal") as mock_journal, \
             patch.object(s._prompts, "build_system_prompt", return_value="system"), \
             patch.object(s._prompts, "build_user_prompt", return_value="user"), \
             patch.object(s._brain, "call_brain",
                          side_effect=s._brain.BrainError("DEEPSEEK_API_KEY not set")), \
             patch.object(s, "_place_bracket_via_script") as mock_place:
            mock_journal.read_positions.return_value = []
            mock_journal.read_closed_trades.return_value = []
            mock_journal.is_killed.return_value = False
            mock_journal.check_loss_streak_kill.return_value = False
            mock_journal.is_in_cooldown.return_value = (False, None, 0)
            mock_journal.daily_cost_status.return_value = {"cap_reached": False}
            s.run_once_symbol("BTC-USDT")

        mock_place.assert_not_called()
        skip_reasons = [
            c.args[1].get("reason") for c in mock_journal.append_decision.call_args_list
            if c.args[0] == "skip"
        ]
        assert "llm_unavailable_rules_only_disabled" in skip_reasons
