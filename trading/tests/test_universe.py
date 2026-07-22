"""Unit tests for universe loader and LLM override tracker.

Run with: pytest tests/test_universe.py tests/test_llm_override_tracker.py -x
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TRADING = Path(__file__).parent.parent
sys.path.insert(0, str(TRADING / "auto"))

import universe  # noqa: E402
import llm_override_tracker as ot  # noqa: E402


# ---------------------------------------------------------------------------
# Universe loader
# ---------------------------------------------------------------------------

class TestUniverseFallback:
    def test_hardcoded_has_50_symbols(self):
        assert len(universe.HARDCODED_UNIVERSE) == 50
        assert all(s.max_notional_pct == pytest.approx(0.20) for s in universe.HARDCODED_UNIVERSE)

    def test_top_bases_keep_original_core_universe(self):
        bases = {s.base for s in universe.HARDCODED_UNIVERSE}
        assert {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "TRX", "LINK"}.issubset(bases)

    def test_load_universe_falls_back_on_api_fail(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
        snap = universe.load_universe(fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("boom")))
        assert snap.source == "fallback_hardcoded"
        assert len(snap.symbols) == 50

    def test_env_override_skips_api(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
        monkeypatch.setenv("UNIVERSE_OVERRIDE", "BTC-USDT-SWAP,ETH-USDT-SWAP")
        called_api = []
        def _fail(url):
            called_api.append(url)
            raise RuntimeError("should not be called")
        snap = universe.load_universe(fetcher=_fail)
        assert snap.source == "env_override"
        assert [s.base for s in snap.symbols] == ["BTC", "ETH"]
        assert called_api == []

    def test_env_override_allows_dynamic_non_stablecoin_symbol(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
        monkeypatch.setenv("UNIVERSE_OVERRIDE", "BTC-USDT-SWAP,FOO-USDT-SWAP")
        snap = universe.load_universe(fetcher=lambda url: {})
        assert [s.base for s in snap.symbols] == ["BTC", "FOO"]
        assert snap.symbols[1].leverage == 3

    def test_cache_used_when_api_fails(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
        # Pre-populate cache
        snap = universe.UniverseSnapshot(
            fetched_at=datetime.now(timezone.utc).isoformat(),
            source="okx_api",
            symbols=universe.HARDCODED_UNIVERSE[:3],
            raw_count=100,
        )
        universe.save_snapshot(snap)
        # Now call load_universe with broken API
        snap2 = universe.load_universe(
            fetcher=lambda url: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert snap2.source == "cache"
        assert len(snap2.symbols) == 3

    def test_stablecoin_filter(self):
        fake_tickers = [
            {"instId": "BTC-USDT-SWAP", "volCcy24h": "5000000000"},
            {"instId": "USDC-USDT-SWAP", "volCcy24h": "9999999999"},
            {"instId": "ETH-USDT-SWAP", "volCcy24h": "1000000000"},
            {"instId": "ETH-USD-SWAP", "volCcy24h": "9999999999"},  # wrong base ccy
        ]
        out = [universe._ticker_to_meta(t) for t in fake_tickers]
        # BTC and ETH pass; USDC filtered (stablecoin); ETH-USD filtered (not USDT)
        assert out[0] is not None
        assert out[1] is None  # USDC stablecoin
        assert out[2] is not None
        assert out[3] is None  # not USDT-margined

    def test_live_okx_universe_accepts_dynamic_top50_symbol(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
        fake_tickers = [
            {"instId": "FOO-USDT-SWAP", "volCcy24h": "100", "last": "10"},
            {"instId": "BTC-USDT-SWAP", "volCcy24h": "50", "last": "10"},
        ]

        snap = universe.load_universe(top_n=2, fetcher=lambda _url: {"data": fake_tickers})

        assert snap.source == "okx_api"
        assert [s.base for s in snap.symbols] == ["FOO", "BTC"]
        assert snap.symbols[0].leverage == 3

    def test_default_fetch_uses_simulated_swap_catalog_without_invalid_uly(self, monkeypatch):
        seen: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            @staticmethod
            def read() -> bytes:
                return json.dumps(
                    {"code": "0", "data": [{"instId": "BTC-USDT-SWAP"}]}
                ).encode("utf-8")

        def fake_urlopen(request, timeout):  # noqa: ANN001
            seen.update({"url": request.full_url, "headers": dict(request.header_items()), "timeout": timeout})
            return FakeResponse()

        import urllib.request

        monkeypatch.setenv("OKX_TESTNET", "true")
        monkeypatch.setenv("OKX_SANDBOX", "true")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        rows = universe.fetch_okx_swap_tickers()

        assert rows == [{"instId": "BTC-USDT-SWAP"}]
        assert str(seen["url"]).endswith("/api/v5/market/tickers?instType=SWAP")
        assert "uly=" not in str(seen["url"])
        headers = {str(key).lower(): value for key, value in dict(seen["headers"]).items()}
        assert headers["x-simulated-trading"] == "1"


class TestUniverseSnapshotIO:
    def test_save_and_load(self, tmp_path):
        snap = universe.UniverseSnapshot(
            fetched_at=datetime.now(timezone.utc).isoformat(),
            source="test",
            symbols=universe.HARDCODED_UNIVERSE[:2],
            raw_count=10,
        )
        path = tmp_path / "u.json"
        universe.save_snapshot(snap, path=path)
        loaded = universe.load_cached_snapshot(path=path)
        assert loaded is not None
        assert loaded.source == "cache"
        assert len(loaded.symbols) == 2
        assert loaded.symbols[0].base == "BTC"

    def test_is_stale(self):
        old = universe.UniverseSnapshot(
            fetched_at="2020-01-01T00:00:00+00:00",
            source="x", symbols=[],
        )
        assert universe.is_stale(old) is True

        fresh = universe.UniverseSnapshot(
            fetched_at=datetime.now(timezone.utc).isoformat(),
            source="x", symbols=[],
        )
        assert universe.is_stale(fresh) is False


# ---------------------------------------------------------------------------
# LLM override tracker
# ---------------------------------------------------------------------------

class TestOverrideTracker:
    def _rec(self, symbol, win=None, used=True):
        return ot.OverrideRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            symbol=symbol,
            llm_action="long",
            rules_action="no_trade",
            llm_overrode=True,
            used_override=used,
            closed_at=datetime.now(timezone.utc).isoformat() if win is not None else None,
            pnl_usd=10.0 if win else -10.0,
            win=win,
        )

    def test_append_and_iter(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        for i in range(3):
            tracker.append(self._rec("BTC", win=True))
        recs = list(tracker.iter_all())
        assert len(recs) == 3
        assert all(r.symbol == "BTC" for r in recs)

    def test_winrate_empty(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        wr, n = tracker.winrate()
        assert wr == 0.0
        assert n == 0

    def test_winrate_60_percent(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        for i in range(10):
            tracker.append(self._rec("BTC", win=(i < 6)))
        wr, n = tracker.winrate()
        assert n == 10
        assert wr == pytest.approx(0.6, rel=1e-9)

    def test_get_recent_filters_unused(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        tracker.append(self._rec("BTC", used=True, win=True))
        tracker.append(self._rec("BTC", used=False, win=False))  # not used
        recs = tracker.get_recent_overrides(only_used=True)
        assert len(recs) == 1
        assert recs[0].used_override is True

    def test_get_recent_filters_unclosed(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        tracker.append(self._rec("BTC", win=True))           # closed
        tracker.append(self._rec("BTC", used=True))           # no close
        recs = tracker.get_recent_overrides(only_closed=True)
        assert len(recs) == 1
        assert recs[0].closed_at is not None

    def test_mark_closed_updates_most_recent(self, tmp_path):
        tracker = ot.OverrideTracker(path=tmp_path / "log.jsonl")
        tracker.append(self._rec("BTC"))  # not closed
        n = tracker.mark_closed("BTC", pnl_usd=15.0, win=True)
        assert n == 1
        # Now winrate should reflect 1 win
        wr, n = tracker.winrate()
        assert n == 1
        assert wr == 1.0


class TestHybridOverrideGate:
    def test_disabled_gate(self, tmp_path):
        gate = ot.HybridOverrideGate(
            tracker=ot.OverrideTracker(path=tmp_path / "log.jsonl"),
            enabled=False,
        )
        ok, reason = gate.allow("BTC-USDT-SWAP")
        assert ok is False
        assert "disabled" in reason

    def test_cold_start_blocks(self, tmp_path):
        gate = ot.HybridOverrideGate(
            tracker=ot.OverrideTracker(path=tmp_path / "log.jsonl"),
            enabled=True, min_samples=20, threshold=0.6, lookback=30,
        )
        ok, reason = gate.allow("BTC-USDT-SWAP")
        assert ok is False
        assert "cold start" in reason

    def test_below_threshold_blocks(self, tmp_path):
        gate = ot.HybridOverrideGate(
            tracker=ot.OverrideTracker(path=tmp_path / "log.jsonl"),
            enabled=True, min_samples=5, threshold=0.6, lookback=30,
        )
        for i in range(10):
            rec = ot.OverrideRecord(
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                llm_action="long", rules_action="no_trade",
                llm_overrode=True, used_override=True,
                closed_at=datetime.now(timezone.utc).isoformat(),
                pnl_usd=-10.0, win=(i < 4),  # 4/10 = 40% < 60%
            )
            gate.record(rec)
        ok, reason = gate.allow("BTC-USDT-SWAP")
        assert ok is False
        assert "underperforming" in reason

    def test_above_threshold_allows(self, tmp_path):
        gate = ot.HybridOverrideGate(
            tracker=ot.OverrideTracker(path=tmp_path / "log.jsonl"),
            enabled=True, min_samples=5, threshold=0.6, lookback=30,
        )
        for i in range(10):
            rec = ot.OverrideRecord(
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                llm_action="long", rules_action="no_trade",
                llm_overrode=True, used_override=True,
                closed_at=datetime.now(timezone.utc).isoformat(),
                pnl_usd=10.0, win=(i < 7),  # 7/10 = 70% > 60%
            )
            gate.record(rec)
        ok, reason = gate.allow("BTC-USDT-SWAP")
        assert ok is True
        assert "allowed" in reason

    def test_per_symbol_isolation(self, tmp_path):
        gate = ot.HybridOverrideGate(
            tracker=ot.OverrideTracker(path=tmp_path / "log.jsonl"),
            enabled=True, min_samples=3, threshold=0.6, lookback=30,
        )
        # BTC wins
        for i in range(5):
            rec = ot.OverrideRecord(
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="BTC-USDT-SWAP",
                llm_action="long", rules_action="no_trade",
                llm_overrode=True, used_override=True,
                closed_at=datetime.now(timezone.utc).isoformat(),
                pnl_usd=10.0, win=True,
            )
            gate.record(rec)
        # ETH loses
        for i in range(5):
            rec = ot.OverrideRecord(
                ts=datetime.now(timezone.utc).isoformat(),
                symbol="ETH-USDT-SWAP",
                llm_action="long", rules_action="no_trade",
                llm_overrode=True, used_override=True,
                closed_at=datetime.now(timezone.utc).isoformat(),
                pnl_usd=-10.0, win=False,
            )
            gate.record(rec)
        ok_btc, _ = gate.allow("BTC-USDT-SWAP")
        ok_eth, _ = gate.allow("ETH-USDT-SWAP")
        assert ok_btc is True
        assert ok_eth is False
