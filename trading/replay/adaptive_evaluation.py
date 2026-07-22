"""Evidence-gated evaluation for adaptive hybrid routing thresholds."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


TRADING_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = TRADING_ROOT / "config" / "decision_policy.json"
CALIBRATION_SOURCES = {"shadow", "backtest"}
STRONG_GRID = (70.0, 75.0, 80.0, 85.0, 90.0)
GRAY_GRID = (50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0)
CALIBRATION_FRACTION = 0.70
ONE_SIDED_90_Z = 1.2815515655446004
TWO_SIDED_90_Z = 1.6448536269514722
MIN_VALIDATION_ZONE = 8
MIN_CHANGED_OBJECTIVE_GAIN = 0.02
MAX_VALIDATION_OBJECTIVE_REGRESSION = 0.05
GRAY_MIN_POSITIVE_RATE = 0.25
SEGMENT_NEGATIVE_TOLERANCE_R = -0.10
CONTINUOUS_CONFLICT_EXPERIMENT_ID = "continuous_conflict_v2"
CONTINUOUS_CONFLICT_SCORE_VERSION = "continuous_base_and_severity_v2"


class AdaptiveEvaluationError(RuntimeError):
    """Raised when canonical policy cannot be evaluated safely."""


def evaluate_adaptive_thresholds(
    records: Iterable[Mapping[str, Any]],
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    zone_override: Mapping[str, Any] | None = None,
    min_total: int = 120,
    min_zone: int = 30,
    include_strategy_diagnostics: bool = True,
    include_conflict_diagnostics: bool = True,
    include_shadow_scoring_diagnostics: bool = True,
) -> dict[str, Any]:
    """Evaluate score thresholds on chronological holdout evidence without mutation."""
    policy = _load_policy(policy_path)
    if zone_override is not None:
        policy = _policy_with_zone_override(policy, zone_override)
    rows = [dict(record) for record in records]
    eligible: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for input_index, row in enumerate(rows):
        normalized, reason = _calibration_row(row, input_index=input_index)
        if normalized is None:
            exclusions[reason or "unknown"] += 1
            continue
        eligible.append(normalized)

    split = _chronological_split(eligible)
    calibration_rows = split["calibration_rows"]
    validation_rows = split["validation_rows"]
    current_strong = float(policy["zones"]["strong_min_score"])
    current_gray = float(policy["zones"]["gray_min_score"])
    total_floor = max(1, int(min_total))
    zone_floor = max(1, int(min_zone))
    validation_zone_floor = max(MIN_VALIDATION_ZONE, math.ceil(zone_floor * 0.25))
    candidates, gate_failures, current_candidate = _rank_candidates(
        eligible,
        calibration_rows=calibration_rows,
        validation_rows=validation_rows,
        current_strong=current_strong,
        current_gray=current_gray,
        min_zone=zone_floor,
        min_validation_zone=validation_zone_floor,
        evidence_floor=_counterfactual_score_floor(eligible),
    )

    insufficiency: list[str] = []
    if len(eligible) < total_floor:
        insufficiency.append(f"eligible_records_below_{total_floor}")
    if len(validation_rows) < validation_zone_floor * 2:
        insufficiency.append(
            f"validation_records_below_{validation_zone_floor * 2}"
        )
    if not candidates:
        insufficiency.append("no_threshold_pair_passed_robustness_gates")
    ready = not insufficiency
    recommended = _recommendation(candidates[0], current_strong, current_gray) if ready else None

    ordering = dict(split["summary"])
    review_effectiveness = _llm_review_effectiveness(
        eligible,
        health_config=policy["llm_review_health"],
    )
    result = {
        "schema_version": "adaptive_threshold_evaluation.v1",
        "recommendation_method": "chronological_risk_adjusted_v1",
        "generated_at": _utc_now(),
        "status": "ready" if ready else "insufficient_evidence",
        "current_policy": {
            "profile": policy.get("profile"),
            "strong_min_score": current_strong,
            "gray_min_score": current_gray,
        },
        "current_policy_metrics": current_candidate["zone_metrics"],
        "current_policy_calibration_metrics": current_candidate["calibration_zone_metrics"],
        "current_policy_validation_metrics": current_candidate["validation_zone_metrics"],
        "total_records": len(rows),
        "eligible_records": len(eligible),
        "excluded_records": len(rows) - len(eligible),
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "insufficiency_reasons": insufficiency,
        "evidence_coverage": _evidence_coverage(rows, eligible, ordering=ordering),
        "chronological_validation": ordering,
        "score_bucket_metrics": _score_bucket_metrics(eligible),
        "llm_review_effectiveness": review_effectiveness,
        "llm_review_health": _compact_llm_review_health(review_effectiveness),
        "recommended_thresholds": recommended,
        "candidate_ranking": candidates[:10] if len(eligible) >= total_floor else [],
        "candidate_gate_failures": dict(sorted(gate_failures.items())),
        "minimum_samples": {
            "total": total_floor,
            "per_strong_and_gray_zone": zone_floor,
            "per_validation_strong_and_gray_zone": validation_zone_floor,
        },
        "auto_apply": False,
        "canonical_policy_path": str(policy_path),
    }
    if include_strategy_diagnostics:
        result["strategy_threshold_diagnostics"] = _strategy_threshold_diagnostics(
            eligible,
            policy_path=policy_path,
            zone_override={
                "strong_min_score": current_strong,
                "gray_min_score": current_gray,
            },
            config=policy["adaptive_controller"]["strategy_diagnostics"],
        )
    if include_conflict_diagnostics:
        result["conflict_penalty_diagnostics"] = _conflict_penalty_diagnostics(
            eligible,
            minimum_samples=int(
                policy["adaptive_controller"]["strategy_diagnostics"][
                    "minimum_conflict_samples"
                ]
            ),
        )
    if include_shadow_scoring_diagnostics:
        experiment = policy["shadow_scoring_experiments"][
            CONTINUOUS_CONFLICT_EXPERIMENT_ID
        ]
        result["shadow_scoring_experiment_evaluation"] = {
            CONTINUOUS_CONFLICT_EXPERIMENT_ID: _shadow_scoring_experiment_evaluation(
                eligible,
                calibration_rows=calibration_rows,
                validation_rows=validation_rows,
                strong_min=current_strong,
                gray_min=current_gray,
                config=experiment,
            )
        }
    return result


def write_adaptive_evaluation_report(
    evaluation: Mapping[str, Any],
    output_dir: str | Path,
    *,
    run_id: str = "adaptive_thresholds",
) -> dict[str, str]:
    """Write review artifacts without modifying canonical config."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    markdown_path = out_dir / f"{run_id}.md"
    payload = dict(evaluation)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        strong = float(payload["zones"]["strong_min_score"])
        gray = float(payload["zones"]["gray_min_score"])
        review_health = payload["llm_review_health"]
        enforcement = str(review_health["enforcement"])
        minimum_reviewed = int(review_health["minimum_reviewed"])
        minimum_approved = int(review_health["minimum_approved"])
        minimum_declined = int(review_health["minimum_declined"])
        minimum_multiplier_coverage = float(review_health["minimum_multiplier_coverage"])
        minimum_segment_reviewed = int(review_health["minimum_segment_reviewed"])
        confidence_level = float(review_health["confidence_level"])
        strategy_diagnostics = payload["adaptive_controller"]["strategy_diagnostics"]
        diagnostics_mode = str(strategy_diagnostics["mode"])
        diagnostics_minimum_total = int(strategy_diagnostics["minimum_total"])
        diagnostics_minimum_zone = int(strategy_diagnostics["minimum_zone"])
        diagnostics_minimum_conflict_samples = int(
            strategy_diagnostics["minimum_conflict_samples"]
        )
        experiment_registry = payload["shadow_scoring_experiments"]
        if not isinstance(experiment_registry, Mapping):
            raise TypeError("shadow scoring experiment registry must be an object")
        experiment = experiment_registry[CONTINUOUS_CONFLICT_EXPERIMENT_ID]
        if not isinstance(experiment, Mapping):
            raise TypeError("shadow scoring experiment must be an object")
        experiment_mode = str(experiment["mode"])
        experiment_version = str(experiment["score_version"])
        experiment_active_value = experiment["active_for_routing"]
        if not isinstance(experiment_active_value, bool):
            raise TypeError("shadow scoring active flag must be a boolean")
        experiment_active = experiment_active_value
        experiment_max_total_penalty = float(experiment["max_total_penalty"])
        experiment_max_penalty = float(experiment["max_penalty_per_conflict"])
        readiness = experiment["readiness"]
        if not isinstance(readiness, Mapping):
            raise TypeError("shadow scoring readiness must be an object")
        threshold_calibration = experiment["threshold_calibration"]
        if not isinstance(threshold_calibration, Mapping):
            raise TypeError("shadow scoring threshold calibration must be an object")
        review_staging = experiment["review_staging"]
        if not isinstance(review_staging, Mapping):
            raise TypeError("shadow scoring review staging must be an object")
        canary = experiment["canary"]
        if not isinstance(canary, Mapping):
            raise TypeError("shadow scoring canary must be an object")
        canary_rollback = canary["rollback"]
        if not isinstance(canary_rollback, Mapping):
            raise TypeError("shadow scoring canary rollback must be an object")
        calibration_mode = str(threshold_calibration["mode"])
        strong_grid_payload = threshold_calibration["strong_candidates"]
        gray_grid_payload = threshold_calibration["gray_candidates"]
        full_capture_payload = threshold_calibration[
            "require_full_counterfactual_capture"
        ]
        if not isinstance(strong_grid_payload, list) or not isinstance(
            gray_grid_payload, list
        ):
            raise TypeError("shadow scoring threshold grids must be arrays")
        if not isinstance(full_capture_payload, bool):
            raise TypeError("shadow scoring full-capture flag must be a boolean")
        calibration_strong_grid = tuple(float(item) for item in strong_grid_payload)
        calibration_gray_grid = tuple(float(item) for item in gray_grid_payload)
        calibration_minimum_total = int(threshold_calibration["minimum_total"])
        calibration_minimum_complete_zone = int(
            threshold_calibration["minimum_complete_zone"]
        )
        calibration_minimum_validation_zone = int(
            threshold_calibration["minimum_validation_zone"]
        )
        calibration_require_full_capture = full_capture_payload
        calibration_max_candidates = int(
            threshold_calibration["max_candidates_reported"]
        )
        review_staging_mode = str(review_staging["mode"])
        review_staging_confirmations = int(review_staging["required_confirmations"])
        review_staging_new_outcomes = int(
            review_staging["minimum_new_eligible_outcomes"]
        )
        review_staging_adapters_payload = review_staging[
            "allowed_execution_adapters"
        ]
        review_staging_approval_payload = review_staging[
            "requires_operator_approval"
        ]
        if not isinstance(review_staging_adapters_payload, list):
            raise TypeError("shadow scoring review adapters must be an array")
        if not isinstance(review_staging_approval_payload, bool):
            raise TypeError("shadow scoring review approval flag must be a boolean")
        review_staging_adapters = tuple(
            str(item).strip().lower()
            for item in review_staging_adapters_payload
        )
        canary_mode = str(canary["mode"])
        canary_adapters_payload = canary["allowed_execution_adapters"]
        canary_disagreement_payload = canary["disagreement_only"]
        if not isinstance(canary_adapters_payload, list):
            raise TypeError("shadow scoring canary adapters must be an array")
        if not isinstance(canary_disagreement_payload, bool):
            raise TypeError("shadow scoring canary disagreement flag must be a boolean")
        canary_adapters = tuple(
            str(item).strip().lower() for item in canary_adapters_payload
        )
        canary_allocation_rate = float(canary["allocation_rate"])
        canary_risk_multiplier = float(canary["risk_multiplier"])
        canary_max_positions = int(canary["max_concurrent_positions"])
        canary_minimum_closed = int(canary_rollback["minimum_closed_trades"])
        canary_lcb_floor = float(canary_rollback["average_r_lower_bound_floor"])
        canary_profit_factor_floor = float(canary_rollback["profit_factor_floor"])
        canary_cumulative_r_floor = float(canary_rollback["cumulative_r_floor"])
        readiness_minimum_valid_scores = int(readiness["minimum_valid_scores"])
        readiness_minimum_score_coverage = float(
            readiness["minimum_score_coverage"]
        )
        readiness_minimum_strategy_count = int(
            readiness["minimum_strategy_count"]
        )
        readiness_minimum_per_strategy = int(readiness["minimum_per_strategy"])
        readiness_minimum_strategy_validation_records = int(
            readiness["minimum_strategy_validation_records"]
        )
        readiness_minimum_strategy_validation_gain = float(
            readiness["minimum_strategy_validation_objective_gain"]
        )
        readiness_minimum_calibration_zone = int(
            readiness["minimum_calibration_zone"]
        )
        readiness_minimum_validation_zone = int(
            readiness["minimum_validation_zone"]
        )
        readiness_minimum_calibration_gain = float(
            readiness["minimum_calibration_objective_gain"]
        )
        readiness_minimum_validation_gain = float(
            readiness["minimum_validation_objective_gain"]
        )
        readiness_validation_lcb_floor = float(
            readiness["validation_average_r_lower_bound_floor"]
        )
        readiness_validation_profit_factor_floor = float(
            readiness["validation_profit_factor_floor"]
        )
        readiness_minimum_segment_samples = int(
            readiness["minimum_segment_samples"]
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdaptiveEvaluationError("canonical decision policy unavailable") from exc
    if not 0 <= gray < strong <= 100:
        raise AdaptiveEvaluationError("canonical decision thresholds are invalid")
    if bool(payload.get("live_enabled", False)):
        raise AdaptiveEvaluationError("evaluation refuses a live-enabled adaptive policy")
    if enforcement != "observe_only":
        raise AdaptiveEvaluationError("unsupported LLM review health enforcement")
    if min(minimum_reviewed, minimum_approved, minimum_declined) <= 0:
        raise AdaptiveEvaluationError("LLM review health sample gates are invalid")
    if minimum_approved + minimum_declined > minimum_reviewed:
        raise AdaptiveEvaluationError("LLM review health class gates exceed total gate")
    if not 0 < minimum_multiplier_coverage <= 1:
        raise AdaptiveEvaluationError("LLM review health multiplier coverage is invalid")
    if minimum_segment_reviewed <= 0:
        raise AdaptiveEvaluationError("LLM review health segment gate is invalid")
    if not math.isclose(confidence_level, 0.90, abs_tol=1e-9):
        raise AdaptiveEvaluationError("unsupported LLM review health confidence level")
    if diagnostics_mode != "observe_only":
        raise AdaptiveEvaluationError("unsupported strategy diagnostics mode")
    if min(diagnostics_minimum_total, diagnostics_minimum_zone) <= 0:
        raise AdaptiveEvaluationError("strategy diagnostics sample gates are invalid")
    if diagnostics_minimum_zone * 2 > diagnostics_minimum_total:
        raise AdaptiveEvaluationError("strategy diagnostics zone gates exceed total gate")
    if diagnostics_minimum_conflict_samples <= 1:
        raise AdaptiveEvaluationError("conflict diagnostics sample gate is invalid")
    if set(experiment_registry) != {CONTINUOUS_CONFLICT_EXPERIMENT_ID}:
        raise AdaptiveEvaluationError("unsupported shadow scoring experiment registry")
    if experiment_mode != "shadow_only":
        raise AdaptiveEvaluationError("shadow scoring experiment must remain shadow-only")
    if experiment_version != CONTINUOUS_CONFLICT_SCORE_VERSION:
        raise AdaptiveEvaluationError("unsupported shadow scoring score version")
    if experiment_active:
        raise AdaptiveEvaluationError("shadow scoring experiment cannot be active for routing")
    if not 0 < experiment_max_penalty <= experiment_max_total_penalty <= 48:
        raise AdaptiveEvaluationError("shadow scoring penalty limits are invalid")
    if calibration_mode != "shadow_only":
        raise AdaptiveEvaluationError("V2 threshold calibration must remain shadow-only")
    if not calibration_strong_grid or not calibration_gray_grid:
        raise AdaptiveEvaluationError("V2 threshold calibration grid is empty")
    if tuple(sorted(set(calibration_strong_grid))) != calibration_strong_grid:
        raise AdaptiveEvaluationError("V2 strong threshold grid is invalid")
    if tuple(sorted(set(calibration_gray_grid))) != calibration_gray_grid:
        raise AdaptiveEvaluationError("V2 gray threshold grid is invalid")
    if any(
        not math.isfinite(value) or not 0 <= value <= 100
        for value in calibration_strong_grid + calibration_gray_grid
    ):
        raise AdaptiveEvaluationError("V2 threshold calibration grid is out of bounds")
    if not any(
        gray_value < strong_value
        for strong_value in calibration_strong_grid
        for gray_value in calibration_gray_grid
    ):
        raise AdaptiveEvaluationError("V2 threshold calibration has no valid pair")
    if min(
        calibration_minimum_total,
        calibration_minimum_complete_zone,
        calibration_minimum_validation_zone,
    ) <= 1:
        raise AdaptiveEvaluationError("V2 threshold calibration sample gates are invalid")
    if calibration_minimum_complete_zone * 2 > calibration_minimum_total:
        raise AdaptiveEvaluationError("V2 threshold calibration zones exceed total gate")
    if not calibration_require_full_capture:
        raise AdaptiveEvaluationError("V2 calibration requires full counterfactual capture")
    if not 1 <= calibration_max_candidates <= 10:
        raise AdaptiveEvaluationError("V2 calibration report limit is invalid")
    if review_staging_mode != "review_only":
        raise AdaptiveEvaluationError("V2 review staging must remain review-only")
    if review_staging_confirmations < 2:
        raise AdaptiveEvaluationError("V2 review staging requires two confirmations")
    if review_staging_new_outcomes <= 0:
        raise AdaptiveEvaluationError("V2 review staging evidence milestone is invalid")
    if review_staging_adapters != ("paper", "okx_demo"):
        raise AdaptiveEvaluationError("V2 review staging adapters are invalid")
    if not review_staging_approval_payload:
        raise AdaptiveEvaluationError("V2 review staging requires operator approval")
    if canary_mode != "manual_demo":
        raise AdaptiveEvaluationError("V2 canary must remain manual demo-only")
    if canary_adapters != ("paper", "okx_demo"):
        raise AdaptiveEvaluationError("V2 canary adapters are invalid")
    if not 0 < canary_allocation_rate <= 0.20:
        raise AdaptiveEvaluationError("V2 canary allocation is invalid")
    if not 0 < canary_risk_multiplier <= 0.50:
        raise AdaptiveEvaluationError("V2 canary risk multiplier is invalid")
    if canary_max_positions != 1:
        raise AdaptiveEvaluationError("V2 canary concurrency limit is invalid")
    if not canary_disagreement_payload:
        raise AdaptiveEvaluationError("V2 canary must remain disagreement-only")
    if canary_minimum_closed != 12:
        raise AdaptiveEvaluationError("V2 canary rollback sample gate is invalid")
    if not math.isfinite(canary_lcb_floor) or canary_lcb_floor < 0:
        raise AdaptiveEvaluationError("V2 canary rollback confidence floor is invalid")
    if not math.isfinite(canary_profit_factor_floor) or canary_profit_factor_floor < 1:
        raise AdaptiveEvaluationError("V2 canary rollback profit-factor floor is invalid")
    if not math.isfinite(canary_cumulative_r_floor) or not (
        -3.0 <= canary_cumulative_r_floor < 0
    ):
        raise AdaptiveEvaluationError("V2 canary rollback cumulative-R floor is invalid")
    if readiness_minimum_valid_scores <= 0:
        raise AdaptiveEvaluationError("shadow scoring readiness sample gate is invalid")
    if not 0 < readiness_minimum_score_coverage <= 1:
        raise AdaptiveEvaluationError("shadow scoring readiness coverage is invalid")
    if min(readiness_minimum_strategy_count, readiness_minimum_per_strategy) <= 0:
        raise AdaptiveEvaluationError("shadow scoring readiness strategy gates are invalid")
    if not (
        1
        < readiness_minimum_strategy_validation_records
        <= readiness_minimum_per_strategy
    ):
        raise AdaptiveEvaluationError(
            "shadow scoring readiness strategy validation gate is invalid"
        )
    if not math.isfinite(readiness_minimum_strategy_validation_gain):
        raise AdaptiveEvaluationError(
            "shadow scoring readiness strategy validation gain is invalid"
        )
    if (
        readiness_minimum_strategy_count * readiness_minimum_per_strategy
        > readiness_minimum_valid_scores
    ):
        raise AdaptiveEvaluationError(
            "shadow scoring readiness strategy gates exceed sample gate"
        )
    if min(
        readiness_minimum_calibration_zone,
        readiness_minimum_validation_zone,
        readiness_minimum_segment_samples,
    ) <= 1:
        raise AdaptiveEvaluationError("shadow scoring readiness robustness gates are invalid")
    if readiness_minimum_calibration_zone * 2 > readiness_minimum_valid_scores:
        raise AdaptiveEvaluationError("shadow scoring readiness zones exceed sample gate")
    if min(readiness_minimum_calibration_gain, readiness_minimum_validation_gain) < 0:
        raise AdaptiveEvaluationError("shadow scoring readiness objective gain is invalid")
    if readiness_validation_profit_factor_floor <= 0:
        raise AdaptiveEvaluationError("shadow scoring readiness profit factor is invalid")
    if not math.isfinite(readiness_validation_lcb_floor):
        raise AdaptiveEvaluationError("shadow scoring readiness confidence floor is invalid")
    return payload


def _policy_with_zone_override(
    policy: Mapping[str, Any],
    zone_override: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate an already-validated runtime zone revision without mutating config."""
    try:
        strong = float(zone_override["strong_min_score"])
        gray = float(zone_override["gray_min_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AdaptiveEvaluationError("runtime decision thresholds are unavailable") from exc
    if not 0 <= gray < strong <= 100:
        raise AdaptiveEvaluationError("runtime decision thresholds are invalid")
    result = dict(policy)
    result["zones"] = {
        **dict(policy.get("zones") or {}),
        "strong_min_score": strong,
        "gray_min_score": gray,
    }
    return result


def _calibration_row(
    row: Mapping[str, Any],
    *,
    input_index: int,
) -> tuple[dict[str, Any] | None, str | None]:
    if not bool(row.get("counterfactual_eligible", False)):
        return None, "not_counterfactual_eligible"
    source = str(row.get("evaluation_source") or "").strip().lower()
    if source not in CALIBRATION_SOURCES:
        return None, "invalid_evaluation_source"
    score_floor = _number(row.get("counterfactual_score_floor", 0.0))
    if score_floor is None or not 0 <= score_floor <= 100:
        return None, "invalid_counterfactual_score_floor"
    score = _number(_first(row.get("rule_score"), _nested(row, "decision_context", "rule_score")))
    if score is None or not 0 <= score <= 100:
        return None, "invalid_rule_score"
    r_multiple = _number(row.get("r_multiple"))
    if r_multiple is None:
        pnl = _number(row.get("pnl_usd"))
        risk = _number(row.get("risk_usd"))
        if pnl is not None and risk is not None and risk > 0:
            r_multiple = pnl / risk
    if r_multiple is None or not math.isfinite(r_multiple):
        return None, "missing_outcome"
    return {
        **dict(row),
        "rule_score": score,
        "r_multiple": r_multiple,
        "evaluation_source": source,
        "counterfactual_score_floor": score_floor,
        "_input_index": input_index,
        "_event_timestamp": _event_timestamp(row),
        "_entry_index": _number(row.get("entry_index")),
    }, None


def _chronological_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[str(row["evaluation_source"])].append(row)

    calibration: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    source_summaries: dict[str, dict[str, Any]] = {}
    fallback_records = 0
    for source in sorted(by_source):
        source_rows = by_source[source]
        if source_rows and all(row.get("_event_timestamp") is not None for row in source_rows):
            method = "event_timestamp"
            ordered = sorted(source_rows, key=lambda row: float(row["_event_timestamp"]))
        elif source_rows and all(row.get("_entry_index") is not None for row in source_rows):
            method = "entry_index"
            ordered = sorted(source_rows, key=lambda row: float(row["_entry_index"]))
        else:
            method = "input_order_fallback"
            fallback_records += len(source_rows)
            ordered = sorted(source_rows, key=lambda row: int(row["_input_index"]))
        split_index = len(ordered)
        if len(ordered) >= 2:
            split_index = max(1, min(len(ordered) - 1, math.floor(len(ordered) * CALIBRATION_FRACTION)))
        source_calibration = ordered[:split_index]
        source_validation = ordered[split_index:]
        calibration.extend(source_calibration)
        validation.extend(source_validation)
        source_summaries[source] = {
            "method": method,
            "total": len(ordered),
            "calibration": len(source_calibration),
            "validation": len(source_validation),
        }
    return {
        "calibration_rows": calibration,
        "validation_rows": validation,
        "summary": {
            "calibration_fraction": CALIBRATION_FRACTION,
            "calibration_records": len(calibration),
            "validation_records": len(validation),
            "fallback_records": fallback_records,
            "by_source": source_summaries,
        },
    }


def _rank_candidates(
    rows: list[dict[str, Any]],
    *,
    calibration_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    current_strong: float,
    current_gray: float,
    min_zone: int,
    min_validation_zone: int,
    evidence_floor: float,
    strong_grid: Iterable[float] = STRONG_GRID,
    gray_grid: Iterable[float] = GRAY_GRID,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Any]]:
    current = _candidate_snapshot(
        rows,
        calibration_rows=calibration_rows,
        validation_rows=validation_rows,
        strong=current_strong,
        gray=current_gray,
        current_calibration_objective=None,
        current_validation_objective=None,
        current_strong=current_strong,
        current_gray=current_gray,
        min_zone=min_zone,
        min_validation_zone=min_validation_zone,
    )
    current_calibration_objective = float(current["objective_score"])
    current_validation_objective = float(current["validation_objective_score"])
    candidates: list[dict[str, Any]] = []
    gate_failures: Counter[str] = Counter()
    for strong in strong_grid:
        for gray in gray_grid:
            if gray >= strong or gray < evidence_floor:
                continue
            candidate = _candidate_snapshot(
                rows,
                calibration_rows=calibration_rows,
                validation_rows=validation_rows,
                strong=strong,
                gray=gray,
                current_calibration_objective=current_calibration_objective,
                current_validation_objective=current_validation_objective,
                current_strong=current_strong,
                current_gray=current_gray,
                min_zone=min_zone,
                min_validation_zone=min_validation_zone,
            )
            failed = [name for name, passed in candidate["gates"].items() if not passed]
            if failed:
                gate_failures.update(failed)
                continue
            candidates.append(candidate)
    return (
        sorted(
            candidates,
            key=lambda item: (
                -float(item["selection_score"]),
                float(item["threshold_drift"]),
                float(item["strong_min_score"]),
                float(item["gray_min_score"]),
            ),
        ),
        gate_failures,
        current,
    )


def _candidate_snapshot(
    rows: list[dict[str, Any]],
    *,
    calibration_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    strong: float,
    gray: float,
    current_calibration_objective: float | None,
    current_validation_objective: float | None,
    current_strong: float,
    current_gray: float,
    min_zone: int,
    min_validation_zone: int,
) -> dict[str, Any]:
    complete_metrics = _metrics_by_zone(rows, strong_min=strong, gray_min=gray)
    calibration_metrics = _metrics_by_zone(calibration_rows, strong_min=strong, gray_min=gray)
    validation_metrics = _metrics_by_zone(validation_rows, strong_min=strong, gray_min=gray)
    objective, components = _candidate_objective(calibration_metrics)
    validation_objective, validation_components = _candidate_objective(validation_metrics)
    drift = abs(strong - current_strong) + abs(gray - current_gray)
    changed = strong != current_strong or gray != current_gray
    gain = 0.0 if current_calibration_objective is None else objective - current_calibration_objective
    validation_delta = (
        0.0
        if current_validation_objective is None
        else validation_objective - current_validation_objective
    )
    strong_metrics = complete_metrics["strong"]
    gray_metrics = complete_metrics["gray"]
    validation_strong = validation_metrics["strong"]
    validation_gray = validation_metrics["gray"]
    segment_stability = _strong_segment_stability(
        rows,
        strong_min=strong,
        minimum_samples=max(8, min_zone // 3),
    )
    gates = {
        "strong_sample": strong_metrics["n"] >= min_zone,
        "gray_sample": gray_metrics["n"] >= min_zone,
        "validation_strong_sample": validation_strong["n"] >= min_validation_zone,
        "validation_gray_sample": validation_gray["n"] >= min_validation_zone,
        "strong_positive_expectancy": (strong_metrics["average_r"] or 0.0) > 0,
        "strong_confidence_lower_bound": (
            strong_metrics["average_r_lower_bound_90"] is not None
            and float(strong_metrics["average_r_lower_bound_90"]) > 0
        ),
        "strong_profit_factor": _profit_factor_at_least(strong_metrics, 1.10),
        "validation_strong_confidence_lower_bound": (
            validation_strong["average_r_lower_bound_90"] is not None
            and float(validation_strong["average_r_lower_bound_90"]) > 0
        ),
        "validation_strong_profit_factor": _profit_factor_at_least(validation_strong, 1.00),
        "gray_has_review_opportunity": (
            gray_metrics["win_rate"] is not None
            and float(gray_metrics["win_rate"]) >= GRAY_MIN_POSITIVE_RATE
        ),
        "strong_segment_stability": bool(segment_stability["passed"]),
        "changed_objective_improvement": not changed or gain >= MIN_CHANGED_OBJECTIVE_GAIN,
        "validation_non_regression": (
            not changed or validation_delta >= -MAX_VALIDATION_OBJECTIVE_REGRESSION
        ),
    }
    return {
        "strong_min_score": strong,
        "gray_min_score": gray,
        "objective_score": round(objective, 6),
        "validation_objective_score": round(validation_objective, 6),
        "selection_score": round(objective - 0.005 * drift, 6),
        "objective_gain_vs_current": round(gain, 6),
        "validation_delta_vs_current": round(validation_delta, 6),
        "threshold_drift": drift,
        "objective_components": components,
        "validation_objective_components": validation_components,
        "gates": gates,
        "strong_segment_stability": segment_stability,
        "zone_metrics": complete_metrics,
        "calibration_zone_metrics": calibration_metrics,
        "validation_zone_metrics": validation_metrics,
    }


def _candidate_objective(metrics: Mapping[str, Mapping[str, Any]]) -> tuple[float, dict[str, float]]:
    strong = metrics["strong"]
    gray = metrics["gray"]
    reject = metrics["reject"]
    strong_lcb = _metric_number(strong, "average_r_lower_bound_90", -5.0)
    strong_avg = _metric_number(strong, "average_r", -5.0)
    reject_avg = _metric_number(reject, "average_r", 0.0)
    gray_avg = _metric_number(gray, "average_r", 0.0)
    gray_win_rate = _metric_number(gray, "win_rate", 0.0)
    strong_pf = _bounded_profit_factor(strong)
    strong_drawdown = _normalized_drawdown(strong)
    gray_drawdown = _normalized_drawdown(gray)
    strong_tail = min(0.0, _metric_number(strong, "lower_tail_average_r", 0.0))
    total_n = sum(int(zone.get("n", 0)) for zone in metrics.values())
    review_load = int(gray.get("n", 0)) / total_n if total_n else 1.0
    components = {
        "strong_confidence": 2.50 * strong_lcb,
        "strong_expectancy": 0.50 * strong_avg,
        "score_separation": 0.40 * (strong_avg - reject_avg),
        "gray_optionality": 0.20 * max(gray_avg, 0.0) + 0.20 * gray_win_rate,
        "profit_factor_quality": 0.15 * math.log1p(strong_pf),
        "strong_drawdown_penalty": -0.25 * strong_drawdown,
        "gray_drawdown_penalty": -0.08 * gray_drawdown,
        "tail_loss_penalty": 0.15 * strong_tail,
        "review_load_penalty": -0.12 * review_load,
    }
    rounded = {key: round(value, 6) for key, value in components.items()}
    return sum(components.values()), rounded


def _metrics_by_zone(
    rows: list[dict[str, Any]],
    *,
    strong_min: float,
    gray_min: float,
) -> dict[str, dict[str, Any]]:
    zones: dict[str, list[float]] = {"strong": [], "gray": [], "reject": []}
    for row in rows:
        score = float(row["rule_score"])
        zone = "strong" if score >= strong_min else "gray" if score >= gray_min else "reject"
        zones[zone].append(float(row["r_multiple"]))
    return {zone: _outcome_metrics(values) for zone, values in zones.items()}


def _outcome_metrics(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    average = sum(values) / len(values) if values else None
    standard_deviation = None
    standard_error = None
    lower_bound = None
    if average is not None and len(values) >= 2:
        variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
        standard_deviation = math.sqrt(max(0.0, variance))
        standard_error = standard_deviation / math.sqrt(len(values))
        lower_bound = average - ONE_SIDED_90_Z * standard_error
    tail_count = max(1, math.ceil(len(values) * 0.10)) if values else 0
    lower_tail = sum(sorted(values)[:tail_count]) / tail_count if tail_count else None
    return {
        "n": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(values), 4) if values else None,
        "average_r": round(average, 6) if average is not None else None,
        "average_r_lower_bound_90": round(lower_bound, 6) if lower_bound is not None else None,
        "standard_deviation_r": (
            round(standard_deviation, 6) if standard_deviation is not None else None
        ),
        "standard_error_r": round(standard_error, 6) if standard_error is not None else None,
        "lower_tail_average_r": round(lower_tail, 6) if lower_tail is not None else None,
        "worst_r": round(min(values), 6) if values else None,
        "cumulative_r": round(sum(values), 6),
        "gross_profit_r": round(gross_profit, 6),
        "gross_loss_r": round(gross_loss, 6),
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss > 0 else None,
        "max_drawdown_r": _max_drawdown(values),
    }


def _mean_confidence_interval_90(
    values: list[float],
) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    average = sum(values) / len(values)
    if len(values) < 2:
        return average, None, None
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    standard_error = math.sqrt(max(0.0, variance)) / math.sqrt(len(values))
    margin = TWO_SIDED_90_Z * standard_error
    return average, average - margin, average + margin


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round(maximum, 6)


def _score_bucket_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[float]] = {
        "0-59": [],
        "60-69": [],
        "70-79": [],
        "80-89": [],
        "90-100": [],
    }
    for row in rows:
        score = float(row["rule_score"])
        if score < 60:
            bucket = "0-59"
        elif score < 70:
            bucket = "60-69"
        elif score < 80:
            bucket = "70-79"
        elif score < 90:
            bucket = "80-89"
        else:
            bucket = "90-100"
        buckets[bucket].append(float(row["r_multiple"]))
    return {key: _outcome_metrics(values) for key, values in buckets.items()}


def _strong_segment_stability(
    rows: list[dict[str, Any]],
    *,
    strong_min: float,
    minimum_samples: int,
) -> dict[str, Any]:
    dimensions = {
        "source": lambda row: str(row.get("evaluation_source") or "unknown"),
        "strategy": lambda row: str(row.get("strategy_id") or row.get("team_id") or "unknown"),
        "regime": lambda row: str(row.get("regime") or "unknown"),
    }
    failures: list[dict[str, Any]] = []
    evaluated = 0
    for dimension, key_fn in dimensions.items():
        groups: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if float(row["rule_score"]) >= strong_min:
                groups[key_fn(row)].append(float(row["r_multiple"]))
        for value, outcomes in groups.items():
            if len(outcomes) < minimum_samples:
                continue
            evaluated += 1
            metrics = _outcome_metrics(outcomes)
            if _metric_number(metrics, "average_r", -5.0) < SEGMENT_NEGATIVE_TOLERANCE_R:
                failures.append(
                    {
                        "dimension": dimension,
                        "value": value,
                        "n": len(outcomes),
                        "average_r": metrics["average_r"],
                    }
                )
    return {
        "passed": evaluated > 0 and not failures,
        "evaluated_segments": evaluated,
        "minimum_samples": minimum_samples,
        "negative_tolerance_r": SEGMENT_NEGATIVE_TOLERANCE_R,
        "failures": failures,
    }


def _llm_review_effectiveness(
    rows: list[dict[str, Any]],
    *,
    health_config: Mapping[str, Any],
) -> dict[str, Any]:
    decisions: dict[str, list[float]] = {"APPROVE": [], "VETO": [], "WAIT": []}
    observations: list[dict[str, Any]] = []
    for row in rows:
        observation = _review_observation(row)
        if observation is None:
            continue
        decision = str(observation["decision"])
        decisions[decision].append(float(observation["r_multiple"]))
        observations.append(observation)
    reviewed = sum(len(values) for values in decisions.values())
    valid_observations = [item for item in observations if item["risk_multiplier"] is not None]
    valid_approved = [item for item in valid_observations if item["decision"] == "APPROVE"]
    valid_declined = [item for item in valid_observations if item["decision"] in {"VETO", "WAIT"}]
    valid_declined_outcomes = [float(item["r_multiple"]) for item in valid_declined]
    valid_approved_outcomes = [float(item["r_multiple"]) for item in valid_approved]
    contributions = [
        float(item["r_multiple"]) * (float(item["risk_multiplier"]) - 1.0)
        for item in valid_observations
    ]
    baseline_total_r = sum(float(item["r_multiple"]) for item in valid_observations)
    observed_total_r = sum(
        float(item["r_multiple"]) * float(item["risk_multiplier"])
        for item in valid_observations
    )
    policy_value_records = len(valid_observations)
    baseline_r_per_review = (
        baseline_total_r / policy_value_records
        if policy_value_records
        else None
    )
    observed_r_per_review = (
        observed_total_r / policy_value_records if policy_value_records else None
    )
    contribution_mean, contribution_lower, contribution_upper = _mean_confidence_interval_90(
        contributions
    )
    minimum_reviewed = int(health_config["minimum_reviewed"])
    minimum_approved = int(health_config["minimum_approved"])
    minimum_declined = int(health_config["minimum_declined"])
    minimum_multiplier_coverage = float(health_config["minimum_multiplier_coverage"])
    minimum_segment_reviewed = int(health_config["minimum_segment_reviewed"])
    multiplier_coverage = policy_value_records / reviewed if reviewed else 0.0
    segment_diagnostics = _review_segment_diagnostics(
        valid_observations,
        minimum_samples=minimum_segment_reviewed,
    )
    evidence_gates = {
        "reviewed": reviewed >= minimum_reviewed,
        "approved": len(valid_approved) >= minimum_approved,
        "declined": len(valid_declined) >= minimum_declined,
        "multiplier_coverage": multiplier_coverage >= minimum_multiplier_coverage,
    }
    approved_average = (
        sum(float(item["r_multiple"]) for item in valid_approved) / len(valid_approved)
        if valid_approved
        else None
    )
    if not all(evidence_gates.values()):
        health_status = "insufficient_evidence"
        operator_recommendation = (
            "repair_review_risk_multiplier_metadata"
            if reviewed > 0 and not evidence_gates["multiplier_coverage"]
            else "collect_reviewed_shadow_outcomes"
        )
    elif approved_average is None or approved_average <= 0:
        health_status = "degraded"
        operator_recommendation = "audit_review_prompt_and_gray_policy"
    elif contribution_upper is not None and contribution_upper < 0:
        health_status = "degraded"
        operator_recommendation = "audit_review_prompt_and_gray_policy"
    elif segment_diagnostics["degraded_segments"]:
        health_status = "degraded"
        operator_recommendation = "audit_degraded_review_segments"
    elif contribution_lower is not None and contribution_lower > 0:
        health_status = "healthy"
        operator_recommendation = "retain_gray_context_review"
    else:
        health_status = "inconclusive"
        operator_recommendation = "collect_more_reviewed_shadow_outcomes"
    return {
        "reviewed_records": reviewed,
        "policy_value_records": policy_value_records,
        "valid_approved_records": len(valid_approved),
        "valid_declined_records": len(valid_declined),
        "coverage_rate": round(reviewed / len(rows), 4) if rows else 0.0,
        "multiplier_coverage": round(multiplier_coverage, 4),
        "invalid_multiplier_records": reviewed - policy_value_records,
        "by_decision": {
            decision.lower(): _outcome_metrics(values)
            for decision, values in decisions.items()
        },
        "by_risk_multiplier": _review_multiplier_metrics(valid_observations),
        "segment_diagnostics": segment_diagnostics,
        "declined_losses_avoided": sum(
            1 for value in valid_declined_outcomes if value <= 0
        ),
        "declined_profitable_outcomes_missed": sum(
            1 for value in valid_declined_outcomes if value > 0
        ),
        "approved_losses": sum(1 for value in valid_approved_outcomes if value <= 0),
        "approved_profitable_outcomes": sum(
            1 for value in valid_approved_outcomes if value > 0
        ),
        "reviewed_approve_all_r": round(baseline_total_r, 6),
        "observed_approved_r": round(observed_total_r, 6),
        "approve_all_baseline_r_per_review": (
            round(baseline_r_per_review, 6) if baseline_r_per_review is not None else None
        ),
        "observed_review_policy_r_per_review": (
            round(observed_r_per_review, 6) if observed_r_per_review is not None else None
        ),
        "selection_contribution_r_per_review": (
            round(contribution_mean, 6) if contribution_mean is not None else None
        ),
        "selection_contribution_ci_90": {
            "lower": round(contribution_lower, 6) if contribution_lower is not None else None,
            "upper": round(contribution_upper, 6) if contribution_upper is not None else None,
        },
        "health": {
            "status": health_status,
            "enforcement": str(health_config["enforcement"]),
            "confidence_level": float(health_config["confidence_level"]),
            "minimum_samples": {
                "reviewed": minimum_reviewed,
                "approved": minimum_approved,
                "declined": minimum_declined,
                "multiplier_coverage": minimum_multiplier_coverage,
                "segment_reviewed": minimum_segment_reviewed,
            },
            "evidence_gates": evidence_gates,
            "degraded_segments": segment_diagnostics["degraded_segments"],
            "operator_recommendation": operator_recommendation,
            "runtime_route_changed": False,
        },
        "interpretation": "observational_review_subset_only",
    }


def _compact_llm_review_health(effectiveness: Mapping[str, Any]) -> dict[str, Any]:
    health = effectiveness.get("health")
    health_payload = dict(health) if isinstance(health, Mapping) else {}
    degraded_segments = health_payload.pop("degraded_segments", [])
    degraded = degraded_segments if isinstance(degraded_segments, list) else []
    by_decision = effectiveness.get("by_decision")
    decisions = by_decision if isinstance(by_decision, Mapping) else {}
    approve = decisions.get("approve")
    veto = decisions.get("veto")
    wait = decisions.get("wait")
    approved = int(approve.get("n", 0)) if isinstance(approve, Mapping) else 0
    vetoed = int(veto.get("n", 0)) if isinstance(veto, Mapping) else 0
    waited = int(wait.get("n", 0)) if isinstance(wait, Mapping) else 0
    return {
        **health_payload,
        "reviewed_records": int(effectiveness.get("reviewed_records", 0)),
        "policy_value_records": int(effectiveness.get("policy_value_records", 0)),
        "approved_records": int(effectiveness.get("valid_approved_records", 0)),
        "declined_records": int(effectiveness.get("valid_declined_records", 0)),
        "recognized_approved_records": approved,
        "recognized_declined_records": vetoed + waited,
        "multiplier_coverage": effectiveness.get("multiplier_coverage"),
        "invalid_multiplier_records": int(
            effectiveness.get("invalid_multiplier_records", 0)
        ),
        "degraded_segment_count": len(degraded),
        "degraded_segments": degraded[:5],
        "selection_contribution_r_per_review": effectiveness.get(
            "selection_contribution_r_per_review"
        ),
        "selection_contribution_ci_90": effectiveness.get("selection_contribution_ci_90"),
        "declined_losses_avoided": int(effectiveness.get("declined_losses_avoided", 0)),
        "declined_profitable_outcomes_missed": int(
            effectiveness.get("declined_profitable_outcomes_missed", 0)
        ),
    }


def _strategy_threshold_diagnostics(
    rows: list[dict[str, Any]],
    *,
    policy_path: Path,
    zone_override: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy_id = str(row.get("strategy_id") or row.get("team_id") or "unknown")
        if strategy_id != "unknown":
            groups[strategy_id].append(row)
    diagnostics: dict[str, Any] = {}
    for strategy_id, strategy_rows in sorted(groups.items()):
        evaluation = evaluate_adaptive_thresholds(
            strategy_rows,
            policy_path=policy_path,
            zone_override=zone_override,
            min_total=int(config["minimum_total"]),
            min_zone=int(config["minimum_zone"]),
            include_strategy_diagnostics=False,
            include_conflict_diagnostics=False,
            include_shadow_scoring_diagnostics=False,
        )
        recommendation = evaluation.get("recommended_thresholds")
        compact_recommendation = None
        if isinstance(recommendation, Mapping):
            compact_recommendation = {
                "strong_min_score": recommendation.get("strong_min_score"),
                "gray_min_score": recommendation.get("gray_min_score"),
                "changed_from_current": bool(
                    recommendation.get("changed_from_current", False)
                ),
                "objective_gain_vs_current": recommendation.get(
                    "objective_gain_vs_current"
                ),
                "validation_delta_vs_current": recommendation.get(
                    "validation_delta_vs_current"
                ),
                "robustness": recommendation.get("robustness"),
            }
        review_health = evaluation.get("llm_review_health")
        compact_review_health = None
        if isinstance(review_health, Mapping):
            compact_review_health = {
                "status": review_health.get("status"),
                "reviewed_records": review_health.get("reviewed_records"),
                "multiplier_coverage": review_health.get("multiplier_coverage"),
                "selection_contribution_r_per_review": review_health.get(
                    "selection_contribution_r_per_review"
                ),
            }
        diagnostics[strategy_id] = {
            "mode": str(config["mode"]),
            "status": evaluation.get("status"),
            "eligible_records": int(evaluation.get("eligible_records", 0) or 0),
            "excluded_records": int(evaluation.get("excluded_records", 0) or 0),
            "current_policy": evaluation.get("current_policy"),
            "chronological_validation": evaluation.get("chronological_validation"),
            "insufficiency_reasons": list(
                evaluation.get("insufficiency_reasons") or []
            )[:5],
            "recommended_thresholds": compact_recommendation,
            "llm_review_health": compact_review_health,
            "auto_apply": False,
        }
    return diagnostics


def _conflict_penalty_diagnostics(
    rows: list[dict[str, Any]],
    *,
    minimum_samples: int,
) -> dict[str, Any]:
    strategy_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy_id = str(row.get("strategy_id") or row.get("team_id") or "unknown")
        if strategy_id != "unknown":
            strategy_groups[strategy_id].append(row)
    strategies: dict[str, Any] = {}
    aggregate_labels: Counter[str] = Counter()
    for strategy_id, strategy_rows in sorted(strategy_groups.items()):
        baseline = [
            float(row["r_multiple"])
            for row in strategy_rows
            if not _row_conflicts(row)
        ]
        conflict_groups: dict[str, list[float]] = defaultdict(list)
        count_groups: dict[int, list[float]] = defaultdict(list)
        for row in strategy_rows:
            conflicts = _row_conflicts(row)
            outcome = float(row["r_multiple"])
            count_groups[len(conflicts)].append(outcome)
            for conflict in conflicts:
                conflict_groups[conflict].append(outcome)
        conflict_rows: list[dict[str, Any]] = []
        strategy_labels: Counter[str] = Counter()
        for conflict_id, outcomes in conflict_groups.items():
            delta, lower, upper = _independent_mean_difference_ci_90(
                outcomes,
                baseline,
            )
            if len(outcomes) < minimum_samples or len(baseline) < minimum_samples:
                label = "insufficient_evidence"
            elif upper is not None and upper < 0:
                label = "harmful"
            elif lower is not None and lower > 0:
                label = "over_penalized_candidate"
            else:
                label = "uncertain"
            strategy_labels[label] += 1
            aggregate_labels[label] += 1
            conflict_rows.append(
                {
                    "conflict_id": conflict_id,
                    **_outcome_metrics(outcomes),
                    "delta_average_r_vs_no_conflict": (
                        round(delta, 6) if delta is not None else None
                    ),
                    "delta_average_r_ci_90": {
                        "lower": round(lower, 6) if lower is not None else None,
                        "upper": round(upper, 6) if upper is not None else None,
                    },
                    "association_label": label,
                }
            )
        conflict_rows.sort(key=lambda item: (-int(item["n"]), str(item["conflict_id"])))
        strategies[strategy_id] = {
            "minimum_samples": minimum_samples,
            "no_conflict_baseline": _outcome_metrics(baseline),
            "label_counts": dict(sorted(strategy_labels.items())),
            "conflicts": conflict_rows[:20],
            "conflict_count_metrics": {
                str(count): _outcome_metrics(outcomes)
                for count, outcomes in sorted(count_groups.items())
            },
        }
    return {
        "mode": "observe_only",
        "minimum_samples": minimum_samples,
        "strategy_count": len(strategies),
        "label_counts": dict(sorted(aggregate_labels.items())),
        "strategies": strategies,
        "interpretation": "non_causal_within_strategy_association",
        "auto_apply": False,
    }


def _row_conflicts(row: Mapping[str, Any]) -> list[str]:
    conflicts = row.get("conflicts")
    if not isinstance(conflicts, list):
        setup_quality = _nested(row, "evidence", "setup_quality")
        conflicts = (
            setup_quality.get("conflicts")
            if isinstance(setup_quality, Mapping)
            else []
        )
    return list(
        dict.fromkeys(
            str(item).strip()
            for item in conflicts
            if str(item).strip()
        )
    )


def _shadow_scoring_experiment_evaluation(
    rows: list[dict[str, Any]],
    *,
    calibration_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    strong_min: float,
    gray_min: float,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    valid_scores: dict[int, float] = {}
    exclusions: Counter[str] = Counter()
    for row in rows:
        experiment_scores = row.get("experimental_scores")
        if not isinstance(experiment_scores, Mapping):
            exclusions["missing_experiment_score"] += 1
            continue
        experiment = experiment_scores.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
        if not isinstance(experiment, Mapping):
            exclusions["missing_experiment_score"] += 1
            continue
        if bool(experiment.get("active_for_routing", False)):
            exclusions["experiment_active_for_routing"] += 1
            continue
        if str(experiment.get("mode")) != str(config["mode"]):
            exclusions["invalid_experiment_mode"] += 1
            continue
        if str(experiment.get("score_version")) != str(config["score_version"]):
            exclusions["invalid_experiment_score_version"] += 1
            continue
        score = _number(experiment.get("score"))
        if score is None or not 0 <= score <= 100:
            exclusions["invalid_experiment_score"] += 1
            continue
        valid_scores[int(row["_input_index"])] = score

    def scored(window: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in window:
            v2_score = valid_scores.get(int(row["_input_index"]))
            if v2_score is None:
                continue
            active_score = float(row["rule_score"])
            selected_score = active_score if score_key == "v1" else v2_score
            output.append(
                {
                    **row,
                    "rule_score": selected_score,
                    "_active_v1_score": active_score,
                    "_experimental_v2_score": v2_score,
                }
            )
        return output

    complete_v1 = scored(rows, "v1")
    complete_v2 = scored(rows, "v2")
    calibration_v1 = scored(calibration_rows, "v1")
    calibration_v2 = scored(calibration_rows, "v2")
    validation_v1 = scored(validation_rows, "v1")
    validation_v2 = scored(validation_rows, "v2")
    deltas = [
        valid_scores[int(row["_input_index"])] - float(row["rule_score"])
        for row in rows
        if int(row["_input_index"]) in valid_scores
    ]
    transitions: Counter[str] = Counter()
    for row in complete_v1:
        input_index = int(row["_input_index"])
        active_zone = _score_zone(float(row["rule_score"]), strong_min, gray_min)
        experiment_zone = _score_zone(valid_scores[input_index], strong_min, gray_min)
        if active_zone != experiment_zone:
            transitions[f"{active_zone}->{experiment_zone}"] += 1
    valid_count = len(valid_scores)
    total_count = len(rows)
    complete_metrics = {
        "active_v1": _metrics_by_zone(
            complete_v1,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
        "experimental_v2": _metrics_by_zone(
            complete_v2,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
    }
    calibration_metrics = {
        "active_v1": _metrics_by_zone(
            calibration_v1,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
        "experimental_v2": _metrics_by_zone(
            calibration_v2,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
    }
    validation_metrics = {
        "active_v1": _metrics_by_zone(
            validation_v1,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
        "experimental_v2": _metrics_by_zone(
            validation_v2,
            strong_min=strong_min,
            gray_min=gray_min,
        ),
    }
    threshold_calibration = _shadow_score_threshold_calibration(
        complete_v2=complete_v2,
        calibration_v2=calibration_v2,
        validation_v2=validation_v2,
        calibration_v1_metrics=calibration_metrics["active_v1"],
        validation_v1_metrics=validation_metrics["active_v1"],
        active_strong_min=strong_min,
        active_gray_min=gray_min,
        config=config["threshold_calibration"],
    )
    candidate_thresholds = threshold_calibration.get("candidate_thresholds")
    if isinstance(candidate_thresholds, Mapping):
        v2_strong_min = float(candidate_thresholds["strong_min_score"])
        v2_gray_min = float(candidate_thresholds["gray_min_score"])
    else:
        v2_strong_min = strong_min
        v2_gray_min = gray_min
    calibrated_complete_v2_metrics = _metrics_by_zone(
        complete_v2,
        strong_min=v2_strong_min,
        gray_min=v2_gray_min,
    )
    calibrated_calibration_v2_metrics = _metrics_by_zone(
        calibration_v2,
        strong_min=v2_strong_min,
        gray_min=v2_gray_min,
    )
    calibrated_validation_v2_metrics = _metrics_by_zone(
        validation_v2,
        strong_min=v2_strong_min,
        gray_min=v2_gray_min,
    )
    strategy_comparison = _shadow_score_strategy_comparison(
        complete_v2,
        v1_strong_min=strong_min,
        v1_gray_min=gray_min,
        v2_strong_min=v2_strong_min,
        v2_gray_min=v2_gray_min,
        config=config["readiness"],
    )
    review_eligibility = _shadow_score_review_eligibility(
        complete_v2=complete_v2,
        calibration_v2=calibration_v2,
        validation_v2=validation_v2,
        score_coverage=(valid_count / total_count if total_count else 0.0),
        v2_strong_min=v2_strong_min,
        v2_gray_min=v2_gray_min,
        calibration_metrics={
            "active_v1": calibration_metrics["active_v1"],
            "experimental_v2": calibrated_calibration_v2_metrics,
        },
        validation_metrics={
            "active_v1": validation_metrics["active_v1"],
            "experimental_v2": calibrated_validation_v2_metrics,
        },
        strategy_comparison=strategy_comparison,
        threshold_calibration=threshold_calibration,
        config=config["readiness"],
    )
    return {
        "mode": str(config["mode"]),
        "score_version": str(config["score_version"]),
        "active_for_routing": False,
        "eligible_records": total_count,
        "score_coverage": {
            "total": total_count,
            "valid": valid_count,
            "ratio": round(valid_count / total_count, 4) if total_count else 0.0,
            "exclusion_reasons": dict(sorted(exclusions.items())),
        },
        "score_delta_v2_minus_v1": _score_delta_summary(deltas),
        "zone_transitions": dict(sorted(transitions.items())),
        "complete_metrics": complete_metrics,
        "calibration_metrics": calibration_metrics,
        "validation_metrics": validation_metrics,
        "threshold_calibration": {
            **threshold_calibration,
            "candidate_metrics": (
                {
                    "complete": calibrated_complete_v2_metrics,
                    "calibration": calibrated_calibration_v2_metrics,
                    "validation": calibrated_validation_v2_metrics,
                }
                if isinstance(candidate_thresholds, Mapping)
                else None
            ),
        },
        "strategy_comparison": strategy_comparison,
        "review_eligibility": review_eligibility,
        "activation_recommendation": None,
        "auto_apply": False,
    }


def _shadow_score_threshold_calibration(
    *,
    complete_v2: list[dict[str, Any]],
    calibration_v2: list[dict[str, Any]],
    validation_v2: list[dict[str, Any]],
    calibration_v1_metrics: Mapping[str, Mapping[str, Any]],
    validation_v1_metrics: Mapping[str, Mapping[str, Any]],
    active_strong_min: float,
    active_gray_min: float,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    minimum_total = int(config["minimum_total"])
    minimum_zone = int(config["minimum_complete_zone"])
    minimum_validation_zone = int(config["minimum_validation_zone"])
    max_candidates = int(config["max_candidates_reported"])
    evidence_floor = _counterfactual_score_floor(complete_v2)
    sample_reasons: list[str] = []
    if len(complete_v2) < minimum_total:
        sample_reasons.append(f"valid_scores_below_{minimum_total}")
    if bool(config["require_full_counterfactual_capture"]) and evidence_floor > 0:
        sample_reasons.append("full_counterfactual_capture_required")

    candidates: list[dict[str, Any]] = []
    gate_failures: Counter[str] = Counter()
    current_v2 = _candidate_snapshot(
        complete_v2,
        calibration_rows=calibration_v2,
        validation_rows=validation_v2,
        strong=active_strong_min,
        gray=active_gray_min,
        current_calibration_objective=None,
        current_validation_objective=None,
        current_strong=active_strong_min,
        current_gray=active_gray_min,
        min_zone=minimum_zone,
        min_validation_zone=minimum_validation_zone,
    )
    if not sample_reasons:
        candidates, gate_failures, current_v2 = _rank_candidates(
            complete_v2,
            calibration_rows=calibration_v2,
            validation_rows=validation_v2,
            current_strong=active_strong_min,
            current_gray=active_gray_min,
            min_zone=minimum_zone,
            min_validation_zone=minimum_validation_zone,
            evidence_floor=0.0,
            strong_grid=tuple(float(item) for item in config["strong_candidates"]),
            gray_grid=tuple(float(item) for item in config["gray_candidates"]),
        )

    active_v1_calibration_objective, _ = _candidate_objective(
        calibration_v1_metrics
    )
    active_v1_validation_objective, _ = _candidate_objective(
        validation_v1_metrics
    )
    candidate = candidates[0] if candidates else None
    if sample_reasons:
        status = "collecting_evidence"
    elif candidate is None:
        status = "not_eligible"
    else:
        status = "candidate_ready"

    candidate_thresholds: dict[str, Any] | None = None
    objective_comparison: dict[str, Any] | None = None
    if candidate is not None:
        calibration_gain = (
            float(candidate["objective_score"])
            - active_v1_calibration_objective
        )
        validation_gain = (
            float(candidate["validation_objective_score"])
            - active_v1_validation_objective
        )
        candidate_thresholds = {
            "strong_min_score": float(candidate["strong_min_score"]),
            "gray_min_score": float(candidate["gray_min_score"]),
            "changed_from_active_v1": (
                float(candidate["strong_min_score"]) != active_strong_min
                or float(candidate["gray_min_score"]) != active_gray_min
            ),
            "requires_human_review": True,
            "active_for_routing": False,
        }
        objective_comparison = {
            "calibration_active_v1": round(active_v1_calibration_objective, 6),
            "calibration_candidate_v2": candidate["objective_score"],
            "calibration_delta_v2_minus_v1": round(calibration_gain, 6),
            "validation_active_v1": round(active_v1_validation_objective, 6),
            "validation_candidate_v2": candidate[
                "validation_objective_score"
            ],
            "validation_delta_v2_minus_v1": round(validation_gain, 6),
        }

    compact_candidates = []
    for item in candidates[:max_candidates]:
        compact_candidates.append(
            {
                "strong_min_score": item["strong_min_score"],
                "gray_min_score": item["gray_min_score"],
                "selection_score": item["selection_score"],
                "objective_score": item["objective_score"],
                "validation_objective_score": item[
                    "validation_objective_score"
                ],
                "objective_gain_vs_current_v2": item[
                    "objective_gain_vs_current"
                ],
                "validation_delta_vs_current_v2": item[
                    "validation_delta_vs_current"
                ],
                "threshold_drift": item["threshold_drift"],
            }
        )
    return {
        "mode": str(config["mode"]),
        "status": status,
        "method": "chronological_risk_adjusted_v2_shadow",
        "valid_scores": len(complete_v2),
        "counterfactual_score_floor": evidence_floor,
        "sample_reasons": sample_reasons,
        "candidate_gate_failures": dict(sorted(gate_failures.items())),
        "current_v2_at_active_thresholds": {
            "strong_min_score": active_strong_min,
            "gray_min_score": active_gray_min,
            "objective_score": current_v2["objective_score"],
            "validation_objective_score": current_v2[
                "validation_objective_score"
            ],
        },
        "candidate_thresholds": candidate_thresholds,
        "objective_comparison_vs_active_v1": objective_comparison,
        "candidate_ranking": compact_candidates,
        "requirements": dict(config),
        "auto_apply": False,
    }


def _shadow_score_strategy_comparison(
    rows: list[dict[str, Any]],
    *,
    v1_strong_min: float,
    v1_gray_min: float,
    v2_strong_min: float,
    v2_gray_min: float,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strategy_id = str(row.get("strategy_id") or row.get("team_id") or "unknown")
        if strategy_id != "unknown":
            groups[strategy_id].append(row)

    minimum_total = int(config["minimum_per_strategy"])
    minimum_validation = int(config["minimum_strategy_validation_records"])
    minimum_validation_gain = float(
        config["minimum_strategy_validation_objective_gain"]
    )
    comparisons: dict[str, Any] = {}
    for strategy_id, strategy_rows in sorted(groups.items()):
        split = _chronological_split(strategy_rows)
        calibration_rows = split["calibration_rows"]
        validation_rows = split["validation_rows"]

        def with_score(
            window: list[dict[str, Any]],
            score_key: str,
        ) -> list[dict[str, Any]]:
            return [
                {**row, "rule_score": float(row[score_key])}
                for row in window
            ]

        calibration_v1 = with_score(calibration_rows, "_active_v1_score")
        calibration_v2 = with_score(calibration_rows, "_experimental_v2_score")
        validation_v1 = with_score(validation_rows, "_active_v1_score")
        validation_v2 = with_score(validation_rows, "_experimental_v2_score")
        calibration_v1_metrics = _metrics_by_zone(
            calibration_v1,
            strong_min=v1_strong_min,
            gray_min=v1_gray_min,
        )
        calibration_v2_metrics = _metrics_by_zone(
            calibration_v2,
            strong_min=v2_strong_min,
            gray_min=v2_gray_min,
        )
        validation_v1_metrics = _metrics_by_zone(
            validation_v1,
            strong_min=v1_strong_min,
            gray_min=v1_gray_min,
        )
        validation_v2_metrics = _metrics_by_zone(
            validation_v2,
            strong_min=v2_strong_min,
            gray_min=v2_gray_min,
        )
        calibration_v1_objective, _ = _candidate_objective(
            calibration_v1_metrics
        )
        calibration_v2_objective, _ = _candidate_objective(
            calibration_v2_metrics
        )
        validation_v1_objective, _ = _candidate_objective(validation_v1_metrics)
        validation_v2_objective, _ = _candidate_objective(validation_v2_metrics)
        calibration_delta = calibration_v2_objective - calibration_v1_objective
        validation_delta = validation_v2_objective - validation_v1_objective
        blocking_reasons: list[str] = []
        if len(strategy_rows) < minimum_total:
            blocking_reasons.append("valid_scores_below_minimum")
        if len(validation_rows) < minimum_validation:
            blocking_reasons.append("validation_records_below_minimum")
        if blocking_reasons:
            status = "insufficient_evidence"
        elif validation_delta < minimum_validation_gain:
            status = "degraded"
            blocking_reasons.append("validation_objective_regression")
        else:
            status = "non_regressing"
        comparisons[strategy_id] = {
            "status": status,
            "valid_scores": len(strategy_rows),
            "calibration_records": len(calibration_rows),
            "validation_records": len(validation_rows),
            "minimum_valid_scores": minimum_total,
            "minimum_validation_records": minimum_validation,
            "minimum_validation_objective_gain": minimum_validation_gain,
            "active_v1_thresholds": {
                "strong_min_score": v1_strong_min,
                "gray_min_score": v1_gray_min,
            },
            "candidate_v2_thresholds": {
                "strong_min_score": v2_strong_min,
                "gray_min_score": v2_gray_min,
            },
            "calibration_delta_v2_minus_v1": round(calibration_delta, 6),
            "validation_delta_v2_minus_v1": round(validation_delta, 6),
            "blocking_reasons": blocking_reasons,
            "chronological_validation": split["summary"],
            "validation_metrics": {
                "active_v1": validation_v1_metrics,
                "experimental_v2": validation_v2_metrics,
            },
            "auto_apply": False,
        }
    return comparisons


def _shadow_score_review_eligibility(
    *,
    complete_v2: list[dict[str, Any]],
    calibration_v2: list[dict[str, Any]],
    validation_v2: list[dict[str, Any]],
    score_coverage: float,
    v2_strong_min: float,
    v2_gray_min: float,
    calibration_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    validation_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    strategy_comparison: Mapping[str, Mapping[str, Any]],
    threshold_calibration: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    minimum_valid_scores = int(config["minimum_valid_scores"])
    minimum_score_coverage = float(config["minimum_score_coverage"])
    minimum_strategy_count = int(config["minimum_strategy_count"])
    minimum_per_strategy = int(config["minimum_per_strategy"])
    minimum_calibration_zone = int(config["minimum_calibration_zone"])
    minimum_validation_zone = int(config["minimum_validation_zone"])
    minimum_calibration_gain = float(config["minimum_calibration_objective_gain"])
    minimum_validation_gain = float(config["minimum_validation_objective_gain"])
    validation_lcb_floor = float(config["validation_average_r_lower_bound_floor"])
    validation_profit_factor_floor = float(config["validation_profit_factor_floor"])
    minimum_segment_samples = int(config["minimum_segment_samples"])

    strategy_counts: Counter[str] = Counter()
    for row in complete_v2:
        strategy_id = str(row.get("strategy_id") or row.get("team_id") or "unknown")
        if strategy_id != "unknown":
            strategy_counts[strategy_id] += 1
    below_strategy_minimum = [
        {
            "strategy_id": strategy_id,
            "valid_scores": count,
            "minimum": minimum_per_strategy,
        }
        for strategy_id, count in sorted(strategy_counts.items())
        if count < minimum_per_strategy
    ]

    calibration_v1_objective, _ = _candidate_objective(
        calibration_metrics["active_v1"]
    )
    calibration_v2_objective, _ = _candidate_objective(
        calibration_metrics["experimental_v2"]
    )
    validation_v1_objective, _ = _candidate_objective(
        validation_metrics["active_v1"]
    )
    validation_v2_objective, _ = _candidate_objective(
        validation_metrics["experimental_v2"]
    )
    calibration_delta = calibration_v2_objective - calibration_v1_objective
    validation_delta = validation_v2_objective - validation_v1_objective
    calibration_v2_zones = calibration_metrics["experimental_v2"]
    validation_v2_zones = validation_metrics["experimental_v2"]
    validation_strong = validation_v2_zones["strong"]
    validation_lcb = _number(validation_strong.get("average_r_lower_bound_90"))
    complete_stability = _strong_segment_stability(
        complete_v2,
        strong_min=v2_strong_min,
        minimum_samples=minimum_segment_samples,
    )
    validation_stability = _strong_segment_stability(
        validation_v2,
        strong_min=v2_strong_min,
        minimum_samples=minimum_segment_samples,
    )
    calibration_status = str(threshold_calibration.get("status") or "")

    gates = {
        "valid_score_sample": len(complete_v2) >= minimum_valid_scores,
        "score_coverage": score_coverage >= minimum_score_coverage,
        "strategy_coverage": (
            len(strategy_counts) >= minimum_strategy_count
            and not below_strategy_minimum
        ),
        "strategy_validation_sample": (
            len(strategy_comparison) >= minimum_strategy_count
            and all(
                item.get("status") != "insufficient_evidence"
                for item in strategy_comparison.values()
            )
        ),
        "strategy_validation_non_regression": (
            len(strategy_comparison) >= minimum_strategy_count
            and all(
                item.get("status") == "non_regressing"
                for item in strategy_comparison.values()
            )
        ),
        "threshold_calibration_sample": calibration_status
        != "collecting_evidence",
        "threshold_calibration_candidate": calibration_status
        == "candidate_ready",
        "calibration_strong_sample": (
            int(calibration_v2_zones["strong"]["n"]) >= minimum_calibration_zone
        ),
        "calibration_gray_sample": (
            int(calibration_v2_zones["gray"]["n"]) >= minimum_calibration_zone
        ),
        "validation_strong_sample": (
            int(validation_v2_zones["strong"]["n"]) >= minimum_validation_zone
        ),
        "validation_gray_sample": (
            int(validation_v2_zones["gray"]["n"]) >= minimum_validation_zone
        ),
        "calibration_objective_gain": calibration_delta >= minimum_calibration_gain,
        "validation_objective_gain": validation_delta >= minimum_validation_gain,
        "validation_strong_confidence": (
            validation_lcb is not None and validation_lcb > validation_lcb_floor
        ),
        "validation_strong_profit_factor": _profit_factor_at_least(
            validation_strong,
            validation_profit_factor_floor,
        ),
        "complete_segment_stability": bool(complete_stability["passed"]),
        "validation_segment_stability": bool(validation_stability["passed"]),
    }
    sample_gate_names = {
        "valid_score_sample",
        "score_coverage",
        "strategy_coverage",
        "calibration_strong_sample",
        "calibration_gray_sample",
        "validation_strong_sample",
        "validation_gray_sample",
        "strategy_validation_sample",
        "threshold_calibration_sample",
    }
    blocking_reasons = [name for name, passed in gates.items() if not passed]
    if calibration_status == "collecting_evidence":
        status = "collecting_evidence"
    elif calibration_status == "not_eligible":
        status = "not_eligible"
    elif any(not gates[name] for name in sample_gate_names):
        status = "collecting_evidence"
    elif blocking_reasons:
        status = "not_eligible"
    else:
        status = "eligible_for_review"
    return {
        "status": status,
        "eligible": status == "eligible_for_review",
        "gates": gates,
        "blocking_reasons": blocking_reasons,
        "requirements": dict(config),
        "objective_comparison": {
            "calibration_active_v1": round(calibration_v1_objective, 6),
            "calibration_experimental_v2": round(calibration_v2_objective, 6),
            "calibration_delta_v2_minus_v1": round(calibration_delta, 6),
            "validation_active_v1": round(validation_v1_objective, 6),
            "validation_experimental_v2": round(validation_v2_objective, 6),
            "validation_delta_v2_minus_v1": round(validation_delta, 6),
        },
        "strategy_coverage": {
            "observed_strategy_count": len(strategy_counts),
            "valid_scores_by_strategy": dict(sorted(strategy_counts.items())),
            "below_minimum": below_strategy_minimum,
        },
        "evaluated_v2_thresholds": {
            "strong_min_score": v2_strong_min,
            "gray_min_score": v2_gray_min,
        },
        "segment_stability": {
            "complete": complete_stability,
            "validation": validation_stability,
        },
        "auto_apply": False,
    }


def _score_zone(score: float, strong_min: float, gray_min: float) -> str:
    if score >= strong_min:
        return "strong"
    if score >= gray_min:
        return "gray"
    return "reject"


def _score_delta_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "average": None,
            "average_absolute": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "n": len(values),
        "average": round(sum(values) / len(values), 6),
        "average_absolute": round(sum(abs(value) for value in values) / len(values), 6),
        "minimum": round(min(values), 6),
        "maximum": round(max(values), 6),
    }


def _independent_mean_difference_ci_90(
    sample: list[float],
    baseline: list[float],
) -> tuple[float | None, float | None, float | None]:
    if not sample or not baseline:
        return None, None, None
    sample_mean = sum(sample) / len(sample)
    baseline_mean = sum(baseline) / len(baseline)
    delta = sample_mean - baseline_mean
    if len(sample) < 2 or len(baseline) < 2:
        return delta, None, None
    sample_variance = sum((value - sample_mean) ** 2 for value in sample) / (
        len(sample) - 1
    )
    baseline_variance = sum(
        (value - baseline_mean) ** 2 for value in baseline
    ) / (len(baseline) - 1)
    standard_error = math.sqrt(
        sample_variance / len(sample) + baseline_variance / len(baseline)
    )
    margin = TWO_SIDED_90_Z * standard_error
    return delta, delta - margin, delta + margin


def _evidence_coverage(
    rows: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    *,
    ordering: Mapping[str, Any],
) -> dict[str, Any]:
    all_sources = Counter(str(row.get("evaluation_source") or "observational") for row in rows)
    eligible_sources = Counter(str(row.get("evaluation_source")) for row in eligible)
    lanes = Counter(str(row.get("decision_lane") or "unknown") for row in rows)
    return {
        "all_by_source": dict(sorted(all_sources.items())),
        "eligible_by_source": dict(sorted(eligible_sources.items())),
        "all_by_decision_lane": dict(sorted(lanes.items())),
        "eligible_by_symbol": _dimension_counts(eligible, "symbol"),
        "eligible_by_strategy": _strategy_counts(eligible),
        "eligible_by_regime": _dimension_counts(eligible, "regime"),
        "counterfactual_score_floor": _counterfactual_score_floor(eligible),
        "ordering_fallback_records": int(ordering.get("fallback_records", 0)),
    }


def _counterfactual_score_floor(rows: list[dict[str, Any]]) -> float:
    """Return the most conservative lower score boundary in the evidence."""
    return max(
        (float(row.get("counterfactual_score_floor", 0.0)) for row in rows),
        default=0.0,
    )


def _recommendation(
    candidate: Mapping[str, Any],
    current_strong: float,
    current_gray: float,
) -> dict[str, Any]:
    strong = float(candidate["strong_min_score"])
    gray = float(candidate["gray_min_score"])
    complete_strong = candidate["zone_metrics"]["strong"]
    validation_strong = candidate["validation_zone_metrics"]["strong"]
    return {
        "strong_min_score": strong,
        "gray_min_score": gray,
        "changed_from_current": strong != current_strong or gray != current_gray,
        "requires_human_review": True,
        "eligible_for_guarded_demo_controller": True,
        "recommendation_method": "chronological_risk_adjusted_v1",
        "objective_gain_vs_current": candidate["objective_gain_vs_current"],
        "validation_delta_vs_current": candidate["validation_delta_vs_current"],
        "robustness": {
            "strong_average_r_lower_bound_90": complete_strong["average_r_lower_bound_90"],
            "validation_strong_average_r_lower_bound_90": validation_strong["average_r_lower_bound_90"],
            "segment_stability_passed": candidate["strong_segment_stability"]["passed"],
        },
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    current = payload.get("current_policy", {})
    recommendation = payload.get("recommended_thresholds")
    validation = payload.get("chronological_validation", {})
    lines = [
        "# Adaptive Threshold Evaluation",
        "",
        f"- Status: {payload.get('status')}",
        f"- Method: {payload.get('recommendation_method')}",
        f"- Eligible records: {payload.get('eligible_records')}",
        f"- Excluded records: {payload.get('excluded_records')}",
        f"- Calibration/validation: {validation.get('calibration_records')}/{validation.get('validation_records')}",
        f"- Current thresholds: gray={current.get('gray_min_score')}, strong={current.get('strong_min_score')}",
        f"- Auto apply: {payload.get('auto_apply')}",
        "",
        "## Recommendation",
        "",
    ]
    if isinstance(recommendation, Mapping):
        lines.extend(
            [
                f"- Reviewed proposal: gray={recommendation.get('gray_min_score')}, "
                f"strong={recommendation.get('strong_min_score')}",
                f"- Calibration objective delta: {recommendation.get('objective_gain_vs_current')}",
                f"- Validation objective delta: {recommendation.get('validation_delta_vs_current')}",
            ]
        )
    else:
        lines.append("- none; evidence gate not satisfied")
    reasons = payload.get("insufficiency_reasons", [])
    if isinstance(reasons, list) and reasons:
        lines.extend(["", "## Insufficiency Reasons", ""])
        lines.extend(f"- {reason}" for reason in reasons)
    gate_failures = payload.get("candidate_gate_failures", {})
    if isinstance(gate_failures, Mapping) and gate_failures:
        lines.extend(["", "## Candidate Gate Failures", ""])
        lines.extend(f"- {key}: {value}" for key, value in gate_failures.items())
    experiments = payload.get("shadow_scoring_experiment_evaluation")
    if isinstance(experiments, Mapping):
        experiment = experiments.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
        if isinstance(experiment, Mapping):
            coverage = experiment.get("score_coverage", {})
            deltas = experiment.get("score_delta_v2_minus_v1", {})
            readiness = experiment.get("review_eligibility", {})
            calibration = experiment.get("threshold_calibration", {})
            candidate_payload = (
                calibration.get("candidate_thresholds")
                if isinstance(calibration, Mapping)
                else None
            )
            candidate = candidate_payload if isinstance(candidate_payload, Mapping) else {}
            lines.extend(
                [
                    "",
                    "## Shadow Score Experiment",
                    "",
                    f"- Mode: {experiment.get('mode')}",
                    f"- Coverage: {coverage.get('valid')}/{coverage.get('total')}",
                    f"- Average V2-V1 score delta: {deltas.get('average')}",
                    f"- Threshold calibration: {calibration.get('status')}",
                    f"- V2 candidate thresholds: gray={candidate.get('gray_min_score')}, "
                    f"strong={candidate.get('strong_min_score')}",
                    f"- Review readiness: {readiness.get('status')}",
                    f"- Readiness blockers: {readiness.get('blocking_reasons')}",
                    f"- Zone transitions: {experiment.get('zone_transitions')}",
                    f"- Auto apply: {experiment.get('auto_apply')}",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def _event_timestamp(row: Mapping[str, Any]) -> float | None:
    trigger_ms = _number(row.get("trigger_timestamp_ms"))
    if trigger_ms is not None:
        return trigger_ms / 1000.0
    for key in (
        "triggered_at",
        "captured_at",
        "opened_at",
        "entry_at",
        "resolved_at",
        "closed_at",
        "generated_at",
        "data_timestamp_utc",
    ):
        raw = row.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def _review_observation(row: Mapping[str, Any]) -> dict[str, Any] | None:
    review: Mapping[str, Any] | None = None
    for key in ("observed_llm_review", "llm_review"):
        candidate = row.get(key)
        if isinstance(candidate, Mapping):
            review = candidate
            break
    if review is None:
        direct_decision = row.get("llm_review_decision")
        if direct_decision is None:
            return None
        review = {
            "decision": direct_decision,
            "risk_multiplier": row.get("llm_risk_multiplier"),
        }
    decision = str(review.get("decision") or "").upper()
    if decision not in {"APPROVE", "VETO", "WAIT"}:
        return None
    multiplier = _number(review.get("risk_multiplier"))
    if decision == "APPROVE":
        valid_multiplier = multiplier if multiplier in {0.5, 1.0} else None
    else:
        valid_multiplier = 0.0 if multiplier == 0.0 else None
    return {
        "decision": decision,
        "risk_multiplier": valid_multiplier,
        "r_multiple": float(row["r_multiple"]),
        "strategy": str(row.get("strategy_id") or row.get("team_id") or "unknown"),
        "regime": str(row.get("regime") or "unknown"),
    }


def _review_multiplier_metrics(observations: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        multiplier = float(observation["risk_multiplier"])
        groups[f"{multiplier:.1f}"].append(observation)
    result: dict[str, Any] = {}
    for multiplier, items in sorted(groups.items()):
        multiplier_value = float(multiplier)
        outcomes = [float(item["r_multiple"]) for item in items]
        result[multiplier] = {
            **_outcome_metrics(outcomes),
            "observed_cumulative_r": round(
                sum(value * multiplier_value for value in outcomes),
                6,
            ),
            "contribution_cumulative_r": round(
                sum(value * (multiplier_value - 1.0) for value in outcomes),
                6,
            ),
        }
    return result


def _review_segment_diagnostics(
    observations: list[dict[str, Any]],
    *,
    minimum_samples: int,
) -> dict[str, Any]:
    established: list[dict[str, Any]] = []
    for dimension in ("strategy", "regime"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            groups[str(observation[dimension])].append(observation)
        for value, items in sorted(groups.items()):
            if len(items) < minimum_samples:
                continue
            baseline = [float(item["r_multiple"]) for item in items]
            observed = [
                float(item["r_multiple"]) * float(item["risk_multiplier"])
                for item in items
            ]
            contributions = [
                observed_value - baseline_value
                for observed_value, baseline_value in zip(observed, baseline)
            ]
            mean, lower, upper = _mean_confidence_interval_90(contributions)
            if upper is not None and upper < 0:
                status = "degraded"
            elif lower is not None and lower > 0:
                status = "healthy"
            else:
                status = "inconclusive"
            established.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "n": len(items),
                    "status": status,
                    "approve_all_baseline_r_per_review": round(sum(baseline) / len(items), 6),
                    "observed_review_policy_r_per_review": round(sum(observed) / len(items), 6),
                    "selection_contribution_r_per_review": (
                        round(mean, 6) if mean is not None else None
                    ),
                    "selection_contribution_ci_90": {
                        "lower": round(lower, 6) if lower is not None else None,
                        "upper": round(upper, 6) if upper is not None else None,
                    },
                }
            )
    return {
        "minimum_samples": minimum_samples,
        "established_segments": established,
        "degraded_segments": [
            {
                "dimension": item["dimension"],
                "value": item["value"],
                "n": item["n"],
            }
            for item in established
            if item["status"] == "degraded"
        ],
    }


def _profit_factor_at_least(metrics: Mapping[str, Any], threshold: float) -> bool:
    profit_factor = _number(metrics.get("profit_factor"))
    if profit_factor is not None:
        return profit_factor >= threshold
    return _metric_number(metrics, "gross_profit_r", 0.0) > 0 and _metric_number(
        metrics,
        "gross_loss_r",
        0.0,
    ) == 0


def _bounded_profit_factor(metrics: Mapping[str, Any]) -> float:
    profit_factor = _number(metrics.get("profit_factor"))
    if profit_factor is None:
        return 5.0 if _metric_number(metrics, "gross_profit_r", 0.0) > 0 else 0.0
    return min(profit_factor, 5.0)


def _normalized_drawdown(metrics: Mapping[str, Any]) -> float:
    count = max(1, int(metrics.get("n", 0)))
    return _metric_number(metrics, "max_drawdown_r", 0.0) / math.sqrt(count)


def _metric_number(metrics: Mapping[str, Any], key: str, default: float) -> float:
    value = _number(metrics.get(key))
    return value if value is not None else default


def _dimension_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row.get(key) or "unknown") for row in rows)
    return dict(sorted(counts.items()))


def _strategy_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("strategy_id") or row.get("team_id") or "unknown") for row in rows)
    return dict(sorted(counts.items()))


def _nested(row: Mapping[str, Any], parent: str, key: str) -> Any:
    value = row.get(parent)
    return value.get(key) if isinstance(value, Mapping) else None


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
