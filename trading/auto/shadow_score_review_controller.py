"""Review-only staging for stable continuous-conflict V2 candidates."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from replay.adaptive_evaluation import evaluate_adaptive_thresholds

try:
    from .adaptive_hybrid import (
        CONTINUOUS_CONFLICT_EXPERIMENT_ID,
        DecisionPolicy,
        ShadowScoringReviewStagingPolicy,
        load_decision_policy,
        load_effective_decision_policy,
        shadow_score_review_state_path,
    )
except ImportError:  # pragma: no cover - direct scheduler import fallback
    from adaptive_hybrid import (  # type: ignore
        CONTINUOUS_CONFLICT_EXPERIMENT_ID,
        DecisionPolicy,
        ShadowScoringReviewStagingPolicy,
        load_decision_policy,
        load_effective_decision_policy,
        shadow_score_review_state_path,
    )


STATE_SCHEMA_VERSION = "continuous_conflict_v2_review_state.v1"
MAX_EVALUATION_RECORDS = 5_000
_STATE_LOCK = threading.RLock()

Evaluator = Callable[..., dict[str, Any]]


def run_shadow_score_review_controller(
    *,
    journal_module: Any,
    policy_path: Path | None = None,
    state_path: Path | None = None,
    execution_adapter: str | None = None,
    evaluator: Evaluator = evaluate_adaptive_thresholds,
) -> dict[str, Any]:
    """Stage a stable review candidate without enabling routing or canary use."""
    selected_state_path = state_path or shadow_score_review_state_path()
    try:
        canonical = (
            load_decision_policy(policy_path)
            if policy_path is not None
            else load_decision_policy()
        )
        experiment = canonical.shadow_scoring_experiment
        if experiment is None:
            raise ValueError("shadow scoring experiment is unavailable")
        config = experiment.review_staging
        adapter = str(
            execution_adapter or os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper")
        ).strip().lower()
        if adapter not in config.allowed_execution_adapters or canonical.live_enabled:
            return _record_result(
                journal_module,
                "skipped",
                {
                    "reason": "non_demo_execution_adapter",
                    "adapter": adapter,
                    "mode": config.mode,
                },
            )
        with _STATE_LOCK:
            state = _load_or_initialize_state(selected_state_path, canonical)
            rows = _read_shadow_outcomes(journal_module)
            evidence_fingerprint = _evidence_fingerprint(rows)
            if state.get("evidence_fingerprint") == evidence_fingerprint:
                return _record_result(
                    journal_module,
                    "skipped",
                    {
                        **compact_review_state(state),
                        "reason": "evidence_unchanged",
                        "adapter": adapter,
                    },
                )
            effective = (
                load_effective_decision_policy(policy_path)
                if policy_path is not None
                else load_effective_decision_policy()
            )
            active_zones = {
                "strong_min_score": effective.strong_min_score,
                "gray_min_score": effective.gray_min_score,
            }
            report = evaluator(
                rows[-MAX_EVALUATION_RECORDS:],
                **({"policy_path": policy_path} if policy_path is not None else {}),
                zone_override=active_zones,
                include_strategy_diagnostics=False,
                include_conflict_diagnostics=False,
                include_shadow_scoring_diagnostics=True,
            )
            experiment_report = _experiment_report(report)
            eligible = _eligible_v2_evidence_count(
                rows,
                score_version=experiment.score_version,
            )
            state.update(
                {
                    "evidence_fingerprint": evidence_fingerprint,
                    "last_evaluated_eligible_records": eligible,
                    "last_evaluation_status": _review_status(experiment_report),
                    "last_evaluated_at": _utc_now(),
                    "last_evidence": _compact_evidence(experiment_report),
                }
            )
            action, reason = _apply_review_candidate(
                state,
                experiment_report,
                config,
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
                    **compact_review_state(state),
                    "reason": reason,
                    "adapter": adapter,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return _record_result(
            journal_module,
            "error",
            {
                "reason": "review_controller_error",
                "error": str(exc),
                "state_path": str(selected_state_path),
            },
        )


def read_shadow_score_review_state(
    *,
    policy_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Return compact review-only state for status consumers."""
    canonical = (
        load_decision_policy(policy_path)
        if policy_path is not None
        else load_decision_policy()
    )
    selected_state_path = state_path or shadow_score_review_state_path()
    try:
        with _STATE_LOCK:
            state = _load_or_initialize_state(
                selected_state_path,
                canonical,
                persist=False,
            )
        return compact_review_state(state)
    except Exception as exc:  # noqa: BLE001
        experiment = canonical.shadow_scoring_experiment
        mode = experiment.review_staging.mode if experiment is not None else "unknown"
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "error",
            "mode": mode,
            "operator_approval_required": True,
            "operator_approved": False,
            "active_for_routing": False,
            "canary_enabled": False,
            "error": str(exc),
        }


def compact_review_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Strip review state to a stable, explicitly non-operational payload."""
    candidate = state.get("candidate")
    compact_candidate = None
    if isinstance(candidate, Mapping):
        compact_candidate = {
            "fingerprint": str(candidate.get("fingerprint") or ""),
            "strong_min_score": _number(candidate.get("strong_min_score")),
            "gray_min_score": _number(candidate.get("gray_min_score")),
            "confirmations": int(candidate.get("confirmations", 0) or 0),
            "required_confirmations": int(
                candidate.get("required_confirmations", 0) or 0
            ),
            "first_seen_eligible_records": int(
                candidate.get("first_seen_eligible_records", 0) or 0
            ),
            "last_confirmed_eligible_records": int(
                candidate.get("last_confirmed_eligible_records", 0) or 0
            ),
        }
    return {
        "schema_version": str(state.get("schema_version") or STATE_SCHEMA_VERSION),
        "mode": str(state.get("mode") or "unknown"),
        "status": str(state.get("status") or "unknown"),
        "revision": int(state.get("revision", 0) or 0),
        "score_version": state.get("score_version"),
        "candidate": compact_candidate,
        "last_evaluated_eligible_records": int(
            state.get("last_evaluated_eligible_records", 0) or 0
        ),
        "last_evaluation_status": state.get("last_evaluation_status"),
        "last_evidence": state.get("last_evidence"),
        "last_action": state.get("last_action"),
        "last_reason": state.get("last_reason"),
        "operator_approval_required": True,
        "operator_approved": False,
        "active_for_routing": False,
        "canary_enabled": False,
        "updated_at": state.get("updated_at"),
    }


def _apply_review_candidate(
    state: dict[str, Any],
    experiment_report: Mapping[str, Any],
    config: ShadowScoringReviewStagingPolicy,
    *,
    eligible: int,
) -> tuple[str, str]:
    readiness = experiment_report.get("review_eligibility")
    calibration = experiment_report.get("threshold_calibration")
    candidate_payload = (
        calibration.get("candidate_thresholds")
        if isinstance(calibration, Mapping)
        else None
    )
    ready = (
        isinstance(readiness, Mapping)
        and readiness.get("status") == "eligible_for_review"
        and readiness.get("eligible") is True
        and isinstance(calibration, Mapping)
        and calibration.get("status") == "candidate_ready"
        and isinstance(candidate_payload, Mapping)
        and candidate_payload.get("active_for_routing") is False
    )
    if not ready:
        had_candidate = isinstance(state.get("candidate"), Mapping)
        state["candidate"] = None
        if had_candidate:
            state["revision"] = int(state.get("revision", 0) or 0) + 1
            state["status"] = "invalidated"
            return "invalidated", "candidate_no_longer_review_eligible"
        state["status"] = "baseline"
        return "observed", "candidate_not_review_eligible"

    strong = _number(candidate_payload.get("strong_min_score"))
    gray = _number(candidate_payload.get("gray_min_score"))
    if strong is None or gray is None or not 0 <= gray < strong <= 100:
        raise ValueError("review candidate thresholds are invalid")
    fingerprint = _candidate_fingerprint(
        score_version=str(state["score_version"]),
        contract_fingerprint=str(state["contract_fingerprint"]),
        strong=strong,
        gray=gray,
    )
    current = state.get("candidate")
    if not isinstance(current, Mapping) or current.get("fingerprint") != fingerprint:
        state["revision"] = int(state.get("revision", 0) or 0) + 1
        state["candidate"] = {
            "fingerprint": fingerprint,
            "strong_min_score": strong,
            "gray_min_score": gray,
            "confirmations": 1,
            "required_confirmations": config.required_confirmations,
            "first_seen_eligible_records": eligible,
            "last_confirmed_eligible_records": eligible,
        }
        state["status"] = "staged"
        return "staged", "candidate_requires_new_evidence_confirmation"
    if state.get("status") == "review_ready":
        return "skipped", "candidate_already_review_ready"
    last_confirmed = int(current.get("last_confirmed_eligible_records", 0) or 0)
    if eligible - last_confirmed < config.minimum_new_eligible_outcomes:
        state["status"] = "staged"
        return "skipped", "candidate_waiting_for_new_evidence"
    updated = dict(current)
    updated["confirmations"] = int(current.get("confirmations", 0) or 0) + 1
    updated["last_confirmed_eligible_records"] = eligible
    state["revision"] = int(state.get("revision", 0) or 0) + 1
    state["candidate"] = updated
    if int(updated["confirmations"]) >= config.required_confirmations:
        state["status"] = "review_ready"
        return "review_ready", "candidate_evidence_confirmed_for_operator_review"
    state["status"] = "staged"
    return "staged", "candidate_needs_additional_confirmation"


def _load_or_initialize_state(
    path: Path,
    policy: DecisionPolicy,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    experiment = policy.shadow_scoring_experiment
    if experiment is None:
        raise ValueError("shadow scoring experiment is unavailable")
    contract_fingerprint = _contract_fingerprint(experiment.to_dict())
    if not path.exists():
        state = _initial_state(policy, contract_fingerprint=contract_fingerprint)
        if persist:
            _write_state(path, state)
        return state
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("review state payload is not an object")
    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("unsupported review state schema")
    if str(payload.get("mode")) != experiment.review_staging.mode:
        raise ValueError("review state mode differs from canonical policy")
    if str(payload.get("score_version")) != experiment.score_version:
        raise ValueError("review state score version is stale")
    if str(payload.get("contract_fingerprint")) != contract_fingerprint:
        raise ValueError("review state canonical contract is stale")
    if int(payload.get("revision", -1)) < 0:
        raise ValueError("review state revision is invalid")
    if payload.get("operator_approval_required") is not True:
        raise ValueError("review state approval requirement is invalid")
    if payload.get("operator_approved") is not False:
        raise ValueError("review state cannot contain operator approval")
    if payload.get("active_for_routing") is not False:
        raise ValueError("review state cannot activate routing")
    if payload.get("canary_enabled") is not False:
        raise ValueError("review state cannot enable canary")
    return payload


def _initial_state(
    policy: DecisionPolicy,
    *,
    contract_fingerprint: str,
) -> dict[str, Any]:
    experiment = policy.shadow_scoring_experiment
    if experiment is None:
        raise ValueError("shadow scoring experiment is unavailable")
    now = _utc_now()
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "mode": experiment.review_staging.mode,
        "status": "baseline",
        "revision": 0,
        "score_version": experiment.score_version,
        "contract_fingerprint": contract_fingerprint,
        "candidate": None,
        "evidence_fingerprint": None,
        "last_evaluated_eligible_records": 0,
        "last_evaluation_status": None,
        "last_evidence": None,
        "last_action": "initialized",
        "last_reason": "no_review_candidate",
        "last_evaluated_at": None,
        "operator_approval_required": True,
        "operator_approved": False,
        "active_for_routing": False,
        "canary_enabled": False,
        "created_at": now,
        "updated_at": now,
    }


def _experiment_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    experiments = report.get("shadow_scoring_experiment_evaluation")
    experiment = (
        experiments.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
        if isinstance(experiments, Mapping)
        else None
    )
    if not isinstance(experiment, Mapping):
        raise ValueError("V2 experiment evaluation is unavailable")
    return experiment


def _review_status(experiment: Mapping[str, Any]) -> str:
    readiness = experiment.get("review_eligibility")
    return (
        str(readiness.get("status") or "unknown")
        if isinstance(readiness, Mapping)
        else "unknown"
    )


def _eligible_v2_evidence_count(
    rows: list[dict[str, Any]],
    *,
    score_version: str,
) -> int:
    count = 0
    for row in rows:
        if not bool(row.get("counterfactual_eligible")):
            continue
        if str(row.get("evaluation_source") or "shadow").strip().lower() not in {
            "shadow",
            "backtest",
        }:
            continue
        active_score = _number(row.get("rule_score"))
        outcome = _number(row.get("r_multiple"))
        if (
            active_score is None
            or not 0 <= active_score <= 100
            or outcome is None
            or not math.isfinite(outcome)
        ):
            continue
        experiments = row.get("experimental_scores")
        experiment = (
            experiments.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
            if isinstance(experiments, Mapping)
            else None
        )
        if not isinstance(experiment, Mapping):
            continue
        v2_score = _number(experiment.get("score"))
        if (
            experiment.get("mode") != "shadow_only"
            or experiment.get("score_version") != score_version
            or experiment.get("active_for_routing") is not False
            or v2_score is None
            or not 0 <= v2_score <= 100
        ):
            continue
        count += 1
    return count


def _compact_evidence(experiment: Mapping[str, Any]) -> dict[str, Any]:
    readiness = experiment.get("review_eligibility")
    calibration = experiment.get("threshold_calibration")
    candidate = (
        calibration.get("candidate_thresholds")
        if isinstance(calibration, Mapping)
        else None
    )
    return {
        "readiness_status": _review_status(experiment),
        "readiness_blockers": (
            list(readiness.get("blocking_reasons") or [])[:8]
            if isinstance(readiness, Mapping)
            else []
        ),
        "calibration_status": (
            calibration.get("status") if isinstance(calibration, Mapping) else None
        ),
        "candidate_thresholds": (
            {
                "strong_min_score": _number(candidate.get("strong_min_score")),
                "gray_min_score": _number(candidate.get("gray_min_score")),
            }
            if isinstance(candidate, Mapping)
            else None
        ),
    }


def _read_shadow_outcomes(journal_module: Any) -> list[dict[str, Any]]:
    reader = getattr(journal_module, "read_shadow_outcomes", None)
    if not callable(reader):
        raise ValueError("journal does not expose shadow outcomes")
    rows = reader()
    if not isinstance(rows, list):
        raise ValueError("shadow outcome journal returned invalid data")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _record_result(
    journal_module: Any,
    action: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = {"action": action, **dict(payload)}
    append = getattr(journal_module, "append_decision", None)
    if callable(append):
        try:
            append(f"shadow_score_review_controller_{action}", result)
        except Exception as exc:  # noqa: BLE001
            result["journal_error"] = str(exc)
    return result


def _evidence_fingerprint(rows: list[dict[str, Any]]) -> str:
    tail = []
    for row in rows[-20:]:
        experiments = row.get("experimental_scores")
        v2 = (
            experiments.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
            if isinstance(experiments, Mapping)
            else None
        )
        tail.append(
            {
                "shadow_id": row.get("shadow_id"),
                "resolved_at": row.get("resolved_at"),
                "rule_score": row.get("rule_score"),
                "v2_score": v2.get("score") if isinstance(v2, Mapping) else None,
                "r_multiple": row.get("r_multiple"),
                "eligible": row.get("counterfactual_eligible"),
            }
        )
    return _contract_fingerprint({"records": len(rows), "tail": tail})


def _candidate_fingerprint(
    *,
    score_version: str,
    contract_fingerprint: str,
    strong: float,
    gray: float,
) -> str:
    return _contract_fingerprint(
        {
            "score_version": score_version,
            "contract_fingerprint": contract_fingerprint,
            "strong_min_score": round(strong, 6),
            "gray_min_score": round(gray, 6),
        }
    )


def _contract_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
