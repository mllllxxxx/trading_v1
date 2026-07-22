"""Tests for non-blocking dashboard cache helpers."""

from __future__ import annotations

from ui_cache import cache_age_seconds, cache_is_fresh, cache_status, should_refresh_cache


def test_cache_age_seconds_returns_none_without_timestamp() -> None:
    """Missing timestamps should not be treated as fresh data."""
    assert cache_age_seconds({}, now=100.0) is None


def test_cache_is_fresh_requires_value_and_ttl() -> None:
    """Freshness requires both cached data and an age inside the TTL."""
    assert cache_is_fresh({"ts": 95.0, "data": [1]}, ttl_s=10.0, value_key="data", now=100.0)
    assert not cache_is_fresh({"ts": 80.0, "data": [1]}, ttl_s=10.0, value_key="data", now=100.0)
    assert not cache_is_fresh({"ts": 95.0, "data": []}, ttl_s=10.0, value_key="data", now=100.0)


def test_cache_status_reports_refreshing_without_value() -> None:
    """A first dashboard request can return immediately while refresh runs."""
    assert cache_status(
        {"ts": 0.0, "data": None, "refreshing": True},
        ttl_s=10.0,
        value_key="data",
        now=100.0,
    ) == {"status": "refreshing", "age_s": None, "refreshing": True}


def test_cache_status_reports_stale_after_stale_ttl() -> None:
    """Old cached data should be clearly labeled as stale."""
    assert cache_status(
        {"ts": 50.0, "data": [1], "refreshing": False},
        ttl_s=10.0,
        stale_ttl_s=40.0,
        value_key="data",
        now=100.0,
    ) == {"status": "stale", "age_s": 50.0, "refreshing": False}


def test_should_refresh_cache_respects_refreshing_flag() -> None:
    """Concurrent frontend polls should not schedule duplicate refreshes."""
    assert not should_refresh_cache(
        {"ts": 0.0, "data": None, "refreshing": True},
        ttl_s=10.0,
        value_key="data",
        now=100.0,
    )
    assert should_refresh_cache(
        {"ts": 0.0, "data": None, "refreshing": False},
        ttl_s=10.0,
        value_key="data",
        now=100.0,
    )
