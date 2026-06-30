from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain import BrainError, call_trade_decision_ticket, parse_trade_decision_ticket
from schemas.models import TradeAction


def _known_ids() -> tuple[set[str], set[str]]:
    data = json.loads(Path("trading/rulebook/compiled/rule_index.json").read_text(encoding="utf-8"))
    rules = data["rules"]
    playbooks = {rule_id for rule_id, meta in rules.items() if meta["category"] == "playbooks"}
    return set(rules), playbooks


def _open_ticket() -> dict:
    return {
        "decision_id": "dec-ticket-001",
        "timestamp_utc": "2026-06-29T00:00:00Z",
        "action": "OPEN_LONG",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
        "rule_citations": ["HARD_RISK_001", "HARD_LLM_001", "SOFT_REGIME_001"],
        "thesis": "Aligned trend context supports a continuation setup.",
        "entry_plan": {
            "order_type": "limit",
            "entry_reference": "pullback into the reclaimed level",
            "chase_market": False,
        },
        "risk_plan": {
            "risk_pct_equity": 0.5,
            "stop_logic": "below invalidation swing",
            "take_profit_logic": "first target at prior high and trail remainder",
        },
        "invalidation_conditions": ["trend flips mixed", "data quality drops"],
        "confidence": 0.74,
        "data_quality": "A",
        "reasoning_summary": "Rule citations and playbook fit the retrieved context.",
    }


def test_parse_trade_decision_ticket_accepts_valid_open_ticket() -> None:
    known_rules, known_playbooks = _known_ids()

    ticket = parse_trade_decision_ticket(
        json.dumps(_open_ticket()),
        known_rule_ids=known_rules,
        known_playbook_ids=known_playbooks,
    )

    assert ticket.action is TradeAction.OPEN_LONG
    assert ticket.playbook_id == "PB_CRYPTO_TREND_CONTINUATION_001"


def test_parse_trade_decision_ticket_accepts_valid_hold_ticket() -> None:
    payload = _open_ticket()
    payload.update(
        {
            "decision_id": "dec-ticket-hold",
            "action": "HOLD",
            "playbook_id": None,
            "rule_citations": [],
            "entry_plan": None,
            "risk_plan": None,
            "invalidation_conditions": [],
            "confidence": 0.2,
            "data_quality": "UNKNOWN",
            "reasoning_summary": "No clean playbook fit in the retrieved context.",
        }
    )

    ticket = parse_trade_decision_ticket(payload)

    assert ticket.action is TradeAction.HOLD
    assert ticket.risk_plan is None


def test_parse_trade_decision_ticket_rejects_invalid_json() -> None:
    with pytest.raises(BrainError, match="JSON"):
        parse_trade_decision_ticket("not-json")


def test_parse_trade_decision_ticket_rejects_hallucinated_rule_id() -> None:
    known_rules, known_playbooks = _known_ids()
    payload = _open_ticket()
    payload["rule_citations"] = ["HARD_FAKE_999"]

    with pytest.raises(BrainError, match="unknown rule"):
        parse_trade_decision_ticket(
            payload,
            known_rule_ids=known_rules,
            known_playbook_ids=known_playbooks,
        )


def test_parse_trade_decision_ticket_rejects_missing_non_hold_risk_plan() -> None:
    payload = _open_ticket()
    payload["risk_plan"] = None

    with pytest.raises(BrainError, match="risk_plan"):
        parse_trade_decision_ticket(payload)


def test_call_trade_decision_ticket_uses_client_and_validates() -> None:
    known_rules, known_playbooks = _known_ids()

    def fake_client(messages: list[dict[str, str]]) -> dict:
        assert messages[0]["role"] == "system"
        return _open_ticket()

    ticket = call_trade_decision_ticket(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        known_rule_ids=known_rules,
        known_playbook_ids=known_playbooks,
        client=fake_client,
    )

    assert ticket.action is TradeAction.OPEN_LONG
