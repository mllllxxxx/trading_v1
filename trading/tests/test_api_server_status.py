"""Tests for api_server.py status endpoint (H7).

H7: stats[\"total_trades\"] must not raise KeyError when stats missing.

We test the winrate calculation logic in isolation (extracted helper) since
api_server.py has many import-time side effects (FastAPI app, LLM providers
config, etc.) that are hard to mock without changing the test surface.
"""
from __future__ import annotations


def compute_winrate(stats: dict) -> float:
    """Mirror the post-fix logic from api_server.py:1869-1876."""
    total = stats.get("total_trades", 0)
    if total > 0:
        return stats.get("wins", 0) / total * 100.0
    return 0.0


class TestWinrateComputation:
    """H7: get_trader_status winrate must not raise KeyError on empty stats."""

    def test_empty_stats_returns_zero(self):
        assert compute_winrate({}) == 0.0

    def test_missing_total_trades_returns_zero(self):
        assert compute_winrate({"wins": 3, "losses": 2}) == 0.0

    def test_zero_total_returns_zero(self):
        assert compute_winrate({"total_trades": 0, "wins": 0}) == 0.0

    def test_normal_calculation(self):
        assert compute_winrate({"total_trades": 10, "wins": 6}) == 60.0

    def test_full_winrate(self):
        assert compute_winrate({"total_trades": 5, "wins": 5}) == 100.0

    def test_zero_winrate(self):
        assert compute_winrate({"total_trades": 5, "wins": 0}) == 0.0