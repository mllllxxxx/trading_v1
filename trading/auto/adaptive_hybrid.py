"""Adaptive strong/gray/reject routing for demo trade candidates."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from llm.prompt_builder import build_context_review_prompt
from schemas.models import (
    ContextReviewDecision,
    DataQuality,
    EntryPlan,
    LLMContextReview,
    RiskPlan,
    SignalCandidate,
    TradeAction,
    TradeDecisionTicket,
)

try:
    from . import brain
except ImportError:  # pragma: no cover - direct test/script import fallback
    import brain  # type: ignore


TRADING_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = TRADING_ROOT / "config" / "decision_policy.json"
ADAPTIVE_POLICY_STATE_FILENAME = "adaptive_policy_state.json"
SHADOW_SCORE_REVIEW_STATE_FILENAME = "continuous_conflict_v2_review_state.json"
SHADOW_SCORE_CANARY_STATE_FILENAME = "continuous_conflict_v2_canary_state.json"
DEMO_EXECUTION_ADAPTERS = {"paper", "okx_demo"}
CONTINUOUS_CONFLICT_EXPERIMENT_ID = "continuous_conflict_v2"
CONTINUOUS_CONFLICT_SCORE_VERSION = "continuous_base_and_severity_v2"
CONTINUOUS_CONFLICT_SEVERITY_KEYS = {
    "momentum_adx_below_25",
    "momentum_late_chase_over_0_5_atr",
    "mean_reversion_adx_above_20",
    "breakout_prior_compression_missing",
    "breakout_volume_z_below_1",
    "breakout_retest_distance_over_0_5_atr",
}


class AdaptiveHybridError(RuntimeError):
    """Raised when adaptive routing cannot produce a safe decision."""


@dataclass(frozen=True)
class AdaptiveControllerPolicy:
    """Canonical guardrails for demo-only policy adaptation."""

    mode: str = "observe_only"
    minimum_new_eligible_outcomes: int = 20
    minimum_strategy_eligible_outcomes: int = 20
    strategy_diagnostics_mode: str = "observe_only"
    strategy_diagnostics_minimum_total: int = 80
    strategy_diagnostics_minimum_zone: int = 20
    strategy_diagnostics_minimum_conflict_samples: int = 10
    required_confirmations: int = 2
    max_threshold_step: float = 5.0
    minimum_zone_gap: float = 10.0
    gray_min: float = 50.0
    gray_max: float = 75.0
    strong_min: float = 70.0
    strong_max: float = 90.0
    rollback_minimum_new_eligible_outcomes: int = 20
    rollback_validation_strong_minimum_samples: int = 8
    rollback_validation_average_r_lower_bound_floor: float = 0.0
    rollback_validation_profit_factor_floor: float = 1.0


@dataclass(frozen=True)
class ShadowScoringThresholdCalibrationPolicy:
    """Canonical grid and evidence gates for shadow-only V2 calibration."""

    mode: str
    strong_candidates: tuple[float, ...]
    gray_candidates: tuple[float, ...]
    minimum_total: int
    minimum_complete_zone: int
    minimum_validation_zone: int
    require_full_counterfactual_capture: bool
    max_candidates_reported: int


@dataclass(frozen=True)
class ShadowScoringReviewStagingPolicy:
    """Canonical evidence milestones before a V2 candidate can be reviewed."""

    mode: str
    required_confirmations: int
    minimum_new_eligible_outcomes: int
    allowed_execution_adapters: tuple[str, ...]
    requires_operator_approval: bool


@dataclass(frozen=True)
class ShadowScoringCanaryPolicy:
    """Canonical bounds for an explicitly approved demo-only V2 canary."""

    mode: str
    allowed_execution_adapters: tuple[str, ...]
    allocation_rate: float
    risk_multiplier: float
    max_concurrent_positions: int
    disagreement_only: bool
    rollback_minimum_closed_trades: int
    rollback_average_r_lower_bound_floor: float
    rollback_profit_factor_floor: float
    rollback_cumulative_r_floor: float


@dataclass(frozen=True)
class ShadowScoringReadinessPolicy:
    """Canonical evidence gates before a shadow score can be reviewed."""

    minimum_valid_scores: int
    minimum_score_coverage: float
    minimum_strategy_count: int
    minimum_per_strategy: int
    minimum_strategy_validation_records: int
    minimum_strategy_validation_objective_gain: float
    minimum_calibration_zone: int
    minimum_validation_zone: int
    minimum_calibration_objective_gain: float
    minimum_validation_objective_gain: float
    validation_average_r_lower_bound_floor: float
    validation_profit_factor_floor: float
    minimum_segment_samples: int


@dataclass(frozen=True)
class ShadowScoringExperimentPolicy:
    """Validated observe-only scoring experiment configuration."""

    experiment_id: str
    mode: str
    score_version: str
    active_for_routing: bool
    max_total_penalty: float
    max_penalty_per_conflict: float
    severity_scales: tuple[tuple[str, float], ...]
    threshold_calibration: ShadowScoringThresholdCalibrationPolicy
    review_staging: ShadowScoringReviewStagingPolicy
    canary: ShadowScoringCanaryPolicy
    readiness: ShadowScoringReadinessPolicy

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-safe experiment contract for feature evaluation."""
        return {
            "experiment_id": self.experiment_id,
            "mode": self.mode,
            "score_version": self.score_version,
            "active_for_routing": self.active_for_routing,
            "max_total_penalty": self.max_total_penalty,
            "max_penalty_per_conflict": self.max_penalty_per_conflict,
            "severity_scales": dict(self.severity_scales),
            "threshold_calibration": asdict(self.threshold_calibration),
            "review_staging": asdict(self.review_staging),
            "canary": asdict(self.canary),
            "readiness": asdict(self.readiness),
        }


@dataclass(frozen=True)
class DecisionPolicy:
    """Canonical three-zone routing policy."""

    profile: str
    strong_min_score: float
    gray_min_score: float
    strong_lane: str
    gray_lane: str
    reject_lane: str
    gray_requires_llm: bool
    review_risk_multipliers: tuple[float, ...]
    live_enabled: bool
    llm_review_health_enforcement: str = "observe_only"
    llm_review_health_minimum_reviewed: int = 30
    llm_review_health_minimum_approved: int = 10
    llm_review_health_minimum_declined: int = 10
    llm_review_health_minimum_multiplier_coverage: float = 0.90
    llm_review_health_minimum_segment_reviewed: int = 10
    llm_review_health_confidence_level: float = 0.90
    adaptive_controller: AdaptiveControllerPolicy = field(
        default_factory=AdaptiveControllerPolicy
    )
    shadow_scoring_experiment: ShadowScoringExperimentPolicy | None = None
    policy_source: str = "canonical"
    policy_revision: int = 0
    policy_state_error: str | None = None


@dataclass(frozen=True)
class RuleProposal:
    """Deterministic baseline proposal created before any LLM call."""

    policy_profile: str
    signal_id: str
    symbol: str
    direction: str
    rule_score: float
    score_components: dict[str, float]
    conflicts: list[str]
    hard_blockers: list[str]
    decision_zone: str
    decision_lane: str
    proposed_risk_pct_equity: float
    confidence_calibrated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_decision_policy(path: Path = DEFAULT_POLICY_PATH) -> DecisionPolicy:
    """Load the canonical adaptive policy or fail closed."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        zones = payload["zones"]
        lanes = payload["lanes"]
        profile = str(payload["profile"])
        strong_min = float(zones["strong_min_score"])
        gray_min = float(zones["gray_min_score"])
        multipliers = tuple(float(item) for item in payload["review_risk_multipliers"])
        review_health = payload["llm_review_health"]
        health_enforcement = str(review_health["enforcement"])
        health_minimum_reviewed = int(review_health["minimum_reviewed"])
        health_minimum_approved = int(review_health["minimum_approved"])
        health_minimum_declined = int(review_health["minimum_declined"])
        health_minimum_multiplier_coverage = float(
            review_health["minimum_multiplier_coverage"]
        )
        health_minimum_segment_reviewed = int(review_health["minimum_segment_reviewed"])
        health_confidence_level = float(review_health["confidence_level"])
        controller_payload = payload["adaptive_controller"]
        strategy_diagnostics = controller_payload["strategy_diagnostics"]
        zone_bounds = controller_payload["zone_bounds"]
        rollback = controller_payload["rollback"]
        adaptive_controller = AdaptiveControllerPolicy(
            mode=str(controller_payload["mode"]),
            minimum_new_eligible_outcomes=int(
                controller_payload["minimum_new_eligible_outcomes"]
            ),
            minimum_strategy_eligible_outcomes=int(
                controller_payload["minimum_strategy_eligible_outcomes"]
            ),
            strategy_diagnostics_mode=str(strategy_diagnostics["mode"]),
            strategy_diagnostics_minimum_total=int(
                strategy_diagnostics["minimum_total"]
            ),
            strategy_diagnostics_minimum_zone=int(
                strategy_diagnostics["minimum_zone"]
            ),
            strategy_diagnostics_minimum_conflict_samples=int(
                strategy_diagnostics["minimum_conflict_samples"]
            ),
            required_confirmations=int(controller_payload["required_confirmations"]),
            max_threshold_step=float(controller_payload["max_threshold_step"]),
            minimum_zone_gap=float(controller_payload["minimum_zone_gap"]),
            gray_min=float(zone_bounds["gray_min"]),
            gray_max=float(zone_bounds["gray_max"]),
            strong_min=float(zone_bounds["strong_min"]),
            strong_max=float(zone_bounds["strong_max"]),
            rollback_minimum_new_eligible_outcomes=int(
                rollback["minimum_new_eligible_outcomes"]
            ),
            rollback_validation_strong_minimum_samples=int(
                rollback["validation_strong_minimum_samples"]
            ),
            rollback_validation_average_r_lower_bound_floor=float(
                rollback["validation_average_r_lower_bound_floor"]
            ),
            rollback_validation_profit_factor_floor=float(
                rollback["validation_profit_factor_floor"]
            ),
        )
        experiment_registry = payload["shadow_scoring_experiments"]
        if not isinstance(experiment_registry, Mapping):
            raise TypeError("shadow scoring experiment registry must be an object")
        if set(experiment_registry) != {CONTINUOUS_CONFLICT_EXPERIMENT_ID}:
            raise AdaptiveHybridError("unsupported shadow scoring experiment registry")
        experiment_payload = experiment_registry[CONTINUOUS_CONFLICT_EXPERIMENT_ID]
        if not isinstance(experiment_payload, Mapping):
            raise TypeError("shadow scoring experiment must be an object")
        severity_payload = experiment_payload["severity_scales"]
        if not isinstance(severity_payload, Mapping):
            raise TypeError("shadow scoring severity scales must be an object")
        readiness_payload = experiment_payload["readiness"]
        if not isinstance(readiness_payload, Mapping):
            raise TypeError("shadow scoring readiness must be an object")
        calibration_payload = experiment_payload["threshold_calibration"]
        if not isinstance(calibration_payload, Mapping):
            raise TypeError("shadow scoring threshold calibration must be an object")
        review_staging_payload = experiment_payload["review_staging"]
        if not isinstance(review_staging_payload, Mapping):
            raise TypeError("shadow scoring review staging must be an object")
        canary_payload = experiment_payload["canary"]
        if not isinstance(canary_payload, Mapping):
            raise TypeError("shadow scoring canary must be an object")
        canary_rollback_payload = canary_payload["rollback"]
        if not isinstance(canary_rollback_payload, Mapping):
            raise TypeError("shadow scoring canary rollback must be an object")
        strong_candidates_payload = calibration_payload["strong_candidates"]
        gray_candidates_payload = calibration_payload["gray_candidates"]
        full_capture_payload = calibration_payload[
            "require_full_counterfactual_capture"
        ]
        if not isinstance(strong_candidates_payload, list) or not isinstance(
            gray_candidates_payload, list
        ):
            raise TypeError("shadow scoring threshold grids must be arrays")
        if not isinstance(full_capture_payload, bool):
            raise TypeError("shadow scoring full-capture flag must be a boolean")
        allowed_adapters_payload = review_staging_payload[
            "allowed_execution_adapters"
        ]
        approval_required_payload = review_staging_payload[
            "requires_operator_approval"
        ]
        if not isinstance(allowed_adapters_payload, list):
            raise TypeError("shadow scoring review adapters must be an array")
        if not isinstance(approval_required_payload, bool):
            raise TypeError("shadow scoring review approval flag must be a boolean")
        canary_adapters_payload = canary_payload["allowed_execution_adapters"]
        canary_disagreement_payload = canary_payload["disagreement_only"]
        if not isinstance(canary_adapters_payload, list):
            raise TypeError("shadow scoring canary adapters must be an array")
        if not isinstance(canary_disagreement_payload, bool):
            raise TypeError("shadow scoring canary disagreement flag must be a boolean")
        active_for_routing = experiment_payload["active_for_routing"]
        if not isinstance(active_for_routing, bool):
            raise TypeError("shadow scoring active flag must be a boolean")
        severity_scales = tuple(
            sorted(
                (str(key), float(value))
                for key, value in severity_payload.items()
            )
        )
        shadow_scoring_experiment = ShadowScoringExperimentPolicy(
            experiment_id=CONTINUOUS_CONFLICT_EXPERIMENT_ID,
            mode=str(experiment_payload["mode"]),
            score_version=str(experiment_payload["score_version"]),
            active_for_routing=active_for_routing,
            max_total_penalty=float(experiment_payload["max_total_penalty"]),
            max_penalty_per_conflict=float(
                experiment_payload["max_penalty_per_conflict"]
            ),
            severity_scales=severity_scales,
            threshold_calibration=ShadowScoringThresholdCalibrationPolicy(
                mode=str(calibration_payload["mode"]),
                strong_candidates=tuple(
                    float(item) for item in strong_candidates_payload
                ),
                gray_candidates=tuple(
                    float(item) for item in gray_candidates_payload
                ),
                minimum_total=int(calibration_payload["minimum_total"]),
                minimum_complete_zone=int(
                    calibration_payload["minimum_complete_zone"]
                ),
                minimum_validation_zone=int(
                    calibration_payload["minimum_validation_zone"]
                ),
                require_full_counterfactual_capture=full_capture_payload,
                max_candidates_reported=int(
                    calibration_payload["max_candidates_reported"]
                ),
            ),
            review_staging=ShadowScoringReviewStagingPolicy(
                mode=str(review_staging_payload["mode"]),
                required_confirmations=int(
                    review_staging_payload["required_confirmations"]
                ),
                minimum_new_eligible_outcomes=int(
                    review_staging_payload["minimum_new_eligible_outcomes"]
                ),
                allowed_execution_adapters=tuple(
                    str(item).strip().lower()
                    for item in allowed_adapters_payload
                ),
                requires_operator_approval=approval_required_payload,
            ),
            canary=ShadowScoringCanaryPolicy(
                mode=str(canary_payload["mode"]),
                allowed_execution_adapters=tuple(
                    str(item).strip().lower()
                    for item in canary_adapters_payload
                ),
                allocation_rate=float(canary_payload["allocation_rate"]),
                risk_multiplier=float(canary_payload["risk_multiplier"]),
                max_concurrent_positions=int(
                    canary_payload["max_concurrent_positions"]
                ),
                disagreement_only=canary_disagreement_payload,
                rollback_minimum_closed_trades=int(
                    canary_rollback_payload["minimum_closed_trades"]
                ),
                rollback_average_r_lower_bound_floor=float(
                    canary_rollback_payload["average_r_lower_bound_floor"]
                ),
                rollback_profit_factor_floor=float(
                    canary_rollback_payload["profit_factor_floor"]
                ),
                rollback_cumulative_r_floor=float(
                    canary_rollback_payload["cumulative_r_floor"]
                ),
            ),
            readiness=ShadowScoringReadinessPolicy(
                minimum_valid_scores=int(readiness_payload["minimum_valid_scores"]),
                minimum_score_coverage=float(
                    readiness_payload["minimum_score_coverage"]
                ),
                minimum_strategy_count=int(
                    readiness_payload["minimum_strategy_count"]
                ),
                minimum_per_strategy=int(readiness_payload["minimum_per_strategy"]),
                minimum_strategy_validation_records=int(
                    readiness_payload["minimum_strategy_validation_records"]
                ),
                minimum_strategy_validation_objective_gain=float(
                    readiness_payload[
                        "minimum_strategy_validation_objective_gain"
                    ]
                ),
                minimum_calibration_zone=int(
                    readiness_payload["minimum_calibration_zone"]
                ),
                minimum_validation_zone=int(
                    readiness_payload["minimum_validation_zone"]
                ),
                minimum_calibration_objective_gain=float(
                    readiness_payload["minimum_calibration_objective_gain"]
                ),
                minimum_validation_objective_gain=float(
                    readiness_payload["minimum_validation_objective_gain"]
                ),
                validation_average_r_lower_bound_floor=float(
                    readiness_payload["validation_average_r_lower_bound_floor"]
                ),
                validation_profit_factor_floor=float(
                    readiness_payload["validation_profit_factor_floor"]
                ),
                minimum_segment_samples=int(
                    readiness_payload["minimum_segment_samples"]
                ),
            ),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdaptiveHybridError("canonical decision policy unavailable") from exc
    if profile != "adaptive_hybrid_v1":
        raise AdaptiveHybridError(f"unsupported decision policy profile: {profile}")
    if not 0 <= gray_min < strong_min <= 100:
        raise AdaptiveHybridError("decision zone thresholds are invalid")
    if set(multipliers) != {0.0, 0.5, 1.0}:
        raise AdaptiveHybridError("review risk multipliers must be 0, 0.5, and 1")
    if bool(payload.get("live_enabled", False)):
        raise AdaptiveHybridError("adaptive policy cannot enable live trading")
    if health_enforcement != "observe_only":
        raise AdaptiveHybridError("unsupported LLM review health enforcement")
    if min(health_minimum_reviewed, health_minimum_approved, health_minimum_declined) <= 0:
        raise AdaptiveHybridError("LLM review health sample gates are invalid")
    if health_minimum_approved + health_minimum_declined > health_minimum_reviewed:
        raise AdaptiveHybridError("LLM review health class gates exceed total gate")
    if not 0 < health_minimum_multiplier_coverage <= 1:
        raise AdaptiveHybridError("LLM review health multiplier coverage is invalid")
    if health_minimum_segment_reviewed <= 0:
        raise AdaptiveHybridError("LLM review health segment gate is invalid")
    if health_confidence_level != 0.90:
        raise AdaptiveHybridError("unsupported LLM review health confidence level")
    _validate_controller_policy(adaptive_controller)
    _validate_shadow_scoring_experiment(shadow_scoring_experiment)
    return DecisionPolicy(
        profile=profile,
        strong_min_score=strong_min,
        gray_min_score=gray_min,
        strong_lane=str(lanes["strong"]),
        gray_lane=str(lanes["gray"]),
        reject_lane=str(lanes["reject"]),
        gray_requires_llm=bool(payload.get("gray_requires_llm", True)),
        review_risk_multipliers=multipliers,
        live_enabled=False,
        llm_review_health_enforcement=health_enforcement,
        llm_review_health_minimum_reviewed=health_minimum_reviewed,
        llm_review_health_minimum_approved=health_minimum_approved,
        llm_review_health_minimum_declined=health_minimum_declined,
        llm_review_health_minimum_multiplier_coverage=health_minimum_multiplier_coverage,
        llm_review_health_minimum_segment_reviewed=health_minimum_segment_reviewed,
        llm_review_health_confidence_level=health_confidence_level,
        adaptive_controller=adaptive_controller,
        shadow_scoring_experiment=shadow_scoring_experiment,
    )


def load_effective_decision_policy(
    path: Path = DEFAULT_POLICY_PATH,
    *,
    state_path: Path | None = None,
    execution_adapter: str | None = None,
) -> DecisionPolicy:
    """Overlay a validated demo runtime revision on the canonical policy."""
    canonical = load_decision_policy(path)
    if canonical.adaptive_controller.mode != "demo_auto":
        return canonical
    if not _env_bool("AUTO_ADAPTIVE_CONTROLLER_ENABLED", True):
        return replace(canonical, policy_source="canonical_controller_disabled")
    adapter = str(
        execution_adapter or os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper")
    ).strip().lower()
    if adapter not in DEMO_EXECUTION_ADAPTERS:
        return replace(
            canonical,
            policy_source="canonical_non_demo_adapter",
            policy_state_error=f"unsupported_execution_adapter:{adapter}",
        )
    selected_state_path = state_path or adaptive_policy_state_path()
    if not selected_state_path.exists():
        return canonical
    try:
        state = json.loads(selected_state_path.read_text(encoding="utf-8"))
        if not isinstance(state, Mapping):
            raise ValueError("state payload is not an object")
        if state.get("schema_version") != "adaptive_policy_state.v1":
            raise ValueError("unsupported state schema")
        if str(state.get("mode")) != canonical.adaptive_controller.mode:
            raise ValueError("state mode differs from canonical policy")
        revision = int(state.get("revision", -1))
        if revision < 0:
            raise ValueError("state revision is invalid")
        zones = state.get("active_zones")
        if not isinstance(zones, Mapping):
            raise ValueError("active zones are missing")
        strong_min = float(zones["strong_min_score"])
        gray_min = float(zones["gray_min_score"])
        canonical_zones = state.get("canonical_zones")
        if not isinstance(canonical_zones, Mapping):
            raise ValueError("canonical state zones are missing")
        if (
            float(canonical_zones["strong_min_score"]) != canonical.strong_min_score
            or float(canonical_zones["gray_min_score"]) != canonical.gray_min_score
        ):
            raise ValueError("state canonical zones are stale")
        if revision == 0 and (
            strong_min != canonical.strong_min_score
            or gray_min != canonical.gray_min_score
        ):
            raise ValueError("revision zero cannot override canonical zones")
        _validate_effective_zones(strong_min, gray_min, canonical.adaptive_controller)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return replace(
            canonical,
            policy_source="canonical_state_fallback",
            policy_state_error=str(exc),
        )
    return replace(
        canonical,
        strong_min_score=strong_min,
        gray_min_score=gray_min,
        policy_source="runtime_override" if revision > 0 else "canonical_state",
        policy_revision=revision,
        policy_state_error=None,
    )


def adaptive_policy_state_path() -> Path:
    """Return the persisted demo policy controller state path."""
    return (
        Path(os.getenv("VIBE_TRADING_HOME", "/data"))
        / "journal"
        / ADAPTIVE_POLICY_STATE_FILENAME
    )


def shadow_score_review_state_path() -> Path:
    """Return the persisted review-only V2 candidate state path."""
    return (
        Path(os.getenv("VIBE_TRADING_HOME", "/data"))
        / "journal"
        / SHADOW_SCORE_REVIEW_STATE_FILENAME
    )


def shadow_score_canary_state_path() -> Path:
    """Return the persisted operator-approved V2 canary state path."""
    return (
        Path(os.getenv("VIBE_TRADING_HOME", "/data"))
        / "journal"
        / SHADOW_SCORE_CANARY_STATE_FILENAME
    )


def decision_policy_snapshot(policy: DecisionPolicy) -> dict[str, Any]:
    """Return stable, journal-safe policy evidence for one runtime cycle."""
    return {
        "profile": policy.profile,
        "zones": {
            "strong_min_score": policy.strong_min_score,
            "gray_min_score": policy.gray_min_score,
        },
        "lanes": {
            "strong": policy.strong_lane,
            "gray": policy.gray_lane,
            "reject": policy.reject_lane,
        },
        "gray_requires_llm": policy.gray_requires_llm,
        "review_risk_multipliers": list(policy.review_risk_multipliers),
        "llm_review_health": {
            "enforcement": policy.llm_review_health_enforcement,
            "minimum_reviewed": policy.llm_review_health_minimum_reviewed,
            "minimum_approved": policy.llm_review_health_minimum_approved,
            "minimum_declined": policy.llm_review_health_minimum_declined,
            "minimum_multiplier_coverage": (
                policy.llm_review_health_minimum_multiplier_coverage
            ),
            "minimum_segment_reviewed": policy.llm_review_health_minimum_segment_reviewed,
            "confidence_level": policy.llm_review_health_confidence_level,
        },
        "adaptive_controller": asdict(policy.adaptive_controller),
        "shadow_scoring_experiments": (
            {
                policy.shadow_scoring_experiment.experiment_id: (
                    policy.shadow_scoring_experiment.to_dict()
                )
            }
            if policy.shadow_scoring_experiment is not None
            else {}
        ),
        "runtime": {
            "source": policy.policy_source,
            "revision": policy.policy_revision,
            "state_error": policy.policy_state_error,
        },
        "live_enabled": policy.live_enabled,
    }


def build_rule_proposal(
    signal: Mapping[str, Any] | SignalCandidate,
    *,
    policy: DecisionPolicy | None = None,
) -> RuleProposal:
    """Create a transparent baseline and select its zone before provider I/O."""
    payload = signal.to_dict() if isinstance(signal, SignalCandidate) else dict(signal)
    selected_policy = policy or load_decision_policy()
    evidence = _mapping(payload.get("evidence"))
    setup_quality = _mapping(evidence.get("setup_quality"))
    raw_score = setup_quality.get("rule_score")
    if raw_score is None:
        raw_score = payload.get("rule_score")
    if raw_score is None:
        raw_score = payload.get("score", 0)
    try:
        rule_score = max(0.0, min(100.0, float(raw_score)))
    except (TypeError, ValueError):
        rule_score = 0.0
    score_components = _number_mapping(
        setup_quality.get(
            "score_components",
            payload.get("score_components", payload.get("confidence_components", {})),
        )
    )
    conflicts = _string_list(setup_quality.get("conflicts", evidence.get("conflicts", [])))
    hard_blockers = _string_list(
        setup_quality.get("hard_blockers", payload.get("hard_blockers", payload.get("blockers", [])))
    )
    if hard_blockers or rule_score < selected_policy.gray_min_score:
        zone = "reject"
        lane = selected_policy.reject_lane
    elif rule_score >= selected_policy.strong_min_score:
        zone = "strong"
        lane = selected_policy.strong_lane
    else:
        zone = "gray"
        lane = selected_policy.gray_lane
    risk = _risk_pct(payload.get("target_risk_pct_equity"), default=0.01)
    return RuleProposal(
        policy_profile=selected_policy.profile,
        signal_id=str(payload.get("signal_id") or "unknown-signal"),
        symbol=str(payload.get("symbol") or ""),
        direction=str(payload.get("direction") or "neutral").lower(),
        rule_score=round(rule_score, 4),
        score_components=score_components,
        conflicts=conflicts,
        hard_blockers=hard_blockers,
        decision_zone=zone,
        decision_lane=lane,
        proposed_risk_pct_equity=risk,
    )


class AdaptiveTicketProvider:
    """Callable ticket provider that exposes routing evidence after invocation."""

    def __init__(
        self,
        signal: SignalCandidate,
        *,
        autonomy_mode: str,
        client: brain.TicketClient | None,
        policy: DecisionPolicy | None = None,
    ) -> None:
        self.signal = signal
        self.autonomy_mode = autonomy_mode
        self.client = client
        self.policy = policy or load_decision_policy()
        self.rule_proposal = build_rule_proposal(signal, policy=self.policy)
        self.llm_review: LLMContextReview | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        """Return journal-safe adaptive routing metadata."""
        return {
            "decision_policy": self.policy.profile,
            "decision_lane": self.rule_proposal.decision_lane,
            "rule_proposal": self.rule_proposal.to_dict(),
            "llm_review": self.llm_review.to_dict() if self.llm_review else None,
        }

    def __call__(
        self,
        dossier: dict[str, Any],
        retrieved_rules: dict[str, Any],
    ) -> TradeDecisionTicket:
        proposal = self.rule_proposal
        if proposal.decision_zone == "reject":
            return self._terminal_ticket(
                dossier,
                action=TradeAction.HOLD,
                summary="Deterministic rule proposal is below the reject threshold.",
            )

        risk_multiplier = 1.0
        if proposal.decision_zone == "gray":
            if not self.policy.gray_requires_llm:
                raise AdaptiveHybridError("gray lane is missing required LLM review policy")
            messages = build_context_review_prompt(
                rule_proposal=proposal.to_dict(),
                market_dossier=dossier,
                retrieved_rules=retrieved_rules,
                signal_candidate=self.signal.to_dict(),
                autonomy_mode=self.autonomy_mode,
            )
            self.llm_review = brain.call_llm_context_review(
                messages,
                client=self.client,
                budget_source=_budget_source(self.signal),
            )
            if self.llm_review.decision is ContextReviewDecision.VETO:
                return self._terminal_ticket(
                    dossier,
                    action=TradeAction.HOLD,
                    summary=self.llm_review.reasoning_summary,
                )
            if self.llm_review.decision is ContextReviewDecision.WAIT:
                return self._terminal_ticket(
                    dossier,
                    action=TradeAction.REQUEST_MORE_DATA,
                    summary=self.llm_review.reasoning_summary,
                )
            risk_multiplier = self.llm_review.risk_multiplier

        playbook_id = _select_playbook(self.signal, retrieved_rules)
        if not playbook_id:
            return self._terminal_ticket(
                dossier,
                action=TradeAction.HOLD,
                summary="No retrieved playbook matches the deterministic proposal.",
            )
        citations = _mandatory_hard_rule_ids(retrieved_rules)
        if not citations:
            raise AdaptiveHybridError("retrieved context has no mandatory hard rules")
        direction = self.signal.direction.value
        action = TradeAction.OPEN_LONG if direction == "long" else TradeAction.OPEN_SHORT
        risk_pct = round(proposal.proposed_risk_pct_equity * risk_multiplier, 8)
        score_fraction = round(proposal.rule_score / 100.0, 4)
        return TradeDecisionTicket(
            decision_id=f"adaptive-{self.signal.signal_id}",
            timestamp_utc=_utc_now(),
            action=action,
            market=str(dossier.get("market") or self.signal.market),
            symbol=str(dossier.get("symbol") or self.signal.symbol),
            timeframe=str(dossier.get("timeframe") or self.signal.timeframe),
            playbook_id=playbook_id,
            rule_citations=citations,
            thesis=f"Rule proposal {proposal.rule_score:.1f}/100 qualifies for the {proposal.decision_zone} lane.",
            entry_plan=EntryPlan(
                order_type="limit",
                entry_reference="trusted signal entry zone",
                chase_market=False,
            ),
            risk_plan=RiskPlan(
                risk_pct_equity=risk_pct,
                stop_logic="use deterministic signal invalidation level",
                take_profit_logic="use deterministic signal target level",
            ),
            invalidation_conditions=[
                self.signal.invalidation or "deterministic signal invalidation level breaks"
            ],
            confidence=score_fraction,
            data_quality=_data_quality(dossier.get("data_quality")),
            reasoning_summary=_open_summary(proposal, self.llm_review),
            profile_compliance_score=score_fraction if self.signal.preferred_playbook_ids else None,
            profile_compliance_summary=(
                f"Rule score {proposal.rule_score:.1f}; preferred playbook and team constraints retained."
                if self.signal.preferred_playbook_ids
                else None
            ),
            profile_compliance_flags=list(proposal.conflicts),
        )

    def _terminal_ticket(
        self,
        dossier: Mapping[str, Any],
        *,
        action: TradeAction,
        summary: str,
    ) -> TradeDecisionTicket:
        return TradeDecisionTicket(
            decision_id=f"adaptive-{self.signal.signal_id}",
            timestamp_utc=_utc_now(),
            action=action,
            market=str(dossier.get("market") or self.signal.market),
            symbol=str(dossier.get("symbol") or self.signal.symbol),
            timeframe=str(dossier.get("timeframe") or self.signal.timeframe),
            playbook_id=None,
            rule_citations=[],
            thesis=summary,
            entry_plan=None,
            risk_plan=None,
            invalidation_conditions=[],
            confidence=round(self.rule_proposal.rule_score / 100.0, 4),
            data_quality=_data_quality(dossier.get("data_quality")),
            reasoning_summary=summary,
        )


def build_adaptive_ticket_provider(
    signal: SignalCandidate,
    *,
    autonomy_mode: str = "paper",
    client: brain.TicketClient | None = None,
    policy: DecisionPolicy | None = None,
) -> AdaptiveTicketProvider:
    """Build the default adaptive provider for one signal candidate."""
    return AdaptiveTicketProvider(
        signal,
        autonomy_mode=autonomy_mode,
        client=client,
        policy=policy,
    )


def _select_playbook(signal: SignalCandidate, rules: Mapping[str, Any]) -> str | None:
    candidates = [
        str(item.get("id"))
        for item in rules.get("candidate_playbooks", [])
        if isinstance(item, Mapping) and item.get("id")
    ]
    for preferred in signal.preferred_playbook_ids:
        if preferred in candidates:
            return preferred
    return candidates[0] if candidates else None


def _mandatory_hard_rule_ids(rules: Mapping[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(item.get("id"))
            for item in rules.get("mandatory_hard_rules", [])
            if isinstance(item, Mapping) and str(item.get("id", "")).startswith("HARD_")
        )
    )


def _open_summary(proposal: RuleProposal, review: LLMContextReview | None) -> str:
    if review is None:
        return f"Strong deterministic setup scored {proposal.rule_score:.1f}/100."
    return f"Gray setup scored {proposal.rule_score:.1f}/100; LLM review approved: {review.reasoning_summary}"


def _data_quality(value: Any) -> DataQuality:
    try:
        return DataQuality(str(value).upper())
    except ValueError:
        return DataQuality.UNKNOWN


def _budget_source(signal: SignalCandidate) -> str:
    return str(signal.team_id or signal.source or "adaptive_hybrid")


def _risk_pct(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _validate_controller_policy(policy: AdaptiveControllerPolicy) -> None:
    if policy.mode not in {"observe_only", "demo_auto"}:
        raise AdaptiveHybridError("unsupported adaptive controller mode")
    if policy.minimum_new_eligible_outcomes <= 0:
        raise AdaptiveHybridError("adaptive controller evidence milestone is invalid")
    if policy.minimum_strategy_eligible_outcomes <= 0:
        raise AdaptiveHybridError("adaptive controller strategy coverage gate is invalid")
    if policy.strategy_diagnostics_mode != "observe_only":
        raise AdaptiveHybridError("unsupported strategy diagnostics mode")
    if policy.strategy_diagnostics_minimum_total <= 0:
        raise AdaptiveHybridError("strategy diagnostics total gate is invalid")
    if policy.strategy_diagnostics_minimum_zone <= 0:
        raise AdaptiveHybridError("strategy diagnostics zone gate is invalid")
    if policy.strategy_diagnostics_minimum_conflict_samples <= 1:
        raise AdaptiveHybridError("conflict diagnostics sample gate is invalid")
    if (
        policy.strategy_diagnostics_minimum_zone * 2
        > policy.strategy_diagnostics_minimum_total
    ):
        raise AdaptiveHybridError("strategy diagnostics zone gates exceed total gate")
    if policy.required_confirmations < 2:
        raise AdaptiveHybridError("adaptive controller requires at least two confirmations")
    if policy.max_threshold_step <= 0:
        raise AdaptiveHybridError("adaptive controller threshold step is invalid")
    if policy.minimum_zone_gap <= 0:
        raise AdaptiveHybridError("adaptive controller zone gap is invalid")
    if not 0 <= policy.gray_min < policy.gray_max <= 100:
        raise AdaptiveHybridError("adaptive controller gray bounds are invalid")
    if not 0 <= policy.strong_min < policy.strong_max <= 100:
        raise AdaptiveHybridError("adaptive controller strong bounds are invalid")
    if policy.gray_max + policy.minimum_zone_gap > policy.strong_max:
        raise AdaptiveHybridError("adaptive controller bounds cannot preserve zone gap")
    if policy.rollback_minimum_new_eligible_outcomes <= 0:
        raise AdaptiveHybridError("adaptive controller rollback milestone is invalid")
    if policy.rollback_validation_strong_minimum_samples <= 1:
        raise AdaptiveHybridError("adaptive controller rollback sample gate is invalid")
    if policy.rollback_validation_profit_factor_floor <= 0:
        raise AdaptiveHybridError("adaptive controller rollback profit factor is invalid")


def _validate_shadow_scoring_experiment(
    experiment: ShadowScoringExperimentPolicy,
) -> None:
    if experiment.experiment_id != CONTINUOUS_CONFLICT_EXPERIMENT_ID:
        raise AdaptiveHybridError("unsupported shadow scoring experiment")
    if experiment.mode != "shadow_only":
        raise AdaptiveHybridError("shadow scoring experiment must remain shadow-only")
    if experiment.score_version != CONTINUOUS_CONFLICT_SCORE_VERSION:
        raise AdaptiveHybridError("unsupported shadow scoring score version")
    if experiment.active_for_routing:
        raise AdaptiveHybridError("shadow scoring experiment cannot be active for routing")
    if not 0 < experiment.max_penalty_per_conflict <= experiment.max_total_penalty <= 48:
        raise AdaptiveHybridError("shadow scoring penalty limits are invalid")
    scales = dict(experiment.severity_scales)
    if set(scales) != CONTINUOUS_CONFLICT_SEVERITY_KEYS:
        raise AdaptiveHybridError("shadow scoring severity scales are incomplete")
    if any(value <= 0 for value in scales.values()):
        raise AdaptiveHybridError("shadow scoring severity scales are invalid")
    _validate_shadow_scoring_threshold_calibration(
        experiment.threshold_calibration
    )
    _validate_shadow_scoring_review_staging(experiment.review_staging)
    _validate_shadow_scoring_canary(experiment.canary)
    _validate_shadow_scoring_readiness(experiment.readiness)


def _validate_shadow_scoring_threshold_calibration(
    calibration: ShadowScoringThresholdCalibrationPolicy,
) -> None:
    if calibration.mode != "shadow_only":
        raise AdaptiveHybridError("V2 threshold calibration must remain shadow-only")
    if not calibration.strong_candidates or not calibration.gray_candidates:
        raise AdaptiveHybridError("V2 threshold calibration grid is empty")
    if tuple(sorted(set(calibration.strong_candidates))) != calibration.strong_candidates:
        raise AdaptiveHybridError("V2 strong threshold grid is invalid")
    if tuple(sorted(set(calibration.gray_candidates))) != calibration.gray_candidates:
        raise AdaptiveHybridError("V2 gray threshold grid is invalid")
    if any(
        not math.isfinite(value) or not 0 <= value <= 100
        for value in calibration.strong_candidates + calibration.gray_candidates
    ):
        raise AdaptiveHybridError("V2 threshold calibration grid is out of bounds")
    if not any(
        gray < strong
        for strong in calibration.strong_candidates
        for gray in calibration.gray_candidates
    ):
        raise AdaptiveHybridError("V2 threshold calibration has no valid pair")
    if min(
        calibration.minimum_total,
        calibration.minimum_complete_zone,
        calibration.minimum_validation_zone,
    ) <= 1:
        raise AdaptiveHybridError("V2 threshold calibration sample gates are invalid")
    if calibration.minimum_complete_zone * 2 > calibration.minimum_total:
        raise AdaptiveHybridError("V2 threshold calibration zones exceed total gate")
    if not calibration.require_full_counterfactual_capture:
        raise AdaptiveHybridError("V2 calibration requires full counterfactual capture")
    if not 1 <= calibration.max_candidates_reported <= 10:
        raise AdaptiveHybridError("V2 calibration report limit is invalid")


def _validate_shadow_scoring_review_staging(
    staging: ShadowScoringReviewStagingPolicy,
) -> None:
    if staging.mode != "review_only":
        raise AdaptiveHybridError("V2 review staging must remain review-only")
    if staging.required_confirmations < 2:
        raise AdaptiveHybridError("V2 review staging requires two confirmations")
    if staging.minimum_new_eligible_outcomes <= 0:
        raise AdaptiveHybridError("V2 review staging evidence milestone is invalid")
    if staging.allowed_execution_adapters != ("paper", "okx_demo"):
        raise AdaptiveHybridError("V2 review staging adapters are invalid")
    if not staging.requires_operator_approval:
        raise AdaptiveHybridError("V2 review staging requires operator approval")


def _validate_shadow_scoring_canary(canary: ShadowScoringCanaryPolicy) -> None:
    if canary.mode != "manual_demo":
        raise AdaptiveHybridError("V2 canary must remain manual demo-only")
    if canary.allowed_execution_adapters != ("paper", "okx_demo"):
        raise AdaptiveHybridError("V2 canary adapters are invalid")
    if not 0 < canary.allocation_rate <= 0.20:
        raise AdaptiveHybridError("V2 canary allocation is invalid")
    if not 0 < canary.risk_multiplier <= 0.50:
        raise AdaptiveHybridError("V2 canary risk multiplier is invalid")
    if canary.max_concurrent_positions != 1:
        raise AdaptiveHybridError("V2 canary concurrency limit is invalid")
    if not canary.disagreement_only:
        raise AdaptiveHybridError("V2 canary must remain disagreement-only")
    if canary.rollback_minimum_closed_trades != 12:
        raise AdaptiveHybridError("V2 canary rollback sample gate is invalid")
    if not math.isfinite(canary.rollback_average_r_lower_bound_floor):
        raise AdaptiveHybridError("V2 canary rollback confidence floor is invalid")
    if canary.rollback_average_r_lower_bound_floor < 0:
        raise AdaptiveHybridError("V2 canary rollback confidence floor is too weak")
    if not math.isfinite(canary.rollback_profit_factor_floor):
        raise AdaptiveHybridError("V2 canary rollback profit-factor floor is invalid")
    if canary.rollback_profit_factor_floor < 1.0:
        raise AdaptiveHybridError("V2 canary rollback profit-factor floor is too weak")
    if not math.isfinite(canary.rollback_cumulative_r_floor):
        raise AdaptiveHybridError("V2 canary rollback cumulative-R floor is invalid")
    if not -3.0 <= canary.rollback_cumulative_r_floor < 0:
        raise AdaptiveHybridError("V2 canary rollback cumulative-R floor is too weak")


def _validate_shadow_scoring_readiness(
    readiness: ShadowScoringReadinessPolicy,
) -> None:
    if readiness.minimum_valid_scores <= 0:
        raise AdaptiveHybridError("shadow scoring readiness sample gate is invalid")
    if not 0 < readiness.minimum_score_coverage <= 1:
        raise AdaptiveHybridError("shadow scoring readiness coverage is invalid")
    if min(readiness.minimum_strategy_count, readiness.minimum_per_strategy) <= 0:
        raise AdaptiveHybridError("shadow scoring readiness strategy gates are invalid")
    if not 1 < readiness.minimum_strategy_validation_records <= readiness.minimum_per_strategy:
        raise AdaptiveHybridError(
            "shadow scoring readiness strategy validation gate is invalid"
        )
    if not math.isfinite(readiness.minimum_strategy_validation_objective_gain):
        raise AdaptiveHybridError(
            "shadow scoring readiness strategy validation gain is invalid"
        )
    if (
        readiness.minimum_strategy_count * readiness.minimum_per_strategy
        > readiness.minimum_valid_scores
    ):
        raise AdaptiveHybridError("shadow scoring readiness strategy gates exceed sample gate")
    if min(
        readiness.minimum_calibration_zone,
        readiness.minimum_validation_zone,
        readiness.minimum_segment_samples,
    ) <= 1:
        raise AdaptiveHybridError("shadow scoring readiness robustness gates are invalid")
    if readiness.minimum_calibration_zone * 2 > readiness.minimum_valid_scores:
        raise AdaptiveHybridError("shadow scoring readiness zones exceed sample gate")
    if readiness.minimum_calibration_objective_gain < 0:
        raise AdaptiveHybridError("shadow scoring readiness calibration gain is invalid")
    if readiness.minimum_validation_objective_gain < 0:
        raise AdaptiveHybridError("shadow scoring readiness validation gain is invalid")
    if readiness.validation_profit_factor_floor <= 0:
        raise AdaptiveHybridError("shadow scoring readiness profit factor is invalid")
    if not math.isfinite(readiness.validation_average_r_lower_bound_floor):
        raise AdaptiveHybridError("shadow scoring readiness confidence floor is invalid")


def _validate_effective_zones(
    strong_min: float,
    gray_min: float,
    controller: AdaptiveControllerPolicy,
) -> None:
    if not controller.gray_min <= gray_min <= controller.gray_max:
        raise ValueError("runtime gray threshold is outside canonical bounds")
    if not controller.strong_min <= strong_min <= controller.strong_max:
        raise ValueError("runtime strong threshold is outside canonical bounds")
    if strong_min - gray_min < controller.minimum_zone_gap:
        raise ValueError("runtime thresholds violate the canonical zone gap")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        try:
            result[str(key)] = float(item)
        except (TypeError, ValueError):
            continue
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
