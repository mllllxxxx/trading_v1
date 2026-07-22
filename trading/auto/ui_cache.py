"""Small cache helpers for non-blocking dashboard reads."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any


def cache_age_seconds(cache: Mapping[str, Any], *, now: float | None = None) -> float | None:
    """Return cache age in seconds, or ``None`` when the cache has no timestamp."""
    timestamp = _float_or_none(cache.get("ts"))
    if timestamp is None or timestamp <= 0:
        return None
    current = time.time() if now is None else now
    return max(0.0, current - timestamp)


def cache_has_value(cache: Mapping[str, Any], value_key: str) -> bool:
    """Return whether ``cache[value_key]`` carries a usable cached value."""
    value = cache.get(value_key)
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def cache_is_fresh(
    cache: Mapping[str, Any],
    *,
    ttl_s: float,
    value_key: str,
    now: float | None = None,
) -> bool:
    """Return whether a cached value exists and is still inside its TTL."""
    age = cache_age_seconds(cache, now=now)
    return cache_has_value(cache, value_key) and age is not None and age < ttl_s


def cache_status(
    cache: Mapping[str, Any],
    *,
    ttl_s: float,
    stale_ttl_s: float | None = None,
    value_key: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Return compact cache metadata suitable for API responses."""
    age = cache_age_seconds(cache, now=now)
    has_value = cache_has_value(cache, value_key)
    refreshing = bool(cache.get("refreshing"))
    if not has_value:
        state = "refreshing" if refreshing else "empty"
    elif age is not None and age < ttl_s:
        state = "fresh"
    elif stale_ttl_s is not None and age is not None and age >= stale_ttl_s:
        state = "stale"
    else:
        state = "refreshing" if refreshing else "stale"
    return {
        "status": state,
        "age_s": round(age, 3) if age is not None else None,
        "refreshing": refreshing,
    }


def should_refresh_cache(
    cache: Mapping[str, Any],
    *,
    ttl_s: float,
    value_key: str,
    now: float | None = None,
) -> bool:
    """Return whether a cache refresh should be scheduled."""
    return not bool(cache.get("refreshing")) and not cache_is_fresh(
        cache,
        ttl_s=ttl_s,
        value_key=value_key,
        now=now,
    )


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
