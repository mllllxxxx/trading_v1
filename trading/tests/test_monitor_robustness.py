"""Tests for monitor.py robustness (M1, M2)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def isolated_monitor(tmp_data_dir, monkeypatch):
    """Reload monitor with DATA_DIR redirected + stub external deps."""
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "auto"))
    # Stub ccxt so import doesn't try to init network
    sys.modules.setdefault("ccxt", MagicMock())
    import journal
    importlib.reload(journal)  # reload FIRST so DATA_DIR is fresh
    import monitor
    importlib.reload(monitor)
    yield monitor
    importlib.reload(monitor)
    importlib.reload(journal)


def _make_position(symbol: str = "BTC-USDT", position_size: float = 0.1) -> dict:
    return {
        "symbol": symbol,
        "side": "buy",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "position_size": position_size,
        "risk_usd": 50.0,
        "rr_ratio": 2.0,
        "confluence_score": 3,
        "regime": "TRENDING_UP",
        "opened_at": "2026-06-21T09:00:00+07:00",
        "orders": {
            "entry_id": "E1", "tp_id": "T1", "sl_id": "S1",
        },
        "status": "open",
    }


# ---- M1: TP partially_filled must NOT close prematurely ------------------

class TestMonitorTPPartialFill:
    """M1: closing logic distinguishes 'closed' (full) from 'partially_filled'."""

    def _setup_exchange(self, tp_status: str, sl_status: str = "open",
                        tp_filled: float = 0.1, tp_avg: float = 110.0):
        exchange = MagicMock()
        entry_order = {"id": "E1", "status": "closed",
                       "filled": 0.1, "average": 100.0, "price": 100.0, "cost": 10.0}
        tp_order = {"id": "T1", "status": tp_status, "filled": tp_filled,
                    "average": tp_avg, "price": 110.0, "cost": tp_filled * tp_avg}
        sl_order = {"id": "S1", "status": sl_status, "filled": 0.0,
                    "average": 0.0, "price": 95.0, "cost": 0.0}
        exchange.fetch_order.side_effect = lambda oid, sym: {
            "E1": entry_order, "T1": tp_order, "S1": sl_order,
        }[oid]
        return exchange

    def test_tp_partial_does_not_close(self, isolated_monitor, tmp_data_dir):
        """Regression: partial TP fill used to close position with wrong PnL."""
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position()
        m.journal.add_position(pos)
        exchange = self._setup_exchange(tp_status="partially_filled",
                                        tp_filled=0.03, tp_avg=109.5)

        m._check_position(exchange, pos)

        # Position should NOT be removed
        assert m.journal.read_positions()  # still has the position

        # A partial_exit decision should have been logged
        with m.journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            entries = [line for line in f if line.strip()]
        assert any('"type": "partial_exit"' in e for e in entries), \
            "Expected partial_exit decision"

    def test_tp_full_closes_position(self, isolated_monitor, tmp_data_dir):
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position()
        m.journal.add_position(pos)
        exchange = self._setup_exchange(tp_status="closed", tp_filled=0.1, tp_avg=110.5)

        m._check_position(exchange, pos)

        # Position should be removed
        assert m.journal.read_positions() == []

    def test_sl_partial_does_not_close(self, isolated_monitor, tmp_data_dir):
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position()
        m.journal.add_position(pos)
        exchange = self._setup_exchange(tp_status="open",
                                        sl_status="partially_filled",
                                        tp_filled=0.0)

        m._check_position(exchange, pos)
        assert m.journal.read_positions()  # still there


# ---- M2: heartbeat + exception resilience ---------------------------------

class TestMonitorHeartbeat:
    """M2: main_loop logs heartbeat + catches fatal exceptions."""

    def test_run_once_exception_logged_and_continues(self, isolated_monitor):
        """Regression: a fatal run_once exception must not kill the thread."""
        m = isolated_monitor
        m.journal.ensure_dirs()
        with patch.object(m, "run_once", side_effect=RuntimeError("boom")), \
             patch.object(m.time, "sleep"):
            m.main_loop_cycle()
        # Verify the fatal was logged (not raised)
        with m.journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert any(e.get("type") == "monitor_fatal" for e in entries)

    def test_heartbeat_appended_every_n_cycles(self, isolated_monitor, tmp_data_dir):
        """Heartbeat decision appended every heartbeat_every cycles."""
        m = isolated_monitor
        m.journal.ensure_dirs()
        m.HEARTBEAT_EVERY = 3  # Override for test (default 20)

        with patch.object(m, "run_once", return_value=None), \
             patch.object(m.time, "sleep"):
            for _ in range(7):
                m.main_loop_cycle()
        with m.journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            import json
            heartbeats = sum(1 for line in f
                             if line.strip() and '"monitor_heartbeat"' in line)
        assert heartbeats == 2  # cycles 3 and 6

    def test_fatal_in_run_once_logs_and_continues(self, isolated_monitor, tmp_data_dir):
        m = isolated_monitor
        m.journal.ensure_dirs()
        m.HEARTBEAT_EVERY = 100

        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("disk full")

        with patch.object(m, "run_once", side_effect=flaky), \
             patch.object(m.time, "sleep"):
            for _ in range(2):
                m.main_loop_cycle()

        with m.journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert any(e.get("type") == "monitor_fatal" for e in entries)


class TestMonitorReconciliation:
    """Test position reconciliation with the exchange for both futures and spot modes."""

    def test_spot_reconciliation_inactive_orders(self, isolated_monitor, tmp_data_dir, monkeypatch):
        """Spot mode: close position if both TP and SL orders are canceled/expired/none."""
        monkeypatch.setenv("TRADE_MODE", "spot")
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position()
        pos["entry_filled"] = True  # already entered
        m.journal.add_position(pos)

        exchange = MagicMock()
        exchange.fetch_order.side_effect = lambda oid, sym: {"status": "canceled"}
        exchange.fetch_ticker.return_value = {"close": 102.0}

        with patch.object(m, "_get_exchange", return_value=exchange):
            m.run_once()

        # Position should be reconciled and closed
        assert m.journal.read_positions() == []
        closed = m.journal.read_closed_trades()
        assert len(closed) == 1
        assert closed[0]["exit_reason"] == "orders_inactive_or_pruned"
        assert closed[0]["exit_price"] == 102.0

    def test_futures_reconciliation_closed_on_exchange(self, isolated_monitor, tmp_data_dir, monkeypatch):
        """Futures mode: close position if not found in exchange.fetch_positions()."""
        monkeypatch.setenv("TRADE_MODE", "futures")
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position(symbol="BTC-USDT-SWAP")
        pos["entry_filled"] = True
        m.journal.add_position(pos)

        exchange = MagicMock()
        exchange.fetch_positions.return_value = []
        exchange.fetch_ticker.return_value = {"close": 109.5}

        with patch.object(m, "_get_exchange", return_value=exchange):
            m.run_once()

        # Position should be closed locally
        assert m.journal.read_positions() == []
        closed = m.journal.read_closed_trades()
        assert len(closed) == 1
        assert closed[0]["exit_reason"] == "take_profit"  # close to 110.0
        assert closed[0]["exit_price"] == 109.5

    def test_futures_reconciliation_active_on_exchange(self, isolated_monitor, tmp_data_dir, monkeypatch):
        """Futures mode: do nothing if position is still active on exchange."""
        monkeypatch.setenv("TRADE_MODE", "futures")
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position(symbol="BTC-USDT-SWAP")
        pos["entry_filled"] = True
        m.journal.add_position(pos)

        exchange = MagicMock()
        exchange.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0}
        ]

        with patch.object(m, "_get_exchange", return_value=exchange):
            m.run_once()

        # Position must remain open
        assert len(m.journal.read_positions()) == 1

    def test_futures_entry_fill_detection(self, isolated_monitor, tmp_data_dir, monkeypatch):
        """Futures mode: detect entry fill when position becomes active on exchange."""
        monkeypatch.setenv("TRADE_MODE", "futures")
        m = isolated_monitor
        m.journal.ensure_dirs()
        pos = _make_position(symbol="BTC-USDT-SWAP")
        pos["entry_filled"] = False
        m.journal.add_position(pos)

        exchange = MagicMock()
        exchange.fetch_positions.return_value = [
            {"symbol": "BTC/USDT:USDT", "contracts": 1.0}
        ]

        with patch.object(m, "_get_exchange", return_value=exchange):
            m.run_once()

        # Position should be updated to entry_filled=True
        open_pos = m.journal.read_positions()
        assert len(open_pos) == 1
        assert open_pos[0]["entry_filled"] is True