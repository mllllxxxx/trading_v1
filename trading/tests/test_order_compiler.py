from __future__ import annotations

import pytest

from market_dossier import build_market_dossier
from risk.order_compiler import OrderCompilerError, compile_order
from schemas.models import VerifierResult


def _dossier(score: float = 4, regime: str = "TRENDING_UP") -> dict:
    return build_market_dossier(
        symbol="BTC-USDT-SWAP",
        market="crypto",
        timeframe="1h",
        current_price=100,
        confluence=score,
        regime=regime,
        data_source="okx",
        data_age_s=5,
    ).to_dict()


def _ticket(action: str = "OPEN_LONG", risk_pct: float = 0.01) -> dict:
    return {
        "decision_id": f"dec-compiler-{action.lower()}",
        "timestamp_utc": "2026-06-29T00:00:00Z",
        "action": action,
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
            "risk_pct_equity": risk_pct,
            "stop_logic": "below invalidation swing",
            "take_profit_logic": "target previous impulse high",
        },
        "invalidation_conditions": ["close below trend support"],
        "confidence": 0.72,
        "data_quality": "A",
        "reasoning_summary": "Rulebook context and playbook fit the current trend.",
    }


def _passed() -> VerifierResult:
    return VerifierResult(passed=True, violations=[], checked_rule_ids=["HARD_EXECUTION_001"])


def test_compile_order_long_computes_size_from_equity_and_stop() -> None:
    order = compile_order(
        _ticket(),
        _dossier(),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
        verifier_result=_passed(),
    )

    assert order.side == "buy"
    assert order.risk_amount_usd == 100.0
    assert order.position_size_units == 20.0
    assert order.position_notional_usd == 2000.0
    assert order.source == "risk_compiler.v1"


def test_compile_order_short_uses_sell_side_and_short_levels() -> None:
    ticket = _ticket(action="OPEN_SHORT")
    ticket["playbook_id"] = "PB_CRYPTO_BREAKOUT_PULLBACK_001"

    order = compile_order(
        ticket,
        _dossier(score=-4, regime="TRENDING_DOWN"),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 105, "take_profit": 90},
        verifier_result=_passed(),
    )

    assert order.side == "sell"
    assert order.position_size_units == 20.0
    assert order.risk_amount_usd == 100.0


def test_compile_order_requires_verifier_pass() -> None:
    with pytest.raises(OrderCompilerError, match="verifier_result"):
        compile_order(
            _ticket(),
            _dossier(),
            equity=10_000,
            price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
            verifier_result=VerifierResult(passed=False),
        )


def test_compile_order_rejects_missing_stop_loss() -> None:
    with pytest.raises(OrderCompilerError, match="stop_loss"):
        compile_order(
            _ticket(),
            _dossier(),
            equity=10_000,
            price_levels={"entry": 100, "take_profit": 110},
            verifier_result=_passed(),
        )


def test_compile_order_rejects_reward_to_risk_below_hard_minimum() -> None:
    with pytest.raises(OrderCompilerError, match="reward-to-risk"):
        compile_order(
            _ticket(),
            _dossier(),
            equity=10_000,
            price_levels={"entry": 100, "stop_loss": 95, "take_profit": 104},
            verifier_result=_passed(),
        )


def test_compile_order_clamps_notional_to_hard_position_cap() -> None:
    order = compile_order(
        _ticket(),
        _dossier(),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 99, "take_profit": 103},
        verifier_result=_passed(),
    )

    assert order.position_notional_usd == 2000.0
    assert order.position_size_units == 20.0
    assert order.risk_amount_usd == 20.0
    assert order.risk_pct_equity == 0.002


def test_compile_order_ignores_llm_raw_quantity_fields() -> None:
    ticket = _ticket()
    ticket["position_size_units"] = 9999
    ticket["position_notional_usd"] = 999999

    order = compile_order(
        ticket,
        _dossier(),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
        verifier_result=_passed(),
    )

    assert order.position_size_units == 20.0
    assert order.position_notional_usd == 2000.0
