"""Tests for AI Berkshire research desk routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from berkshire_routes import register_berkshire_routes


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

