from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from adaptive_hybrid import DecisionPolicy
from berkshire_signal_scheduler import (
    BerkshireSignalSchedulerConfig,
    _attempt_cooldown,
    _prepare_canary_candidate_routes,
    _symbol_cooldown_active,
    run_once,
)
from adaptive_hybrid import load_decision_policy


@pytest.fixture(autouse=True)
def _disable_background_shadow_resolution(monkeypatch):
    """Keep scheduler tests deterministic; resolver concurrency is tested separately."""
    monkeypatch.setenv("AUTO_SHADOW_EVALUATION_ENABLED", "false")
    monkeypatch.setenv("AUTO_ADAPTIVE_CONTROLLER_ENABLED", "false")


def _eligible_signal() -> dict:
    return {
        "signal_id": "sig-scheduled",
        "symbol": "BTC-USDT",
        "status": "candidate",
        "signal": "candidate",
        "direction": "long",
        "action_hint": "OPEN_LONG",
        "confidence": 0.8,
        "score": 80,
        "volume_usd_24h": "100000000",
        "blockers": [],
    }


def _canary_state() -> dict:
    return {
        "status": "active",
        "routing_enabled": True,
        "approval_id": "approval-test",
        "candidate_fingerprint": "candidate-test",
        "score_version": "continuous_base_and_severity_v2",
        "candidate_thresholds": {
            "strong_min_score": 76.0,
            "gray_min_score": 54.0,
        },
        "allocation_rate": 1.0,
        "risk_multiplier": 0.5,
        "max_concurrent_positions": 1,
    }


def _canary_signal(*, v1: float, v2: float) -> dict:
    return {
        **_eligible_signal(),
        "signal_id": f"sig-canary-{v1}-{v2}",
        "status": "watchlist" if v1 < 50 else "strong_candidate",
        "signal": "watchlist" if v1 < 50 else "strong_candidate",
        "score": int(v1),
        "rule_score": v1,
        "target_risk_pct_equity": 0.01,
        "evidence": {"setup_quality": {"rule_score": v1, "hard_blockers": []}},
        "experimental_scores": {
            "continuous_conflict_v2": {
                "mode": "shadow_only",
                "score_version": "continuous_base_and_severity_v2",
                "score": v2,
                "active_for_routing": False,
            }
        },
    }


def test_attempt_cooldown_is_outcome_aware() -> None:
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=None,
        limit=1,
        max_promotions=1,
        equity_usd=200,
    )

    assert _attempt_cooldown({"executed": True}, cache_config=cfg) == ("executed", 14_400)
    assert _attempt_cooldown({"stage": "llm_hold", "reason": "llm_hold"}, cache_config=cfg) == ("hold", 3_600)
    assert _attempt_cooldown({"stage": "provider", "reason": "invalid json"}, cache_config=cfg) == ("transient_error", 900)
    assert _attempt_cooldown(
        {
            "stage": "llm_ticket",
            "reason": "llm_failed: TradeDecisionTicket validation failed: entry_plan must be an object",
        },
        cache_config=cfg,
    ) == ("transient_error", 900)
    assert _attempt_cooldown(
        {
            "stage": "llm_ticket",
            "reason": "llm_failed: LLM budget exhausted: source_hourly_call_cap",
        },
        cache_config=cfg,
    ) == ("transient_error", 900)
    assert _attempt_cooldown(
        {
            "stage": "execution",
            "reason": "execution_failed: OKX contract metadata unavailable",
        },
        cache_config=cfg,
    ) == ("transient_error", 900)
    assert _attempt_cooldown(
        {
            "stage": "llm_ticket",
            "reason": "llm_failed: LLM budget gate unavailable: No module named journal",
        },
        cache_config=cfg,
    ) == ("transient_error", 900)


def test_old_validation_failure_cache_uses_short_cooldown() -> None:
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=None,
        limit=1,
        max_promotions=1,
        equity_usd=200,
    )
    cache = {
        "symbols": {
            "berkshire:BTC-USDT": {
                "last_ts": 0,
                "cooldown_s": 3600,
                "stage": "llm_ticket",
                "reason": "llm_failed: TradeDecisionTicket validation failed: entry_plan must be an object",
                "outcome_class": "setup_rejected",
            }
        }
    }

    active, reason = _symbol_cooldown_active(
        cache,
        _eligible_signal(),
        cfg=cfg,
        now_ts=1000,
    )

    assert active is False
    assert reason == ""


def test_scheduler_run_once_scans_and_promotes_eligible_signal(isolated_journal):
    seen: dict[str, object] = {}

    def fake_scan(*, symbols, limit):
        seen["scan_kwargs"] = {"symbols": symbols, "limit": limit}
        return {
            "id": "scan-scheduled",
            "signal_count": 1,
            "top_symbol": "BTC-USDT",
            "top_signal": "candidate",
            "signals": [_eligible_signal()],
        }

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": True,
                "stage": "execution",
                "reason": "okx_demo_executed",
            }

    def fake_promote(signal, *, equity, autonomy_mode):
        seen["signal_id"] = signal["signal_id"]
        seen["promote_kwargs"] = {
            "equity": equity,
            "autonomy_mode": autonomy_mode,
        }
        return FakePromotion(signal_id=signal["signal_id"])

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=12_345,
    )

    result = run_once(
        config=cfg,
        scan_fn=fake_scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert result["status"] == "ok"
    assert result["promotions"][0]["reason"] == "okx_demo_executed"
    assert seen["scan_kwargs"] == {"symbols": ["BTC-USDT"], "limit": 1}
    assert seen["signal_id"] == "sig-scheduled"
    assert seen["promote_kwargs"]["equity"] == 12_345


def test_scheduler_canary_promotes_v1_watchlist_at_half_risk(isolated_journal) -> None:
    seen: dict[str, Any] = {}

    def fake_scan(*, symbols, limit, decision_policy):
        del symbols, limit, decision_policy
        return {"id": "scan-canary", "signal_count": 1, "signals": [_canary_signal(v1=48, v2=80)]}

    def fake_promote(signal, *, equity, autonomy_mode, decision_policy):
        del equity, autonomy_mode
        seen["signal"] = signal
        seen["policy"] = decision_policy
        return {
            "signal_id": signal["signal_id"],
            "promoted": True,
            "executed": True,
            "stage": "execution",
            "reason": "paper_executed",
        }

    result = run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=60,
            symbols=["BTC-USDT"],
            limit=1,
            max_promotions=1,
            equity_usd=200,
        ),
        scan_fn=fake_scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
        canary_controller_fn=lambda **_kwargs: _canary_state(),
    )

    signal = seen["signal"]
    assert signal["status"] == "strong_candidate"
    assert signal["target_risk_pct_equity"] == pytest.approx(0.005)
    assert signal["llm_context"]["routing_experiment"]["v1_zone"] == "reject"
    assert seen["policy"].policy_source == "continuous_conflict_v2_canary"
    assert result["summary"]["canary_selected"] == 1


def test_scheduler_canary_v2_reject_is_no_order(isolated_journal) -> None:
    def fake_scan(*, symbols, limit, decision_policy):
        del symbols, limit, decision_policy
        return {"id": "scan-veto", "signal_count": 1, "signals": [_canary_signal(v1=80, v2=20)]}

    def fail_if_promoted(*_args, **_kwargs):
        raise AssertionError("V2 reject reached execution")

    result = run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=60,
            symbols=["BTC-USDT"],
            limit=1,
            max_promotions=1,
            equity_usd=200,
        ),
        scan_fn=fake_scan,
        promotion_fn=fail_if_promoted,
        journal_module=isolated_journal,
        canary_controller_fn=lambda **_kwargs: _canary_state(),
    )

    assert result["promotions"][0]["reason"] == "v2_rule_reject"
    assert result["promotions"][0]["executed"] is False
    assert result["summary"]["canary_vetoed"] == 1
    decision_types = {
        json.loads(line)["type"]
        for line in isolated_journal.DECISIONS_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "shadow_score_canary_route_selected" in decision_types
    assert "shadow_score_canary_route_veto" in decision_types


def test_selected_v2_promotion_is_not_starved_by_v1_ranking(
    isolated_journal,
) -> None:
    promoted: list[str] = []
    v1_top = {
        **_eligible_signal(),
        "signal_id": "sig-v1-top",
        "score": 95,
        "rule_score": 95.0,
        "evidence": {"setup_quality": {"rule_score": 95.0, "hard_blockers": []}},
    }
    selected_canary = {
        **_canary_signal(v1=48, v2=80),
        "signal_id": "sig-v2-selected",
        "symbol": "ETH-USDT",
    }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return {
            "signal_id": signal["signal_id"],
            "promoted": True,
            "executed": True,
            "stage": "execution",
            "reason": "paper_executed",
        }

    result = run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=60,
            symbols=["BTC-USDT", "ETH-USDT"],
            limit=2,
            max_promotions=1,
            equity_usd=200,
        ),
        scan_fn=lambda **_kwargs: {
            "id": "scan-canary-priority",
            "signal_count": 2,
            "signals": [v1_top, selected_canary],
        },
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
        canary_controller_fn=lambda **_kwargs: _canary_state(),
    )

    assert promoted == ["sig-v2-selected"]
    assert result["promotions"][0]["routing_experiment"]["v2_zone"] == "strong"


def test_canary_allows_only_one_execution_per_cycle(
    isolated_journal,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STRATEGY_TEAM_MAX_OPEN_POSITIONS", "2")
    promoted: list[str] = []
    first = {**_canary_signal(v1=48, v2=82), "signal_id": "sig-canary-first"}
    second = {
        **_canary_signal(v1=47, v2=81),
        "signal_id": "sig-canary-second",
        "symbol": "ETH-USDT",
    }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return {
            "signal_id": signal["signal_id"],
            "promoted": True,
            "executed": True,
            "stage": "execution",
            "reason": "paper_executed",
        }

    run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=60,
            symbols=["BTC-USDT", "ETH-USDT"],
            limit=2,
            max_promotions=2,
            equity_usd=200,
        ),
        scan_fn=lambda **_kwargs: {
            "id": "scan-canary-one-slot",
            "signal_count": 2,
            "signals": [first, second],
        },
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
        canary_controller_fn=lambda **_kwargs: _canary_state(),
    )

    assert promoted == ["sig-canary-first"]


def test_canary_slot_is_global_across_strategy_teams(isolated_journal) -> None:
    promoted: list[str] = []

    def fake_scan(**kwargs):
        team_id = kwargs.get("team_id", "berkshire")
        symbol = "BTC-USDT" if team_id == "berkshire" else "ETH-USDT"
        signal = {
            **_canary_signal(v1=48, v2=80),
            "signal_id": f"sig-canary-{team_id}",
            "symbol": symbol,
            "team_id": team_id,
        }
        return {
            "id": f"scan-{team_id}",
            "signal_count": 1,
            "signals": [signal],
        }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return {
            "signal_id": signal["signal_id"],
            "promoted": True,
            "executed": True,
            "stage": "execution",
            "reason": "paper_executed",
        }

    result = run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=60,
            symbols=["BTC-USDT", "ETH-USDT"],
            limit=2,
            max_promotions=1,
            equity_usd=200,
            team_ids=("berkshire", "momentum"),
        ),
        scan_fn=fake_scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
        canary_controller_fn=lambda **_kwargs: _canary_state(),
    )

    assert len(promoted) == 1
    assert result["summary"]["executed"] == 1


def test_inactive_canary_keeps_v1_candidates_unchanged() -> None:
    candidates = [_eligible_signal(), {**_eligible_signal(), "signal_id": "sig-2"}]

    routed = _prepare_canary_candidate_routes(
        candidates,
        policy=load_decision_policy(),
        canary_state={"routing_enabled": False},
        canary_slot_available=False,
    )

    assert [signal for signal, decision in routed] == candidates
    assert all(decision is None for _signal, decision in routed)


def test_scheduler_captures_below_threshold_shadow_without_promotion(
    isolated_journal,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTO_SHADOW_EVALUATION_ENABLED", "true")
    monkeypatch.setattr(
        "berkshire_signal_scheduler.start_shadow_outcome_resolver",
        lambda **_kwargs: {
            "enabled": True,
            "started": True,
            "already_running": False,
            "broker_calls": 0,
        },
    )
    signal = {
        **_eligible_signal(),
        "signal_id": "sig-shadow-watchlist",
        "status": "watchlist",
        "signal": "watchlist",
        "action_hint": "HOLD",
        "score": 55,
        "rule_score": 55,
        "generated_at": "2026-01-01T00:15:00Z",
        "data_timestamp_utc": "2026-01-01T00:15:00Z",
        "entry_zone": "100",
        "invalidation": "95",
        "target_zone": "110",
        "team_id": "berkshire",
        "strategy_id": "berkshire_crypto_quality",
        "experimental_scores": {
            "continuous_conflict_v2": {
                "mode": "shadow_only",
                "score_version": "continuous_base_and_severity_v2",
                "score": 57.5,
                "active_for_routing": False,
            }
        },
    }

    def fail_if_promoted(*_args, **_kwargs):
        raise AssertionError("below-threshold shadow candidate reached execution promotion")

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=900,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=200,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {
            "id": "scan-shadow-watchlist",
            "signal_count": 1,
            "signals": [signal],
        },
        promotion_fn=fail_if_promoted,
        journal_module=isolated_journal,
    )

    pending = isolated_journal.read_shadow_positions()
    assert result["status"] == "ok"
    assert result["summary"]["shadow_capture"]["captured"] == 1
    assert result["promotions"] == []
    assert len(pending) == 1
    assert pending[0]["decision_zone"] == "reject"
    assert pending[0]["experimental_scores"]["continuous_conflict_v2"]["score"] == 57.5


def test_scheduler_uses_one_canonical_policy_snapshot_for_reviewed_thresholds(
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
    monkeypatch.setattr("berkshire_signal_scheduler.load_decision_policy", lambda: policy)
    promoted: list[str] = []

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": False,
                "stage": "llm_veto",
                "reason": "reviewed_gray_candidate",
                "decision_lane": "rules_plus_llm",
            }

    seen_policy: list[DecisionPolicy | None] = []
    seen_scan_policy: list[DecisionPolicy] = []

    def fake_promote(signal, **kwargs):
        promoted.append(signal["signal_id"])
        seen_policy.append(kwargs.get("decision_policy"))
        return FakePromotion(signal_id=signal["signal_id"])

    def fake_scan(*, symbols, limit, decision_policy):
        assert symbols == ["BTC-USDT"]
        assert limit == 1
        seen_scan_policy.append(decision_policy)
        return {
            "id": "scan-reviewed-gray",
            "signal_count": 1,
            "signals": [signal],
        }

    signal = {
        **_eligible_signal(),
        "signal_id": "sig-reviewed-gray",
        "score": 57,
        "rule_score": 57,
        "status": "candidate",
        "signal": "candidate",
    }
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=900,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=200,
        shadow_evaluation_enabled=False,
    )

    result = run_once(
        config=cfg,
        scan_fn=fake_scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert promoted == ["sig-reviewed-gray"]
    assert seen_scan_policy == [policy]
    assert seen_policy == [policy]
    assert result["promotions"][0]["decision_lane"] == "rules_plus_llm"
    assert result["summary"]["adaptive_route_rejected"] == 0
    assert result["summary"]["decision_policy"]["zones"] == {
        "strong_min_score": 75,
        "gray_min_score": 55,
    }


def test_scheduler_cycle_journals_all_team_skill_profiles(isolated_journal, monkeypatch):
    monkeypatch.setattr("berkshire_signal_scheduler.time.time", lambda: 0.0)
    seen_team_ids: list[str] = []
    seen_policies: list[DecisionPolicy] = []
    policy_loads = 0
    policy = DecisionPolicy(
        profile="adaptive_hybrid_v1",
        strong_min_score=80,
        gray_min_score=60,
        strong_lane="rules_baseline",
        gray_lane="rules_plus_llm",
        reject_lane="no_trade",
        gray_requires_llm=True,
        review_risk_multipliers=(0.0, 0.5, 1.0),
        live_enabled=False,
    )

    def fake_load_policy() -> DecisionPolicy:
        nonlocal policy_loads
        policy_loads += 1
        return policy

    monkeypatch.setattr("berkshire_signal_scheduler.load_decision_policy", fake_load_policy)

    def fake_scan(**kwargs):
        team_id = kwargs.get("team_id", "berkshire")
        seen_team_ids.append(team_id)
        seen_policies.append(kwargs["decision_policy"])
        return {
            "id": f"scan-{team_id}",
            "universe_count": 3,
            "signal_count": 0,
            "top_symbol": None,
            "top_signal": None,
            "signals": [],
        }

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT", "ETH-USDT", "SOL-USDT"],
        limit=3,
        max_promotions=1,
        equity_usd=10_000,
        team_ids=("berkshire", "momentum", "mean_reversion", "volatility_breakout"),
    )

    result = run_once(
        config=cfg,
        scan_fn=fake_scan,
        journal_module=isolated_journal,
    )

    assert result["status"] == "ok"
    assert policy_loads == 1
    assert seen_policies == [policy, policy, policy, policy]
    assert seen_team_ids == ["berkshire", "momentum", "mean_reversion", "volatility_breakout"]
    teams = result["summary"]["teams"]
    profiles = {team["team_id"]: team for team in teams}
    assert profiles["momentum"]["preferred_playbook_ids"] == ["PB_CRYPTO_TREND_CONTINUATION_001"]
    assert profiles["mean_reversion"]["preferred_playbook_ids"] == ["PB_CRYPTO_MEAN_REVERSION_001"]
    assert profiles["volatility_breakout"]["preferred_playbook_ids"] == [
        "PB_CRYPTO_BREAKOUT_PULLBACK_001"
    ]
    assert "stretched" in profiles["mean_reversion"]["entry_style"]
    assert profiles["volatility_breakout"]["risk_personality"]

    journal_lines = [
        json.loads(line)
        for line in isolated_journal.DECISIONS_LOG.read_text(encoding="utf-8").splitlines()
    ]
    cycle = journal_lines[-1]
    assert cycle["type"] == "berkshire_signal_scheduler_cycle"
    assert cycle["decision_policy"]["profile"] == "adaptive_hybrid_v1"
    assert len(cycle["teams"]) == 4
    assert cycle["teams"][2]["required_soft_policy_ids"]


def test_controller_runs_before_single_effective_policy_load(
    isolated_journal,
    monkeypatch,
) -> None:
    call_order: list[str] = []
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
        policy_source="runtime_override",
        policy_revision=1,
    )

    def fake_controller(**_kwargs):
        call_order.append("controller")
        return {"action": "activated", "revision": 1}

    def fake_review_controller(**_kwargs):
        call_order.append("review_controller")
        return {"action": "staged", "active_for_routing": False}

    def fake_canary_controller(**_kwargs):
        call_order.append("canary_controller")
        return {"status": "inactive", "routing_enabled": False}

    def fake_load_policy() -> DecisionPolicy:
        call_order.append("load_policy")
        assert call_order == [
            "controller",
            "review_controller",
            "canary_controller",
            "load_policy",
        ]
        return policy

    def fake_scan(**kwargs):
        call_order.append("scan")
        assert kwargs["decision_policy"] is policy
        return {"id": "scan-post-controller", "signal_count": 0, "signals": []}

    monkeypatch.setattr("berkshire_signal_scheduler.load_decision_policy", fake_load_policy)
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=900,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=200,
        shadow_evaluation_enabled=True,
    )

    result = run_once(
        config=cfg,
        scan_fn=fake_scan,
        journal_module=isolated_journal,
        policy_controller_fn=fake_controller,
        review_controller_fn=fake_review_controller,
        canary_controller_fn=fake_canary_controller,
    )

    assert call_order == [
        "controller",
        "review_controller",
        "canary_controller",
        "load_policy",
        "scan",
    ]
    assert result["summary"]["adaptive_policy_controller"] == {
        "action": "activated",
        "revision": 1,
    }
    assert result["summary"]["shadow_score_review_controller"] == {
        "action": "staged",
        "active_for_routing": False,
    }
    assert result["summary"]["shadow_score_canary"] == {
        "status": "inactive",
        "routing_enabled": False,
    }
    assert result["summary"]["decision_policy"]["runtime"] == {
        "source": "runtime_override",
        "revision": 1,
        "state_error": None,
    }


def test_controller_failure_does_not_abort_scheduler_cycle(
    isolated_journal,
    monkeypatch,
) -> None:
    policy = DecisionPolicy(
        profile="adaptive_hybrid_v1",
        strong_min_score=80,
        gray_min_score=60,
        strong_lane="rules_baseline",
        gray_lane="rules_plus_llm",
        reject_lane="no_trade",
        gray_requires_llm=True,
        review_risk_multipliers=(0.0, 0.5, 1.0),
        live_enabled=False,
    )
    monkeypatch.setattr("berkshire_signal_scheduler.load_decision_policy", lambda: policy)

    def broken_controller(**_kwargs):
        raise RuntimeError("state disk unavailable")

    result = run_once(
        config=BerkshireSignalSchedulerConfig(
            enabled=True,
            interval_s=900,
            symbols=["BTC-USDT"],
            limit=1,
            max_promotions=1,
            equity_usd=200,
            shadow_evaluation_enabled=False,
        ),
        scan_fn=lambda **_kwargs: {
            "id": "scan-after-controller-error",
            "signal_count": 0,
            "signals": [],
        },
        journal_module=isolated_journal,
        policy_controller_fn=broken_controller,
    )

    assert result["status"] == "ok"
    assert result["summary"]["adaptive_policy_controller"] == {
        "action": "error",
        "reason": "controller_callback_failed",
        "error": "state disk unavailable",
    }


def test_scheduler_rotates_team_first_pick_by_interval(monkeypatch) -> None:
    from berkshire_signal_scheduler import _rotated_team_ids

    monkeypatch.setattr("berkshire_signal_scheduler.time.time", lambda: 60.0)

    assert _rotated_team_ids(("berkshire", "momentum", "mean_reversion"), 60) == (
        "momentum",
        "mean_reversion",
        "berkshire",
    )


def test_scheduler_run_once_respects_kill_switch(isolated_journal):
    isolated_journal.KILL_SWITCH.touch()
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=10_000,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"signals": [_eligible_signal()]},
        journal_module=isolated_journal,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "kill_switch_active"


def test_scheduler_run_once_respects_startup_sync_guard(isolated_journal):
    isolated_journal.set_startup_sync_guard("exchange_snapshot_failed", {"error": "okx down"})
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=10_000,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"signals": [_eligible_signal()]},
        journal_module=isolated_journal,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "startup_sync_blocked"


def test_scheduler_selects_top10_by_confidence(isolated_journal, monkeypatch):
    monkeypatch.setenv("STRATEGY_TEAM_MAX_OPEN_POSITIONS", "10")
    signals = [
        {
            "signal_id": f"sig-{idx:02d}",
            "symbol": f"SIG{idx:02d}-USDT",
            "status": "candidate",
            "signal": "candidate",
            "direction": "long",
            "action_hint": "OPEN_LONG",
            "confidence": 0.8 + idx / 1000,
            "score": 100 - idx,
            "volume_usd_24h": str(1_000_000 + idx),
            "blockers": [],
        }
        for idx in range(12)
    ]
    promoted: list[str] = []

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": True,
                "stage": "execution",
                "reason": "paper_demo_executed",
            }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return FakePromotion(signal_id=signal["signal_id"])

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=None,
        limit=50,
        max_promotions=10,
        equity_usd=10_000,
        max_llm_attempts_per_cycle=10,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {
            "id": "scan-top10",
            "universe_count": 50,
            "signal_count": 12,
            "top_symbol": "SIG11-USDT",
            "top_signal": "candidate",
            "signals": signals,
        },
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert result["summary"]["eligible_candidates"] == 12
    assert result["summary"]["selected_candidates"] == 10
    assert promoted == [f"sig-{idx:02d}" for idx in range(11, 1, -1)]


def test_scheduler_limits_llm_attempts_per_cycle(isolated_journal):
    signals = [
        {
            **_eligible_signal(),
            "signal_id": f"sig-attempt-{idx}",
            "symbol": f"ATT{idx}-USDT",
            "confidence": 0.9 - idx * 0.01,
            "score": 79 - idx,
        }
        for idx in range(6)
    ]
    promoted: list[str] = []

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": False,
                "stage": "final_ticket",
                "reason": "ticket_only",
            }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return FakePromotion(signal_id=signal["signal_id"])

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=None,
        limit=50,
        max_promotions=10,
        equity_usd=10_000,
        max_llm_attempts_per_cycle=3,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"id": "scan-attempts", "signals": signals, "signal_count": 6},
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert result["summary"]["llm_attempts"] == 3
    assert result["summary"]["llm_attempt_cap"] == 3
    assert promoted == ["sig-attempt-0", "sig-attempt-1", "sig-attempt-2"]


def test_scheduler_strong_lane_is_not_blocked_by_legacy_llm_prefilter(isolated_journal):
    promoted: list[str] = []
    weak_signal = {
        **_eligible_signal(),
        "signal_id": "sig-weak",
        "symbol": "WEAK-USDT",
        "confidence": 0.71,
        "score": 90,
    }
    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["WEAK-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=10_000,
        max_llm_attempts_per_cycle=3,
        llm_min_confidence=0.72,
        llm_min_score=70,
    )

    result = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"id": "scan-weak", "signals": [weak_signal], "signal_count": 1},
        promotion_fn=lambda signal, **_kwargs: promoted.append(signal["signal_id"]),
        journal_module=isolated_journal,
    )

    assert result["summary"]["llm_attempts"] == 0
    assert result["summary"]["llm_prefilter_skipped"] == 0
    assert promoted == ["sig-weak"]


def test_scheduler_symbol_cooldown_skips_repeat_llm_attempt(isolated_journal):
    promoted: list[str] = []

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": False,
                "stage": "final_ticket",
                "reason": "ticket_only",
            }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return FakePromotion(signal_id=signal["signal_id"])

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=10_000,
        max_llm_attempts_per_cycle=3,
        llm_symbol_cooldown_minutes=240,
    )

    scan = {"id": "scan-cooldown", "signals": [_eligible_signal()], "signal_count": 1}
    first = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )
    second = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: scan,
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert first["summary"]["llm_attempts"] == 0
    assert second["summary"]["llm_attempts"] == 0
    assert second["summary"]["cooldown_skipped"] == 1
    assert second["promotions"][0]["stage"] == "llm_symbol_cooldown"
    assert promoted == ["sig-scheduled"]


def test_scheduler_fingerprint_cache_skips_similar_signal(isolated_journal):
    promoted: list[str] = []

    @dataclass
    class FakePromotion:
        signal_id: str

        def to_dict(self) -> dict:
            return {
                "signal_id": self.signal_id,
                "promoted": True,
                "executed": False,
                "stage": "final_ticket",
                "reason": "ticket_only",
            }

    def fake_promote(signal, **_kwargs):
        promoted.append(signal["signal_id"])
        return FakePromotion(signal_id=signal["signal_id"])

    cfg = BerkshireSignalSchedulerConfig(
        enabled=True,
        interval_s=60,
        symbols=["BTC-USDT"],
        limit=1,
        max_promotions=1,
        equity_usd=10_000,
        max_llm_attempts_per_cycle=3,
        llm_symbol_cooldown_minutes=0,
        llm_cache_ttl_s=21_600,
    )
    signal = {
        **_eligible_signal(),
        "evidence": {"last_price": 65000, "regime": "TRENDING_UP"},
    }
    similar = {
        **signal,
        "signal_id": "sig-similar",
        "confidence": 0.81,
        "evidence": {"last_price": 65020, "regime": "TRENDING_UP"},
    }

    first = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"id": "scan-cache-1", "signals": [signal], "signal_count": 1},
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )
    second = run_once(
        config=cfg,
        scan_fn=lambda **_kwargs: {"id": "scan-cache-2", "signals": [similar], "signal_count": 1},
        promotion_fn=fake_promote,
        journal_module=isolated_journal,
    )

    assert first["summary"]["llm_attempts"] == 0
    assert second["summary"]["llm_attempts"] == 0
    assert second["summary"]["cache_skipped"] == 1
    assert second["promotions"][0]["stage"] == "llm_fingerprint_cache"
    assert promoted == ["sig-scheduled"]
