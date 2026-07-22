"""Contract tests for broker-free adaptive shadow outcomes."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from adaptive_hybrid import DecisionPolicy
from market_features import Candle
from replay.adaptive_evaluation import evaluate_adaptive_thresholds
from shadow_outcomes import (
    ShadowOutcomeConfig,
    annotate_shadow_result,
    capture_shadow_candidates,
    resolve_pending_shadow_outcomes,
    start_shadow_outcome_resolver,
)


TRIGGER_AT = "2026-01-01T00:15:00Z"
TRIGGER_MS = int(datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc).timestamp() * 1000)


def _config(*, max_hold_bars: int = 4) -> ShadowOutcomeConfig:
    return ShadowOutcomeConfig(
        enabled=True,
        max_hold_bars=max_hold_bars,
        fee_bps_per_leg=5.0,
        slippage_bps=2.0,
        max_symbols_per_cycle=12,
        max_pending=2000,
        candle_limit=300,
    )


def _signal(*, score: float = 55, side: str = "long") -> dict[str, object]:
    levels = (
        {"entry_zone": "100", "invalidation": "95", "target_zone": "110"}
        if side == "long"
        else {"entry_zone": "100", "invalidation": "105", "target_zone": "90"}
    )
    return {
        "signal_id": "sig-shadow-1",
        "generated_at": TRIGGER_AT,
        "symbol": "BTC-USDT",
        "market": "crypto",
        "timeframe": "15m_1h_4h",
        "source": "momentum_crypto_scanner",
        "team_id": "momentum",
        "strategy_id": "crypto_momentum_breakout",
        "direction": side,
        "score": score,
        "rule_score": score,
        "status": "watchlist" if score < 60 else "candidate",
        "signal": "watchlist" if score < 60 else "candidate",
        "action_hint": "HOLD" if score < 60 else ("OPEN_LONG" if side == "long" else "OPEN_SHORT"),
        "blockers": [],
        "hard_blockers": [],
        "conflicts": ["context_conflict"],
        "experimental_scores": {
            "continuous_conflict_v2": {
                "mode": "shadow_only",
                "score_version": "continuous_base_and_severity_v2",
                "score": score + 1.25,
                "base_score": score + 5,
                "total_penalty": 3.75,
                "conflict_penalties": [],
                "active_for_routing": False,
            }
        },
        "regime": "TRENDING_UP" if side == "long" else "TRENDING_DOWN",
        "data_timestamp_utc": TRIGGER_AT,
        **levels,
        "evidence": {
            "data_timestamp_utc": TRIGGER_AT,
            "regime": "TRENDING_UP" if side == "long" else "TRENDING_DOWN",
            "setup_quality": {
                "rule_score": score,
                "hard_blockers": [],
                "conflicts": ["context_conflict"],
            },
            "experimental_scores": {
                "continuous_conflict_v2": {
                    "mode": "shadow_only",
                    "score_version": "continuous_base_and_severity_v2",
                    "score": score + 1.25,
                    "active_for_routing": False,
                }
            },
        },
    }


def test_capture_is_idempotent_persistent_and_not_real_exposure(isolated_journal) -> None:
    now = datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc)

    first = capture_shadow_candidates(
        [_signal()],
        scan_id="scan-1",
        journal_module=isolated_journal,
        config=_config(),
        now=now,
    )
    second = capture_shadow_candidates(
        [_signal()],
        scan_id="scan-1-retry",
        journal_module=isolated_journal,
        config=_config(),
        now=now,
    )
    isolated_journal.ensure_dirs()

    pending = isolated_journal.read_shadow_positions()
    assert first["captured"] == 1
    assert second["duplicates"] == 1
    assert len(pending) == 1
    assert pending[0]["rule_score"] == 55
    assert pending[0]["decision_zone"] == "reject"
    assert pending[0]["counterfactual_score_floor"] == 0
    assert pending[0]["experimental_scores"]["continuous_conflict_v2"]["score"] == 56.25
    assert isolated_journal.read_positions() == []
    assert isolated_journal.read_stats()["total_trades"] == 0


def test_shadow_capture_uses_injected_cycle_policy_without_reloading(
    isolated_journal,
    monkeypatch,
) -> None:
    policy = DecisionPolicy(
        profile="adaptive_hybrid_v1",
        strong_min_score=75,
        gray_min_score=55,
        strong_lane="rules_baseline",
        gray_lane="rules_plus_llm",
        reject_lane="no_trade",
        gray_requires_llm=True,
        review_risk_multipliers=(0.0, 0.5, 1.0),
        live_enabled=False,
    )
    monkeypatch.setattr(
        "shadow_outcomes.load_decision_policy",
        lambda: (_ for _ in ()).throw(AssertionError("policy was reloaded")),
    )

    result = capture_shadow_candidates(
        [_signal(score=57)],
        scan_id="scan-cycle-policy",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
        decision_policy=policy,
    )

    pending = isolated_journal.read_shadow_positions()
    assert result["captured"] == 1
    assert result["decision_policy"]["zones"]["gray_min_score"] == 55
    assert pending[0]["decision_zone"] == "gray"
    assert pending[0]["decision_lane"] == "rules_plus_llm"
    assert pending[0]["decision_policy"] == result["decision_policy"]


def test_hard_blocked_or_invalid_levels_are_not_captured(isolated_journal) -> None:
    blocked = _signal()
    blocked["hard_blockers"] = ["stale_confirmed_candles"]
    invalid = _signal(side="short")
    invalid["invalidation"] = "95"

    result = capture_shadow_candidates(
        [blocked, invalid],
        scan_id="scan-invalid",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )

    assert result["captured"] == 0
    assert result["ineligible"] == 2
    assert isolated_journal.read_shadow_positions() == []


def test_observed_llm_veto_is_retained_without_changing_shadow_path(isolated_journal) -> None:
    signal = _signal(score=70)
    capture_shadow_candidates(
        [signal],
        scan_id="scan-veto",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )

    updated = annotate_shadow_result(
        signal,
        {
            "stage": "llm_veto",
            "reason": "context_conflict",
            "executed": False,
            "decision_lane": "rules_plus_llm",
            "llm_review": {"decision": "VETO", "risk_multiplier": 0},
        },
        journal_module=isolated_journal,
        config=_config(),
    )

    pending = isolated_journal.read_shadow_positions()[0]
    assert updated is True
    assert pending["observed_stage"] == "llm_veto"
    assert pending["observed_llm_review"]["decision"] == "VETO"
    assert pending["counterfactual_eligible"] is True


def test_confirmed_candle_resolves_take_profit_fee_aware(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-tp",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    candles = [Candle(TRIGGER_MS, 100, 111, 99, 110, 1000)]

    result = resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=lambda *_args, **_kwargs: candles,
        now=datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc),
    )

    outcomes = isolated_journal.read_shadow_outcomes()
    assert result["broker_calls"] == 0
    assert result["resolved"] == 1
    assert isolated_journal.read_shadow_positions() == []
    assert outcomes[0]["exit_reason"] == "take_profit"
    assert outcomes[0]["counterfactual_eligible"] is True
    assert outcomes[0]["fees_per_unit"] > 0
    assert outcomes[0]["r_multiple"] > 0
    assert outcomes[0]["experimental_scores"]["continuous_conflict_v2"]["score"] == 56.25
    assert isolated_journal.read_stats()["total_trades"] == 0


def test_shadow_identity_ignores_experimental_score(isolated_journal) -> None:
    first = _signal()
    changed_experiment = _signal()
    changed_experiment["experimental_scores"]["continuous_conflict_v2"]["score"] = 99.0

    initial = capture_shadow_candidates(
        [first],
        scan_id="scan-experiment-a",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    repeated = capture_shadow_candidates(
        [changed_experiment],
        scan_id="scan-experiment-b",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )

    assert initial["captured"] == 1
    assert repeated["duplicates"] == 1
    assert len(isolated_journal.read_shadow_positions()) == 1


def test_same_candle_stop_and_target_is_excluded(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-ambiguous",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    candles = [Candle(TRIGGER_MS, 100, 111, 94, 102, 1000)]

    resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=lambda *_args, **_kwargs: candles,
        now=datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc),
    )

    outcome = isolated_journal.read_shadow_outcomes()[0]
    assert outcome["exit_reason"] == "ambiguous_both_touched"
    assert outcome["counterfactual_eligible"] is False
    assert outcome["exclusion_reason"] == "ambiguous_intrabar_sequence"
    assert outcome["r_multiple"] is None


def test_bounded_horizon_resolves_timeout(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-timeout",
        journal_module=isolated_journal,
        config=_config(max_hold_bars=2),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    candles = [
        Candle(TRIGGER_MS, 100, 104, 97, 102, 1000),
        Candle(TRIGGER_MS + 900_000, 102, 105, 98, 104, 1000),
    ]

    resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(max_hold_bars=2),
        candle_fetcher=lambda *_args, **_kwargs: candles,
        now=datetime(2026, 1, 1, 0, 46, tzinfo=timezone.utc),
    )

    outcome = isolated_journal.read_shadow_outcomes()[0]
    assert outcome["exit_reason"] == "timeout"
    assert outcome["holding_bars"] == 2
    assert outcome["exit_price"] == 104
    assert outcome["counterfactual_eligible"] is True


def test_missing_confirmed_candle_resolves_ineligible_history_gap(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-gap",
        journal_module=isolated_journal,
        config=_config(max_hold_bars=2),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    candles = [Candle(TRIGGER_MS + 900_000, 100, 104, 97, 102, 1000)]

    resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(max_hold_bars=2),
        candle_fetcher=lambda *_args, **_kwargs: candles,
        now=datetime(2026, 1, 1, 0, 46, tzinfo=timezone.utc),
    )

    outcome = isolated_journal.read_shadow_outcomes()[0]
    assert outcome["exit_reason"] == "history_gap"
    assert outcome["counterfactual_eligible"] is False
    assert outcome["exclusion_reason"] == "missing_confirmed_candle"


def test_public_provider_failure_leaves_shadow_pending(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-provider-error",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )

    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("public candles unavailable")

    result = resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=fail_fetch,
        now=datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc),
    )

    assert result["resolved"] == 0
    assert result["errors"][0]["symbol"] == "BTC-USDT"
    assert len(isolated_journal.read_shadow_positions()) == 1
    assert isolated_journal.read_shadow_outcomes() == []


def test_background_resolver_is_nonblocking_and_single_flight(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal()],
        scan_id="scan-background",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    entered = threading.Event()
    release = threading.Event()

    def slow_fetch(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        return [Candle(TRIGGER_MS, 100, 111, 99, 110, 1000)]

    started_at = time.monotonic()
    first = start_shadow_outcome_resolver(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=slow_fetch,
    )
    elapsed = time.monotonic() - started_at
    assert entered.wait(timeout=1)
    second = start_shadow_outcome_resolver(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=slow_fetch,
    )

    assert first["started"] is True
    assert elapsed < 0.5
    assert second["started"] is False
    assert second["already_running"] is True
    release.set()
    for _ in range(100):
        if isolated_journal.read_shadow_outcomes():
            break
        time.sleep(0.01)
    assert isolated_journal.read_shadow_outcomes()[0]["exit_reason"] == "take_profit"


def test_resolved_shadow_outcome_is_accepted_by_adaptive_evaluator(isolated_journal) -> None:
    capture_shadow_candidates(
        [_signal(score=85)],
        scan_id="scan-evaluator",
        journal_module=isolated_journal,
        config=_config(),
        now=datetime(2026, 1, 1, 0, 16, tzinfo=timezone.utc),
    )
    resolve_pending_shadow_outcomes(
        journal_module=isolated_journal,
        config=_config(),
        candle_fetcher=lambda *_args, **_kwargs: [Candle(TRIGGER_MS, 100, 111, 99, 110, 1000)],
        now=datetime(2026, 1, 1, 0, 31, tzinfo=timezone.utc),
    )

    evaluation = evaluate_adaptive_thresholds(
        isolated_journal.read_shadow_outcomes(),
        min_total=1,
        min_zone=1,
    )

    assert evaluation["eligible_records"] == 1
    assert evaluation["evidence_coverage"]["eligible_by_source"] == {"shadow": 1}
