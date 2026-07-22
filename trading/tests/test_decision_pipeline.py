from __future__ import annotations

from market_dossier import build_market_dossier
from rule_retriever import retrieve_rules
from decision_pipeline import run_decision_pipeline
from schemas.models import CriticReview, CriticVerdict, VerifierResult


def _dossier() -> dict:
    return build_market_dossier(
        symbol="BTC-USDT-SWAP",
        market="crypto",
        timeframe="1h",
        current_price=100,
        confluence=4,
        regime="TRENDING_UP",
        data_source="okx",
        data_age_s=5,
    ).to_dict()


def _ticket() -> dict:
    return {
        "decision_id": "dec-pipeline-001",
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
            "stop_logic": "below invalidation swing",
            "take_profit_logic": "target previous impulse high",
        },
        "invalidation_conditions": ["close below trend support"],
        "confidence": 0.72,
        "data_quality": "A",
        "reasoning_summary": "Rulebook context and playbook fit the current trend.",
    }


def test_decision_pipeline_approves_and_compiles_without_execution() -> None:
    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
    )

    assert result.approved is True
    assert result.stage == "compiled_order"
    assert result.compiled_order is not None
    assert result.compiled_order["position_size_units"] == 20.0
    assert "broker_order_id" not in result.to_dict()


def test_decision_pipeline_fails_closed_on_rule_retrieval_error() -> None:
    def broken_rules(_dossier: dict) -> dict:
        raise RuntimeError("missing manifest")

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        rules_retriever=broken_rules,
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
    )

    assert result.approved is False
    assert result.stage == "rule_retrieval"
    assert "rule_retrieval_failed" in result.reason


def test_decision_pipeline_fails_closed_on_llm_error() -> None:
    def broken_ticket(_dossier: dict, _rules: dict) -> dict:
        raise RuntimeError("invalid json")

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=broken_ticket,
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
    )

    assert result.approved is False
    assert result.stage == "llm_ticket"
    assert "llm_failed" in result.reason


def test_decision_pipeline_stops_hold_before_critic_verifier_and_compiler() -> None:
    hold = _ticket()
    hold.update(
        {
            "action": "HOLD",
            "playbook_id": None,
            "rule_citations": [],
            "entry_plan": None,
            "risk_plan": None,
            "invalidation_conditions": [],
            "confidence": 0.2,
        }
    )
    called = {"critic": False, "verifier": False, "compiler": False}

    def critic_spy(*_args):  # type: ignore[no-untyped-def]
        called["critic"] = True
        raise AssertionError("critic should not run for HOLD")

    def verifier_spy(*_args):  # type: ignore[no-untyped-def]
        called["verifier"] = True
        raise AssertionError("verifier should not run for HOLD")

    def compiler_spy(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        called["compiler"] = True
        raise AssertionError("compiler should not run for HOLD")

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: hold,
        equity=10_000,
        price_levels=None,
        critic_fn=critic_spy,
        verifier_fn=verifier_spy,
        compiler_fn=compiler_spy,
    )

    assert result.approved is False
    assert result.stage == "decision"
    assert result.reason == "llm_hold"
    assert result.ticket is not None
    assert called == {"critic": False, "verifier": False, "compiler": False}


def test_decision_pipeline_stops_request_more_data_before_compiler() -> None:
    request = _ticket()
    request.update(
        {
            "action": "REQUEST_MORE_DATA",
            "playbook_id": None,
            "rule_citations": [],
            "entry_plan": None,
            "risk_plan": None,
            "invalidation_conditions": [],
            "confidence": 0.1,
        }
    )

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: request,
        equity=10_000,
        price_levels=None,
        compiler_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("compiler should not run for REQUEST_MORE_DATA")
        ),
    )

    assert result.approved is False
    assert result.stage == "decision"
    assert result.reason == "llm_request_more_data"


def test_decision_pipeline_stops_on_critic_reject() -> None:
    bad = _ticket()
    bad["risk_plan"]["risk_pct_equity"] = 0.5

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: bad,
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
    )

    assert result.approved is False
    assert result.stage == "critic"
    assert result.reason == "critic_reject"


def test_decision_pipeline_stops_on_verifier_reject_before_compiler() -> None:
    compiler_called = False

    def compiler_spy(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal compiler_called
        compiler_called = True
        raise AssertionError("compiler should not run")

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        equity=10_000,
        price_levels={"entry": 100, "stop_loss": 95, "take_profit": 110},
        critic_fn=lambda *_args: CriticReview(verdict=CriticVerdict.APPROVE),
        verifier_fn=lambda *_args: VerifierResult(passed=False, violations=[{"rule_id": "HARD_TEST"}]),
        compiler_fn=compiler_spy,
    )

    assert result.approved is False
    assert result.stage == "verifier"
    assert compiler_called is False


def test_decision_pipeline_fails_closed_on_compiler_error() -> None:
    rules = retrieve_rules(_dossier()).to_dict()

    result = run_decision_pipeline(
        _dossier(),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        rules_retriever=lambda _dossier: rules,
        equity=10_000,
        price_levels={"entry": 100, "take_profit": 110},
    )

    assert result.approved is False
    assert result.stage == "compiler"
    assert "order_compiler_failed" in result.reason
