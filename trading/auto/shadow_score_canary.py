"""Operator-approved, bounded demo canary for continuous-conflict V2 scoring."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import statistics
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from .adaptive_hybrid import (
        CONTINUOUS_CONFLICT_EXPERIMENT_ID,
        DecisionPolicy,
        build_rule_proposal,
        load_decision_policy,
        shadow_score_canary_state_path,
        shadow_score_review_state_path,
    )
except ImportError:  # pragma: no cover - direct script fallback
    from adaptive_hybrid import (  # type: ignore
        CONTINUOUS_CONFLICT_EXPERIMENT_ID,
        DecisionPolicy,
        build_rule_proposal,
        load_decision_policy,
        shadow_score_canary_state_path,
        shadow_score_review_state_path,
    )


STATE_SCHEMA_VERSION = "continuous_conflict_v2_canary_state.v1"
REVIEW_SCHEMA_VERSION = "continuous_conflict_v2_review_state.v1"
_STATE_LOCK = threading.RLock()
_LCB_Z_90_ONE_SIDED = 1.2815515655446004


class ShadowScoreCanaryError(RuntimeError):
    """Raised when canary approval or state violates the canonical contract."""


@dataclass(frozen=True)
class CanaryRoutingDecision:
    """Pure routing result for one V1/V2 score comparison."""

    eligible: bool
    selected: bool
    reason: str
    v1_score: float | None = None
    v2_score: float | None = None
    v1_zone: str | None = None
    v2_zone: str | None = None
    allocation_bucket: float | None = None
    routing_experiment: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe routing evidence."""
        return asdict(self)


def approve_shadow_score_canary(
    *,
    candidate_fingerprint: str,
    operator: str,
    acknowledge_demo_only: bool,
    policy_path: Path | None = None,
    review_state_path: Path | None = None,
    canary_state_path: Path | None = None,
    execution_adapter: str | None = None,
) -> dict[str, Any]:
    """Approve the exact review-ready candidate for bounded demo routing."""
    if not acknowledge_demo_only:
        raise ShadowScoreCanaryError("explicit demo-only acknowledgement is required")
    operator_name = operator.strip()
    if not operator_name:
        raise ShadowScoreCanaryError("operator is required")
    policy = _load_policy(policy_path)
    experiment = _experiment(policy)
    adapter = _adapter(execution_adapter)
    if policy.live_enabled or adapter not in experiment.canary.allowed_execution_adapters:
        raise ShadowScoreCanaryError("canary approval requires a canonical demo adapter")
    review_path = review_state_path or shadow_score_review_state_path()
    review = _read_json_object(review_path, "review state")
    candidate = review.get("candidate")
    contract_fingerprint = _fingerprint(experiment.to_dict())
    if (
        review.get("schema_version") != REVIEW_SCHEMA_VERSION
        or review.get("status") != "review_ready"
        or review.get("score_version") != experiment.score_version
        or review.get("contract_fingerprint") != contract_fingerprint
        or not isinstance(candidate, Mapping)
        or str(candidate.get("fingerprint") or "") != candidate_fingerprint
    ):
        raise ShadowScoreCanaryError("candidate is not the exact canonical review-ready candidate")
    strong, gray = _candidate_thresholds(candidate)
    expected_candidate_fingerprint = _candidate_fingerprint(
        score_version=experiment.score_version,
        contract_fingerprint=contract_fingerprint,
        strong=strong,
        gray=gray,
    )
    if candidate_fingerprint != expected_candidate_fingerprint:
        raise ShadowScoreCanaryError("review candidate fingerprint is internally invalid")
    now = _utc_now()
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "mode": experiment.canary.mode,
        "status": "active",
        "revision": 1,
        "approval_id": str(uuid.uuid4()),
        "operator": operator_name,
        "approved_at": now,
        "updated_at": now,
        "adapter": adapter,
        "score_version": experiment.score_version,
        "contract_fingerprint": contract_fingerprint,
        "candidate_fingerprint": candidate_fingerprint,
        "candidate_thresholds": {
            "strong_min_score": strong,
            "gray_min_score": gray,
        },
        "allocation_rate": experiment.canary.allocation_rate,
        "risk_multiplier": experiment.canary.risk_multiplier,
        "max_concurrent_positions": experiment.canary.max_concurrent_positions,
        "disagreement_only": experiment.canary.disagreement_only,
        "rollback_metrics": _empty_metrics(),
        "last_action": "approved",
        "last_reason": "operator_approved_exact_review_candidate",
    }
    selected_path = canary_state_path or shadow_score_canary_state_path()
    with _STATE_LOCK:
        if selected_path.exists():
            existing = _read_json_object(selected_path, "canary state")
            if existing.get("status") == "active":
                raise ShadowScoreCanaryError("an active canary approval already exists")
        _write_state(selected_path, state)
    return compact_canary_state(state)


def revoke_shadow_score_canary(
    *,
    operator: str,
    reason: str,
    canary_state_path: Path | None = None,
) -> dict[str, Any]:
    """Revoke the current approval without allowing implicit reactivation."""
    if not operator.strip() or not reason.strip():
        raise ShadowScoreCanaryError("operator and reason are required")
    path = canary_state_path or shadow_score_canary_state_path()
    with _STATE_LOCK:
        state = _read_json_object(path, "canary state")
        _validate_state_shape(state)
        if state.get("status") != "active":
            raise ShadowScoreCanaryError("only an active canary can be revoked")
        state.update(
            {
                "status": "revoked",
                "revision": int(state.get("revision", 0)) + 1,
                "revoked_by": operator.strip(),
                "revoked_at": _utc_now(),
                "updated_at": _utc_now(),
                "last_action": "revoked",
                "last_reason": reason.strip(),
            }
        )
        _write_state(path, state)
    return compact_canary_state(state)


def run_shadow_score_canary_controller(
    *,
    journal_module: Any,
    policy_path: Path | None = None,
    review_state_path: Path | None = None,
    canary_state_path: Path | None = None,
    execution_adapter: str | None = None,
) -> dict[str, Any]:
    """Validate approval and apply evidence-driven rollback before each cycle."""
    try:
        policy = _load_policy(policy_path)
        experiment = _experiment(policy)
        adapter = _adapter(execution_adapter)
        path = canary_state_path or shadow_score_canary_state_path()
        if not path.exists():
            return _record_controller_result(
                journal_module, "skipped", _inactive("approval_missing", policy)
            )
        with _STATE_LOCK:
            state = _read_json_object(path, "canary state")
            _validate_state_shape(state)
            if state.get("status") != "active":
                return _record_controller_result(
                    journal_module, str(state.get("status")), compact_canary_state(state)
                )
            try:
                _validate_operational_state(state, policy, adapter)
            except Exception as exc:  # noqa: BLE001
                return _record_controller_result(
                    journal_module,
                    "rolled_back",
                    _rollback(
                        state,
                        path,
                        f"approval_validation_failed:{exc}",
                    ),
                )
            review = _read_json_object(
                review_state_path or shadow_score_review_state_path(),
                "review state",
            )
            candidate = review.get("candidate")
            approved_thresholds = state.get("candidate_thresholds")
            still_ready = (
                review.get("schema_version") == REVIEW_SCHEMA_VERSION
                and review.get("status") == "review_ready"
                and review.get("score_version") == state.get("score_version")
                and review.get("contract_fingerprint") == state.get("contract_fingerprint")
                and isinstance(candidate, Mapping)
                and isinstance(approved_thresholds, Mapping)
                and candidate.get("fingerprint") == state.get("candidate_fingerprint")
                and _number(candidate.get("strong_min_score"))
                == _number(approved_thresholds.get("strong_min_score"))
                and _number(candidate.get("gray_min_score"))
                == _number(approved_thresholds.get("gray_min_score"))
            )
            if not still_ready:
                return _record_controller_result(
                    journal_module,
                    "rolled_back",
                    _rollback(state, path, "review_candidate_is_stale"),
                )
            rows = _closed_canary_rows(journal_module, str(state["approval_id"]))
            metrics = _canary_metrics(rows)
            state["rollback_metrics"] = metrics
            state["updated_at"] = _utc_now()
            rollback = experiment.canary
            if metrics["closed_trades"] >= rollback.rollback_minimum_closed_trades:
                reasons = []
                if metrics["average_r_lower_bound"] <= rollback.rollback_average_r_lower_bound_floor:
                    reasons.append("average_r_lower_bound")
                if metrics["profit_factor"] < rollback.rollback_profit_factor_floor:
                    reasons.append("profit_factor")
                if metrics["cumulative_r"] <= rollback.rollback_cumulative_r_floor:
                    reasons.append("cumulative_r")
                if reasons:
                    return _record_controller_result(
                        journal_module,
                        "rolled_back",
                        _rollback(
                            state,
                            path,
                            "rollback_floor_breached:" + ",".join(reasons),
                        ),
                    )
            state["last_action"] = "active"
            state["last_reason"] = "approval_and_review_candidate_valid"
            _write_state(path, state)
            return _record_controller_result(
                journal_module, "active", compact_canary_state(state)
            )
    except Exception as exc:  # noqa: BLE001
        result = {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "error",
            "routing_enabled": False,
            "reason": "canary_controller_error",
            "error": str(exc),
        }
        _journal_event(journal_module, "error", result)
        return result


def read_shadow_score_canary_state(
    *,
    policy_path: Path | None = None,
    canary_state_path: Path | None = None,
) -> dict[str, Any]:
    """Read compact state without creating an approval file."""
    policy = _load_policy(policy_path)
    path = canary_state_path or shadow_score_canary_state_path()
    if not path.exists():
        return _inactive("approval_missing", policy)
    try:
        state = _read_json_object(path, "canary state")
        _validate_state_shape(state)
        if state.get("status") == "active":
            _validate_operational_state(state, policy, _adapter(None))
        return compact_canary_state(state)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "error",
            "routing_enabled": False,
            "reason": "invalid_canary_state",
            "error": str(exc),
        }


def evaluate_canary_signal(
    signal: Mapping[str, Any],
    *,
    policy: DecisionPolicy,
    canary_state: Mapping[str, Any],
    canary_slot_available: bool = True,
) -> CanaryRoutingDecision:
    """Select a stable fraction of valid V1/V2 zone disagreements."""
    if not bool(canary_state.get("routing_enabled")):
        return CanaryRoutingDecision(False, False, "canary_inactive")
    proposal = build_rule_proposal(signal, policy=policy)
    if proposal.hard_blockers or signal.get("blockers"):
        return CanaryRoutingDecision(False, False, "hard_blocker_present")
    if str(signal.get("direction") or "") not in {"long", "short"}:
        return CanaryRoutingDecision(False, False, "signal_not_directional")
    experimental = signal.get("experimental_scores")
    v2 = (
        experimental.get(CONTINUOUS_CONFLICT_EXPERIMENT_ID)
        if isinstance(experimental, Mapping)
        else None
    )
    if not isinstance(v2, Mapping):
        return CanaryRoutingDecision(False, False, "v2_score_missing")
    if (
        v2.get("mode") != "shadow_only"
        or v2.get("active_for_routing") is not False
        or v2.get("score_version") != canary_state.get("score_version")
    ):
        return CanaryRoutingDecision(False, False, "v2_score_contract_mismatch")
    v2_score = _number(v2.get("score"))
    thresholds = canary_state.get("candidate_thresholds")
    if v2_score is None or not isinstance(thresholds, Mapping):
        return CanaryRoutingDecision(False, False, "v2_score_invalid")
    v2_zone = _zone(v2_score, thresholds)
    if proposal.decision_zone == v2_zone:
        return CanaryRoutingDecision(
            False,
            False,
            "zones_agree",
            proposal.rule_score,
            v2_score,
            proposal.decision_zone,
            v2_zone,
        )
    bucket = stable_allocation_bucket(
        candidate_fingerprint=str(canary_state.get("candidate_fingerprint") or ""),
        signal=signal,
    )
    allocated = bucket < float(canary_state.get("allocation_rate", 0.0))
    selected = allocated and canary_slot_available
    reason = "selected" if selected else ("canary_slot_unavailable" if allocated else "allocation_miss")
    routing = {
        "schema_version": "continuous_conflict_v2_routing.v1",
        "experiment_id": CONTINUOUS_CONFLICT_EXPERIMENT_ID,
        "approval_id": canary_state.get("approval_id"),
        "candidate_fingerprint": canary_state.get("candidate_fingerprint"),
        "score_version": canary_state.get("score_version"),
        "v1_score": proposal.rule_score,
        "v1_zone": proposal.decision_zone,
        "base_target_risk_pct_equity": proposal.proposed_risk_pct_equity,
        "v2_score": round(v2_score, 4),
        "v2_zone": v2_zone,
        "allocation_bucket": round(bucket, 8),
        "allocation_rate": canary_state.get("allocation_rate"),
        "risk_multiplier": canary_state.get("risk_multiplier"),
        "candidate_thresholds": dict(thresholds),
    }
    return CanaryRoutingDecision(
        True,
        selected,
        reason,
        proposal.rule_score,
        v2_score,
        proposal.decision_zone,
        v2_zone,
        bucket,
        routing,
    )


def apply_canary_signal(
    signal: Mapping[str, Any],
    decision: CanaryRoutingDecision,
) -> dict[str, Any]:
    """Return a V2-routed signal copy while preserving all V1 evidence."""
    if not decision.selected or decision.routing_experiment is None:
        raise ShadowScoreCanaryError("only a selected canary signal can be applied")
    payload = copy.deepcopy(dict(signal))
    score = float(decision.v2_score or 0.0)
    zone = str(decision.v2_zone)
    payload["rule_score"] = score
    payload["score"] = max(0, min(100, int(round(score))))
    payload["decision_zone"] = zone
    payload["status"] = "strong_candidate" if zone == "strong" else "candidate"
    payload["signal"] = payload["status"]
    direction = str(payload.get("direction") or "")
    payload["action_hint"] = "OPEN_LONG" if direction == "long" else "OPEN_SHORT"
    payload["promotion_gate"] = "eligible_for_draft_ticket"
    evidence = payload.setdefault("evidence", {})
    setup_quality = evidence.setdefault("setup_quality", {})
    setup_quality["rule_score"] = score
    target_risk = _number(payload.get("target_risk_pct_equity")) or _number(
        decision.routing_experiment.get("base_target_risk_pct_equity")
    )
    multiplier = float(decision.routing_experiment["risk_multiplier"])
    payload["target_risk_pct_equity"] = (target_risk or 0.01) * multiplier
    llm_context = payload.setdefault("llm_context", {})
    llm_context["routing_experiment"] = dict(decision.routing_experiment)
    return payload


def canary_decision_policy(
    policy: DecisionPolicy,
    canary_state: Mapping[str, Any],
) -> DecisionPolicy:
    """Build the immutable V2 threshold view used only by selected candidates."""
    thresholds = canary_state.get("candidate_thresholds")
    if not isinstance(thresholds, Mapping):
        raise ShadowScoreCanaryError("candidate thresholds are missing")
    return replace(
        policy,
        strong_min_score=float(thresholds["strong_min_score"]),
        gray_min_score=float(thresholds["gray_min_score"]),
        policy_source="continuous_conflict_v2_canary",
    )


def stable_allocation_bucket(
    *,
    candidate_fingerprint: str,
    signal: Mapping[str, Any],
) -> float:
    """Hash stable signal identity into [0, 1) without runtime randomness."""
    identity = {
        "candidate_fingerprint": candidate_fingerprint,
        "team_id": signal.get("team_id"),
        "strategy_id": signal.get("strategy_id"),
        "symbol": str(signal.get("symbol") or "").upper(),
        "direction": signal.get("direction"),
        "signal_id": signal.get("signal_id"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def compact_canary_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return status/API-safe operational state."""
    status = str(state.get("status") or "unknown")
    return {
        "schema_version": str(state.get("schema_version") or STATE_SCHEMA_VERSION),
        "mode": state.get("mode"),
        "status": status,
        "routing_enabled": status == "active",
        "revision": int(state.get("revision", 0) or 0),
        "approval_id": state.get("approval_id"),
        "operator": state.get("operator"),
        "adapter": state.get("adapter"),
        "score_version": state.get("score_version"),
        "candidate_fingerprint": state.get("candidate_fingerprint"),
        "candidate_thresholds": state.get("candidate_thresholds"),
        "allocation_rate": state.get("allocation_rate"),
        "risk_multiplier": state.get("risk_multiplier"),
        "max_concurrent_positions": state.get("max_concurrent_positions"),
        "rollback_metrics": state.get("rollback_metrics", _empty_metrics()),
        "last_action": state.get("last_action"),
        "last_reason": state.get("last_reason"),
        "approved_at": state.get("approved_at"),
        "updated_at": state.get("updated_at"),
    }


def _canary_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := _row_r_multiple(row)) is not None]
    if not values:
        return _empty_metrics(excluded=len(rows))
    average = statistics.fmean(values)
    lower_bound = average
    if len(values) > 1:
        lower_bound -= _LCB_Z_90_ONE_SIDED * statistics.stdev(values) / math.sqrt(len(values))
    gains = sum(value for value in values if value > 0)
    losses = abs(sum(value for value in values if value < 0))
    profit_factor = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    return {
        "closed_trades": len(values),
        "excluded_trades": len(rows) - len(values),
        "average_r": round(average, 6),
        "average_r_lower_bound": round(lower_bound, 6),
        "profit_factor": round(profit_factor, 6),
        "cumulative_r": round(sum(values), 6),
    }


def _closed_canary_rows(journal_module: Any, approval_id: str) -> list[dict[str, Any]]:
    reader = getattr(journal_module, "read_closed_trades", None)
    if not callable(reader):
        raise ShadowScoreCanaryError("journal does not expose closed trades")
    rows = reader()
    return [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and isinstance(row.get("routing_experiment"), Mapping)
        and row["routing_experiment"].get("approval_id") == approval_id
    ]


def _row_r_multiple(row: Mapping[str, Any]) -> float | None:
    direct = _number(row.get("r_multiple"))
    if direct is not None and math.isfinite(direct):
        return direct
    pnl, risk = _number(row.get("pnl_usd")), _number(row.get("risk_usd"))
    return pnl / risk if pnl is not None and risk is not None and risk > 0 else None


def _rollback(state: dict[str, Any], path: Path, reason: str) -> dict[str, Any]:
    state.update(
        {
            "status": "rolled_back",
            "revision": int(state.get("revision", 0)) + 1,
            "rolled_back_at": _utc_now(),
            "updated_at": _utc_now(),
            "last_action": "rolled_back",
            "last_reason": reason,
        }
    )
    _write_state(path, state)
    return compact_canary_state(state)


def _validate_operational_state(
    state: Mapping[str, Any], policy: DecisionPolicy, adapter: str
) -> None:
    _validate_state_shape(state)
    experiment = _experiment(policy)
    if policy.live_enabled or adapter not in experiment.canary.allowed_execution_adapters:
        raise ShadowScoreCanaryError("non-demo adapter cannot run a canary")
    if state.get("adapter") != adapter:
        raise ShadowScoreCanaryError("approved adapter differs from runtime adapter")
    if state.get("score_version") != experiment.score_version:
        raise ShadowScoreCanaryError("approved score version is stale")
    if state.get("contract_fingerprint") != _fingerprint(experiment.to_dict()):
        raise ShadowScoreCanaryError("approved canonical contract is stale")
    canary = experiment.canary
    if state.get("mode") != canary.mode:
        raise ShadowScoreCanaryError("approved canary mode is invalid")
    if not math.isclose(
        float(state.get("allocation_rate", -1.0)), canary.allocation_rate
    ):
        raise ShadowScoreCanaryError("approved allocation differs from canonical policy")
    if not math.isclose(
        float(state.get("risk_multiplier", -1.0)), canary.risk_multiplier
    ):
        raise ShadowScoreCanaryError("approved risk differs from canonical policy")
    if int(state.get("max_concurrent_positions", -1)) != canary.max_concurrent_positions:
        raise ShadowScoreCanaryError("approved position limit differs from canonical policy")
    if state.get("disagreement_only") is not canary.disagreement_only:
        raise ShadowScoreCanaryError("approved disagreement policy is invalid")
    thresholds = state.get("candidate_thresholds")
    if not isinstance(thresholds, Mapping):
        raise ShadowScoreCanaryError("approved candidate thresholds are missing")
    strong, gray = _candidate_thresholds(thresholds)
    expected_candidate_fingerprint = _candidate_fingerprint(
        score_version=experiment.score_version,
        contract_fingerprint=str(state["contract_fingerprint"]),
        strong=strong,
        gray=gray,
    )
    if state.get("candidate_fingerprint") != expected_candidate_fingerprint:
        raise ShadowScoreCanaryError("approved candidate fingerprint is invalid")


def _validate_state_shape(state: Mapping[str, Any]) -> None:
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ShadowScoreCanaryError("unsupported canary state schema")
    if state.get("status") not in {"active", "revoked", "rolled_back"}:
        raise ShadowScoreCanaryError("invalid canary status")
    if not str(state.get("approval_id") or ""):
        raise ShadowScoreCanaryError("approval id is missing")


def _inactive(reason: str, policy: DecisionPolicy) -> dict[str, Any]:
    experiment = _experiment(policy)
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "mode": experiment.canary.mode,
        "status": "inactive",
        "routing_enabled": False,
        "reason": reason,
        "allocation_rate": experiment.canary.allocation_rate,
        "risk_multiplier": experiment.canary.risk_multiplier,
        "max_concurrent_positions": experiment.canary.max_concurrent_positions,
        "rollback_metrics": _empty_metrics(),
    }


def _empty_metrics(*, excluded: int = 0) -> dict[str, Any]:
    return {
        "closed_trades": 0,
        "excluded_trades": excluded,
        "average_r": None,
        "average_r_lower_bound": None,
        "profit_factor": None,
        "cumulative_r": 0.0,
    }


def _experiment(policy: DecisionPolicy) -> Any:
    if policy.shadow_scoring_experiment is None:
        raise ShadowScoreCanaryError("canonical V2 experiment is unavailable")
    return policy.shadow_scoring_experiment


def _load_policy(path: Path | None) -> DecisionPolicy:
    return load_decision_policy(path) if path is not None else load_decision_policy()


def _adapter(value: str | None) -> str:
    return str(value or os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper")).strip().lower()


def _candidate_thresholds(candidate: Mapping[str, Any]) -> tuple[float, float]:
    strong = _number(candidate.get("strong_min_score"))
    gray = _number(candidate.get("gray_min_score"))
    if strong is None or gray is None or not 0 <= gray < strong <= 100:
        raise ShadowScoreCanaryError("review candidate thresholds are invalid")
    return strong, gray


def _zone(score: float, thresholds: Mapping[str, Any]) -> str:
    strong, gray = _candidate_thresholds(thresholds)
    return "strong" if score >= strong else ("gray" if score >= gray else "reject")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _candidate_fingerprint(
    *,
    score_version: str,
    contract_fingerprint: str,
    strong: float,
    gray: float,
) -> str:
    return _fingerprint(
        {
            "score_version": score_version,
            "contract_fingerprint": contract_fingerprint,
            "strong_min_score": round(strong, 6),
            "gray_min_score": round(gray, 6),
        }
    )


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShadowScoreCanaryError(f"{label} unavailable") from exc
    if not isinstance(payload, dict):
        raise ShadowScoreCanaryError(f"{label} is not an object")
    return payload


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _journal_event(journal_module: Any, action: str, payload: Mapping[str, Any]) -> None:
    append = getattr(journal_module, "append_decision", None)
    if callable(append):
        append(f"shadow_score_canary_controller_{action}", dict(payload))


def _record_controller_result(
    journal_module: Any,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _journal_event(journal_module, action, payload)
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    """Manage canary approval from an explicit operator CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    approve = subparsers.add_parser("approve")
    approve.add_argument("candidate_fingerprint")
    approve.add_argument("--operator", required=True)
    approve.add_argument("--ack-demo-only", action="store_true")
    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--operator", required=True)
    revoke.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "approve":
        result = approve_shadow_score_canary(
            candidate_fingerprint=args.candidate_fingerprint,
            operator=args.operator,
            acknowledge_demo_only=args.ack_demo_only,
        )
    elif args.command == "revoke":
        result = revoke_shadow_score_canary(operator=args.operator, reason=args.reason)
    else:
        result = read_shadow_score_canary_state()
    if args.command in {"approve", "revoke"}:
        try:
            from . import journal
        except ImportError:  # pragma: no cover - direct script fallback
            import journal  # type: ignore
        journal.append_decision(
            f"shadow_score_canary_controller_{args.command}d",
            result,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
