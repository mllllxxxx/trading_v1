from __future__ import annotations

import json
from pathlib import Path

from market_dossier import build_market_dossier
from rule_retriever import retrieve_rules
from verifier.rule_verifier import load_verifier_rules, verify_trade_ticket


def _context(score: float = 4, regime: str = "TRENDING_UP") -> tuple[dict, dict]:
    dossier = build_market_dossier(
        symbol="BTC-USDT-SWAP",
        market="crypto",
        timeframe="1h",
        current_price=65000,
        confluence=score,
        regime=regime,
        data_source="okx",
        data_age_s=5,
    ).to_dict()
    return dossier, retrieve_rules(dossier).to_dict()


def _ticket() -> dict:
    return {
        "decision_id": "dec-verifier-001",
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
            "SOFT_REGIME_001",
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
        "invalidation_conditions": ["close below trend support", "data quality drops"],
        "confidence": 0.72,
        "data_quality": "A",
        "reasoning_summary": "Rulebook context and playbook fit the current trend.",
    }


def _rule_ids(result: object) -> set[str]:
    return {str(item["rule_id"]) for item in result.violations}


def test_load_verifier_rules_reads_generated_hard_rules() -> None:
    rules = load_verifier_rules()

    assert "HARD_RISK_001" in rules
    assert rules["HARD_RISK_001"]["enforcement"]["fields"]["max_position_pct"] == 0.2


def test_verify_trade_ticket_accepts_valid_ticket() -> None:
    dossier, rules = _context()

    result = verify_trade_ticket(_ticket(), dossier, rules)

    assert result.passed is True
    assert "HARD_RISK_001" in result.checked_rule_ids
    assert result.violations == []


def test_verify_trade_ticket_rejects_missing_playbook() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["playbook_id"] = None

    result = verify_trade_ticket(ticket, dossier, rules)

    assert result.passed is False
    assert "HARD_LLM_001" in _rule_ids(result)


def test_verify_trade_ticket_rejects_hallucinated_rule_id() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["rule_citations"] = ["HARD_FAKE_999"]

    result = verify_trade_ticket(ticket, dossier, rules)

    assert result.passed is False
    assert "HARD_LLM_001" in _rule_ids(result)


def test_verify_trade_ticket_rejects_data_quality_c() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["data_quality"] = "C"

    result = verify_trade_ticket(ticket, dossier, rules)

    assert result.passed is False
    assert "HARD_DATA_001" in _rule_ids(result)


def test_verify_trade_ticket_rejects_risk_above_compiled_limit() -> None:
    dossier, rules = _context()
    ticket = _ticket()
    ticket["risk_plan"]["risk_pct_equity"] = 0.5

    result = verify_trade_ticket(ticket, dossier, rules)

    assert result.passed is False
    assert "HARD_RISK_001" in _rule_ids(result)


def test_verify_trade_ticket_rejects_playbook_not_retrieved_for_dossier() -> None:
    dossier, rules = _context(regime="RANGING")
    ticket = _ticket()

    result = verify_trade_ticket(ticket, dossier, rules)

    assert result.passed is False
    assert "HARD_LLM_001" in _rule_ids(result)


def test_verify_trade_ticket_error_fails_closed(tmp_path: Path) -> None:
    dossier, rules = _context()
    bad_rules = tmp_path / "verifier_rules.json"
    bad_rules.write_text(json.dumps({"hard_rules": []}), encoding="utf-8")

    result = verify_trade_ticket(_ticket(), dossier, rules, verifier_rules_path=bad_rules)

    assert result.passed is False
    assert "SYSTEM_VERIFIER" in _rule_ids(result)
