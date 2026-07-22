"""Unit tests for okx_futures_bracket — Day 1 deliverables.

Run with: pytest tests/test_futures_bracket.py -x
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
    def test_default_notional_cap_matches_margin_and_leverage_contract(self):
        p = fb.compute_bracket_futures(
            "ETH-USDT-SWAP", "long", 3000, 2850, 3300, 1000, leverage=3,
        )

        assert fb.MAX_POSITION_PCT == pytest.approx(0.60, rel=1e-9)
        assert fb.MAX_MARGIN_PCT == pytest.approx(0.20, rel=1e-9)
        assert p["max_notional_pct"] == pytest.approx(0.60, rel=1e-9)
        assert p["position_pct"] <= 60.0
        assert p["margin_required"] <= 200.0

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

    def test_200_usd_cap_limits_eth_margin_to_40_usd_before_contract_rounding(self):
        p = fb.compute_bracket_futures(
            "ETH-USDT-SWAP", "long", 3000, 2850, 3300, 200, leverage=3,
        )

        assert p["max_notional_pct"] == pytest.approx(0.60, rel=1e-9)
        assert p["position_notional"] <= 120.0
        assert p["position_pct"] <= 60.0
        assert p["margin_required"] <= 40.0

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

    def test_dynamic_symbol_uses_conservative_alt_defaults(self):
        p = fb.compute_bracket_futures(
            "FOO-USDT-SWAP", "long", 100, 90, 110, 1000, leverage=3,
        )

        assert p["symbol"] == "FOO-USDT-SWAP"
        assert p["leverage"] == 3
        assert p["contract_size"] == 1

    def test_dynamic_symbol_can_use_exchange_contract_size_override(self):
        p = fb.compute_bracket_futures(
            "NEAR-USDT-SWAP",
            "long",
            1.93,
            1.88,
            2.03,
            200,
            leverage=3,
            risk_pct=0.005,
            contract_size=10,
            min_qty=0.1,
        )

        assert p["contracts"] == 2
        assert p["contract_size"] == 10
        assert p["position_size_base"] == pytest.approx(20)
        assert p["position_notional"] == pytest.approx(38.6)
        assert p["margin_required"] == pytest.approx(12.8666666667)
        assert p["position_pct"] <= 20.0

    def test_leverage_above_max_raises(self):
        with pytest.raises(ValueError, match="exceeds MAX_LEVERAGE"):
            fb.compute_bracket_futures(
                "BTC-USDT-SWAP", "long", 100000, 95000, 110000, 1000, leverage=20,
            )

    def test_risk_pct_above_hard_ceiling_raises(self):
        with pytest.raises(ValueError, match="risk_pct .* exceeds default"):
            fb.compute_bracket_futures(
                "ETH-USDT-SWAP", "long", 3000, 2850, 3300, 1000,
                leverage=3, risk_pct=0.06,
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
        # The global 3x hard ceiling rejects this before validation.
        with pytest.raises(ValueError, match="exceeds MAX_LEVERAGE"):
            self._good_eth_long(symbol="BTC-USDT-SWAP", entry=100_000,
                                stop_loss=95_000, take_profit=110_000,
                                leverage=15)

    def test_eth_5x_lev_rejected_at_compute(self):
        # The same global ceiling applies to alt symbols.
        with pytest.raises(ValueError, match="exceeds MAX_LEVERAGE"):
            self._good_eth_long(leverage=5)

    def test_btc_8pct_liq_distance_fails_h7(self):
        # Isolate the H7 branch with a broker-like unsafe liquidation snapshot.
        p = self._good_eth_long(symbol="BTC-USDT-SWAP", entry=100_000,
                                stop_loss=95_000, take_profit=110_000,
                                leverage=3)
        p["liq_distance_pct"] = 0.05
        violations = fb.validate_futures(p)
        assert any("H7 liq buffer" in v for v in violations)

    def test_low_rr_fails(self):
        # R:R = 0.5 < min_rr 1.5
        p = self._good_eth_long(take_profit=3075)  # reward=75, risk=150
        violations = fb.validate_futures(p)
        assert any("R:R" in v and "minimum" in v for v in violations)


def test_contract_metadata_falls_back_to_exact_public_instrument(monkeypatch):
    class EmptySandboxExchange:
        def load_markets(self):
            return {}

    seen: dict[str, object] = {}

    def fake_get(url, params, headers, timeout):  # noqa: ANN001
        seen.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "code": "0",
                "data": [
                    {
                        "instId": "ONDO-USDT-SWAP",
                        "ctVal": "10",
                        "minSz": "1",
                        "lotSz": "1",
                    }
                ],
            },
        )

    import requests

    monkeypatch.setattr(fb, "_make_exchange", lambda _cfg: EmptySandboxExchange())
    monkeypatch.setattr(requests, "get", fake_get)

    metadata = fb.fetch_contract_trade_metadata(
        {"api_key": "", "api_secret": "", "passphrase": "", "testnet": True},
        "ONDO-USDT",
    )

    assert metadata == {
        "symbol": "ONDO-USDT-SWAP",
        "contract_size": 10.0,
        "min_qty": 1.0,
        "qty_step": 1.0,
        "source": "okx_public_instruments",
    }
    assert seen["params"] == {"instType": "SWAP", "instId": "ONDO-USDT-SWAP"}
    assert seen["headers"] == {"x-simulated-trading": "1"}


def test_compute_futures_preserves_fractional_contract_step() -> None:
    proposal = fb.compute_bracket_futures(
        "BTC-USDT-SWAP",
        "buy",
        66_000,
        65_000,
        68_000,
        200,
        leverage=3,
        risk_pct=0.04,
        contract_size=0.01,
        min_qty=0.01,
        qty_step=0.01,
    )

    assert proposal["contracts"] == pytest.approx(0.18)
    assert proposal["qty_step"] == pytest.approx(0.01)
    assert proposal["below_min_qty"] is False
    assert proposal["position_notional"] == pytest.approx(118.8)


def test_contract_metadata_public_fallback_rejects_wrong_symbol(monkeypatch):
    class EmptySandboxExchange:
        def load_markets(self):
            return {}

    def fake_get(_url, params, headers, timeout):  # noqa: ANN001
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "code": "0",
                "data": [{"instId": "BTC-USDT-SWAP", "ctVal": "0.01", "minSz": "1"}],
            },
        )

    import requests

    monkeypatch.setattr(fb, "_make_exchange", lambda _cfg: EmptySandboxExchange())
    monkeypatch.setattr(requests, "get", fake_get)

    with pytest.raises(RuntimeError, match="exact instrument metadata unavailable"):
        fb.fetch_contract_trade_metadata(
            {"api_key": "", "api_secret": "", "passphrase": "", "testnet": True},
            "ONDO-USDT",
        )


def test_set_leverage_uses_native_okx_instrument_without_ccxt_symbol_lookup(monkeypatch):
    seen: dict[str, object] = {}

    class UnexpectedCCXT:
        def set_leverage(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("CCXT symbol lookup must not run")

    def fake_post(url, data, headers, timeout):  # noqa: ANN001
        seen.update({"url": url, "body": data, "headers": headers, "timeout": timeout})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "code": "0",
                "data": [
                    {
                        "instId": "ONDO-USDT-SWAP",
                        "lever": "3",
                        "mgnMode": "isolated",
                        "posSide": "long",
                    }
                ],
            },
        )

    import requests

    monkeypatch.setattr(fb, "_make_exchange", lambda _cfg: UnexpectedCCXT())
    monkeypatch.setattr(requests, "post", fake_post)

    result = fb.set_leverage(
        {
            "api_key": "key",
            "api_secret": "secret",
            "passphrase": "pass",
            "testnet": True,
            "sandbox": True,
        },
        "ONDO-USDT-SWAP",
        3,
        "long",
    )

    assert result["instId"] == "ONDO-USDT-SWAP"
    assert str(seen["url"]).endswith("/api/v5/account/set-leverage")
    assert json.loads(str(seen["body"])) == {
        "instId": "ONDO-USDT-SWAP",
        "lever": "3",
        "mgnMode": "isolated",
        "posSide": "long",
    }
    assert seen["headers"]["x-simulated-trading"] == "1"


def test_place_orders_futures_uses_demo_header_and_algo_id(monkeypatch):
    seen: dict[str, object] = {}

    def fake_post(url, data, headers, timeout):  # noqa: ANN001
        seen["url"] = url
        seen["body"] = data
        seen["headers"] = headers
        seen["timeout"] = timeout
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"code": "0", "data": [{"ordId": "ord-demo-1"}]},
        )

    import requests

    monkeypatch.setattr(fb, "_make_exchange", lambda _cfg: object())
    monkeypatch.setattr(fb, "set_leverage", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(fb, "fetch_account_config", lambda _cfg: {"posMode": "long_short_mode"})
    monkeypatch.setattr(requests, "post", fake_post)

    result = fb.place_orders_futures(
        {
            "symbol": "BTC-USDT-SWAP",
            "td_mode": "isolated",
            "is_long": True,
            "pos_side": "long",
            "entry": 100,
            "contracts": 1,
            "take_profit": 110,
            "stop_loss": 95,
            "leverage": 10,
            "liq_price": 90,
            "margin_required": 10,
        },
        {
            "api_key": "key",
            "api_secret": "secret",
            "passphrase": "pass",
            "testnet": True,
            "sandbox": True,
        },
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["order_id"] == "ord-demo-1"
    assert result["algo_order_id"] == "ord-demo-1"
    assert str(seen["url"]).endswith("/api/v5/trade/order")
    assert seen["headers"]["x-simulated-trading"] == "1"
    body = json.loads(str(seen["body"]))
    assert body["ordType"] == "limit"
    assert body["px"] == "100"
    assert body["attachAlgoOrds"][0]["tpTriggerPx"] == "110"
    assert body["attachAlgoOrds"][0]["slTriggerPx"] == "95"


def test_place_orders_futures_omits_pos_side_in_net_mode(monkeypatch):
    seen: dict[str, object] = {}

    def fake_post(url, data, headers, timeout):  # noqa: ANN001
        seen["body"] = data
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"code": "0", "data": [{"algoId": "algo-demo-net"}]},
        )

    import requests

    monkeypatch.setattr(fb, "_make_exchange", lambda _cfg: object())
    monkeypatch.setattr(fb, "set_leverage", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(fb, "fetch_account_config", lambda _cfg: {"posMode": "net_mode"})
    monkeypatch.setattr(requests, "post", fake_post)

    result = fb.place_orders_futures(
        {
            "symbol": "BTC-USDT-SWAP",
            "td_mode": "isolated",
            "is_long": False,
            "pos_side": "short",
            "entry": 100,
            "contracts": 1,
            "take_profit": 90,
            "stop_loss": 105,
            "leverage": 10,
            "liq_price": 110,
            "margin_required": 10,
        },
        {
            "api_key": "key",
            "api_secret": "secret",
            "passphrase": "pass",
            "testnet": True,
            "sandbox": True,
        },
        dry_run=False,
    )

    assert result["ok"] is True
    body = json.loads(str(seen["body"]))
    assert body["side"] == "sell"
    assert body["ordType"] == "limit"
    assert body["px"] == "100"
    assert body["attachAlgoOrds"][0]["tpTriggerPx"] == "90"
    assert body["attachAlgoOrds"][0]["slTriggerPx"] == "105"
    assert "posSide" not in body
    assert "tgtCcy" not in body
