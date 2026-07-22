"""Guarded demo/testnet closed loop for adaptive routing thresholds."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from replay.adaptive_evaluation import evaluate_adaptive_thresholds
from strategy_teams import resolve_team, team_ids_from_env

try:
    from .adaptive_hybrid import (
        AdaptiveControllerPolicy,
        DecisionPolicy,
        adaptive_policy_state_path,
        load_decision_policy,
        load_effective_decision_policy,
    )
except ImportError:  # pragma: no cover - direct scheduler import fallback
    from adaptive_hybrid import (  # type: ignore
        AdaptiveControllerPolicy,
        DecisionPolicy,
        adaptive_policy_state_path,
        load_decision_policy,
        load_effective_decision_policy,
    )


STATE_SCHEMA_VERSION = "adaptive_policy_state.v1"
DEMO_EXECUTION_ADAPTERS = {"paper", "okx_demo"}
MAX_EVALUATION_RECORDS = 5_000
_STATE_LOCK = threading.RLock()

Evaluator = Callable[..., dict[str, Any]]


def run_adaptive_policy_controller(
    *,
    journal_module: Any,
    policy_path: Path | None = None,
    state_path: Path | None = None,
    execution_adapter: str | None = None,
    evaluator: Evaluator = evaluate_adaptive_thresholds,
) -> dict[str, Any]:
    """Evaluate, stage, activate, or roll back one demo policy revision."""
    selected_state_path = state_path or adaptive_policy_state_path()
    if not _env_bool("AUTO_ADAPTIVE_CONTROLLER_ENABLED", True):
        return _record_result(
            journal_module,
            "skipped",
            {"reason": "controller_disabled"},
        )
    try:
        canonical = (
            load_decision_policy(policy_path)
            if policy_path is not None
            else load_decision_policy()
        )
        adapter = str(
            execution_adapter or os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper")
        ).strip().lower()
        if canonical.adaptive_controller.mode not in {"observe_only", "demo_auto"}:
            raise ValueError("unsupported controller mode")
        if adapter not in DEMO_EXECUTION_ADAPTERS or canonical.live_enabled:
            return _record_result(
                journal_module,
                "skipped",
                {
                    "reason": "non_demo_execution_adapter",
                    "adapter": adapter,
                    "mode": canonical.adaptive_controller.mode,
                },
            )
        with _STATE_LOCK:
            state = _load_or_initialize_state(selected_state_path, canonical)
            rows = _read_shadow_outcomes(journal_module)
            fingerprint = _evidence_fingerprint(rows)
            if state.get("evidence_fingerprint") == fingerprint:
                return _record_result(
                    journal_module,
                    "skipped",
                    {
                        **compact_controller_state(state),
                        "reason": "evidence_unchanged",
                        "adapter": adapter,
                    },
                )
            active_zones = _zones(state["active_zones"])
            evaluation_rows = rows[-MAX_EVALUATION_RECORDS:]
            report = evaluator(
                evaluation_rows,
                **({"policy_path": policy_path} if policy_path is not None else {}),
                zone_override=active_zones,
                include_strategy_diagnostics=False,
                include_conflict_diagnostics=False,
                include_shadow_scoring_diagnostics=False,
            )
            eligible = _eligible_evidence_count(rows)
            state.update(
                {
                    "evidence_fingerprint": fingerprint,
                    "last_evaluated_eligible_records": eligible,
                    "last_evaluation_status": str(report.get("status") or "unknown"),
                    "last_evaluated_at": _utc_now(),
                    "last_evidence": _compact_evaluation_evidence(report),
                }
            )
            rollback_reason = _rollback_reason(
                state,
                report,
                canonical.adaptive_controller,
                eligible=eligible,
            )
            if rollback_reason:
                previous = _zones(state["previous_zones"])
                state.update(
                    {
                        "revision": int(state["revision"]) + 1,
                        "status": "rolled_back",
                        "active_zones": previous,
                        "previous_zones": None,
                        "staged_candidate": None,
                        "last_activation_eligible_records": None,
                        "last_rollback_eligible_records": eligible,
                        "last_action": "rolled_back",
                        "last_reason": rollback_reason,
                        "updated_at": _utc_now(),
                    }
                )
                _write_state(selected_state_path, state)
                return _record_result(
                    journal_module,
                    "rolled_back",
                    {
                        **compact_controller_state(state),
                        "reason": rollback_reason,
                        "adapter": adapter,
                    },
                )
            if canonical.adaptive_controller.mode == "observe_only":
                state.update(
                    {
                        "last_action": "observed",
                        "last_reason": "canonical_observe_only",
                        "updated_at": _utc_now(),
                    }
                )
                _write_state(selected_state_path, state)
                return _record_result(
                    journal_module,
                    "observed",
                    {**compact_controller_state(state), "adapter": adapter},
                )
            action, reason = _apply_recommendation(
                state,
                report,
                canonical.adaptive_controller,
                eligible=eligible,
            )
            state.update(
                {
                    "last_action": action,
                    "last_reason": reason,
                    "updated_at": _utc_now(),
                }
            )
            _write_state(selected_state_path, state)
            return _record_result(
                journal_module,
                action,
                {
                    **compact_controller_state(state),
                    "reason": reason,
                    "adapter": adapter,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return _record_result(
            journal_module,
            "error",
            {
                "reason": "controller_error",
                "error": str(exc),
                "state_path": str(selected_state_path),
            },
        )


def read_controller_state(
    *,
    policy_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Return compact persisted controller state for status consumers."""
    canonical = (
        load_decision_policy(policy_path)
        if policy_path is not None
        else load_decision_policy()
    )
    selected_state_path = state_path or adaptive_policy_state_path()
    try:
        with _STATE_LOCK:
            state = _load_or_initialize_state(
                selected_state_path,
                canonical,
                persist=False,
            )
        compact = compact_controller_state(state)
        effective = (
            load_effective_decision_policy(
                policy_path,
                state_path=selected_state_path,
            )
            if policy_path is not None
            else load_effective_decision_policy(state_path=selected_state_path)
        )
        effective_zones = {
            "strong_min_score": effective.strong_min_score,
            "gray_min_score": effective.gray_min_score,
        }
        if compact["active_zones"] != effective_zones:
            compact["persisted_active_zones"] = compact["active_zones"]
        compact["active_zones"] = effective_zones
        compact["effective_source"] = effective.policy_source
        compact["state_error"] = effective.policy_state_error
        return compact
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "error",
            "mode": canonical.adaptive_controller.mode,
            "revision": 0,
            "active_zones": _canonical_zones(canonical),
            "error": str(exc),
        }


def compact_controller_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Strip controller state to a stable status payload."""
    staged = state.get("staged_candidate")
    compact_stage = None
    if isinstance(staged, Mapping):
        compact_stage = {
            "zones": _zones(staged.get("zones")),
            "confirmations": int(staged.get("confirmations", 0) or 0),
            "required_confirmations": int(
                staged.get("required_confirmations", 0) or 0
            ),
            "first_seen_eligible_records": int(
                staged.get("first_seen_eligible_records", 0) or 0
            ),
            "last_confirmed_eligible_records": int(
                staged.get("last_confirmed_eligible_records", 0) or 0
            ),
        }
    return {
        "schema_version": str(state.get("schema_version") or STATE_SCHEMA_VERSION),
        "mode": str(state.get("mode") or "unknown"),
        "status": str(state.get("status") or "unknown"),
        "revision": int(state.get("revision", 0) or 0),
        "active_zones": _zones(state.get("active_zones")),
        "previous_zones": (
            _zones(state.get("previous_zones"))
            if isinstance(state.get("previous_zones"), Mapping)
            else None
        ),
        "staged_candidate": compact_stage,
        "last_evaluated_eligible_records": int(
            state.get("last_evaluated_eligible_records", 0) or 0
        ),
        "last_activation_eligible_records": state.get(
            "last_activation_eligible_records"
        ),
        "last_rollback_eligible_records": state.get("last_rollback_eligible_records"),
        "last_action": state.get("last_action"),
        "last_reason": state.get("last_reason"),
        "last_evidence": state.get("last_evidence"),
        "strategy_coverage_failures": list(
            state.get("strategy_coverage_failures") or []
        ),
        "updated_at": state.get("updated_at"),
    }


def _apply_recommendation(
    state: dict[str, Any],
    report: Mapping[str, Any],
    config: AdaptiveControllerPolicy,
    *,
    eligible: int,
) -> tuple[str, str]:
    recommendation = report.get("recommended_thresholds")
    if report.get("status") != "ready" or not isinstance(recommendation, Mapping):
        state["staged_candidate"] = None
        state["strategy_coverage_failures"] = []
        if int(state.get("revision", 0) or 0) == 0:
            state["status"] = "baseline"
        return "skipped", "evaluation_not_ready"
    if not bool(recommendation.get("eligible_for_guarded_demo_controller")):
        state["staged_candidate"] = None
        state["strategy_coverage_failures"] = []
        return "skipped", "recommendation_not_controller_eligible"
    active = _zones(state["active_zones"])
    desired = _zones(recommendation)
    if desired == active or not bool(recommendation.get("changed_from_current", True)):
        state["staged_candidate"] = None
        state["strategy_coverage_failures"] = []
        state["status"] = "active" if int(state["revision"]) > 0 else "baseline"
        return "skipped", "current_policy_remains_best"
    coverage_failures = _strategy_coverage_failures(report, config)
    state["strategy_coverage_failures"] = coverage_failures
    if coverage_failures:
        state["staged_candidate"] = None
        return "skipped", "strategy_evidence_coverage_insufficient"
    target = _bounded_zones(active, desired, config)
    review_health = report.get("llm_review_health")
    review_status = (
        str(review_health.get("status") or "unknown")
        if isinstance(review_health, Mapping)
        else "unknown"
    )
    if _expands_gray_lane(active, target) and review_status != "healthy":
        state["staged_candidate"] = None
        return "skipped", "llm_review_health_not_healthy_for_gray_expansion"
    identity = _zone_identity(target)
    staged = state.get("staged_candidate")
    if not isinstance(staged, Mapping) or str(staged.get("identity")) != identity:
        state["staged_candidate"] = {
            "identity": identity,
            "zones": target,
            "confirmations": 1,
            "required_confirmations": config.required_confirmations,
            "first_seen_eligible_records": eligible,
            "last_confirmed_eligible_records": eligible,
            "evidence": _compact_recommendation(recommendation),
        }
        state["status"] = "staged"
        return "staged", "candidate_requires_new_evidence_confirmation"
    last_confirmed = int(staged.get("last_confirmed_eligible_records", 0) or 0)
    if eligible - last_confirmed < config.minimum_new_eligible_outcomes:
        state["status"] = "staged"
        return "skipped", "candidate_waiting_for_new_evidence"
    updated_stage = dict(staged)
    updated_stage["confirmations"] = int(staged.get("confirmations", 0) or 0) + 1
    updated_stage["last_confirmed_eligible_records"] = eligible
    updated_stage["evidence"] = _compact_recommendation(recommendation)
    if int(updated_stage["confirmations"]) < config.required_confirmations:
        state["staged_candidate"] = updated_stage
        state["status"] = "staged"
        return "staged", "candidate_needs_additional_confirmation"
    state.update(
        {
            "revision": int(state.get("revision", 0) or 0) + 1,
            "status": "active",
            "previous_zones": active,
            "active_zones": target,
            "staged_candidate": None,
            "last_activation_eligible_records": eligible,
        }
    )
    return "activated", "evidence_confirmed_bounded_policy_revision"


def _rollback_reason(
    state: Mapping[str, Any],
    report: Mapping[str, Any],
    config: AdaptiveControllerPolicy,
    *,
    eligible: int,
) -> str | None:
    if int(state.get("revision", 0) or 0) <= 0:
        return None
    if not isinstance(state.get("previous_zones"), Mapping):
        return None
    activated_at = state.get("last_activation_eligible_records")
    if not isinstance(activated_at, int):
        return None
    if eligible - activated_at < config.rollback_minimum_new_eligible_outcomes:
        return None
    validation = report.get("current_policy_validation_metrics")
    if not isinstance(validation, Mapping):
        return None
    strong = validation.get("strong")
    if not isinstance(strong, Mapping):
        return None
    if int(strong.get("n", 0) or 0) < config.rollback_validation_strong_minimum_samples:
        return None
    lower_bound = _number(strong.get("average_r_lower_bound_90"))
    if (
        lower_bound is None
        or lower_bound <= config.rollback_validation_average_r_lower_bound_floor
    ):
        return "validation_strong_confidence_degraded"
    profit_factor = _number(strong.get("profit_factor"))
    if profit_factor is None:
        gross_profit = _number(strong.get("gross_profit_r")) or 0.0
        gross_loss = _number(strong.get("gross_loss_r")) or 0.0
        profit_factor_passed = gross_profit > 0 and gross_loss == 0
    else:
        profit_factor_passed = (
            profit_factor >= config.rollback_validation_profit_factor_floor
        )
    if not profit_factor_passed:
        return "validation_strong_profit_factor_degraded"
    return None


def _bounded_zones(
    active: Mapping[str, float],
    desired: Mapping[str, float],
    config: AdaptiveControllerPolicy,
) -> dict[str, float]:
    if desired["strong_min_score"] - desired["gray_min_score"] < config.minimum_zone_gap:
        raise ValueError("recommended zones violate minimum gap")
    strong = _bounded_step(
        active["strong_min_score"],
        desired["strong_min_score"],
        config.max_threshold_step,
    )
    gray = _bounded_step(
        active["gray_min_score"],
        desired["gray_min_score"],
        config.max_threshold_step,
    )
    strong = min(config.strong_max, max(config.strong_min, strong))
    gray = min(config.gray_max, max(config.gray_min, gray))
    if strong - gray < config.minimum_zone_gap:
        raise ValueError("bounded zones violate minimum gap")
    return {
        "strong_min_score": round(strong, 4),
        "gray_min_score": round(gray, 4),
    }


def _load_or_initialize_state(
    path: Path,
    policy: DecisionPolicy,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    if not path.exists():
        state = _initial_state(policy)
        if persist:
            _write_state(path, state)
        return state
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("controller state payload is not an object")
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported controller state schema")
    if str(payload.get("mode")) != policy.adaptive_controller.mode:
        raise ValueError("controller state mode differs from canonical policy")
    if _zones(payload.get("canonical_zones")) != _canonical_zones(policy):
        raise ValueError("controller state canonical zones are stale")
    if int(payload.get("revision", -1)) < 0:
        raise ValueError("controller state revision is invalid")
    _validate_zones(_zones(payload.get("active_zones")), policy.adaptive_controller)
    if isinstance(payload.get("previous_zones"), Mapping):
        _validate_zones(_zones(payload.get("previous_zones")), policy.adaptive_controller)
    return payload


def _initial_state(policy: DecisionPolicy) -> dict[str, Any]:
    now = _utc_now()
    zones = _canonical_zones(policy)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "mode": policy.adaptive_controller.mode,
        "status": "baseline",
        "revision": 0,
        "canonical_zones": zones,
        "active_zones": zones,
        "previous_zones": None,
        "staged_candidate": None,
        "evidence_fingerprint": None,
        "last_evaluated_eligible_records": 0,
        "last_activation_eligible_records": None,
        "last_rollback_eligible_records": None,
        "last_evaluation_status": None,
        "last_evidence": None,
        "strategy_coverage_failures": [],
        "last_action": "initialized",
        "last_reason": "canonical_baseline",
        "last_evaluated_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_shadow_outcomes(journal_module: Any) -> list[dict[str, Any]]:
    reader = getattr(journal_module, "read_shadow_outcomes", None)
    if not callable(reader):
        raise ValueError("journal does not expose shadow outcomes")
    rows = reader()
    if not isinstance(rows, list):
        raise ValueError("shadow outcome journal returned invalid data")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _record_result(
    journal_module: Any,
    action: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = {"action": action, **dict(payload)}
    append = getattr(journal_module, "append_decision", None)
    if callable(append):
        try:
            append(f"adaptive_policy_controller_{action}", result)
        except Exception as exc:  # noqa: BLE001
            result["journal_error"] = str(exc)
    return result


def _evidence_fingerprint(rows: list[dict[str, Any]]) -> str:
    evidence_tail = [
        {
            "shadow_id": row.get("shadow_id"),
            "resolved_at": row.get("resolved_at"),
            "rule_score": row.get("rule_score"),
            "r_multiple": row.get("r_multiple"),
            "eligible": row.get("counterfactual_eligible"),
        }
        for row in rows[-20:]
    ]
    encoded = json.dumps(
        {"records": len(rows), "tail": evidence_tail},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _eligible_evidence_count(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        if not bool(row.get("counterfactual_eligible")):
            continue
        score = _number(row.get("rule_score"))
        outcome = _number(row.get("r_multiple"))
        if score is None or not 0 <= score <= 100 or outcome is None:
            continue
        if str(row.get("evaluation_source") or "shadow").lower() not in {
            "shadow",
            "backtest",
        }:
            continue
        count += 1
    return count


def _compact_evaluation_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    recommendation = report.get("recommended_thresholds")
    return {
        "status": report.get("status"),
        "eligible_records": int(report.get("eligible_records", 0) or 0),
        "excluded_records": int(report.get("excluded_records", 0) or 0),
        "recommendation": (
            _compact_recommendation(recommendation)
            if isinstance(recommendation, Mapping)
            else None
        ),
        "insufficiency_reasons": list(report.get("insufficiency_reasons") or [])[:5],
    }


def _compact_recommendation(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "strong_min_score": _number(recommendation.get("strong_min_score")),
        "gray_min_score": _number(recommendation.get("gray_min_score")),
        "objective_gain_vs_current": _number(
            recommendation.get("objective_gain_vs_current")
        ),
        "validation_delta_vs_current": _number(
            recommendation.get("validation_delta_vs_current")
        ),
    }


def _strategy_coverage_failures(
    report: Mapping[str, Any],
    config: AdaptiveControllerPolicy,
) -> list[dict[str, Any]]:
    evidence = report.get("evidence_coverage")
    coverage = evidence.get("eligible_by_strategy") if isinstance(evidence, Mapping) else None
    counts = coverage if isinstance(coverage, Mapping) else {}
    failures: list[dict[str, Any]] = []
    for team_id in team_ids_from_env():
        strategy_id = resolve_team(team_id).strategy_id
        count = int(counts.get(strategy_id, 0) or 0)
        if count < config.minimum_strategy_eligible_outcomes:
            failures.append(
                {
                    "team_id": team_id,
                    "strategy_id": strategy_id,
                    "eligible_records": count,
                    "minimum_records": config.minimum_strategy_eligible_outcomes,
                }
            )
    return failures


def _canonical_zones(policy: DecisionPolicy) -> dict[str, float]:
    return {
        "strong_min_score": float(policy.strong_min_score),
        "gray_min_score": float(policy.gray_min_score),
    }


def _zones(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("zone payload is missing")
    try:
        strong = float(value["strong_min_score"])
        gray = float(value["gray_min_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("zone payload is invalid") from exc
    return {"strong_min_score": strong, "gray_min_score": gray}


def _validate_zones(
    zones: Mapping[str, float],
    config: AdaptiveControllerPolicy,
) -> None:
    if not config.strong_min <= zones["strong_min_score"] <= config.strong_max:
        raise ValueError("strong threshold is outside canonical controller bounds")
    if not config.gray_min <= zones["gray_min_score"] <= config.gray_max:
        raise ValueError("gray threshold is outside canonical controller bounds")
    if zones["strong_min_score"] - zones["gray_min_score"] < config.minimum_zone_gap:
        raise ValueError("controller state violates minimum zone gap")


def _zone_identity(zones: Mapping[str, float]) -> str:
    return f"{zones['strong_min_score']:.4f}:{zones['gray_min_score']:.4f}"


def _expands_gray_lane(
    active: Mapping[str, float],
    target: Mapping[str, float],
) -> bool:
    return (
        target["gray_min_score"] < active["gray_min_score"]
        or target["strong_min_score"] > active["strong_min_score"]
    )


def _bounded_step(current: float, desired: float, maximum_step: float) -> float:
    return current + max(-maximum_step, min(maximum_step, desired - current))


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
