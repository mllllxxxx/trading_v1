from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.export_json_schemas import build_artifacts, check_artifacts
from schemas.json_schema import GENERATED_NOTICE
from schemas.models import (
    SchemaValidationError,
    SignalDirection,
    TradeAction,
    validate_signal_candidate,
    validate_trade_decision_ticket,
)


def _rulebook_ids() -> tuple[set[str], set[str]]:
    rule_index_path = Path("trading/rulebook/compiled/rule_index.json")
    data = json.loads(rule_index_path.read_text(encoding="utf-8"))
    rules = data["rules"]
    known_rule_ids = set(rules)
    known_playbook_ids = {
        rule_id for rule_id, meta in rules.items() if meta["category"] == "playbooks"
    }
    return known_rule_ids, known_playbook_ids


def _valid_open_ticket() -> dict:
    return {
        "decision_id": "dec-001",
        "timestamp_utc": "2026-06-29T00:00:00Z",
        "action": "OPEN_LONG",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
        "rule_citations": ["HARD_RISK_001", "HARD_DATA_001", "SOFT_REGIME_001"],
        "thesis": "Trend is aligned after a pullback.",
        "entry_plan": {
            "order_type": "limit",
            "entry_reference": "retest near EMA area",
            "chase_market": False,
        },
        "risk_plan": {
            "risk_pct_equity": 0.5,
            "stop_logic": "below recent swing low",
            "take_profit_logic": "partial at 2R and trail",
        },
        "invalidation_conditions": ["close below EMA50", "data quality drops to C"],
        "confidence": 0.72,
        "data_quality": "A",
        "reasoning_summary": "Trend continuation fits rulebook context.",
    }


def _valid_signal_candidate() -> dict:
    return {
        "signal_id": "sig-001",
        "generated_at": "2026-06-30T00:00:00Z",
        "source": "berkshire_crypto_scanner",
        "market": "crypto",
        "symbol": "BTC-USDT",
        "timeframe": "24h_ticker",
        "direction": "long",
        "status": "strong_candidate",
        "confidence": 0.82,
        "score": 82,
        "grade": "A",
        "action_hint": "OPEN_LONG",
        "mode": "signal_only",
        "time_horizon": "swing_2d_7d",
        "promotion_gate": "eligible_for_draft_ticket",
        "confidence_components": {
            "momentum": 0.8,
            "liquidity": 1.0,
            "spread": 0.9,
            "range": 0.7,
            "evidence": 1.0,
            "final": 0.82,
        },
        "reasons": ["Momentum and liquidity pass the first screen."],
        "blockers": [],
        "entry_zone": "100.0000 - 101.0000",
        "invalidation": "98.0000",
        "target_zone": "106.0000",
        "risk_reward": "2.0000",
        "last_price": "100.5000",
        "llm_context": {"role": "advisory_signal_context"},
        "evidence": {"provider_source": "okx_public_tickers"},
    }


def test_valid_signal_candidate_passes() -> None:
    signal = validate_signal_candidate(_valid_signal_candidate())

    assert signal.direction is SignalDirection.LONG
    assert signal.action_hint is TradeAction.OPEN_LONG
    assert signal.promotion_gate == "eligible_for_draft_ticket"
    assert signal.confidence_components["final"] == 0.82


def test_candidate_signal_requires_directional_action_hint() -> None:
    payload = _valid_signal_candidate()
    payload["action_hint"] = "HOLD"

    with pytest.raises(SchemaValidationError, match="action_hint"):
        validate_signal_candidate(payload)


def test_blocked_signal_may_request_more_data() -> None:
    payload = _valid_signal_candidate()
    payload.update(
        {
            "direction": "neutral",
            "status": "blocked",
            "grade": "D",
            "confidence": 0.0,
            "score": 0,
            "action_hint": "REQUEST_MORE_DATA",
            "promotion_gate": "blocked_missing_evidence",
            "blockers": ["ticker_missing"],
            "reasons": ["Provider evidence is missing."],
        }
    )

    signal = validate_signal_candidate(payload)

    assert signal.action_hint is TradeAction.REQUEST_MORE_DATA


def test_valid_open_long_ticket_passes_with_known_ids() -> None:
    known_rules, known_playbooks = _rulebook_ids()
    ticket = validate_trade_decision_ticket(
        _valid_open_ticket(),
        known_rule_ids=known_rules,
        known_playbook_ids=known_playbooks,
    )
    assert ticket.action is TradeAction.OPEN_LONG
    assert ticket.playbook_id == "PB_CRYPTO_TREND_CONTINUATION_001"
    assert ticket.risk_plan is not None
    assert ticket.entry_plan is not None


def test_trade_decision_ticket_profile_compliance_fields_are_optional() -> None:
    old_style = validate_trade_decision_ticket(_valid_open_ticket())
    assert old_style.profile_compliance_score is None
    assert old_style.profile_compliance_flags == []

    payload = _valid_open_ticket()
    payload["profile_compliance_score"] = 0.67
    payload["profile_compliance_summary"] = "Setup fits the team skill profile."
    payload["profile_compliance_flags"] = ["no_late_chase"]

    ticket = validate_trade_decision_ticket(payload)

    assert ticket.profile_compliance_score == 0.67
    assert ticket.profile_compliance_summary == "Setup fits the team skill profile."
    assert ticket.profile_compliance_flags == ["no_late_chase"]


def test_hold_ticket_may_omit_playbook_and_risk_plan() -> None:
    payload = {
        "decision_id": "dec-hold",
        "timestamp_utc": "2026-06-29T00:00:00Z",
        "action": "HOLD",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "playbook_id": None,
        "rule_citations": [],
        "thesis": "No clean playbook fit.",
        "confidence": 0.2,
        "data_quality": "UNKNOWN",
        "reasoning_summary": "Holding because setup is unclear.",
    }
    ticket = validate_trade_decision_ticket(payload)
    assert ticket.action is TradeAction.HOLD
    assert ticket.risk_plan is None


def test_unknown_action_fails() -> None:
    payload = _valid_open_ticket()
    payload["action"] = "BUY_NOW"
    with pytest.raises(SchemaValidationError, match="action must be one of"):
        validate_trade_decision_ticket(payload)


def test_confidence_out_of_range_fails() -> None:
    payload = _valid_open_ticket()
    payload["confidence"] = 1.5
    with pytest.raises(SchemaValidationError, match="confidence"):
        validate_trade_decision_ticket(payload)


def test_invalid_data_quality_fails() -> None:
    payload = _valid_open_ticket()
    payload["data_quality"] = "D"
    with pytest.raises(SchemaValidationError, match="data_quality"):
        validate_trade_decision_ticket(payload)


def test_non_hold_without_playbook_fails() -> None:
    payload = _valid_open_ticket()
    payload["playbook_id"] = None
    with pytest.raises(SchemaValidationError, match="playbook_id"):
        validate_trade_decision_ticket(payload)


def test_non_hold_without_hard_rule_fails() -> None:
    payload = _valid_open_ticket()
    payload["rule_citations"] = ["SOFT_REGIME_001"]
    with pytest.raises(SchemaValidationError, match="HARD_"):
        validate_trade_decision_ticket(payload)


def test_non_hold_without_risk_plan_fails() -> None:
    payload = _valid_open_ticket()
    payload["risk_plan"] = None
    with pytest.raises(SchemaValidationError, match="risk_plan"):
        validate_trade_decision_ticket(payload)


def test_hallucinated_rule_id_fails() -> None:
    known_rules, known_playbooks = _rulebook_ids()
    payload = _valid_open_ticket()
    payload["rule_citations"] = ["HARD_FAKE_999"]
    with pytest.raises(SchemaValidationError, match="unknown rule"):
        validate_trade_decision_ticket(
            payload,
            known_rule_ids=known_rules,
            known_playbook_ids=known_playbooks,
        )


def test_unknown_playbook_id_fails() -> None:
    known_rules, known_playbooks = _rulebook_ids()
    payload = _valid_open_ticket()
    payload["playbook_id"] = "PB_FAKE_999"
    with pytest.raises(SchemaValidationError, match="unknown playbook"):
        validate_trade_decision_ticket(
            payload,
            known_rule_ids=known_rules,
            known_playbook_ids=known_playbooks,
        )


def test_json_schema_artifacts_are_fresh() -> None:
    assert check_artifacts(build_artifacts()) == []


def test_json_schema_artifacts_have_generated_marker() -> None:
    schema_dir = Path("trading/schemas")
    for path in schema_dir.glob("*.schema.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["_generated_notice"] == GENERATED_NOTICE
