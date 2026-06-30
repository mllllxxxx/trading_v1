from __future__ import annotations

import json

from critic import review_ticket
from market_dossier import build_market_dossier
from rule_retriever import retrieve_rules
from schemas.models import CriticVerdict


def _context() -> tuple[dict, dict]:
    dossier = build_market_dossier(
        symbol="BTC-USDT-SWAP",
        market="crypto",
        timeframe="1h",
        current_price=65000,
        confluence=4,
        regime="TRENDING_UP",
        data_source="okx",
        data_age_s=5,
    ).to_dict()
    return dossier, retrieve_rules(dossier).to_dict()


def _ticket() -> dict:
    return {
        "decision_id": "dec-critic-001",
        "timestamp_utc": "2026-06-29T00:00:00Z",
        "action": "OPEN_LONG",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
        "rule_citations": [
            "HARD_RISK_001",
            "HARD_RISK_002",
            "HARD_RISK_003",
            "HARD_DATA_001",
            "HARD_EXECUTION_001",
            "HARD_LLM_001",
            "HARD_MODE_001",
        ],
        "thesis": "Trend continuation is aligned with dossier context.",
        "entry_plan": {
            "order_type": "limit",
            "entry_reference": "pullback into trend support",
            "chase_market": False,
        },
        "risk_plan": {
            "risk_pct_equity": 0.01,
            "stop_logic": "below recent swing low",
            "take_profit_logic": "target previous impulse high then trail",
        },
        "invalidation_conditions": ["close below trend support"],
        "confidence": 0.72,
        "data_quality": "A",
        "reasoning_summary": "Rulebook context and playbook fit the current trend.",
    }


def test_review_ticket_approves_valid_draft() -> None:
    dossier, rules = _context()

    review = review_ticket(dossier, rules, _ticket())

    assert review.verdict is CriticVerdict.APPROVE
    assert review.suggested_changes["recommended_action"] == "KEEP"


def test_review_ticket_rejects_hard_rule_violation() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["risk_plan"]["risk_pct_equity"] = 0.5

    review = review_ticket(dossier, rules, ticket)

    assert review.verdict is CriticVerdict.REJECT
    assert "HARD_RISK_001" in review.cited_rules
    assert review.suggested_changes["recommended_action"] == "HOLD"


def test_review_ticket_output_is_journal_friendly() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["rule_citations"] = ["HARD_FAKE_999"]

    review = review_ticket(dossier, rules, ticket)
    payload = review.to_dict()

    assert json.loads(json.dumps(payload))["verdict"] == "REJECT"
    assert "position_size_units" not in json.dumps(payload)
    assert "broker_order_id" not in json.dumps(payload)
