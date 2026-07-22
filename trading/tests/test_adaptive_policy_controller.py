"""Tests for guarded demo adaptive-policy staging and rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adaptive_hybrid import load_effective_decision_policy
from adaptive_policy_controller import read_controller_state, run_adaptive_policy_controller


POLICY_PATH = Path("trading/config/decision_policy.json")


class FakeJournal:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.events: list[tuple[str, dict[str, Any]]] = []

    def read_shadow_outcomes(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = list(self.rows)
        return rows[-limit:] if limit is not None else rows

    def append_decision(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, dict(payload)))


class FakeEvaluator:
    def __init__(self, recommendations: list[tuple[float, float]]) -> None:
        self.recommendations = list(recommendations)
        self.calls: list[dict[str, Any]] = []
        self.degraded = False
        self.review_health = "healthy"

    def __call__(self, rows, **kwargs) -> dict[str, Any]:
        self.calls.append({"rows": len(rows), **kwargs})
        index = min(len(self.calls) - 1, len(self.recommendations) - 1)
        strong, gray = self.recommendations[index]
        lower_bound = -0.2 if self.degraded else 0.2
        return {
            "status": "ready",
            "eligible_records": len(rows),
            "excluded_records": 0,
            "insufficiency_reasons": [],
            "recommended_thresholds": {
                "strong_min_score": strong,
                "gray_min_score": gray,
                "changed_from_current": True,
                "objective_gain_vs_current": 0.25,
                "validation_delta_vs_current": 0.10,
                "eligible_for_guarded_demo_controller": True,
            },
            "llm_review_health": {"status": self.review_health},
            "evidence_coverage": {
                "eligible_by_strategy": {
                    "quality_directional": 30,
                    "crypto_momentum_breakout": 30,
                    "crypto_mean_reversion": 30,
                    "crypto_volatility_breakout": 30,
                }
            },
            "current_policy_validation_metrics": {
                "strong": {
                    "n": 12,
                    "average_r_lower_bound_90": lower_bound,
                    "profit_factor": 1.5,
                    "gross_profit_r": 12.0,
                    "gross_loss_r": 8.0,
                }
            },
        }


def _rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            "shadow_id": f"shadow-{index}",
            "resolved_at": f"2026-01-01T00:{index % 60:02d}:00Z",
            "rule_score": 70,
            "r_multiple": 0.5,
            "counterfactual_eligible": True,
        }
        for index in range(count)
    ]


def _actual_evaluation_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(40):
        for score, outcome in (
            (88 + index % 5, 1.4 if index % 4 else -1.0),
            (68 + index % 8, 0.7 if index % 2 else -0.6),
            (45 + index % 10, -0.8 if index % 3 else 0.3),
        ):
            sequence = len(rows)
            rows.append(
                {
                    "shadow_id": f"actual-{sequence}",
                    "rule_score": score,
                    "r_multiple": outcome,
                    "evaluation_source": "shadow",
                    "counterfactual_eligible": True,
                    "symbol": "BTC-USDT-SWAP",
                    "strategy_id": "momentum",
                    "regime": "trending_up",
                    "entry_index": sequence,
                }
            )
    return rows


def test_same_candidate_requires_new_evidence_before_activation(tmp_path: Path) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(70, 50)])

    first = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    repeated = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    confirmed = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )

    assert first["action"] == "staged"
    assert first["staged_candidate"]["zones"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 55.0,
    }
    assert repeated["action"] == "skipped"
    assert repeated["reason"] == "evidence_unchanged"
    assert len(evaluator.calls) == 2
    assert confirmed["action"] == "activated"
    assert confirmed["revision"] == 1
    assert confirmed["active_zones"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 55.0,
    }
    effective = load_effective_decision_policy(
        POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
    )
    assert effective.policy_source == "runtime_override"
    assert effective.policy_revision == 1
    assert (effective.strong_min_score, effective.gray_min_score) == (75.0, 55.0)


def test_real_evaluator_path_keeps_best_current_policy_without_external_calls(
    tmp_path: Path,
) -> None:
    journal = FakeJournal(_actual_evaluation_rows())

    result = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=tmp_path / "adaptive_policy_state.json",
        execution_adapter="okx_demo",
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "current_policy_remains_best"
    assert result["last_evidence"]["status"] == "ready"
    assert result["last_evidence"]["eligible_records"] == 120


def test_changed_candidate_resets_confirmation(tmp_path: Path) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 55), (85, 65)])

    first = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    changed = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )

    assert first["action"] == "staged"
    assert changed["action"] == "staged"
    assert changed["revision"] == 0
    assert changed["staged_candidate"]["confirmations"] == 1
    assert changed["staged_candidate"]["zones"] == {
        "strong_min_score": 85.0,
        "gray_min_score": 65.0,
    }


def test_non_demo_adapter_never_evaluates_or_writes_state(tmp_path: Path) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 55)])

    result = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_live",
        evaluator=evaluator,
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "non_demo_execution_adapter"
    assert evaluator.calls == []
    assert not state_path.exists()


def test_unhealthy_llm_review_blocks_gray_expansion_but_not_contraction(
    tmp_path: Path,
) -> None:
    journal = FakeJournal(_rows(120))
    expansion_evaluator = FakeEvaluator([(75, 55)])
    expansion_evaluator.review_health = "degraded"

    expansion = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=tmp_path / "expansion.json",
        execution_adapter="paper",
        evaluator=expansion_evaluator,
    )
    contraction_evaluator = FakeEvaluator([(75, 65)])
    contraction_evaluator.review_health = "degraded"
    contraction = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=tmp_path / "contraction.json",
        execution_adapter="paper",
        evaluator=contraction_evaluator,
    )

    assert expansion["action"] == "skipped"
    assert expansion["reason"] == "llm_review_health_not_healthy_for_gray_expansion"
    assert expansion["staged_candidate"] is None
    assert contraction["action"] == "staged"
    assert contraction["staged_candidate"]["zones"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 65.0,
    }


def test_global_candidate_waits_for_every_enabled_strategy(tmp_path: Path) -> None:
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(75, 65)])
    original_call = evaluator.__call__

    def sparse_report(rows, **kwargs):
        report = original_call(rows, **kwargs)
        report["evidence_coverage"]["eligible_by_strategy"][
            "crypto_volatility_breakout"
        ] = 19
        return report

    result = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=tmp_path / "adaptive_policy_state.json",
        execution_adapter="paper",
        evaluator=sparse_report,
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "strategy_evidence_coverage_insufficient"
    assert result["staged_candidate"] is None
    assert result["strategy_coverage_failures"] == [
        {
            "team_id": "volatility_breakout",
            "strategy_id": "crypto_volatility_breakout",
            "eligible_records": 19,
            "minimum_records": 20,
        }
    ]


def test_corrupt_state_falls_back_to_canonical_and_is_not_overwritten(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    state_path.write_text("{broken", encoding="utf-8")
    journal = FakeJournal(_rows(120))

    effective = load_effective_decision_policy(
        POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
    )
    result = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=FakeEvaluator([(75, 55)]),
    )

    assert effective.policy_source == "canonical_state_fallback"
    assert effective.policy_state_error
    assert (effective.strong_min_score, effective.gray_min_score) == (80.0, 60.0)
    assert result["action"] == "error"
    assert state_path.read_text(encoding="utf-8") == "{broken"


def test_revision_zero_cannot_smuggle_runtime_override(tmp_path: Path) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "adaptive_policy_state.v1",
                "mode": "demo_auto",
                "revision": 0,
                "canonical_zones": {
                    "strong_min_score": 80,
                    "gray_min_score": 60,
                },
                "active_zones": {
                    "strong_min_score": 75,
                    "gray_min_score": 55,
                },
            }
        ),
        encoding="utf-8",
    )

    effective = load_effective_decision_policy(
        POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
    )

    assert effective.policy_source == "canonical_state_fallback"
    assert "revision zero" in str(effective.policy_state_error)
    assert (effective.strong_min_score, effective.gray_min_score) == (80.0, 60.0)


def test_degraded_post_activation_validation_rolls_back(tmp_path: Path) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(70, 50)])

    run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    activated = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )
    evaluator.degraded = True
    journal.rows.extend(_rows(160)[140:])
    rolled_back = run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="okx_demo",
        evaluator=evaluator,
    )

    assert activated["action"] == "activated"
    assert rolled_back["action"] == "rolled_back"
    assert rolled_back["reason"] == "validation_strong_confidence_degraded"
    assert rolled_back["revision"] == 2
    assert rolled_back["active_zones"] == {
        "strong_min_score": 80.0,
        "gray_min_score": 60.0,
    }
    assert rolled_back["previous_zones"] is None


def test_disabled_controller_status_reports_canonical_effective_zones(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "adaptive_policy_state.json"
    journal = FakeJournal(_rows(120))
    evaluator = FakeEvaluator([(70, 50)])
    run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    journal.rows.extend(_rows(140)[120:])
    run_adaptive_policy_controller(
        journal_module=journal,
        policy_path=POLICY_PATH,
        state_path=state_path,
        execution_adapter="paper",
        evaluator=evaluator,
    )
    monkeypatch.setenv("AUTO_ADAPTIVE_CONTROLLER_ENABLED", "false")

    status = read_controller_state(policy_path=POLICY_PATH, state_path=state_path)

    assert status["effective_source"] == "canonical_controller_disabled"
    assert status["active_zones"] == {
        "strong_min_score": 80.0,
        "gray_min_score": 60.0,
    }
    assert status["persisted_active_zones"] == {
        "strong_min_score": 75.0,
        "gray_min_score": 55.0,
    }
