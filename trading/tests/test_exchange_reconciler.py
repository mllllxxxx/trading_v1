"""Tests for OKX demo exchange-to-journal reconciliation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _load_modules(tmp_data_dir):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auto"))
    import journal  # type: ignore
    import exchange_reconciler  # type: ignore
    importlib.reload(journal)
    importlib.reload(exchange_reconciler)
    return journal, exchange_reconciler


def test_symbol_normalization_handles_okx_and_ccxt_swap(tmp_data_dir):
    _journal, reconciler = _load_modules(tmp_data_dir)

    assert reconciler.canonical_symbol("BTC-USDT") == "BTC-USDT"
    assert reconciler.canonical_symbol("BTC-USDT-SWAP") == "BTC-USDT"
    assert reconciler.canonical_symbol("BTC/USDT:USDT") == "BTC-USDT"
    assert reconciler.ccxt_swap_symbol("BTC-USDT") == "BTC/USDT:USDT"
    assert reconciler.okx_swap_symbol("BTC/USDT:USDT") == "BTC-USDT-SWAP"


def test_reconcile_imports_missing_exchange_position(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    assert journal.read_positions() == []
    snapshot = {
        "fetched_at": "2026-07-01T00:00:00Z",
        "exchange": "okx",
        "mode": "demo",
        "positions": [
            reconciler.normalize_exchange_position(
                {
                    "symbol": "BTC/USDT:USDT",
                    "side": "short",
                    "contracts": 3,
                    "entryPrice": 58500,
                    "markPrice": 58400,
                    "unrealizedPnl": 3.0,
                    "leverage": 10,
                    "marginMode": "isolated",
                    "info": {"instId": "BTC-USDT-SWAP", "posSide": "net"},
                },
                pending_algo=[
                    {
                        "instId": "BTC-USDT-SWAP",
                        "algoId": "oco-1",
                        "ordType": "oco",
                        "side": "buy",
                        "state": "live",
                        "sz": "3",
                        "tpTriggerPx": "56200",
                        "slTriggerPx": "59700",
                    }
                ],
                fetched_at="2026-07-01T00:00:00Z",
            )
        ],
        "pending_algo": [],
        "errors": [],
    }

    status = reconciler.reconcile_journal_with_exchange(
        snapshot=snapshot,
        journal_module=journal,
    )

    positions = journal.read_positions()
    assert status["status"] == "journal_missing"
    assert len(positions) == 1
    assert positions[0]["symbol"] == "BTC-USDT"
    assert positions[0]["ccxt_symbol"] == "BTC/USDT:USDT"
    assert positions[0]["position_size"] == 0.03
    assert positions[0]["status"] == "exchange_open"
    assert positions[0]["stop_loss"] == 59700
    assert positions[0]["take_profit"] == 56200


def test_normalize_exchange_position_uses_broker_contract_size(tmp_data_dir):
    _journal, reconciler = _load_modules(tmp_data_dir)

    position = reconciler.normalize_exchange_position(
        {
            "symbol": "NEAR/USDT:USDT",
            "side": "long",
            "contracts": 20,
            "contractSize": 10,
            "notional": 385.52908,
            "entryPrice": 1.93,
            "markPrice": 1.946,
            "unrealizedPnl": 3.2,
            "leverage": 3,
            "marginMode": "isolated",
            "info": {"instId": "NEAR-USDT-SWAP", "posSide": "net"},
        },
        fetched_at="2026-07-01T00:00:00Z",
    )

    assert position is not None
    assert position["symbol"] == "NEAR-USDT"
    assert position["contracts"] == 20
    assert position["contract_size"] == 10
    assert position["position_size"] == 200
    assert position["notional"] == 385.52908


def test_reconcile_does_not_mark_pending_entry_missing_on_exchange(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    journal.add_position(
        {
            "symbol": "NEAR-USDT",
            "side": "buy",
            "entry": 1.93,
            "stop_loss": 1.88,
            "take_profit": 2.03,
            "position_size": 20.0,
            "risk_usd": 1.0,
            "status": "pending_entry",
            "entry_filled": False,
            "orders": {"entry_id": "okx-entry-123", "status": "okx_demo_accepted"},
        }
    )
    snapshot = {
        "fetched_at": "2026-07-01T00:00:00Z",
        "exchange": "okx",
        "mode": "demo",
        "positions": [],
        "pending_algo": [],
        "errors": [],
    }

    status = reconciler.reconcile_journal_with_exchange(
        snapshot=snapshot,
        journal_module=journal,
    )

    assert status["status"] == "in_sync"
    assert status["missing_on_exchange"] == []
    assert status["positions_in_journal"] == 1
    assert journal.read_positions()[0]["status"] == "pending_entry"


def test_reconcile_preserves_canary_attribution_on_restart(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    journal.add_position(
        {
            "symbol": "BTC-USDT",
            "side": "buy",
            "entry": 58_500,
            "stop_loss": 57_500,
            "take_profit": 60_500,
            "position_size": 0.01,
            "risk_usd": 10.0,
            "status": "open",
            "entry_filled": True,
            "routing_experiment": {
                "approval_id": "approval-1",
                "candidate_fingerprint": "candidate-1",
            },
        }
    )
    exchange_position = reconciler.normalize_exchange_position(
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "contracts": 1,
            "contractSize": 0.01,
            "entryPrice": 58_500,
            "markPrice": 58_600,
            "unrealizedPnl": 1.0,
            "leverage": 3,
            "marginMode": "isolated",
            "info": {"instId": "BTC-USDT-SWAP", "posSide": "net"},
        },
        fetched_at="2026-07-01T00:00:00Z",
    )

    reconciler.reconcile_journal_with_exchange(
        snapshot={
            "fetched_at": "2026-07-01T00:00:00Z",
            "exchange": "okx",
            "mode": "demo",
            "positions": [exchange_position],
            "pending_algo": [],
            "errors": [],
        },
        journal_module=journal,
    )

    position = journal.read_positions()[0]
    assert position["sync_status"] == "in_sync"
    assert position["routing_experiment"]["approval_id"] == "approval-1"


def test_reconcile_pending_entry_expires_without_closed_trade(tmp_data_dir, monkeypatch):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    monkeypatch.setenv("OKX_TESTNET", "true")
    monkeypatch.setenv("OKX_SANDBOX", "true")
    monkeypatch.setenv("AUTO_PENDING_ENTRY_TTL_S", "3600")
    journal.add_position(
        {
            "position_id": "pending-1",
            "symbol": "NEAR-USDT",
            "side": "buy",
            "entry": 1.93,
            "stop_loss": 1.88,
            "take_profit": 2.03,
            "position_size": 20.0,
            "risk_usd": 1.0,
            "status": "pending_entry",
            "entry_filled": False,
            "opened_at": "2026-07-01T00:00:00Z",
            "orders": {"entry_id": "okx-entry-123", "status": "okx_demo_accepted"},
        }
    )
    exchange = MagicMock()
    exchange.fetch_order.return_value = {"id": "okx-entry-123", "status": "open"}
    exchange.cancel_order.return_value = {"id": "okx-entry-123", "status": "canceled"}

    status = reconciler.reconcile_pending_entries(
        exchange=exchange,
        snapshot={"positions": []},
        journal_module=journal,
        now_utc="2026-07-18T00:00:00Z",
    )

    assert status["resolved"] == 1
    assert status["retained"] == 0
    assert journal.read_positions() == []
    assert journal.read_closed_trades() == []
    exchange.fetch_order.assert_called_once_with("okx-entry-123", "NEAR/USDT:USDT")
    exchange.cancel_order.assert_called_once_with("okx-entry-123", "NEAR/USDT:USDT")
    decisions = [json.loads(line) for line in journal.DECISIONS_LOG.read_text().splitlines()]
    assert decisions[-1]["type"] == "pending_entry_resolved"
    assert decisions[-1]["reason"] == "ttl_expired_canceled"


def test_reconcile_pending_entry_preserves_order_outside_demo(tmp_data_dir, monkeypatch):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    monkeypatch.setenv("OKX_TESTNET", "false")
    monkeypatch.setenv("OKX_SANDBOX", "false")
    journal.add_position(
        {
            "position_id": "pending-live-guard",
            "symbol": "NEAR-USDT",
            "side": "buy",
            "entry": 1.93,
            "stop_loss": 1.88,
            "take_profit": 2.03,
            "position_size": 20.0,
            "risk_usd": 1.0,
            "entry_filled": False,
            "status": "pending_entry",
            "opened_at": "2026-07-01T00:00:00Z",
            "orders": {"entry_id": "entry-live-guard"},
        }
    )
    exchange = MagicMock()
    exchange.fetch_order.return_value = {"id": "entry-live-guard", "status": "open"}

    status = reconciler.reconcile_pending_entries(
        exchange=exchange,
        snapshot={"positions": []},
        journal_module=journal,
        now_utc="2026-07-18T00:00:00Z",
    )

    assert status["resolved"] == 0
    assert status["retained"] == 1
    assert "pending_cancel_blocked_outside_demo" in status["errors"][0]
    assert len(journal.read_positions()) == 1
    assert journal.read_closed_trades() == []
    exchange.cancel_order.assert_not_called()


def test_reconcile_archives_stale_filled_entry_without_fake_performance(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    journal.add_position(
        {
            "position_id": "pending-filled",
            "symbol": "LINK-USDT",
            "side": "buy",
            "entry": 7.5,
            "stop_loss": 7.35,
            "take_profit": 7.79,
            "position_size": 5.0,
            "risk_usd": 0.75,
            "entry_filled": False,
            "status": "pending_entry",
            "opened_at": "2026-07-01T00:00:00Z",
            "orders": {"entry_id": "filled-entry-123"},
        }
    )
    exchange = MagicMock()
    exchange.fetch_order.return_value = {
        "id": "filled-entry-123",
        "status": "closed",
        "filled": 5.0,
        "average": 7.5,
        "timestamp": 1782982722686,
    }

    status = reconciler.reconcile_pending_entries(
        exchange=exchange,
        snapshot={"positions": [], "errors": []},
        journal_module=journal,
        now_utc="2026-07-18T00:00:00Z",
    )

    assert status["resolved"] == 1
    assert status["unresolved"] == 1
    assert status["retained"] == 0
    assert journal.read_positions() == []
    assert journal.read_closed_trades() == []
    decisions = [json.loads(line) for line in journal.DECISIONS_LOG.read_text().splitlines()]
    resolution = decisions[-1]
    assert resolution["type"] == "pending_entry_resolved"
    assert resolution["reason"] == "filled_without_active_exposure"
    assert resolution["outcome_status"] == "unresolved"
    assert resolution["performance_eligible"] is False
    assert resolution["broker_evidence"]["filled"] == 5.0
    exchange.cancel_order.assert_not_called()


def test_reconcile_updates_existing_position_sizing_from_exchange(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    journal.add_position(
        {
            "symbol": "NEAR-USDT",
            "side": "buy",
            "entry": 1.93,
            "stop_loss": 1.88,
            "take_profit": 2.03,
            "position_size": 20.0,
            "contracts": 20.0,
            "contract_size": 1.0,
            "notional": 38.6,
            "risk_usd": 1.0,
            "status": "open",
            "entry_filled": True,
        }
    )
    exchange_position = reconciler.normalize_exchange_position(
        {
            "symbol": "NEAR/USDT:USDT",
            "side": "long",
            "contracts": 20,
            "contractSize": 10,
            "notional": 385.52908,
            "entryPrice": 1.93,
            "markPrice": 1.946,
            "unrealizedPnl": 3.2,
            "leverage": 3,
            "marginMode": "isolated",
            "info": {"instId": "NEAR-USDT-SWAP", "posSide": "net"},
        },
        fetched_at="2026-07-01T00:00:00Z",
    )

    status = reconciler.reconcile_journal_with_exchange(
        snapshot={
            "fetched_at": "2026-07-01T00:00:00Z",
            "exchange": "okx",
            "mode": "demo",
            "positions": [exchange_position],
            "pending_algo": [],
            "errors": [],
        },
        journal_module=journal,
    )

    position = journal.read_positions()[0]
    assert status["status"] == "in_sync"
    assert position["contract_size"] == 10
    assert position["position_size"] == 200
    assert position["notional"] == 385.52908
    assert position["leverage"] == 3
    assert position["margin_mode"] == "isolated"


def test_startup_reconciliation_imports_exchange_position_when_journal_empty(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "futures")
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    exchange = MagicMock()
    exchange.fetch_positions.return_value = [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "contracts": 2,
            "entryPrice": 60000,
            "markPrice": 60100,
            "unrealizedPnl": 2.0,
            "info": {"instId": "BTC-USDT-SWAP", "posSide": "net"},
        }
    ]

    status = reconciler.run_startup_reconciliation(
        trigger="test_startup",
        exchange=exchange,
        journal_module=journal,
        include_pending_algo=False,
    )

    positions = journal.read_positions()
    assert status["status"] == "ok"
    assert status["positions_on_exchange"] == 1
    assert len(positions) == 1
    assert positions[0]["symbol"] == "BTC-USDT"
    assert positions[0]["source"] == "exchange_reconciler"
    assert journal.startup_sync_guard_active() is False


def test_startup_reconciliation_failure_blocks_entries_without_deleting_positions(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("TRADE_MODE", "futures")
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    journal.add_position(
        {
            "symbol": "BTC-USDT",
            "side": "buy",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "position_size": 1.0,
            "risk_usd": 5.0,
        }
    )
    exchange = MagicMock()
    exchange.fetch_positions.side_effect = RuntimeError("okx unavailable")

    status = reconciler.run_startup_reconciliation(
        trigger="test_startup",
        exchange=exchange,
        journal_module=journal,
    )

    assert status["status"] == "error"
    assert status["positions_preserved"] is True
    assert [pos["symbol"] for pos in journal.read_positions()] == ["BTC-USDT"]
    assert journal.startup_sync_guard_active() is True
    assert journal.is_trading_blocked() is True
    assert journal.trading_block_reason() == "startup_sync_blocked"


def test_exchange_snapshot_omits_html_error_body(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    exchange = MagicMock()
    exchange.fetch_positions.side_effect = RuntimeError(
        "okx GET https://www.okx.com/api/v5/account/positions 502 Bad Gateway "
        "<!DOCTYPE html><html><body>Your IP: 203.0.113.10</body></html>"
    )

    snapshot = reconciler.fetch_okx_demo_snapshot(
        exchange=exchange,
        journal_module=journal,
    )

    assert snapshot["ok"] is False
    assert snapshot["errors"] == [
        "okx GET https://www.okx.com/api/v5/account/positions 502 Bad Gateway [html response omitted]"
    ]
    decisions = [json.loads(line) for line in journal.DECISIONS_LOG.read_text().splitlines()]
    assert decisions[-1]["error"] == snapshot["errors"][0]
    assert "203.0.113.10" not in decisions[-1]["error"]


def test_has_active_exchange_exposure_uses_normalized_symbol(tmp_data_dir):
    _journal, reconciler = _load_modules(tmp_data_dir)
    exchange = MagicMock()
    exchange.fetch_positions.return_value = [
        {
            "symbol": "ETH/USDT:USDT",
            "side": "short",
            "contracts": 126,
            "entryPrice": 1575,
            "markPrice": 1570,
            "info": {"instId": "ETH-USDT-SWAP"},
        }
    ]

    active, position, snapshot = reconciler.has_active_exchange_exposure(
        "ETH-USDT",
        exchange=exchange,
    )

    assert snapshot["ok"] is True
    assert active is True
    assert position is not None
    assert position["symbol"] == "ETH-USDT"
    assert position["position_size"] == 1.26


def test_account_balance_normalizes_exchange_equity(tmp_data_dir):
    _journal, reconciler = _load_modules(tmp_data_dir)
    account = reconciler.normalize_account_balance(
        {
            "total": {"USDT": 10021.5},
            "free": {"USDT": 9975.25},
            "used": {"USDT": 46.25},
            "info": {
                "data": [
                    {
                        "totalEq": "10023.45",
                        "details": [
                            {
                                "ccy": "USDT",
                                "eqUsd": "10023.45",
                                "availEq": "9980.12",
                                "imr": "43.33",
                                "upl": "-7.86",
                            }
                        ],
                    }
                ]
            },
        },
        fetched_at="2026-07-01T00:00:00Z",
        mode="demo",
        journal_stats={"starting_capital": 10000.0, "total_pnl_usd": 31.31},
        positions=[],
    )

    assert account["source"] == "okx_demo"
    assert account["current_capital_usd"] == 10023.45
    assert account["total_pnl_usd"] == 23.45
    assert account["unrealized_pnl_usd"] == -7.86
    assert account["journal_realized_pnl_usd"] == 31.31
    assert account["available_balance_usd"] == 9980.12
    assert account["margin_used_usd"] == 43.33


def test_account_balance_applies_200_usd_equity_cap(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("TRADING_RISK_PROFILE", "demo_small_200")
    monkeypatch.setenv("TRADING_EQUITY_CAP_USD", "200")
    _journal, reconciler = _load_modules(tmp_data_dir)

    account = reconciler.normalize_account_balance(
        {
            "total": {"USDT": 10021.5},
            "free": {"USDT": 9975.25},
            "used": {"USDT": 46.25},
            "info": {
                "data": [
                    {
                        "totalEq": "10023.45",
                        "details": [
                            {
                                "ccy": "USDT",
                                "eqUsd": "10023.45",
                                "availEq": "9980.12",
                                "imr": "43.33",
                                "upl": "-7.86",
                            }
                        ],
                    }
                ]
            },
        },
        fetched_at="2026-07-01T00:00:00Z",
        mode="demo",
        journal_stats={"starting_capital": 10000.0, "total_pnl_usd": 31.31},
        positions=[],
    )

    assert account["source"] == "okx_demo_capped"
    assert account["risk_profile"] == "demo_small_200"
    assert account["simulation_equity_cap_usd"] == 200.0
    assert account["starting_capital_usd"] == 200.0
    assert account["current_capital_usd"] == 223.45
    assert account["total_pnl_usd"] == 23.45
    assert account["available_balance_usd"] == 223.45
    assert account["actual_current_capital_usd"] == 10023.45
    assert account["actual_available_balance_usd"] == 9980.12
    assert account["actual_total_pnl_usd"] == 23.45
    assert "equity_cap_active" in account["errors"]


def test_account_balance_subtracts_equity_study_baseline(tmp_data_dir, monkeypatch):
    monkeypatch.setenv("TRADING_RISK_PROFILE", "demo_small_200")
    monkeypatch.setenv("TRADING_EQUITY_CAP_USD", "200")
    monkeypatch.setenv("TRADING_EQUITY_CAP_PNL_BASELINE_USD", "23.45")
    _journal, reconciler = _load_modules(tmp_data_dir)

    account = reconciler.normalize_account_balance(
        {
            "total": {"USDT": 10021.5},
            "free": {"USDT": 9975.25},
            "used": {"USDT": 46.25},
            "info": {
                "data": [
                    {
                        "totalEq": "10023.45",
                        "details": [
                            {
                                "ccy": "USDT",
                                "eqUsd": "10023.45",
                                "availEq": "9980.12",
                                "imr": "43.33",
                                "upl": "-7.86",
                            }
                        ],
                    }
                ]
            },
        },
        fetched_at="2026-07-01T00:00:00Z",
        mode="demo",
        journal_stats={"starting_capital": 10000.0, "total_pnl_usd": 31.31},
        positions=[],
    )

    assert account["source"] == "okx_demo_capped"
    assert account["equity_cap_pnl_baseline_usd"] == 23.45
    assert account["pre_cap_total_pnl_usd"] == 23.45
    assert account["starting_capital_usd"] == 200.0
    assert account["current_capital_usd"] == 200.0
    assert account["total_pnl_usd"] == 0.0


def test_account_state_falls_back_to_journal_without_balance(tmp_data_dir):
    _journal, reconciler = _load_modules(tmp_data_dir)
    account = reconciler.build_account_state(
        snapshot={
            "fetched_at": "2026-07-01T00:00:00Z",
            "mode": "demo",
            "positions": [{"unrealized_pnl": -3.0}],
            "account_errors": ["balance unavailable"],
            "errors": [],
        },
        journal_stats={
            "starting_capital": 10000.0,
            "current_capital": 10059.0,
            "total_pnl_usd": 59.0,
        },
    )

    assert account["source"] == "journal_fallback"
    assert account["current_capital_usd"] == 10059.0
    assert account["total_pnl_usd"] == 59.0
    assert account["unrealized_pnl_usd"] == 0.0
    assert account["errors"] == ["balance unavailable"]


def test_account_errors_do_not_break_position_sync_status(tmp_data_dir):
    journal, reconciler = _load_modules(tmp_data_dir)
    journal.ensure_dirs()
    snapshot = {
        "fetched_at": "2026-07-01T00:00:00Z",
        "exchange": "okx",
        "mode": "demo",
        "positions": [],
        "pending_algo": [],
        "account_errors": ["balance unavailable"],
        "errors": [],
    }

    status = reconciler.reconcile_journal_with_exchange(
        snapshot=snapshot,
        journal_module=journal,
    )

    assert status["status"] == "in_sync"
    assert status["errors"] == []
