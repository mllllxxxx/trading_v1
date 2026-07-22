"""Tests for evidence-gated adaptive threshold evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from replay.adaptive_evaluation import (
    AdaptiveEvaluationError,
    evaluate_adaptive_thresholds,
    write_adaptive_evaluation_report,
)
from replay.run_adaptive_evaluation import load_adaptive_records, run_adaptive_evaluation


POLICY_PATH = Path("trading/config/decision_policy.json")


def _record(
    score: float,
    r_multiple: float,
    *,
    source: str = "backtest",
    eligible: bool = True,
    sequence: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "rule_score": score,
        "r_multiple": r_multiple,
        "pnl_usd": r_multiple * 10,
        "evaluation_source": source,
        "counterfactual_eligible": eligible,
        "symbol": "BTC-USDT-SWAP",
        "strategy_id": "crypto_momentum_breakout",
        "regime": "TRENDING_UP",
    }
    if sequence is not None:
        payload["entry_index"] = sequence
    return payload


def _eligible_sample() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(40):
        records.append(
            _record(88 + index % 5, 1.4 if index % 4 else -1.0, sequence=len(records))
        )
        records.append(
            _record(68 + index % 8, 0.7 if index % 2 else -0.6, sequence=len(records))
        )
        records.append(
            _record(45 + index % 10, -0.8 if index % 3 else 0.3, sequence=len(records))
        )
    return records


def _v2_readiness_sample(*, v2_better: bool) -> list[dict[str, object]]:
    strategies = (
        "quality_directional",
        "crypto_momentum_breakout",
        "crypto_mean_reversion",
        "crypto_volatility_breakout",
    )
    rows: list[dict[str, object]] = []
    patterns = (
        (75.0, 85.0, 1.5),
        (55.0, 70.0, 0.6),
        (85.0, 55.0, -1.0),
        (70.0, 65.0, -0.4),
    )
    for index in range(40):
        active_score, experiment_score, outcome = patterns[index % len(patterns)]
        if not v2_better:
            active_score, experiment_score = experiment_score, active_score
        for strategy_id in strategies:
            row = _record(active_score, outcome, sequence=len(rows))
            row["strategy_id"] = strategy_id
            row["experimental_scores"] = {
                "continuous_conflict_v2": {
                    "mode": "shadow_only",
                    "score_version": "continuous_base_and_severity_v2",
                    "score": experiment_score,
                    "active_for_routing": False,
                }
            }
            rows.append(row)
    return rows


def test_observational_trades_cannot_recommend_thresholds() -> None:
    rows = [_record(85, 1.2, source="observational", eligible=False) for _ in range(150)]

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)

    assert result["status"] == "insufficient_evidence"
    assert result["recommended_thresholds"] is None
    assert result["eligible_records"] == 0
    assert result["exclusion_reasons"]["not_counterfactual_eligible"] == 150
    assert result["auto_apply"] is False


def test_invalid_score_and_missing_outcome_are_excluded() -> None:
    rows = [
        _record(101, 1.0),
        {**_record(80, 1.0), "r_multiple": None, "pnl_usd": None},
        _record(85, 1.0),
    ]

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH, min_total=1, min_zone=1)

    assert result["eligible_records"] == 1
    assert result["excluded_records"] == 2
    assert result["exclusion_reasons"]["invalid_rule_score"] == 1
    assert result["exclusion_reasons"]["missing_outcome"] == 1


def test_shadow_score_experiment_compares_v1_v2_on_identical_outcomes() -> None:
    rows = [
        _record(82, 1.0, sequence=0),
        _record(78, 0.8, sequence=1),
        _record(58, -1.0, sequence=2),
        _record(62, -0.8, sequence=3),
    ]
    v2_scores = [78.0, 82.0, 62.0, 58.0]
    for row, score in zip(rows, v2_scores):
        row["experimental_scores"] = {
            "continuous_conflict_v2": {
                "mode": "shadow_only",
                "score_version": "continuous_base_and_severity_v2",
                "score": score,
                "active_for_routing": False,
            }
        }

    result = evaluate_adaptive_thresholds(
        rows,
        policy_path=POLICY_PATH,
        min_total=1,
        min_zone=1,
    )
    experiment = result["shadow_scoring_experiment_evaluation"][
        "continuous_conflict_v2"
    ]

    assert experiment["eligible_records"] == 4
    assert experiment["score_coverage"]["valid"] == 4
    assert experiment["score_coverage"]["ratio"] == 1.0
    assert experiment["zone_transitions"] == {
        "gray->reject": 1,
        "gray->strong": 1,
        "reject->gray": 1,
        "strong->gray": 1,
    }
    assert experiment["complete_metrics"]["active_v1"]["strong"]["n"] == 1
    assert experiment["complete_metrics"]["experimental_v2"]["strong"]["n"] == 1
    assert experiment["auto_apply"] is False
    assert experiment["activation_recommendation"] is None
    assert experiment["review_eligibility"]["status"] == "collecting_evidence"
    assert experiment["review_eligibility"]["eligible"] is False


def test_shadow_score_experiment_excludes_missing_or_unsafe_evidence() -> None:
    rows = [_record(82, 1.0, sequence=index) for index in range(3)]
    rows[0]["experimental_scores"] = {
        "continuous_conflict_v2": {
            "mode": "shadow_only",
            "score_version": "continuous_base_and_severity_v2",
            "score": 81.5,
            "active_for_routing": False,
        }
    }
    rows[2]["experimental_scores"] = {
        "continuous_conflict_v2": {
            "mode": "shadow_only",
            "score_version": "continuous_base_and_severity_v2",
            "score": 90,
            "active_for_routing": True,
        }
    }

    result = evaluate_adaptive_thresholds(
        rows,
        policy_path=POLICY_PATH,
        min_total=1,
        min_zone=1,
    )
    coverage = result["shadow_scoring_experiment_evaluation"][
        "continuous_conflict_v2"
    ]["score_coverage"]

    assert coverage["valid"] == 1
    assert coverage["exclusion_reasons"] == {
        "experiment_active_for_routing": 1,
        "missing_experiment_score": 1,
    }


def test_evaluator_rejects_operational_v2_threshold_calibration(
    tmp_path: Path,
) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "threshold_calibration"
    ]["mode"] = "demo_auto"
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveEvaluationError, match="must remain shadow-only"):
        evaluate_adaptive_thresholds([], policy_path=invalid)


def test_evaluator_rejects_v2_review_staging_without_approval(
    tmp_path: Path,
) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"][
        "review_staging"
    ]["requires_operator_approval"] = False
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveEvaluationError, match="requires operator approval"):
        evaluate_adaptive_thresholds([], policy_path=invalid)


def test_evaluator_rejects_weakened_v2_canary_allocation(tmp_path: Path) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["shadow_scoring_experiments"]["continuous_conflict_v2"]["canary"][
        "allocation_rate"
    ] = 0.5
    invalid = tmp_path / "decision_policy.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AdaptiveEvaluationError, match="canary allocation"):
        evaluate_adaptive_thresholds([], policy_path=invalid)


def test_shadow_score_readiness_requires_holdout_improvement() -> None:
    result = evaluate_adaptive_thresholds(
        _v2_readiness_sample(v2_better=True),
        policy_path=POLICY_PATH,
    )
    experiment = result["shadow_scoring_experiment_evaluation"][
        "continuous_conflict_v2"
    ]
    readiness = experiment["review_eligibility"]

    assert readiness["status"] == "eligible_for_review"
    assert readiness["eligible"] is True
    assert readiness["blocking_reasons"] == []
    assert all(readiness["gates"].values())
    assert readiness["objective_comparison"]["calibration_delta_v2_minus_v1"] > 0.02
    assert readiness["objective_comparison"]["validation_delta_v2_minus_v1"] > 0
    assert readiness["strategy_coverage"]["observed_strategy_count"] == 4
    assert readiness["strategy_coverage"]["below_minimum"] == []
    assert experiment["activation_recommendation"] is None
    assert experiment["auto_apply"] is False


def test_shadow_score_calibrates_shifted_v2_distribution_before_review() -> None:
    rows = _v2_readiness_sample(v2_better=True)
    for row in rows:
        experiment = row["experimental_scores"]["continuous_conflict_v2"]
        experiment["score"] = float(experiment["score"]) - 10

    experiment = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "shadow_scoring_experiment_evaluation"
    ]["continuous_conflict_v2"]
    calibration = experiment["threshold_calibration"]

    assert experiment["complete_metrics"]["experimental_v2"]["strong"]["n"] == 0
    assert calibration["status"] == "candidate_ready"
    assert calibration["candidate_thresholds"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 60.0,
        "changed_from_active_v1": True,
        "requires_human_review": True,
        "active_for_routing": False,
    }
    assert calibration["objective_comparison_vs_active_v1"][
        "validation_delta_v2_minus_v1"
    ] > 0
    assert experiment["review_eligibility"]["status"] == "eligible_for_review"
    assert experiment["review_eligibility"]["evaluated_v2_thresholds"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 60.0,
    }
    assert experiment["activation_recommendation"] is None


def test_shadow_score_calibration_requires_full_counterfactual_capture() -> None:
    rows = _v2_readiness_sample(v2_better=True)
    for row in rows:
        row["counterfactual_score_floor"] = 60

    experiment = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "shadow_scoring_experiment_evaluation"
    ]["continuous_conflict_v2"]
    calibration = experiment["threshold_calibration"]

    assert calibration["status"] == "collecting_evidence"
    assert calibration["candidate_thresholds"] is None
    assert "full_counterfactual_capture_required" in calibration["sample_reasons"]
    assert experiment["review_eligibility"]["gates"][
        "threshold_calibration_sample"
    ] is False
    assert experiment["review_eligibility"]["status"] == "collecting_evidence"


def test_shadow_score_calibration_gain_must_survive_final_holdout() -> None:
    rows = _v2_readiness_sample(v2_better=True)
    validation_start = int(len(rows) * 0.70)
    for row in rows[validation_start:]:
        experiment = row["experimental_scores"]["continuous_conflict_v2"]
        experiment["score"] = 55.0 if float(row["r_multiple"]) > 0 else 85.0

    experiment = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "shadow_scoring_experiment_evaluation"
    ]["continuous_conflict_v2"]
    calibration = experiment["threshold_calibration"]

    assert calibration["status"] == "not_eligible"
    assert calibration["candidate_thresholds"] is None
    assert calibration["candidate_gate_failures"][
        "validation_strong_confidence_lower_bound"
    ] > 0
    assert experiment["review_eligibility"]["status"] == "not_eligible"
    assert "threshold_calibration_candidate" in experiment[
        "review_eligibility"
    ]["blocking_reasons"]


def test_shadow_score_readiness_rejects_worse_v2_after_sample_gates_pass() -> None:
    result = evaluate_adaptive_thresholds(
        _v2_readiness_sample(v2_better=False),
        policy_path=POLICY_PATH,
    )
    readiness = result["shadow_scoring_experiment_evaluation"][
        "continuous_conflict_v2"
    ]["review_eligibility"]

    assert readiness["status"] == "not_eligible"
    assert readiness["eligible"] is False
    assert readiness["gates"]["valid_score_sample"] is True
    assert readiness["gates"]["strategy_coverage"] is True
    assert readiness["gates"]["validation_objective_gain"] is False
    assert readiness["gates"]["validation_strong_confidence"] is False
    assert "validation_objective_gain" in readiness["blocking_reasons"]


def test_shadow_score_readiness_does_not_hide_one_degraded_strategy() -> None:
    rows = _v2_readiness_sample(v2_better=True)
    degraded_strategy = "crypto_volatility_breakout"
    for row in rows:
        if row["strategy_id"] != degraded_strategy:
            continue
        active_score = float(row["rule_score"])
        if active_score >= 80:
            row["r_multiple"] = 1.5
        elif active_score < 60:
            row["r_multiple"] = -1.0

    experiment = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "shadow_scoring_experiment_evaluation"
    ]["continuous_conflict_v2"]
    readiness = experiment["review_eligibility"]
    strategy = experiment["strategy_comparison"][degraded_strategy]

    assert readiness["gates"]["validation_objective_gain"] is True
    assert readiness["gates"]["strategy_validation_non_regression"] is False
    assert readiness["status"] == "not_eligible"
    assert "strategy_validation_non_regression" in readiness["blocking_reasons"]
    assert strategy["status"] == "degraded"
    assert strategy["validation_delta_v2_minus_v1"] < -0.05


def test_backtest_evidence_can_produce_reviewed_proposal_without_mutating_policy() -> None:
    before = POLICY_PATH.read_text(encoding="utf-8")

    result = evaluate_adaptive_thresholds(_eligible_sample(), policy_path=POLICY_PATH)

    assert result["status"] == "ready"
    assert result["recommended_thresholds"] is not None
    assert result["recommended_thresholds"]["eligible_for_guarded_demo_controller"] is True
    assert result["recommended_thresholds"]["gray_min_score"] < result["recommended_thresholds"]["strong_min_score"]
    assert result["candidate_ranking"]
    assert result["recommendation_method"] == "chronological_risk_adjusted_v1"
    assert result["chronological_validation"]["validation_records"] == 36
    assert result["chronological_validation"]["fallback_records"] == 0
    assert result["current_policy_metrics"]["strong"]["average_r_lower_bound_90"] > 0
    assert result["auto_apply"] is False
    assert POLICY_PATH.read_text(encoding="utf-8") == before


def test_runtime_zone_override_changes_only_current_evaluation_baseline() -> None:
    before = POLICY_PATH.read_text(encoding="utf-8")

    result = evaluate_adaptive_thresholds(
        _eligible_sample(),
        policy_path=POLICY_PATH,
        zone_override={"strong_min_score": 75, "gray_min_score": 55},
    )

    assert result["current_policy"]["strong_min_score"] == 75
    assert result["current_policy"]["gray_min_score"] == 55
    strategy = result["strategy_threshold_diagnostics"]["crypto_momentum_breakout"]
    assert strategy["current_policy"]["strong_min_score"] == 75
    assert strategy["current_policy"]["gray_min_score"] == 55
    assert "strategy_threshold_diagnostics" not in strategy
    assert POLICY_PATH.read_text(encoding="utf-8") == before


def test_strategy_diagnostics_do_not_borrow_outcomes_from_other_strategies() -> None:
    rows = _eligible_sample()
    for index in range(20):
        row = _record(82, 1.0, sequence=len(rows))
        row["strategy_id"] = "sparse_strategy"
        rows.append(row)

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    diagnostics = result["strategy_threshold_diagnostics"]

    assert diagnostics["crypto_momentum_breakout"]["eligible_records"] == 120
    assert diagnostics["crypto_momentum_breakout"]["status"] == "ready"
    assert diagnostics["sparse_strategy"]["eligible_records"] == 20
    assert diagnostics["sparse_strategy"]["status"] == "insufficient_evidence"
    assert "eligible_records_below_80" in diagnostics["sparse_strategy"][
        "insufficiency_reasons"
    ]
    assert diagnostics["sparse_strategy"]["recommended_thresholds"] is None


def test_strategy_diagnostics_can_recommend_opposite_threshold_directions() -> None:
    rows: list[dict[str, object]] = []

    def add(strategy_id: str, score: float, outcome: float) -> None:
        row = _record(score, outcome, sequence=len(rows))
        row["strategy_id"] = strategy_id
        rows.append(row)

    for index in range(40):
        add("lower_threshold", 78, 1.2 if index % 5 else -0.4)
        add("lower_threshold", 68, 0.6 if index % 2 else -0.3)
        add("lower_threshold", 55, -0.8 if index % 3 else 0.2)
    for index in range(40):
        add("higher_threshold", 88, 1.5 if index % 5 else -0.5)
        if index < 20:
            add("higher_threshold", 82, -1.0)
        if index < 30:
            add("higher_threshold", 72, 0.5 if index % 2 else -0.4)
            add("higher_threshold", 55, -0.8 if index % 3 else 0.2)

    diagnostics = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "strategy_threshold_diagnostics"
    ]

    assert diagnostics["lower_threshold"]["status"] == "ready"
    assert diagnostics["higher_threshold"]["status"] == "ready"
    assert diagnostics["lower_threshold"]["recommended_thresholds"][
        "strong_min_score"
    ] == 75
    assert diagnostics["higher_threshold"]["recommended_thresholds"][
        "strong_min_score"
    ] == 85
    assert diagnostics["lower_threshold"]["auto_apply"] is False
    assert diagnostics["higher_threshold"]["auto_apply"] is False


def test_conflict_penalty_diagnostics_separate_harmful_and_over_penalized() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(20):
        row = _record(70, 0.2, sequence=len(rows))
        row["strategy_id"] = "strategy_a"
        row["conflicts"] = []
        rows.append(row)
    for conflict_id, outcome in (("conflict_bad", -1.0), ("conflict_good", 1.0)):
        for _index in range(12):
            row = _record(70, outcome, sequence=len(rows))
            row["strategy_id"] = "strategy_a"
            row["conflicts"] = [conflict_id]
            rows.append(row)
    for _index in range(12):
        row = _record(70, -1.0, sequence=len(rows))
        row["strategy_id"] = "strategy_without_baseline"
        row["conflicts"] = ["conflict_bad"]
        rows.append(row)

    diagnostics = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "conflict_penalty_diagnostics"
    ]
    strategy = diagnostics["strategies"]["strategy_a"]
    associations = {
        item["conflict_id"]: item for item in strategy["conflicts"]
    }
    sparse = diagnostics["strategies"]["strategy_without_baseline"]["conflicts"][0]

    assert associations["conflict_bad"]["association_label"] == "harmful"
    assert associations["conflict_bad"]["delta_average_r_ci_90"]["upper"] < 0
    assert (
        associations["conflict_good"]["association_label"]
        == "over_penalized_candidate"
    )
    assert associations["conflict_good"]["delta_average_r_ci_90"]["lower"] > 0
    assert strategy["conflict_count_metrics"]["0"]["n"] == 20
    assert strategy["conflict_count_metrics"]["1"]["n"] == 24
    assert sparse["association_label"] == "insufficient_evidence"
    assert diagnostics["interpretation"] == "non_causal_within_strategy_association"
    assert diagnostics["auto_apply"] is False


def test_recommendation_does_not_cross_counterfactual_score_floor() -> None:
    rows: list[dict[str, object]] = []
    for index in range(40):
        rows.append(
            {
                **_record(
                    88 + index % 5,
                    1.4 if index % 4 else -1.0,
                    sequence=len(rows),
                ),
                "counterfactual_score_floor": 60,
            }
        )
        for offset in range(2):
            rows.append(
                {
                    **_record(
                        62 + (index * 2 + offset) % 16,
                        0.7 if (index + offset) % 2 else -0.6,
                        sequence=len(rows),
                    ),
                    "counterfactual_score_floor": 60,
                }
            )

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)

    assert result["status"] == "ready"
    assert result["evidence_coverage"]["counterfactual_score_floor"] == 60
    assert result["recommended_thresholds"]["gray_min_score"] >= 60
    assert all(item["gray_min_score"] >= 60 for item in result["candidate_ranking"])


def test_positive_in_sample_mean_cannot_bypass_confidence_gate() -> None:
    rows: list[dict[str, object]] = []
    for index in range(40):
        strong_r = 1.0 if index % 2 == 0 else -0.9
        rows.extend(
            [
                _record(92, strong_r, sequence=len(rows)),
                _record(65, 0.4 if index % 2 == 0 else -0.2, sequence=len(rows) + 1),
                _record(45, -0.5, sequence=len(rows) + 2),
            ]
        )

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)

    assert result["current_policy_metrics"]["strong"]["average_r"] > 0
    assert result["current_policy_metrics"]["strong"]["average_r_lower_bound_90"] <= 0
    assert result["status"] == "insufficient_evidence"
    assert result["candidate_gate_failures"]["strong_confidence_lower_bound"] > 0


def test_final_chronological_window_blocks_calibration_overfit() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(28):
        rows.extend(
            [
                _record(92, 1.5, sequence=len(rows)),
                _record(65, 0.3, sequence=len(rows) + 1),
                _record(45, -0.5, sequence=len(rows) + 2),
            ]
        )
    for _index in range(12):
        rows.extend(
            [
                _record(92, -1.0, sequence=len(rows)),
                _record(65, 0.3, sequence=len(rows) + 1),
                _record(45, -0.5, sequence=len(rows) + 2),
            ]
        )

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)

    assert result["current_policy_metrics"]["strong"]["average_r"] > 0
    assert result["current_policy_calibration_metrics"]["strong"]["average_r"] > 0
    assert result["current_policy_validation_metrics"]["strong"]["average_r"] < 0
    assert result["status"] == "insufficient_evidence"
    assert result["candidate_gate_failures"]["validation_strong_confidence_lower_bound"] > 0


def test_llm_review_effectiveness_reports_avoided_and_missed_outcomes() -> None:
    rows = _eligible_sample()
    rows[0]["observed_llm_review"] = {"decision": "APPROVE", "risk_multiplier": 1.0}
    rows[1]["observed_llm_review"] = {"decision": "VETO", "risk_multiplier": 0.0}
    rows[2]["observed_llm_review"] = {"decision": "WAIT", "risk_multiplier": 0.0}
    rows[3]["observed_llm_review"] = {"decision": "VETO", "risk_multiplier": 0.0}

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    review = result["llm_review_effectiveness"]

    assert review["reviewed_records"] == 4
    assert review["declined_losses_avoided"] >= 1
    assert review["declined_profitable_outcomes_missed"] >= 1
    assert review["interpretation"] == "observational_review_subset_only"
    assert review["health"]["status"] == "insufficient_evidence"
    assert review["health"]["runtime_route_changed"] is False
    assert result["llm_review_health"]["reviewed_records"] == 4
    assert result["llm_review_health"]["status"] == "insufficient_evidence"


def test_llm_review_health_is_healthy_when_declines_avoid_losses() -> None:
    rows: list[dict[str, object]] = []
    for index in range(10):
        rows.append(
            {
                **_record(70, 0.8, sequence=len(rows)),
                "observed_llm_review": {"decision": "APPROVE", "risk_multiplier": 1.0},
            }
        )
    for index in range(20):
        rows.append(
            {
                **_record(70, -0.6, sequence=len(rows)),
                "observed_llm_review": {
                    "decision": "VETO" if index % 2 else "WAIT",
                    "risk_multiplier": 0.0,
                },
            }
        )

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    review = result["llm_review_effectiveness"]
    compact = result["llm_review_health"]

    assert review["health"]["status"] == "healthy"
    assert review["health"]["enforcement"] == "observe_only"
    assert review["selection_contribution_ci_90"]["lower"] > 0
    assert review["observed_review_policy_r_per_review"] > review[
        "approve_all_baseline_r_per_review"
    ]
    assert compact["approved_records"] == 10
    assert compact["declined_records"] == 20
    assert compact["declined_losses_avoided"] == 20


def test_llm_review_health_is_degraded_when_it_rejects_profitable_setups() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(10):
        rows.append(
            {
                **_record(70, -0.4, sequence=len(rows)),
                "observed_llm_review": {"decision": "APPROVE", "risk_multiplier": 1.0},
            }
        )
    for index in range(20):
        rows.append(
            {
                **_record(70, 0.8, sequence=len(rows)),
                "observed_llm_review": {
                    "decision": "VETO" if index % 2 else "WAIT",
                    "risk_multiplier": 0.0,
                },
            }
        )

    review = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "llm_review_effectiveness"
    ]

    assert review["health"]["status"] == "degraded"
    assert review["health"]["operator_recommendation"] == "audit_review_prompt_and_gray_policy"
    assert review["health"]["runtime_route_changed"] is False
    assert review["selection_contribution_ci_90"]["upper"] < 0


def test_llm_review_health_is_inconclusive_when_selection_edge_is_uncertain() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(10):
        rows.append(
            {
                **_record(70, 0.5, sequence=len(rows)),
                "observed_llm_review": {"decision": "APPROVE", "risk_multiplier": 1.0},
            }
        )
    for index in range(20):
        outcome = -1.0 if index % 2 == 0 else 1.0
        rows.append(
            {
                **_record(70, outcome, sequence=len(rows)),
                "observed_llm_review": {"decision": "VETO", "risk_multiplier": 0.0},
            }
        )

    review = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)[
        "llm_review_effectiveness"
    ]

    assert review["health"]["status"] == "inconclusive"
    assert review["selection_contribution_ci_90"]["lower"] < 0
    assert review["selection_contribution_ci_90"]["upper"] > 0


def test_llm_review_policy_value_applies_approved_risk_multiplier() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(10):
        rows.append(
            {
                **_record(70, 1.0, sequence=len(rows)),
                "observed_llm_review": {"decision": "APPROVE", "risk_multiplier": 0.5},
            }
        )
    for _index in range(20):
        rows.append(
            {
                **_record(70, -0.5, sequence=len(rows)),
                "observed_llm_review": {"decision": "VETO", "risk_multiplier": 0.0},
            }
        )

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    review = result["llm_review_effectiveness"]

    assert review["reviewed_approve_all_r"] == 0
    assert review["observed_approved_r"] == 5
    assert review["approve_all_baseline_r_per_review"] == 0
    assert review["observed_review_policy_r_per_review"] == 0.166667
    assert review["selection_contribution_r_per_review"] == 0.166667
    assert review["by_risk_multiplier"]["0.5"]["contribution_cumulative_r"] == -5
    assert review["multiplier_coverage"] == 1.0


def test_missing_review_multipliers_fail_metadata_quality_gate() -> None:
    rows = [
        {
            **_record(70, 0.5, sequence=index),
            "observed_llm_review": {
                "decision": "APPROVE" if index < 10 else "VETO",
            },
        }
        for index in range(30)
    ]

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    review = result["llm_review_effectiveness"]
    compact = result["llm_review_health"]

    assert review["reviewed_records"] == 30
    assert review["policy_value_records"] == 0
    assert review["invalid_multiplier_records"] == 30
    assert review["health"]["status"] == "insufficient_evidence"
    assert review["health"]["evidence_gates"]["multiplier_coverage"] is False
    assert (
        review["health"]["operator_recommendation"]
        == "repair_review_risk_multiplier_metadata"
    )
    assert review["declined_profitable_outcomes_missed"] == 0
    assert compact["invalid_multiplier_records"] == 30


def test_degraded_strategy_segment_overrides_healthy_aggregate() -> None:
    rows: list[dict[str, object]] = []
    for _index in range(20):
        row = {
            **_record(70, 0.5, sequence=len(rows)),
            "observed_llm_review": {"decision": "APPROVE", "risk_multiplier": 1.0},
        }
        row["strategy_id"] = "strategy_a"
        rows.append(row)
    for _index in range(30):
        row = {
            **_record(70, -1.0, sequence=len(rows)),
            "observed_llm_review": {"decision": "VETO", "risk_multiplier": 0.0},
        }
        row["strategy_id"] = "strategy_a"
        rows.append(row)
    for _index in range(10):
        row = {
            **_record(70, 1.0, sequence=len(rows)),
            "observed_llm_review": {"decision": "VETO", "risk_multiplier": 0.0},
        }
        row["strategy_id"] = "strategy_b"
        rows.append(row)

    result = evaluate_adaptive_thresholds(rows, policy_path=POLICY_PATH)
    review = result["llm_review_effectiveness"]
    compact = result["llm_review_health"]

    assert review["selection_contribution_ci_90"]["lower"] > 0
    assert review["health"]["status"] == "degraded"
    assert review["health"]["operator_recommendation"] == "audit_degraded_review_segments"
    assert {item["value"] for item in review["health"]["degraded_segments"]} == {
        "strategy_b"
    }
    assert compact["degraded_segment_count"] == 1


def test_evaluation_report_writes_json_and_markdown(tmp_path: Path) -> None:
    evaluation = evaluate_adaptive_thresholds(_eligible_sample(), policy_path=POLICY_PATH)

    paths = write_adaptive_evaluation_report(evaluation, tmp_path, run_id="adaptive-unit")

    payload = json.loads((tmp_path / "adaptive-unit.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / "adaptive-unit.md").read_text(encoding="utf-8")
    assert payload["auto_apply"] is False
    assert "# Adaptive Threshold Evaluation" in markdown
    assert "Review readiness: collecting_evidence" in markdown
    assert set(paths) == {"json", "markdown"}


def test_run_adaptive_evaluation_is_broker_free(tmp_path: Path) -> None:
    result = run_adaptive_evaluation(
        _eligible_sample(),
        output_dir=tmp_path,
        run_id="adaptive-smoke",
        policy_path=POLICY_PATH,
    )

    assert result["broker_calls"] == 0
    assert result["evaluation"]["status"] == "ready"
    assert (tmp_path / "adaptive-smoke.json").exists()


def test_load_adaptive_records_accepts_strategy_backtest_result(tmp_path: Path) -> None:
    source = tmp_path / "strategy-backtest.json"
    source.write_text(
        json.dumps({"team_id": "momentum", "trades": [_record(84, 1.2)]}),
        encoding="utf-8",
    )

    rows = load_adaptive_records(source)

    assert len(rows) == 1
    assert rows[0]["rule_score"] == 84
