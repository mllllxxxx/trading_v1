from __future__ import annotations

import json

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
        signal_candidates=[
            {
                "signal_id": "sig-test",
                "generated_at": "2026-06-30T00:00:00Z",
                "source": "berkshire_crypto_scanner",
                "market": "crypto",
                "symbol": "BTC-USDT",
                "timeframe": "24h_ticker",
                "direction": "long",
                "status": "candidate",
                "confidence": 0.7,
                "score": 70,
                "grade": "B",
                "action_hint": "OPEN_LONG",
                "mode": "signal_only",
                "time_horizon": "swing_2d_7d",
                "promotion_gate": "eligible_for_draft_ticket",
                "reasons": ["Berkshire scanner found a directional setup."],
                "blockers": [],
            }
        ],
        autonomy_mode="paper",
    )


def test_prompt_builder_reads_schema_and_rendered_rulebook() -> None:
    messages = _prompt_messages()
    content = "\n\n".join(message["content"] for message in messages)

    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "TradeDecisionTicket" in content
    assert "SignalCandidate" in content
    assert "sig-test" in content
    assert "advisory inputs, not executable orders" in content
    assert "DO NOT EDIT - generated from trading/schemas/models.py" in content
    assert "HARD_RISK_001" in content
    assert "PB_CRYPTO_TREND_CONTINUATION_001" in content
    assert "Mandatory Hard Rule Citations For Non-HOLD" in content
    assert "Non-HOLD tickets must cite every ID" in content
    assert "HARD_EXECUTION_001" in content
    assert "Compiled Hard Rule Limits For Non-HOLD" in content
    assert "max_risk_pct_equity" in content
    assert "0.05" in content
    assert "profile_compliance_score" in content
    assert "0.60" in content
    assert '"order_type":"limit"' in content
    assert '"risk_pct_equity":0.03' in content
    assert "set entry_plan and risk_plan to null" in content


def test_prompt_builder_context_sources_are_allowlisted() -> None:
    sources = prompt_builder.allowed_context_roots()

    assert "trading/schemas/trade_decision_ticket.schema.json" in sources
    assert "trading/schemas/signal_candidate.schema.json" in sources
    assert "trading/docs/architecture/SIGNAL_CONTRACTS.md" in sources
    assert "trading/docs/product/LIVE_READINESS.md" in sources
    assert "trading/rulebook/rendered/llm" in sources
    assert "trading/rulebook/compiled/verifier_rules.json" in sources
    assert not any("docs/harness" in source for source in sources)
    assert not any(source.endswith("AGENTS.md") for source in sources)
    assert not any(source.endswith("README.md") for source in sources)


def test_prompt_builder_does_not_define_legacy_risk_constants() -> None:
    content = "\n\n".join(message["content"] for message in _prompt_messages())

    assert "R:R (reward:risk) must be" not in content
    assert "Position size must be <=" not in content
    assert "Confidence MUST be >=" not in content
    assert "1 TF aligned = 5% capital" not in content


def test_compact_prompt_omits_full_schema_but_keeps_contract(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_LLM_PROMPT_MODE", "compact")
    messages = _prompt_messages()
    content = "\n\n".join(message["content"] for message in messages)

    assert "Compact Output Contract" in content
    assert "Primary SignalCandidate" in content
    assert "sig-test" in content
    assert "TradeDecisionTicket JSON Schema" not in content
    assert "SignalCandidate JSON Schema" not in content
    assert "DO NOT EDIT - generated from trading/schemas/models.py" not in content
    assert "Generated Rulebook Context" not in content
    assert "HARD_RISK_001" in content
    assert "PB_CRYPTO_TREND_CONTINUATION_001" in content
    assert "max_risk_pct_equity" in content
    assert "profile_compliance_score" in content
    assert "0.60" in content
    assert "thesis <=160 chars" in content
    assert "reasoning_summary <=220 chars" in content
    assert "invalidation_conditions <=3 short" in content
    assert '"order_type":"limit"' in content
    assert '"risk_pct_equity":0.03' in content
    assert "set entry_plan and risk_plan to null" in content


def _compact_section(content: str, title: str) -> dict:
    marker = f"## {title}\n```json\n"
    start = content.index(marker) + len(marker)
    end = content.index("\n```", start)
    return json.loads(content[start:end])


def test_compact_prompt_minifies_json_and_bounds_optional_context(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_LLM_PROMPT_MODE", "compact")
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
    dossier["open_positions"] = [
        {"symbol": f"COIN{i}-USDT", "note": "x" * 320} for i in range(7)
    ]
    dossier["recent_trades"] = [
        {"symbol": f"COIN{i}-USDT", "summary": "y" * 320} for i in range(5)
    ]
    dossier["news"] = {
        "headline": "z" * 320,
        "events": [{"name": f"event-{i}", "details": "n" * 320} for i in range(5)],
    }
    rules = retrieve_rules(dossier).to_dict()
    messages = prompt_builder.build_trader_prompt(
        market_dossier=dossier,
        retrieved_rules=rules,
        signal_candidates=[
            {
                "signal_id": "sig-compact",
                "generated_at": "2026-06-30T00:00:00Z",
                "source": "test",
                "market": "crypto",
                "symbol": "BTC-USDT",
                "timeframe": "1h",
                "direction": "long",
                "status": "candidate",
                "confidence": 0.82,
                "score": 82,
                "grade": "A",
                "action_hint": "OPEN_LONG",
                "promotion_gate": "eligible_for_draft_ticket",
                "reasons": [f"reason-{i}-" + ("r" * 260) for i in range(5)],
                "blockers": [f"blocker-{i}-" + ("b" * 260) for i in range(5)],
            }
        ],
        autonomy_mode="paper",
    )
    content = messages[1]["content"]

    assert "```json\n{\n" not in content
    signal = _compact_section(content, "Primary SignalCandidate")
    market = _compact_section(content, "Compact MarketDossier")

    assert len(signal["reasons"]) == 3
    assert len(signal["blockers"]) == 3
    assert all(len(item) <= 180 for item in signal["reasons"])
    assert all(len(item) <= 180 for item in signal["blockers"])
    assert len(market["open_positions"]) == 5
    assert len(market["recent_trades"]) == 3
    assert len(market["news"]["events"]) == 3
    assert len(market["open_positions"][0]["note"]) == 240
    assert len(market["news"]["headline"]) == 240
