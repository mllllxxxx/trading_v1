"""Tests for adaptive strong/gray/reject decision routing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from adaptive_hybrid import (
    AdaptiveHybridError,
    DecisionPolicy,
    build_rule_proposal,
    load_decision_policy,
)
from schemas.models import LLMContextReview, TradeDecisionTicket
from signal_pipeline import run_signal_to_demo_execution


def _signal(*, score: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_id": f"sig-adaptive-{score}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "team_momentum_scanner",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "15m_1h_4h",
        "direction": "long",
        "status": "strong_candidate" if score >= 80 else "candidate",
        "confidence": score / 100,
        "confidence_components": {"setup_quality": score / 100},
        "score": score,
        "grade": "A" if score >= 80 else "B",
        "action_hint": "OPEN_LONG",
        "mode": "signal_only",
        "time_horizon": "swing_2d_7d",
        "promotion_gate": "eligible_for_draft_ticket",
        "reasons": ["Continuous momentum evidence."],
        "blockers": [],
        "entry_zone": "99.5 - 100.5",
        "invalidation": "95",
        "target_zone": "110",
        "risk_reward": "2",
        "last_price": "100",
        "team_id": "momentum",
        "team_name": "Momentum",
        "strategy_id": "crypto_momentum_breakout",
        "strategy_name": "Momentum Breakout",
        "target_risk_pct_equity": 0.04,
        "preferred_playbook_ids": ["PB_CRYPTO_TREND_CONTINUATION_001"],
        "required_soft_policy_ids": ["SOFT_STRATEGY_TEAM_001"],
        "entry_style": "Wait for pullback.",
        "avoid_conditions": ["late chase"],
        "llm_guidance": "Veto unresolved context conflicts.",
        "risk_personality": "trend follower",
        "llm_context": {"role": "advisory_signal_context"},
        "evidence": {
            "provider_source": "okx_public_tickers+okx_confirmed_candles",
            "last_price": "100",
            "spread_bps": "1.5",
            "data_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_age_s": 30.0,
            "regime": "TRENDING_UP",
            "confluence_score": 2.8,
            "feature_snapshot": {"1H": {"atr14": 2.0}},
            "regime_evidence": {"one_hour_adx14": 30.0},
            "setup_quality": {
                "rule_score": score,
                "score_components": {"trend_alignment": score / 100},
                "conflicts": [],
            },
        },
    }
    payload.update(overrides)
    return payload


def _review(decision: str = "APPROVE", risk_multiplier: float = 0.5) -> dict[str, object]:
    return {
        "schema_version": "llm_context_review.v1",
        "review_id": "review-adaptive-001",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "risk_multiplier": risk_multiplier,
        "conflict_flags": ["late_chase_checked"],
        "evidence_refs": ["signal:sig-adaptive-72", "rule:SOFT_STRATEGY_TEAM_001"],
        "reasoning_summary": "Context supports the rule proposal at reduced risk.",
    }


def _decision_types(journal_module: object) -> list[str]:
    import json

    path = journal_module.DECISIONS_LOG
    return [json.loads(line)["type"] for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_rule_proposal_uses_canonical_three_zone_thresholds() -> None:
    assert build_rule_proposal(_signal(score=84)).decision_zone == "strong"
    assert build_rule_proposal(_signal(score=72)).decision_zone == "gray"
    assert build_rule_proposal(_signal(score=55)).decision_zone == "reject"


def test_policy_loader_includes_canonical_review_health_contract() -> None:
    policy = load_decision_policy()

    assert policy.llm_review_health_enforcement == "observe_only"
    assert policy.llm_review_health_minimum_reviewed == 30
    assert policy.llm_review_health_minimum_approved == 10
    assert policy.llm_review_health_minimum_declined == 10
    assert policy.llm_review_health_minimum_multiplier_coverage == 0.90
    assert policy.llm_review_health_minimum_segment_reviewed == 10
    assert policy.llm_review_health_confidence_level == 0.90
    assert policy.adaptive_controller.mode == "demo_auto"
    assert policy.adaptive_controller.minimum_new_eligible_outcomes == 20
    assert policy.adaptive_controller.minimum_strategy_eligible_outcomes == 20
    assert policy.adaptive_controller.strategy_diagnostics_mode == "observe_only"
    assert policy.adaptive_controller.strategy_diagnostics_minimum_total == 80
    assert policy.adaptive_controller.strategy_diagnostics_minimum_zone == 20
    assert policy.adaptive_controller.strategy_diagnostics_minimum_conflict_samples == 10
    assert policy.adaptive_controller.required_confirmations == 2
    assert policy.adaptive_controller.max_threshold_step == 5
    assert policy.adaptive_controller.minimum_zone_gap == 10
    experiment = policy.shadow_scoring_experiment
    assert experiment is not None
    assert experiment.experiment_id == "continuous_conflict_v2"
    assert experiment.mode == "shadow_only"
    assert experiment.score_version == "continuous_base_and_severity_v2"
    assert experiment.active_for_routing is False
    assert experiment.max_penalty_per_conflict == 12
    calibration = experiment.threshold_calibration
    assert calibration.mode == "shadow_only"
    assert calibration.strong_candidates == (70, 75, 80, 85, 90)
    assert calibration.gray_candidates == (50, 55, 60, 65, 70, 75)
    assert calibration.minimum_total == 120
    assert calibration.minimum_complete_zone == 30
    assert calibration.minimum_validation_zone == 8
    assert calibration.require_full_counterfactual_capture is True
    assert calibration.max_candidates_reported == 5
    staging = experiment.review_staging
    assert staging.mode == "review_only"
    assert staging.required_confirmations == 2
    assert staging.minimum_new_eligible_outcomes == 20
    assert staging.allowed_execution_adapters == ("paper", "okx_demo")
    assert staging.requires_operator_approval is True
    canary = experiment.canary
    assert canary.mode == "manual_demo"
    assert canary.allowed_execution_adapters == ("paper", "okx_demo")
    assert canary.allocation_rate == 0.2
    assert canary.risk_multiplier == 0.5
    assert canary.max_concurrent_positions == 1
    assert canary.disagreement_only is True
    assert canary.rollback_minimum_closed_trades == 12
    assert experiment.readiness.minimum_valid_scores == 120
    assert experiment.readiness.minimum_score_coverage == 0.9
    assert experiment.readiness.minimum_strategy_count == 4
    assert experiment.readiness.minimum_per_strategy == 30
    assert experiment.readiness.minimum_strategy_validation_records == 8
    assert experiment.readiness.minimum_strategy_validation_objective_gain == -0.05
    assert experiment.readiness.minimum_validation_zone == 8


def test_policy_loader_rejects_shadow_score_activation(tmp_path: Path) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "active_for_routing"
    ] = True
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="cannot be active for routing"):
        load_decision_policy(invalid)


def test_policy_loader_rejects_invalid_shadow_readiness_gate(tmp_path: Path) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "readiness"
    ]["minimum_score_coverage"] = 1.1
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="readiness coverage"):
        load_decision_policy(invalid)


def test_policy_loader_rejects_operational_v2_threshold_calibration(
    tmp_path: Path,
) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "threshold_calibration"
    ]["mode"] = "demo_auto"
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="must remain shadow-only"):
        load_decision_policy(invalid)


def test_policy_loader_rejects_v2_review_without_operator_approval(
    tmp_path: Path,
) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "review_staging"
    ]["requires_operator_approval"] = False
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="requires operator approval"):
        load_decision_policy(invalid)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("allocation_rate", 0.21, "allocation"),
        ("risk_multiplier", 0.51, "risk multiplier"),
        ("disagreement_only", False, "disagreement-only"),
    ],
)
def test_policy_loader_rejects_weakened_v2_canary_contract(
    tmp_path: Path,
    key: str,
    value: object,
    message: str,
) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"]["canary"][key] = value
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match=message):
        load_decision_policy(invalid)


def test_policy_loader_rejects_unsupported_review_health_enforcement(
    tmp_path: Path,
) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["llm_review_health"]["enforcement"] = "rules_only_fallback"
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="review health enforcement"):
        load_decision_policy(invalid)


def test_policy_loader_rejects_single_confirmation_auto_activation(
    tmp_path: Path,
) -> None:
    source = Path("trading/config/decision_policy.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["adaptive_controller"]["required_confirmations"] = 1
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveHybridError, match="at least two confirmations"):
        load_decision_policy(invalid)


def test_context_review_schema_rejects_nonzero_risk_for_veto() -> None:
    payload = _review(decision="VETO", risk_multiplier=0.5)

    try:
        LLMContextReview.from_dict(payload)
    except ValueError as exc:
        assert "risk_multiplier" in str(exc)
    else:
        raise AssertionError("VETO with risk must be rejected")


def test_request_more_data_ticket_allows_null_entry_and_risk() -> None:
    ticket = TradeDecisionTicket.from_dict(
        {
            "decision_id": "dec-wait-001",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": "REQUEST_MORE_DATA",
            "market": "crypto",
            "symbol": "BTC-USDT-SWAP",
            "timeframe": "1h",
            "playbook_id": None,
            "rule_citations": [],
            "thesis": "Wait for fresh confirmation.",
            "entry_plan": None,
            "risk_plan": None,
            "invalidation_conditions": [],
            "confidence": 0.4,
            "data_quality": "B",
            "reasoning_summary": "The candidate needs more evidence.",
        }
    )

    assert ticket.entry_plan is None
    assert ticket.risk_plan is None


def test_strong_lane_executes_without_calling_llm(isolated_journal, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1")

    def forbidden_client(_messages: list[dict[str, str]]) -> dict[str, object]:
        raise AssertionError("strong lane must not call LLM")

    result = run_signal_to_demo_execution(
        _signal(score=84),
        ticket_client=forbidden_client,
        journal_module=isolated_journal,
    )

    assert result.executed is True
    assert result.decision_lane == "rules_baseline"
    assert result.llm_review is None
    assert "rule_proposal" in _decision_types(isolated_journal)
    assert "llm_context_review" not in _decision_types(isolated_journal)


def test_gray_lane_requires_review_and_applies_risk_multiplier(isolated_journal, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1")
    calls = 0

    def review_client(messages: list[dict[str, str]]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        assert "LLMContextReview" in "\n".join(item["content"] for item in messages)
        return _review()

    result = run_signal_to_demo_execution(
        _signal(score=72),
        ticket_client=review_client,
        journal_module=isolated_journal,
    )

    assert result.executed is True
    assert calls == 1
    assert result.decision_lane == "rules_plus_llm"
    assert result.llm_review is not None
    assert result.pipeline_result is not None
    assert result.pipeline_result["ticket"]["risk_plan"]["risk_pct_equity"] == 0.02
    assert "llm_context_review" in _decision_types(isolated_journal)


def test_signal_pipeline_uses_injected_policy_snapshot(isolated_journal, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1")
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
    calls = 0

    def review_client(_messages: list[dict[str, str]]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        payload = _review()
        payload["evidence_refs"] = [
            "signal:sig-adaptive-57",
            "rule:SOFT_STRATEGY_TEAM_001",
        ]
        return payload

    result = run_signal_to_demo_execution(
        _signal(score=57),
        ticket_client=review_client,
        journal_module=isolated_journal,
        decision_policy=policy,
    )

    assert result.decision_lane == "rules_plus_llm"
    assert result.rule_proposal is not None
    assert result.rule_proposal["decision_zone"] == "gray"
    assert calls == 1


def test_reject_lane_does_not_call_llm_or_execute(isolated_journal, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1")

    def forbidden_client(_messages: list[dict[str, str]]) -> dict[str, object]:
        raise AssertionError("reject lane must not call LLM")

    result = run_signal_to_demo_execution(
        _signal(score=55),
        ticket_client=forbidden_client,
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.decision_lane == "no_trade"
    assert result.stage == "decision"
    assert isolated_journal.read_positions() == []
