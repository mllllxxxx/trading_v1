"""Unit tests for okx_futures_bracket — Day 1 deliverables.

Run with: pytest tests/test_futures_bracket.py -x
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make modules importable
TRADING = Path(__file__).parent.parent
sys.path.insert(0, str(TRADING))           # so 'auto' and 'brackets' are packages
sys.path.insert(0, str(TRADING / "brackets"))
sys.path.insert(0, str(TRADING / "auto"))

import okx_futures_bracket as fb  # noqa: E402


# ---------------------------------------------------------------------------
# compute_liquidation_price
# ---------------------------------------------------------------------------

class TestComputeLiquidationPrice:
    def test_long_10x_btc(self):
        liq = fb.compute_liquidation_price(100_000, 10, "long", maintenance_margin_rate=0.005)
        # 100000 * (1 - 0.1 + 0.005) = 100000 * 0.905 = 90500
        assert liq == pytest.approx(90_500, rel=1e-9)

    def test_short_10x_btc(self):
        liq = fb.compute_liquidation_price(100_000, 10, "short", maintenance_margin_rate=0.005)
        # 100000 * (1 + 0.1 - 0.005) = 100000 * 1.095 = 109500
        assert liq == pytest.approx(109_500, rel=1e-9)

    def test_long_3x_eth(self):
        liq = fb.compute_liquidation_price(3_000, 3, "long", maintenance_margin_rate=0.005)
        # 3000 * (1 - 1/3 + 0.005) = 3000 * 0.671666... ≈ 2015
        assert liq == pytest.approx(2_015, rel=1e-3)

    def test_distance_matches_formula(self):
        for lev in [2, 3, 5, 10, 20]:
            liq = fb.compute_liquidation_price(100, lev, "long", 0.005)
            distance_pct = (100 - liq) / 100
            # Should be roughly 1/lev minus MMR
            assert distance_pct == pytest.approx(1 / lev - 0.005, abs=1e-9)

    def test_leverage_zero_raises(self):
        with pytest.raises(ValueError, match="leverage must be >= 1"):
            fb.compute_liquidation_price(100, 0, "long")

    def test_negative_entry_raises(self):
        with pytest.raises(ValueError, match="entry must be > 0"):
            fb.compute_liquidation_price(-100, 10, "long")

    def test_invalid_mmr_raises(self):
        with pytest.raises(ValueError, match="maintenance_margin_rate out of range"):
            fb.compute_liquidation_price(100, 10, "long", maintenance_margin_rate=1.5)


class TestComputeLiquidationBufferPct:
    def test_long_distance_positive(self):
        assert fb.compute_liquidation_buffer_pct(100, 90) == pytest.approx(0.1, rel=1e-9)

    def test_short_distance_positive(self):
        assert fb.compute_liquidation_buffer_pct(100, 110) == pytest.approx(0.1, rel=1e-9)

    def test_zero_entry_raises(self):
        with pytest.raises(ValueError, match="entry must be > 0"):
            fb.compute_liquidation_buffer_pct(0, 50)


# ---------------------------------------------------------------------------
# compute_bracket_futures — happy paths
# ---------------------------------------------------------------------------

class TestComputeBracketFuturesHappyPath:
    def test_eth_long_basic(self):
        p = fb.compute_bracket_futures(
            "ETH-USDT-SWAP", "long", 3000, 2850, 3300, 1000, leverage=3,
        )
        assert p["symbol"] == "ETH-USDT-SWAP"
        assert p["side"] == "buy"
        assert p["is_long"] is True
        assert p["pos_side"] == "long"
        assert p["leverage"] == 3
        assert p["td_mode"] == "isolated"
        assert p["entry"] == 3000
        assert p["stop_loss"] == 2850
        assert p["take_profit"] == 3300
        # R:R = (3300-3000)/(3000-2850) = 300/150 = 2.0
        assert p["rr_ratio"] == pytest.approx(2.0, rel=1e-9)
        assert p["rr_ratio_str"] == "1:2.00"

    def test_sol_long_3x(self):
        p = fb.compute_bracket_futures(
            "SOL-USDT-SWAP", "long", 150, 140, 175, 1000, leverage=3,
        )
        assert p["side"] == "buy"
        # R:R = (175-150)/(150-140) = 25/10 = 2.5
        assert p["rr_ratio"] == pytest.approx(2.5, rel=1e-9)
        # Liq ≈ 150 * (1 - 1/3 + 0.01) = 150 * 0.6767... = 101.5
        assert p["liq_price"] == pytest.approx(101.5, rel=1e-2)

    def test_short_side(self):
        p = fb.compute_bracket_futures(
            "ETH-USDT-SWAP", "short", 3000, 3150, 2700, 1000, leverage=3,
        )
        assert p["side"] == "sell"
        assert p["is_long"] is False
        assert p["pos_side"] == "short"
        # R:R = (3000-2700)/(3150-3000) = 300/150 = 2.0
        assert p["rr_ratio"] == pytest.approx(2.0, rel=1e-9)


# ---------------------------------------------------------------------------
# compute_bracket_futures — error cases
# ---------------------------------------------------------------------------

class TestComputeBracketFuturesErrors:
    def test_long_with_sl_above_entry_raises(self):
        with pytest.raises(ValueError, match="LONG: stop_loss must be BELOW entry"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "long", 3000, 3100, 3300, 1000, leverage=3,
            )

    def test_long_with_tp_below_entry_raises(self):
        with pytest.raises(ValueError, match="LONG: take_profit must be ABOVE entry"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "long", 3000, 2850, 2900, 1000, leverage=3,
            )

    def test_short_with_sl_below_entry_raises(self):
        with pytest.raises(ValueError, match="SHORT: stop_loss must be ABOVE entry"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "short", 3000, 2900, 2700, 1000, leverage=3,
            )

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side must be"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "weird", 3000, 2850, 3300, 1000, leverage=3,
            )

    def test_unknown_symbol_raises(self):
        with pytest.raises(ValueError, match="Unknown symbol base"):
            fb.compute_bracket_futures(
                "FOO-USDT-SWAP", "long", 100, 90, 110, 1000, leverage=3,
            )

    def test_leverage_above_max_raises(self):
        with pytest.raises(ValueError, match="exceeds MAX_LEVERAGE"):
            fb.compute_bracket_futures(
                "BTC-USDT-SWAP", "long", 100000, 95000, 110000, 1000, leverage=20,
            )

    def test_risk_pct_above_default_raises(self):
        with pytest.raises(ValueError, match="risk_pct .* exceeds default"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "long", 3000, 2850, 3300, 1000,
                leverage=3, risk_pct=0.05,
            )

    def test_zero_entry_raises(self):
        with pytest.raises(ValueError, match="must all be > 0"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "long", 0, 0, 0, 1000, leverage=3,
            )


# ---------------------------------------------------------------------------
# validate_futures — H5/H7 enforcement
# ---------------------------------------------------------------------------

class TestValidateFutures:
    def _good_eth_long(self, **overrides):
        kwargs = dict(symbol="ETH-USDT-SWAP", side="long", entry=3000,
                      stop_loss=2850, take_profit=3300, capital=1000, leverage=3)
        kwargs.update(overrides)
        return fb.compute_bracket_futures(**kwargs)

    def test_valid_proposal_passes(self):
        p = self._good_eth_long()
        violations = fb.validate_futures(p)
        assert violations == [], f"expected no violations, got {violations}"

    def test_btc_15x_lev_rejected_at_compute(self):
        # Bracket raises on leverage > MAX_LEVERAGE (10) before validator sees it
        with pytest.raises(ValueError, match="exceeds MAX_LEVERAGE"):
            self._good_eth_long(symbol="BTC-USDT-SWAP", entry=100_000,
                                stop_loss=95_000, take_profit=110_000,
                                leverage=15)

    def test_eth_5x_lev_fails_h5_in_validator(self):
        # Bracket allows 5x (≤MAX_LEVERAGE 10), but per-symbol validator caps
        # alts at 3x. So compute succeeds, validate_futures flags H5.
        p = self._good_eth_long(leverage=5)
        violations = fb.validate_futures(p)
        # Either H5 or H7 should fire (H7 is also triggered at 5x for alts)
        assert any("H5" in v or "H7" in v for v in violations), violations
        assert any("H5 leverage" in v for v in violations), (
            f"expected H5 per-symbol cap, got {violations}"
        )

    def test_btc_8pct_liq_distance_fails_h7(self):
        # Override leverage to make liq distance < required buffer
        # At 10x, distance = 1/10 - 0.005 = 0.095 = 9.5%
        # buffer required = 0.08, so 9.5% should PASS — let's force a fail
        # by using a custom proposal where liq_distance < 0.08
        p = self._good_eth_long(symbol="BTC-USDT-SWAP", entry=100_000,
                                stop_loss=95_000, take_profit=110_000,
                                leverage=10)
        # Manually set liq_distance_pct below buffer to test the check
        p["liq_distance_pct"] = 0.05
        violations = fb.validate_futures(p)
        assert any("H7 liq buffer" in v for v in violations)

    def test_low_rr_fails(self):
        # R:R = 0.5 < min_rr 1.5
        p = self._good_eth_long(take_profit=3075)  # reward=75, risk=150
        violations = fb.validate_futures(p)
        assert any("R:R" in v and "minimum" in v for v in violations)
