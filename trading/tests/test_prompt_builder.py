from __future__ import annotations

from llm import prompt_builder
from market_dossier import build_market_dossier
from rule_retriever import retrieve_rules


def _prompt_messages() -> list[dict[str, str]]:
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
    rules = retrieve_rules(dossier).to_dict()
    return prompt_builder.build_trader_prompt(
        market_dossier=dossier,
        retrieved_rules=rules,
        autonomy_mode="paper",
    )


def test_prompt_builder_reads_schema_and_rendered_rulebook() -> None:
    messages = _prompt_messages()
    content = "\n\n".join(message["content"] for message in messages)

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "TradeDecisionTicket" in content
    assert "DO NOT EDIT - generated from trading/schemas/models.py" in content
    assert "HARD_RISK_001" in content
    assert "PB_CRYPTO_TREND_CONTINUATION_001" in content


def test_prompt_builder_context_sources_are_allowlisted() -> None:
    sources = prompt_builder.allowed_context_roots()

    assert "trading/schemas/trade_decision_ticket.schema.json" in sources
    assert "trading/rulebook/rendered/llm" in sources
    assert not any("docs/harness" in source for source in sources)
    assert not any(source.endswith("AGENTS.md") for source in sources)
    assert not any(source.endswith("README.md") for source in sources)


def test_prompt_builder_does_not_define_legacy_risk_constants() -> None:
    content = "\n\n".join(message["content"] for message in _prompt_messages())

    assert "R:R (reward:risk) must be" not in content
    assert "Position size must be <=" not in content
    assert "Confidence MUST be >=" not in content
    assert "1 TF aligned = 5% capital" not in content
