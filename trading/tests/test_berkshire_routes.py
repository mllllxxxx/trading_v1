"""Tests for AI Berkshire research desk routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from adaptive_hybrid import DecisionPolicy
from berkshire_scanner import (
    _feature_enrichment_symbols,
    rank_signal_candidates,
    scan_crypto_market,
)
from berkshire_routes import register_berkshire_routes
from schemas.models import validate_signal_candidate
from strategy_teams import resolve_team


def _scanner_feature_snapshot(*, price: float = 105.0, mean_reversion: bool = False) -> dict:
    def timeframe(*, trend: str, close: float, previous: float, adx: float, bb_z: float = 0.0, rsi: float = 55.0) -> dict:
        atr = max(price * 0.02, 0.00000001)
        return {
            "close": close,
            "previous_close": previous,
            "ema20": price,
            "ema50": price * (1.01 if trend == "up" else 0.99),
            "ema200": price * (0.99 if trend == "up" else 1.01),
            "ema50_slope_pct_5": 1.0 if trend == "up" else -1.0 if trend == "down" else 0.0,
            "adx14": adx,
            "atr14": atr,
            "atr_pct": 2.0,
            "atr_percentile": 0.5,
            "rsi14": rsi,
            "bb_mid": price,
            "bb_upper": price + 2 * atr,
            "bb_lower": price - 2 * atr,
            "bb_z": bb_z,
            "previous_bb_z": 2.4 if mean_reversion else bb_z,
            "bb_width_pct": 8.0,
            "bb_width_percentile": 0.5,
            "prior_compression_percentile": 0.2,
            "donchian20_high": price + atr,
            "donchian20_low": price - atr,
            "volume_z20": 1.5,
            "efficiency_ratio20": 0.2,
            "distance_ema20_atr": 0.2,
            "swing_high10": price + atr,
            "swing_low10": price - atr,
            "trend": trend,
        }

    if mean_reversion:
        one = timeframe(trend="mixed", close=price, previous=price * 0.99, adx=15, bb_z=2.1, rsi=72)
        fifteen = timeframe(trend="mixed", close=price * 0.999, previous=price, adx=15, bb_z=1.5, rsi=65)
        regime = "RANGING"
    else:
        one = timeframe(trend="up", close=price, previous=price * 0.999, adx=32)
        fifteen = timeframe(trend="up", close=price, previous=price * 0.999, adx=28)
        regime = "TRENDING_UP"
    four = timeframe(trend="up", close=price, previous=price * 0.995, adx=30)
    return {
        "data_timestamp_utc": "2026-06-30T00:00:00+00:00",
        "data_age_s": 30.0,
        "regime": regime,
        "regime_evidence": {"one_hour_adx14": one["adx14"]},
        "features": {"15m": fifteen, "1H": one, "4H": four},
    }


def test_feature_shortlist_reserves_liquidity_anchors(monkeypatch) -> None:
    symbols = ["BTC-USDT", *[f"NOISE{i}-USDT" for i in range(12)]]
    tickers = {
        "BTC-USDT": {
            "last": "100000",
            "open24h": "99000",
            "high24h": "102000",
            "low24h": "98000",
            "volCcy24h": "100",
        }
    }
    for index, symbol in enumerate(symbols[1:], start=1):
        tickers[symbol] = {
            "last": str(100 + index),
            "open24h": "50",
            "high24h": str(110 + index),
            "low24h": "40",
            "volCcy24h": "1000",
        }

    monkeypatch.setenv("STRATEGY_MTF_ENRICH_LIMIT", "6")
    selected = _feature_enrichment_symbols(
        symbols,
        tickers,
        team=resolve_team("berkshire"),
        explicit_symbols=False,
    )

    assert len(selected) == 6
    assert "BTC-USDT" in selected


async def _allow_auth() -> None:
    """No-op auth dependency for route unit tests."""
    return None


def _client(tmp_data_dir) -> TestClient:
    app = FastAPI()
    register_berkshire_routes(app, require_auth=_allow_auth)
    return TestClient(app)


class TestBerkshireRoutes:
    """Berkshire state and research workflow behavior."""

    def test_state_bootstraps_from_empty_store(self, tmp_data_dir):
        client = _client(tmp_data_dir)

        res = client.get("/api/berkshire/state")

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert {lane["key"] for lane in data["lanes"]} == {"crypto", "forex"}
        assert data["active_run"] is None
        assert (tmp_data_dir / "berkshire" / "state.json").exists()

    def test_create_crypto_research_run_persists_decimal_audit(self, tmp_data_dir):
        client = _client(tmp_data_dir)

        res = client.post(
            "/api/berkshire/research",
            json={
                "lane": "crypto",
                "symbol": "BTC-USDT",
                "skill": "investment-team",
                "catalyst": "ETF inflow acceleration with funding still contained.",
                "thesis": "BTC trend remains supported while volatility compression gives a clear invalidation level.",
                "entry_price": "65000",
                "stop_loss": "62000",
                "target_price": "73000",
                "capital_usd": "10000",
            },
        )

        assert res.status_code == 201
        body = res.json()
        run = body["run"]
        assert run["symbol"] == "BTC-USDT"
        assert run["mode"] == "research_only"
        assert run["financial_checks"]["risk_reward"] == "2.6667"
        assert run["financial_checks"]["risk_pct"] == "4.62"
        assert len(run["analysts"]) == 4
        assert body["state"]["active_run"]["id"] == run["id"]

        persisted = client.get("/api/berkshire/state").json()
        assert persisted["runs"][0]["id"] == run["id"]

    def test_forex_research_is_blocked_from_execution(self, tmp_data_dir):
        client = _client(tmp_data_dir)

        res = client.post(
            "/api/berkshire/research",
            json={
                "lane": "forex",
                "symbol": "EUR/USD",
                "skill": "quality-screen",
                "catalyst": "ECB repricing and US data surprise.",
                "thesis": "EUR/USD has a researchable macro setup, but execution needs spread and session contracts.",
            },
        )

        assert res.status_code == 201
        run = res.json()["run"]
        assert run["verdict"] == "research_only_blocked"
        assert any(item["label"] == "Forex readiness" and item["status"] == "block" for item in run["checklist"])
        assert "no order payload generated" in run["audit"][1]["value"]

    def test_crypto_scan_persists_signal_only_state(self, tmp_data_dir, monkeypatch):
        def fake_scan_crypto_market(**_kwargs):
            return {
                "id": "bscan_test",
                "created_at": "2026-06-30T00:00:00+00:00",
                "market": "crypto",
                "mode": "signal_only",
                "source": "test",
                "provider_error": None,
                "universe_count": 1,
                "signal_count": 1,
                "top_symbol": "BTC-USDT",
                "top_signal": "strong_candidate",
                "signals": [
                    {
                        "symbol": "BTC-USDT",
                        "market": "crypto",
                        "signal_id": "sig_route_test",
                        "generated_at": "2026-06-30T00:00:00+00:00",
                        "source": "berkshire_crypto_scanner",
                        "timeframe": "24h_ticker",
                        "direction": "long",
                        "status": "strong_candidate",
                        "signal": "strong_candidate",
                        "score": 88,
                        "grade": "A",
                        "confidence": 0.88,
                        "action_hint": "OPEN_LONG",
                        "mode": "signal_only",
                        "time_horizon": "swing_2d_7d",
                        "promotion_gate": "eligible_for_draft_ticket",
                        "last_price": "105.0000",
                        "change_pct_24h": "5.00",
                        "range_pct_24h": "8.57",
                        "volume_usd_24h": "2000000000.0000",
                        "spread_bps": "1.90",
                        "entry_zone": "104.7375 - 105.2625",
                        "invalidation": "102.4286",
                        "target_zone": "110.1428",
                        "risk_reward": "2.0000",
                        "reasons": ["24h momentum points long at 5.00%."],
                        "why": ["24h momentum points long at 5.00%."],
                        "blockers": [],
                        "llm_context": {
                            "role": "advisory_signal_context",
                            "candidate_action": "OPEN_LONG",
                            "ticket_gate": "eligible_for_draft_ticket",
                            "instruction": "Use as evidence only.",
                            "prompt_context": "BTC-USDT advisory context",
                        },
                        "evidence": {"provider_source": "okx_public_tickers", "last_price": "105.0000"},
                    }
                ],
                "audit": [
                    {
                        "time": "07:00",
                        "label": "Crypto scan guard",
                        "value": "signal_only, no order payload generated",
                        "tone": "success",
                    }
                ],
            }

        monkeypatch.setattr("berkshire_routes.scan_crypto_market", fake_scan_crypto_market)
        client = _client(tmp_data_dir)

        res = client.post("/api/berkshire/crypto/scan", json={"symbols": ["BTC-USDT"], "limit": 1})

        assert res.status_code == 201
        body = res.json()
        assert body["scan"]["mode"] == "signal_only"
        assert body["scan"]["signals"][0]["llm_context"]["candidate_action"] == "OPEN_LONG"
        assert body["state"]["latest_crypto_scan"]["id"] == "bscan_test"

        persisted = client.get("/api/berkshire/state").json()
        assert persisted["crypto_scans"][0]["id"] == "bscan_test"

    def test_crypto_scan_can_auto_promote_demo_signal(self, tmp_data_dir, monkeypatch):
        def fake_scan_crypto_market(**_kwargs):
            return {
                "id": "bscan_promote",
                "created_at": "2026-06-30T00:00:00+00:00",
                "market": "crypto",
                "mode": "signal_only",
                "source": "test",
                "provider_error": None,
                "universe_count": 1,
                "signal_count": 1,
                "top_symbol": "BTC-USDT",
                "top_signal": "candidate",
                "signals": [
                    {
                        "signal_id": "sig_promote",
                        "generated_at": "2026-06-30T00:00:00+00:00",
                        "source": "berkshire_crypto_scanner",
                        "market": "crypto",
                        "symbol": "BTC-USDT",
                        "timeframe": "24h_ticker",
                        "direction": "long",
                        "status": "candidate",
                        "signal": "candidate",
                        "score": 72,
                        "grade": "B",
                        "confidence": 0.72,
                        "action_hint": "OPEN_LONG",
                        "mode": "signal_only",
                        "time_horizon": "swing_2d_7d",
                        "promotion_gate": "eligible_for_draft_ticket",
                        "last_price": "100.0000",
                        "entry_zone": "99.5000 - 100.5000",
                        "invalidation": "95.0000",
                        "target_zone": "110.0000",
                        "risk_reward": "2.0000",
                        "reasons": ["directional setup"],
                        "why": ["directional setup"],
                        "blockers": [],
                        "llm_context": {
                            "role": "advisory_signal_context",
                            "candidate_action": "OPEN_LONG",
                            "ticket_gate": "eligible_for_draft_ticket",
                            "instruction": "Use as evidence only.",
                            "prompt_context": "BTC-USDT advisory context",
                        },
                        "evidence": {"provider_source": "okx_public_tickers", "last_price": "100.0000"},
                    }
                ],
                "audit": [],
            }

        class FakePromotion:
            def to_dict(self):
                return {
                    "signal_id": "sig_promote",
                    "promoted": True,
                    "executed": True,
                    "stage": "execution",
                    "reason": "paper_demo_executed",
                    "decision_id": "sigexec_sig_promote",
                }

        seen: dict[str, object] = {}

        def fake_run_signal_to_demo_execution(signal, **kwargs):
            seen["signal_id"] = signal["signal_id"]
            seen["equity"] = kwargs["equity"]
            return FakePromotion()

        monkeypatch.setattr("berkshire_routes.scan_crypto_market", fake_scan_crypto_market)
        monkeypatch.setattr("berkshire_routes.run_signal_to_demo_execution", fake_run_signal_to_demo_execution)
        client = _client(tmp_data_dir)

        res = client.post(
            "/api/berkshire/crypto/scan",
            json={
                "symbols": ["BTC-USDT"],
                "limit": 1,
                "auto_promote_demo": True,
                "max_promotions": 1,
                "equity_usd": 12345,
            },
        )

        assert res.status_code == 201
        body = res.json()
        assert seen == {"signal_id": "sig_promote", "equity": 12345.0}
        assert body["scan"]["demo_promotions"][0]["executed"] is True
        assert body["state"]["latest_crypto_scan"]["demo_promotions"][0]["reason"] == "paper_demo_executed"


class TestBerkshireScanner:
    """Standalone crypto scanner behavior."""

    def test_scan_crypto_market_scores_long_signal_and_llm_context(self):
        def fetcher(_url: str):
            return {
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "105",
                        "open24h": "100",
                        "high24h": "108",
                        "low24h": "99",
                        "volCcy24h": "2000000000",
                        "bidPx": "104.99",
                        "askPx": "105.01",
                    }
                ]
            }

        scan = scan_crypto_market(
            symbols=["BTC-USDT"],
            limit=1,
            tickers_fetcher=fetcher,
            feature_fetcher=lambda _symbol: _scanner_feature_snapshot(),
        )

        signal = scan["signals"][0]
        assert scan["mode"] == "signal_only"
        assert signal["source"] == "berkshire_crypto_scanner"
        assert signal["status"] == "strong_candidate"
        assert signal["action_hint"] == "OPEN_LONG"
        assert signal["promotion_gate"] == "eligible_for_draft_ticket"
        assert signal["confidence_components"]["final"] == signal["confidence"]
        assert signal["signal"] == "strong_candidate"
        assert signal["direction"] == "long"
        experiment = signal["experimental_scores"]["continuous_conflict_v2"]
        assert experiment["mode"] == "shadow_only"
        assert experiment["active_for_routing"] is False
        assert signal["evidence"]["experimental_scores"] == signal[
            "experimental_scores"
        ]
        assert signal["llm_context"]["candidate_action"] == "OPEN_LONG"
        assert "advisory evidence only" in signal["llm_context"]["instruction"]
        validate_signal_candidate(signal)

    def test_scanner_injects_reviewed_canonical_thresholds(self, monkeypatch):
        seen: dict[str, float] = {}
        policy = DecisionPolicy(
            profile="adaptive_hybrid_v1",
            strong_min_score=75,
            gray_min_score=55,
            strong_lane="rules_baseline",
            gray_lane="rules_plus_llm",
            reject_lane="no_trade",
            gray_requires_llm=True,
            review_risk_multipliers=(0.0, 0.5, 1.0),
            live_enabled=False,
        )

        def fake_setup(_snapshot, _team_id, **kwargs):
            seen["strong"] = kwargs["strong_min_score"]
            seen["gray"] = kwargs["gray_min_score"]
            return {
                "direction": "long",
                "eligible": True,
                "score": 57,
                "confidence": 0.57,
                "blockers": [],
                "hard_blockers": [],
                "conflicts": [],
                "reasons": ["reviewed threshold candidate"],
                "levels": {"entry": 100, "stop_loss": 95, "take_profit": 110, "rr": 2},
                "setup_quality": {"rule_score": 57},
                "score_components": {"base_setup_quality": 0.57},
                "decision_zone": "gray",
                "confidence_calibrated": False,
                "setup_confluence_score": 1.0,
            }

        monkeypatch.setattr(
            "berkshire_scanner.load_decision_policy",
            lambda: (_ for _ in ()).throw(AssertionError("policy was reloaded")),
        )
        monkeypatch.setattr("berkshire_scanner.evaluate_strategy_setup", fake_setup)

        scan = scan_crypto_market(
            symbols=["BTC-USDT"],
            limit=1,
            tickers_fetcher=lambda _url: {
                "data": [{
                    "instId": "BTC-USDT-SWAP",
                    "last": "100",
                    "open24h": "99",
                    "high24h": "102",
                    "low24h": "98",
                    "volCcy24h": "2000000000",
                    "bidPx": "99.99",
                    "askPx": "100.01",
                }]
            },
            feature_fetcher=lambda _symbol: _scanner_feature_snapshot(price=100),
            decision_policy=policy,
        )

        signal = scan["signals"][0]
        assert seen == {"strong": 75, "gray": 55}
        assert signal["score"] == 57
        assert signal["decision_zone"] == "gray"
        assert signal["status"] == "candidate"
        assert signal["action_hint"] == "OPEN_LONG"
        assert scan["decision_policy"]["zones"] == {
            "strong_min_score": 75,
            "gray_min_score": 55,
        }

    def test_scan_crypto_market_supports_mean_reversion_team(self):
        def fetcher(_url: str):
            return {
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "105",
                        "open24h": "100",
                        "high24h": "108",
                        "low24h": "99",
                        "volCcy24h": "2000000000",
                        "bidPx": "104.99",
                        "askPx": "105.01",
                    }
                ]
            }

        scan = scan_crypto_market(
            symbols=["BTC-USDT"],
            limit=1,
            tickers_fetcher=fetcher,
            feature_fetcher=lambda _symbol: _scanner_feature_snapshot(mean_reversion=True),
            team_id="mean_reversion",
        )

        signal = scan["signals"][0]
        assert scan["team_id"] == "mean_reversion"
        assert signal["source"] == "team_mean_reversion_scanner"
        assert signal["team_name"] == "Mean Reversion"
        assert signal["direction"] == "short"
        assert signal["action_hint"] == "OPEN_SHORT"
        assert signal["target_risk_pct_equity"] == 0.03
        assert signal["preferred_playbook_ids"] == ["PB_CRYPTO_MEAN_REVERSION_001"]
        assert "SOFT_STRATEGY_TEAM_001" in signal["required_soft_policy_ids"]
        assert signal["llm_context"]["skill_profile"]["entry_style"] == signal["entry_style"]
        assert signal["evidence"]["skill_profile"]["risk_personality"] == signal["risk_personality"]
        validate_signal_candidate(signal)

    def test_scan_crypto_market_preserves_micro_price_precision(self):
        def fetcher(_url: str):
            return {
                "data": [
                    {
                        "instId": "BONK-USDT-SWAP",
                        "last": "0.00001234",
                        "open24h": "0.00001100",
                        "high24h": "0.00001300",
                        "low24h": "0.00001000",
                        "volCcy24h": "90000000000000",
                        "bidPx": "0.00001233",
                        "askPx": "0.00001235",
                    }
                ]
            }

        scan = scan_crypto_market(
            symbols=["BONK-USDT"],
            limit=1,
            tickers_fetcher=fetcher,
            feature_fetcher=lambda _symbol: _scanner_feature_snapshot(price=0.00001234),
        )

        signal = scan["signals"][0]
        assert signal["last_price"] == "0.00001234"
        assert float(signal["last_price"]) > 0
        assert all(float(value.strip()) > 0 for value in signal["entry_zone"].split("-"))
        validate_signal_candidate(signal)

    def test_scan_crypto_market_blocks_missing_provider_data(self, monkeypatch):
        def broken_fetcher(**_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr("berkshire_scanner._fetch_okx_tickers", broken_fetcher)

        scan = scan_crypto_market(symbols=["ETH-USDT"], limit=1)

        signal = scan["signals"][0]
        assert signal["signal"] == "blocked"
        assert signal["status"] == "blocked"
        assert signal["action_hint"] == "REQUEST_MORE_DATA"
        assert signal["llm_context"]["candidate_action"] == "REQUEST_MORE_DATA"
        assert "okx_ticker_provider_failed: provider unavailable" in signal["blockers"]
        validate_signal_candidate(signal)

    def test_rank_signal_candidates_prefers_confidence_over_score(self):
        ranked = rank_signal_candidates(
            [
                {"symbol": "LOW-USDT", "confidence": 0.55, "score": 99, "volume_usd_24h": "1000000000"},
                {"symbol": "HIGH-USDT", "confidence": 0.81, "score": 70, "volume_usd_24h": "1000000"},
            ]
        )

        assert [item["symbol"] for item in ranked] == ["HIGH-USDT", "LOW-USDT"]

    def test_scan_crypto_market_defaults_to_top50_universe(self, monkeypatch):
        metas = [
            SimpleNamespace(spot_symbol=f"COIN{i}-USDT", swap_symbol=f"COIN{i}-USDT-SWAP")
            for i in range(50)
        ]

        def fake_tickers(**_kwargs):
            return [
                {
                    "instId": f"COIN{i}-USDT-SWAP",
                    "last": "105",
                    "open24h": "100",
                    "high24h": "108",
                    "low24h": "99",
                    "volCcy24h": str(1_000_000 + i),
                    "bidPx": "104.99",
                    "askPx": "105.01",
                }
                for i in range(50)
            ]

        monkeypatch.setattr("berkshire_scanner._load_universe", lambda top_n: SimpleNamespace(symbols=metas[:top_n]))
        monkeypatch.setattr("berkshire_scanner._fetch_okx_tickers", fake_tickers)
        monkeypatch.setattr(
            "berkshire_scanner.build_market_feature_snapshot",
            lambda _symbol: _scanner_feature_snapshot(),
        )

        scan = scan_crypto_market()

        assert scan["universe_count"] == 50
        assert scan["signal_count"] == 50
        assert all("confidence_components" in signal for signal in scan["signals"])
