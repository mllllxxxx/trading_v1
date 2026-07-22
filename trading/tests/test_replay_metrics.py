from __future__ import annotations

import json

from replay.metrics import compute_replay_metrics, write_replay_report
from replay.run_replay import load_replay_records, run_mock_replay
from replay.snapshot import load_snapshot_bundle


def _records() -> list[dict]:
    return [
        {
            "decision_id": "dec-win",
            "ticket_json_valid": True,
            "rule_citations_valid": True,
            "action": "OPEN_LONG",
            "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
            "strategy_id": "crypto_momentum_breakout",
            "regime": "TRENDING_UP",
            "profile_compliance_score": 0.74,
            "decision_lane": "rules_baseline",
            "rule_score": 85,
            "verifier_passed": True,
            "pnl_usd": 120.0,
            "r_multiple": 1.5,
            "decision_stable": True,
        },
        {
            "decision_id": "dec-hold",
            "ticket_json_valid": True,
            "rule_citations_valid": True,
            "action": "HOLD",
            "playbook_id": None,
            "regime": "RANGING",
            "verifier_passed": True,
            "decision_stable": True,
        },
        {
            "decision_id": "dec-reject",
            "ticket_json_valid": False,
            "hallucinated_rule_ids": ["HARD_FAKE_999"],
            "action": "OPEN_SHORT",
            "playbook_id": "PB_CRYPTO_BREAKOUT_PULLBACK_001",
            "strategy_id": "crypto_volatility_breakout",
            "regime": "TRENDING_DOWN",
            "profile_compliance_score": 0.42,
            "decision_lane": "rules_plus_llm",
            "rule_score": 72,
            "verifier_passed": False,
            "verifier_violations": [{"rule_id": "HARD_LLM_001"}],
            "pnl_usd": -40.0,
            "r_multiple": -1.0,
            "decision_stable": False,
        },
    ]


def test_compute_replay_metrics_covers_quality_and_performance() -> None:
    metrics = compute_replay_metrics(_records())

    assert metrics["total_decisions"] == 3
    assert metrics["json_validity_rate"] == 0.6667
    assert metrics["rule_citation_validity_rate"] == 0.6667
    assert metrics["hallucinated_rule_rate"] == 0.3333
    assert metrics["hold_rate"] == 0.3333
    assert metrics["rejected_ticket_rate"] == 0.3333
    assert metrics["verifier_rejection_reasons"] == {"HARD_LLM_001": 1}
    assert metrics["win_rate"] == 0.5
    assert metrics["profit_factor"] == 3.0
    assert metrics["max_drawdown"] == 40.0
    assert metrics["average_r"] == 0.25
    assert metrics["decision_stability"] == 0.6667
    assert metrics["performance_by_playbook"]["PB_CRYPTO_TREND_CONTINUATION_001"]["pnl_usd"] == 120.0
    assert metrics["performance_by_regime"]["TRENDING_DOWN"]["losses"] == 1
    assert metrics["performance_by_strategy_profile"]["crypto_momentum_breakout"]["wins"] == 1
    assert metrics["performance_by_profile_regime"]["crypto_volatility_breakout|TRENDING_DOWN"]["losses"] == 1
    assert metrics["performance_by_decision_lane"]["rules_baseline"]["wins"] == 1
    assert metrics["performance_by_rule_score_bucket"]["80-89"]["pnl_usd"] == 120.0
    assert metrics["performance_by_rule_score_bucket"]["70-79"]["losses"] == 1
    assert metrics["average_profile_compliance_score"] == 0.58
    assert metrics["average_profile_compliance_by_strategy_profile"]["crypto_momentum_breakout"] == 0.74


def test_write_replay_report_outputs_json_and_markdown(tmp_path) -> None:
    metrics = compute_replay_metrics(_records())

    paths = write_replay_report(metrics, tmp_path, run_id="unit_replay")

    assert json.loads((tmp_path / "unit_replay.json").read_text(encoding="utf-8")) == metrics
    assert "# Replay Report: unit_replay" in (tmp_path / "unit_replay.md").read_text(encoding="utf-8")
    assert set(paths) == {"json", "markdown"}


def test_run_mock_replay_is_broker_free_and_writes_report(tmp_path) -> None:
    result = run_mock_replay(_records(), output_dir=tmp_path, run_id="mock")

    assert result["mode"] == "mock"
    assert result["broker_calls"] == 0
    assert result["metrics"]["total_decisions"] == 3
    assert (tmp_path / "mock.json").exists()
    assert (tmp_path / "mock.md").exists()


def test_load_replay_records_supports_json_and_jsonl(tmp_path) -> None:
    json_path = tmp_path / "records.json"
    json_path.write_text(json.dumps(_records()), encoding="utf-8")
    jsonl_path = tmp_path / "records.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(row) for row in _records()), encoding="utf-8")

    assert len(load_replay_records(json_path)) == 3
    assert len(load_replay_records(jsonl_path)) == 3


def test_load_snapshot_bundle_from_explicit_root(tmp_path) -> None:
    day = tmp_path / "2026-06-29"
    day.mkdir()
    (day / "dec-1.ticket.json").write_text(
        json.dumps({"action": "HOLD"}),
        encoding="utf-8",
    )

    bundle = load_snapshot_bundle("dec-1", snapshots_root=tmp_path)

    assert bundle == {"ticket": {"action": "HOLD"}}
