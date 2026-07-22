"""Tests for review-only continuous-conflict V2 candidate staging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shadow_score_review_controller import (
    read_shadow_score_review_state,
    run_shadow_score_review_controller,
)


POLICY_PATH = Path("trading/config/decision_policy.json")


class FakeJournal:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)
        self.events: list[tuple[str, dict[str, Any]]] = []

    def read_shadow_outcomes(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def append_decision(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))


class FakeEvaluator:
    def __init__(self, candidates: list[tuple[float, float]]) -> None:
        self.candidates = list(candidates)
        self.calls: list[dict[str, Any]] = []
        self.eligible = True

    def __call__(self, rows, **kwargs) -> dict[str, Any]:
        self.calls.append({"rows": len(rows), **kwargs})
        index = min(len(self.calls) - 1, len(self.candidates) - 1)
        strong, gray = self.candidates[index]
        return {
            "shadow_scoring_experiment_evaluation": {
                "continuous_conflict_v2": {
                    "score_coverage": {
                        "valid": len(rows),
                        "total": len(rows),
                    },
                    "threshold_calibration": {
                        "status": "candidate_ready" if self.eligible else "not_eligible",
                        "candidate_thresholds": (
                            {
                                "strong_min_score": strong,
                                "gray_min_score": gray,
                                "active_for_routing": False,
                            }
                            if self.eligible
                            else None
                        ),
                    },
                    "review_eligibility": {
                        "status": (
                            "eligible_for_review" if self.eligible else "not_eligible"
                        ),
                        "eligible": self.eligible,
                        "blocking_reasons": (
                            [] if self.eligible else ["validation_objective_gain"]
                        ),
                    },
                }
            }
        }


def _rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            "shadow_id": f"shadow-v2-{index}",
            "resolved_at": f"2026-01-01T{index // 60:02d}:{index % 60:02d}:00Z",
            "rule_score": 70,
            "r_multiple": 0.5,
            "evaluation_source": "shadow",
            "counterfactual_eligible": True,
            "experimental_scores": {
                "continuous_conflict_v2": {
                    "mode": "shadow_only",
                    "score_version": "continuous_base_and_severity_v2",
                    "score": 75,
                    "active_for_routing": False,
                }
            },
        }
        for index in range(count)
    ]


def _actual_v2_rows() -> list[dict[str, Any]]:
    strategies = (
        "quality_directional",
        "crypto_momentum_breakout",
        "crypto_mean_reversion",
        "crypto_volatility_breakout",
    )
    patterns = (
        (75.0, 85.0, 1.5),
        (55.0, 70.0, 0.6),
        (85.0, 55.0, -1.0),
        (70.0, 65.0, -0.4),
    )
    rows: list[dict[str, Any]] = []
    for index in range(40):
        active_score, experiment_score, outcome = patterns[index % len(patterns)]
        for strategy_id in strategies:
            sequence = len(rows)
            rows.append(
                {
                    "shadow_id": f"actual-v2-{sequence}",
                    "rule_score": active_score,
                    "r_multiple": outcome,
                    "evaluation_source": "shadow",
                    "counterfactual_eligible": True,
                    "counterfactual_score_floor": 0,
                    "symbol": "BTC-USDT-SWAP",
                    "strategy_id": strategy_id,
                    "regime": "TRENDING_UP",
                    "entry_index": sequence,
                    "experimental_scores": {
                        "continuous_conflict_v2": {
                            "mode": "shadow_only",
                            "score_version": "continuous_base_and_severity_v2",
                            "score": experiment_score,
                            "active_for_routing": False,
                        }
                    },
                }
            )
    return rows


def test_unchanged_evidence_cannot_manufacture_review_confirmation(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 60)])

    first = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    repeated = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    confirmed = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )

    assert first["action"] == "staged"
    assert first["candidate"]["confirmations"] == 1
    assert repeated["action"] == "skipped"
    assert repeated["reason"] == "evidence_unchanged"
    assert confirmed["action"] == "review_ready"
    assert confirmed["candidate"]["confirmations"] == 2
    assert len(evaluator.calls) == 2
    assert confirmed["operator_approval_required"] is True
    assert confirmed["operator_approved"] is False
    assert confirmed["active_for_routing"] is False
    assert confirmed["canary_enabled"] is False


def test_real_evaluator_can_stage_then_confirm_review_candidate(
    tmp_path: Path,
) -> None:
    rows = _actual_v2_rows()
    journal = FakeJournal(rows[:120])
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"

    staged = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
    )
    journal.rows.extend(rows[120:140])
    review_ready = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
    )

    assert staged["action"] == "staged"
    assert staged["last_evaluation_status"] == "eligible_for_review"
    assert review_ready["action"] == "review_ready"
    assert review_ready["candidate"]["confirmations"] == 2
    assert review_ready["operator_approved"] is False
    assert review_ready["active_for_routing"] is False


def test_changed_candidate_resets_review_confirmation(tmp_path: Path) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 60), (80, 65)])

    run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    changed = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )

    assert changed["action"] == "staged"
    assert changed["candidate"]["confirmations"] == 1
    assert changed["candidate"]["strong_min_score"] == 80
    assert changed["candidate"]["gray_min_score"] == 65


def test_evidence_confirmation_keeps_advancing_beyond_evaluation_window(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    journal = FakeJournal(_rows(5_000))
    evaluator = FakeEvaluator([(75, 60)])

    staged = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(5_020)[5_000:])
    confirmed = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )

    assert evaluator.calls[0]["rows"] == 5_000
    assert evaluator.calls[1]["rows"] == 5_000
    assert staged["last_evaluated_eligible_records"] == 5_000
    assert confirmed["last_evaluated_eligible_records"] == 5_020
    assert confirmed["action"] == "review_ready"


def test_loss_of_readiness_invalidates_staged_candidate(tmp_path: Path) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 60)])
    run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    evaluator.eligible = False
    journal.rows.extend(_rows(140)[120:])

    invalidated = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )

    assert invalidated["action"] == "invalidated"
    assert invalidated["status"] == "invalidated"
    assert invalidated["candidate"] is None
    assert invalidated["active_for_routing"] is False


def test_non_demo_adapter_never_evaluates_or_writes_review_state(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    evaluator = FakeEvaluator([(75, 60)])

    result = run_shadow_score_review_controller(
        journal_module=FakeJournal(_rows(120)),
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_live",
        evaluator=evaluator,
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "non_demo_execution_adapter"
    assert evaluator.calls == []
    assert not state_path.exists()


def test_corrupt_review_state_is_reported_without_overwrite(tmp_path: Path) -> None:
    state_path = tmp_path / "continuous_conflict_v2_review_state.json"
    state_path.write_text("{broken", encoding="utf-8")
    journal = FakeJournal(_rows(120))

    result = run_shadow_score_review_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=FakeEvaluator([(75, 60)]),
    )
    status = read_shadow_score_review_state(
        policy_path=POLICY_PATH,
        state_path=state_path,
    )

    assert result["action"] == "error"
    assert status["status"] == "error"
    assert status["operator_approved"] is False
    assert status["active_for_routing"] is False
    assert state_path.read_text(encoding="utf-8") == "{broken"
