"""Tests for the read-only Telegram trading cockpit."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import telegram_dashboard as dashboard


def _snapshot() -> dict:
    return {
        "running": True,
        "timestamp": "2026-07-19T12:00:00+07:00",
        "trading_blocked": False,
        "trading_block_reason": "",
        "positions": [
            {
                "symbol": "BTC-<TEST>",
                "side": "buy",
                "status": "pending_entry",
                "entry": 100.0,
                "mark_price": 101.0,
                "stop_loss": 98.0,
                "take_profit": 104.0,
                "position_size": 0.2,
                "broker_contracts": 2,
                "risk_usd": 4.0,
                "margin_used_usd": 10.0,
                "leverage": 2,
                "team_id": "momentum",
                "team_name": "Momentum & Sons",
                "unrealized_pnl": 0.2,
            }
        ],
        "closed_trades": [],
        "stats": {
            "winrate": 50.0,
            "max_drawdown_usd": 3.0,
            "total_pnl_usd": 5.0,
            "daily_llm_cost": {
                "cost_usd": 0.1,
                "cap_usd": 0.2,
                "pct_of_cap": 50.0,
                "calls": 5,
                "call_cap": 120,
                "hourly_calls": 2,
                "hourly_call_cap": 12,
            },
        },
        "account_state": {
            "source": "okx_demo",
            "current_capital_usd": 205.0,
            "available_balance_usd": 195.0,
            "margin_used_usd": 10.0,
            "journal_realized_pnl_usd": 5.0,
            "unrealized_pnl_usd": 0.2,
        },
        "strategy_teams": [
            {
                "rank": 1,
                "team_id": "momentum",
                "team_name": "Momentum",
                "team_capital_usd": 200.0,
                "current_equity_usd": 205.2,
                "realized_pnl_usd": 5.0,
                "unrealized_pnl_usd": 0.2,
                "closed_trades": 2,
                "winrate": 50.0,
                "expectancy_r": 0.3,
                "profit_factor": 1.4,
                "max_drawdown_usd": 3.0,
                "competition_score": 4.2,
                "ranking_status": "provisional",
            }
        ],
        "llm_decisions": [
            {
                "decision_id": "decision-1",
                "ts": "2026-07-19T11:59:00+07:00",
                "team_id": "momentum",
                "team_name": "Momentum",
                "symbol": "BTC-USDT",
                "action": "OPEN_LONG",
                "confidence": 0.8,
                "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
                "reasoning": "Confirmed pullback and reclaim.",
            }
        ],
        "decisions": [
            {
                "type": "final_ticket",
                "decision_id": "decision-1",
                "payload": {"reason": "approved"},
            }
        ],
        "sync_status": {"status": "ok", "synced_at": "2026-07-19T12:00:00+07:00"},
        "_telegram_source": {"source": "trader_status_api", "fallback": False},
    }


def test_render_views_escape_dynamic_html_and_fit_limit() -> None:
    rendered = dashboard.render_dashboard(_snapshot(), view="positions")

    assert "BTC-&lt;TEST&gt;" in rendered.text
    assert "Momentum &amp; Sons" in rendered.text
    assert len(rendered.text) <= dashboard.MAX_TEXT_LEN
    assert rendered.reply_markup["inline_keyboard"]


def test_decision_detail_uses_stable_callback_key_and_timeline() -> None:
    snapshot = _snapshot()
    key = dashboard.decision_key(snapshot["llm_decisions"][0])

    rendered = dashboard.render_dashboard(
        snapshot,
        view="decision",
        detail_key=key,
    )

    assert "decision-1" in rendered.text
    assert "Lifecycle" in rendered.text
    assert "final_ticket" in rendered.text


def test_performance_metrics_are_fee_aware_and_windowed() -> None:
    now = datetime.fromisoformat("2026-07-19T12:00:00+07:00")
    trades = [
        {
            "closed_at": "2026-07-19T08:00:00+07:00",
            "gross_pnl_usd": 12.0,
            "fees_usd": 2.0,
            "pnl_usd": 10.0,
            "risk_usd": 5.0,
        },
        {
            "closed_at": "2026-07-18T08:00:00+07:00",
            "gross_pnl_usd": -4.0,
            "fees_usd": 1.0,
            "pnl_usd": -5.0,
            "risk_usd": 5.0,
        },
    ]

    today = dashboard.performance_metrics(trades, window="today", now=now)
    seven_days = dashboard.performance_metrics(trades, window="7d", now=now)

    assert today["trades"] == 1
    assert today["gross_pnl_usd"] == 12.0
    assert today["fees_usd"] == 2.0
    assert today["net_pnl_usd"] == 10.0
    assert seven_days["trades"] == 2
    assert seven_days["net_pnl_usd"] == 5.0
    assert seven_days["expectancy_r"] == 0.5


def test_state_store_round_trip_and_corrupt_fallback(tmp_path) -> None:
    path = tmp_path / "telegram" / "dashboard_state.json"
    store = dashboard.DashboardStateStore(path)
    state = dashboard.DashboardState(message_id=123, view="teams", page=2)

    store.save(state)
    loaded = store.load()

    assert loaded.message_id == 123
    assert loaded.view == "teams"
    assert loaded.page == 2
    path.write_text("{broken", encoding="utf-8")
    assert store.load() == dashboard.DashboardState()


def test_callback_parser_rejects_mutating_or_invalid_namespaces() -> None:
    assert dashboard.parse_dashboard_callback("dash:positions:2") == ("positions", 2, None)
    assert dashboard.parse_dashboard_callback("dash:decision:0:abc123") == ("decision", 0, "abc123")
    assert dashboard.parse_dashboard_callback("trade:close:BTC") is None
    assert dashboard.parse_dashboard_callback("dash:close:0") is None
    assert dashboard.parse_dashboard_callback("dash:positions:not-a-page") is None


def test_snapshot_provider_uses_api_payload(monkeypatch) -> None:
    response = SimpleNamespace(
        ok=True,
        status_code=200,
        json=lambda: {"running": True, "positions": []},
    )
    monkeypatch.setattr(dashboard.requests, "get", lambda *args, **kwargs: response)

    snapshot = dashboard.TelegramSnapshotProvider("http://status").load()

    assert snapshot["running"] is True
    assert snapshot["_telegram_source"]["source"] == "trader_status_api"
    assert snapshot["_telegram_source"]["fallback"] is False


def test_snapshot_provider_labels_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests_error()),
    )
    monkeypatch.setattr(
        dashboard,
        "build_local_snapshot",
        lambda *, error: {"_telegram_source": {"fallback": True, "error": error}},
    )

    snapshot = dashboard.TelegramSnapshotProvider("http://status").load()

    assert snapshot["_telegram_source"]["fallback"] is True
    assert "offline" in snapshot["_telegram_source"]["error"]


def test_corrupt_positions_degrades_without_reporting_false_flat(monkeypatch) -> None:
    import journal

    def corrupt_positions() -> list[dict]:
        raise journal.JournalCorruptError("positions.json corrupt")

    monkeypatch.setattr(journal, "ensure_dirs", lambda: None)
    monkeypatch.setattr(journal, "read_positions", corrupt_positions)
    monkeypatch.setattr(journal, "read_closed_trades", lambda: [])
    monkeypatch.setattr(journal, "read_stats", lambda: {})
    monkeypatch.setattr(journal, "daily_cost_status", lambda: {})
    monkeypatch.setattr(journal, "read_llm_decisions", lambda **kwargs: [])
    monkeypatch.setattr(journal, "is_killed", lambda: False)
    monkeypatch.setattr(journal, "is_trading_blocked", lambda: False)
    monkeypatch.setattr(journal, "trading_block_reason", lambda: "")
    monkeypatch.setattr(journal, "startup_sync_guard_active", lambda: False)

    snapshot = dashboard.build_local_snapshot(error="status API failed")
    rendered = dashboard.render_dashboard(snapshot, view="positions")

    assert snapshot["positions"] == []
    assert "positions" in snapshot["_telegram_source"]["component_errors"]
    assert "không khả dụng" in rendered.text
    assert "Không có lệnh open" not in rendered.text


def test_snapshot_provider_returns_minimal_snapshot_when_fallback_crashes(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("api offline")),
    )
    monkeypatch.setattr(
        dashboard,
        "build_local_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("journal offline")),
    )

    snapshot = dashboard.TelegramSnapshotProvider("http://status").load()

    assert snapshot["state_unknown"] is True
    assert snapshot["_telegram_source"]["source"] == "minimal_fallback"
    assert "positions" in snapshot["_telegram_source"]["component_errors"]


def requests_error() -> RuntimeError:
    """Return a deterministic network-like error for provider tests."""
    return RuntimeError("offline")


def test_dashboard_content_hash_changes_with_keyboard() -> None:
    first = dashboard.render_dashboard(_snapshot(), view="overview")
    second = dashboard.render_dashboard(_snapshot(), view="teams")

    assert dashboard.content_hash(first) != dashboard.content_hash(second)


def test_state_file_is_valid_json(tmp_path) -> None:
    path = tmp_path / "dashboard_state.json"
    dashboard.DashboardStateStore(path).save(dashboard.DashboardState(message_id=7))

    assert json.loads(path.read_text(encoding="utf-8"))["message_id"] == 7
