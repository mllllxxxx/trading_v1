"""Tests for the bounded continuous-conflict V2 demo canary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from adaptive_hybrid import load_decision_policy
from shadow_score_canary import (
    ShadowScoreCanaryError,
    apply_canary_signal,
    approve_shadow_score_canary,
    evaluate_canary_signal,
    revoke_shadow_score_canary,
    run_shadow_score_canary_controller,
    stable_allocation_bucket,
)


class _Journal:
    def __init__(self, closed: list[dict[str, Any]] | None = None) -> None:
        self.closed = closed or []
        self.decisions: list[tuple[str, dict[str, Any]]] = []

    def read_closed_trades(self) -> list[dict[str, Any]]:
        return self.closed

    def append_decision(self, event: str, payload: dict[str, Any]) -> None:
        self.decisions.append((event, payload))


def _contract_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_review(path: Path, *, fingerprint: str | None = None) -> str:
    policy = load_decision_policy()
    experiment = policy.shadow_scoring_experiment
    assert experiment is not None
    contract_fingerprint = _contract_fingerprint(experiment.to_dict())
    selected_fingerprint = fingerprint or _contract_fingerprint(
        {
            "score_version": experiment.score_version,
            "contract_fingerprint": contract_fingerprint,
            "strong_min_score": 76.0,
            "gray_min_score": 54.0,
        }
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": "continuous_conflict_v2_review_state.v1",
                "status": "review_ready",
                "score_version": experiment.score_version,
                "contract_fingerprint": contract_fingerprint,
                "candidate": {
                    "fingerprint": selected_fingerprint,
                    "strong_min_score": 76.0,
                    "gray_min_score": 54.0,
                },
            }
        ),
        encoding="utf-8",
    )
    return selected_fingerprint


def _signal(*, v1: float = 48.0, v2: float = 80.0) -> dict[str, Any]:
    return {
        "signal_id": "sig-1",
        "symbol": "BTC-USDT",
        "direction": "long",
        "status": "watchlist",
        "signal": "watchlist",
        "action_hint": "OPEN_LONG",
        "promotion_gate": "research_only_or_request_more_data",
        "score": int(v1),
        "rule_score": v1,
        "target_risk_pct_equity": 0.01,
        "blockers": [],
        "hard_blockers": [],
        "evidence": {"setup_quality": {"rule_score": v1, "hard_blockers": []}},
        "llm_context": {},
        "experimental_scores": {
            "continuous_conflict_v2": {
                "mode": "shadow_only",
                "score_version": "continuous_base_and_severity_v2",
                "score": v2,
                "active_for_routing": False,
            }
        },
    }


def test_approval_requires_exact_review_candidate_and_demo_ack(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)

    with pytest.raises(ShadowScoreCanaryError, match="acknowledgement"):
        approve_shadow_score_canary(
            candidate_fingerprint=fingerprint,
            operator="Ben",
            acknowledge_demo_only=False,
            review_state_path=review_path,
            canary_state_path=state_path,
        )
    with pytest.raises(ShadowScoreCanaryError, match="exact canonical"):
        approve_shadow_score_canary(
            candidate_fingerprint="wrong",
            operator="Ben",
            acknowledge_demo_only=True,
            review_state_path=review_path,
            canary_state_path=state_path,
        )
    with pytest.raises(ShadowScoreCanaryError, match="demo adapter"):
        approve_shadow_score_canary(
            candidate_fingerprint=fingerprint,
            operator="Ben",
            acknowledge_demo_only=True,
            review_state_path=review_path,
            canary_state_path=state_path,
            execution_adapter="live",
        )
    assert not state_path.exists()


def test_approval_route_transform_and_revoke_are_attributable(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)
    approved = approve_shadow_score_canary(
        candidate_fingerprint=fingerprint,
        operator="Ben",
        acknowledge_demo_only=True,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )
    assert approved["routing_enabled"] is True
    selected_state = {**approved, "allocation_rate": 1.0}
    decision = evaluate_canary_signal(
        _signal(),
        policy=load_decision_policy(),
        canary_state=selected_state,
    )
    assert decision.selected is True
    assert (decision.v1_zone, decision.v2_zone) == ("reject", "strong")
    transformed = apply_canary_signal(_signal(), decision)
    assert transformed["status"] == "strong_candidate"
    assert transformed["target_risk_pct_equity"] == pytest.approx(0.005)
    assert transformed["llm_context"]["routing_experiment"]["approval_id"]
    signal_without_risk = _signal()
    signal_without_risk.pop("target_risk_pct_equity")
    transformed_without_risk = apply_canary_signal(signal_without_risk, decision)
    assert transformed_without_risk["target_risk_pct_equity"] == pytest.approx(0.005)

    revoked = revoke_shadow_score_canary(
        operator="Ben",
        reason="operator stop",
        canary_state_path=state_path,
    )
    assert revoked["status"] == "revoked"
    assert revoked["routing_enabled"] is False


def test_stable_bucket_and_v2_reject_veto() -> None:
    signal = _signal(v1=80.0, v2=20.0)
    first = stable_allocation_bucket(candidate_fingerprint="candidate-1", signal=signal)
    second = stable_allocation_bucket(candidate_fingerprint="candidate-1", signal=signal)
    assert first == second
    state = {
        "routing_enabled": True,
        "approval_id": "approval-1",
        "candidate_fingerprint": "candidate-1",
        "score_version": "continuous_base_and_severity_v2",
        "candidate_thresholds": {"strong_min_score": 76.0, "gray_min_score": 54.0},
        "allocation_rate": 1.0,
        "risk_multiplier": 0.5,
    }
    decision = evaluate_canary_signal(signal, policy=load_decision_policy(), canary_state=state)
    assert decision.selected is True
    assert (decision.v1_zone, decision.v2_zone) == ("strong", "reject")


def test_controller_rolls_back_after_twelve_losing_trades(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)
    approved = approve_shadow_score_canary(
        candidate_fingerprint=fingerprint,
        operator="Ben",
        acknowledge_demo_only=True,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )
    approval_id = approved["approval_id"]
    journal = _Journal(
        [
            {
                "pnl_usd": -1.0,
                "risk_usd": 1.0,
                "routing_experiment": {"approval_id": approval_id},
            }
            for _ in range(12)
        ]
    )
    result = run_shadow_score_canary_controller(
        journal_module=journal,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )
    assert result["status"] == "rolled_back"
    assert result["routing_enabled"] is False
    assert result["rollback_metrics"]["closed_trades"] == 12


def test_controller_rolls_back_when_review_candidate_becomes_stale(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)
    approve_shadow_score_canary(
        candidate_fingerprint=fingerprint,
        operator="Ben",
        acknowledge_demo_only=True,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = "staged"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    result = run_shadow_score_canary_controller(
        journal_module=_Journal(),
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )

    assert result["status"] == "rolled_back"
    assert result["last_reason"] == "review_candidate_is_stale"


def test_controller_rolls_back_when_approval_state_is_tampered(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)
    approve_shadow_score_canary(
        candidate_fingerprint=fingerprint,
        operator="Ben",
        acknowledge_demo_only=True,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["allocation_rate"] = 1.0
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_shadow_score_canary_controller(
        journal_module=_Journal(),
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )

    assert result["status"] == "rolled_back"
    assert result["routing_enabled"] is False
    assert "allocation differs" in result["last_reason"]
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "rolled_back"


def test_controller_rolls_back_before_routing_on_live_adapter(tmp_path: Path) -> None:
    review_path = tmp_path / "review.json"
    state_path = tmp_path / "canary.json"
    fingerprint = _write_review(review_path)
    approve_shadow_score_canary(
        candidate_fingerprint=fingerprint,
        operator="Ben",
        acknowledge_demo_only=True,
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="paper",
    )

    result = run_shadow_score_canary_controller(
        journal_module=_Journal(),
        review_state_path=review_path,
        canary_state_path=state_path,
        execution_adapter="live",
    )

    assert result["status"] == "rolled_back"
    assert result["routing_enabled"] is False
    assert "non-demo adapter" in result["last_reason"]
