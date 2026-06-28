"""In-process pub/sub event bus.

Threads subscribe (e.g., Telegram notifier); scheduler/monitor emit events
(trade_opened, trade_closed, regime_change, error, decision).

Thread-safe. Subscribers should not raise (errors are caught and logged).
"""
from __future__ import annotations

import threading
import traceback
from collections import defaultdict
from typing import Any, Callable

_lock = threading.Lock()
_subs: dict[str, list[Callable]] = defaultdict(list)


def subscribe(event_type: str, callback: Callable[[str, dict[str, Any]], None]) -> None:
    with _lock:
        _subs[event_type].append(callback)


def unsubscribe(event_type: str, callback: Callable) -> None:
    with _lock:
        if callback in _subs.get(event_type, []):
            _subs[event_type].remove(callback)


def emit(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Fire-and-forget broadcast. Catches subscriber errors so one bad
    subscriber doesn't break the chain."""
    payload = payload or {}
    with _lock:
        callbacks = list(_subs.get(event_type, []))
    for cb in callbacks:
        try:
            cb(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[alerts] subscriber error for {event_type}: {exc}")
            print(traceback.format_exc()[:500])


def subscriber_count(event_type: str | None = None) -> int:
    """Debug helper: count subscribers (optionally for one event type)."""
    with _lock:
        if event_type:
            return len(_subs.get(event_type, []))
        return sum(len(v) for v in _subs.values())
