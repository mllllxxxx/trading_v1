"""Tests for non-blocking adaptive evaluation status caching."""

from __future__ import annotations

import asyncio
import threading
import time

import api_server


def _reset_cache() -> None:
    api_server._ADAPTIVE_EVALUATION_CACHE.update(
        {
            "ts": 0.0,
            "data": None,
            "fingerprint": "",
            "error": None,
            "refreshing": False,
        }
    )
    api_server._ADAPTIVE_EVALUATION_REFRESH_TASK = None


def test_cold_adaptive_cache_returns_refreshing_without_waiting(monkeypatch) -> None:
    _reset_cache()
    started = threading.Event()
    release = threading.Event()

    def slow_compute(_rows, *, zone_override=None):
        started.set()
        release.wait(timeout=2)
        return {
            "schema_version": "adaptive_threshold_evaluation.v1",
            "status": "ready",
            "current_policy": dict(zone_override or {}),
            "strategy_threshold_diagnostics": {},
            "conflict_penalty_diagnostics": {"mode": "observe_only"},
            "shadow_scoring_experiment_evaluation": {
                "continuous_conflict_v2": {
                    "mode": "shadow_only",
                    "score_coverage": {"valid": 12, "total": 20},
                    "review_eligibility": {
                        "status": "collecting_evidence",
                        "eligible": False,
                    },
                    "auto_apply": False,
                }
            },
            "auto_apply": False,
        }

    monkeypatch.setattr(api_server, "_compute_adaptive_evaluation", slow_compute)

    async def scenario() -> None:
        started_at = time.perf_counter()
        cold = await api_server._cached_adaptive_evaluation(
            [],
            zone_override={"strong_min_score": 75, "gray_min_score": 55},
        )
        elapsed = time.perf_counter() - started_at
        assert elapsed < 0.30
        assert cold["status"] == "refreshing"
        assert cold["cache"]["status"] == "refreshing"
        assert await asyncio.to_thread(started.wait, 1)
        release.set()
        task = api_server._ADAPTIVE_EVALUATION_REFRESH_TASK
        assert task is not None
        await task
        warm = await api_server._cached_adaptive_evaluation(
            [],
            zone_override={"strong_min_score": 75, "gray_min_score": 55},
        )
        assert warm["status"] == "ready"
        assert warm["cache"]["status"] == "fresh"
        assert warm["current_policy"] == {
            "strong_min_score": 75,
            "gray_min_score": 55,
        }
        assert warm["conflict_penalty_diagnostics"] == {"mode": "observe_only"}
        assert warm["shadow_scoring_experiment_evaluation"][
            "continuous_conflict_v2"
        ]["score_coverage"] == {"valid": 12, "total": 20}
        assert warm["shadow_scoring_experiment_evaluation"][
            "continuous_conflict_v2"
        ]["review_eligibility"]["status"] == "collecting_evidence"

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_stale_adaptive_cache_remains_readable_during_refresh(monkeypatch) -> None:
    _reset_cache()
    api_server._ADAPTIVE_EVALUATION_CACHE.update(
        {
            "ts": 1.0,
            "data": {"status": "old_ready", "auto_apply": False},
            "fingerprint": "old-fingerprint",
        }
    )
    release = threading.Event()

    def slow_compute(_rows, *, zone_override=None):
        release.wait(timeout=2)
        return {
            "status": "new_ready",
            "current_policy": dict(zone_override or {}),
            "auto_apply": False,
        }

    monkeypatch.setattr(api_server, "_compute_adaptive_evaluation", slow_compute)

    async def scenario() -> None:
        stale = await api_server._cached_adaptive_evaluation(
            [{"shadow_id": "new-evidence"}],
            zone_override={"strong_min_score": 80, "gray_min_score": 60},
        )
        assert stale["status"] == "old_ready"
        assert stale["cache"]["refreshing"] is True
        release.set()
        task = api_server._ADAPTIVE_EVALUATION_REFRESH_TASK
        assert task is not None
        await task
        refreshed = await api_server._cached_adaptive_evaluation(
            [{"shadow_id": "new-evidence"}],
            zone_override={"strong_min_score": 80, "gray_min_score": 60},
        )
        assert refreshed["status"] == "new_ready"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
