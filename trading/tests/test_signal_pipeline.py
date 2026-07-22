from __future__ import annotations

import json
from datetime import datetime, timezone

import signal_pipeline
from signal_pipeline import build_llm_ticket_provider, run_signal_to_demo_execution
from schemas.models import OrderResult


def _signal(**overrides):
    payload = {
        "signal_id": "sig-demo-001",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "berkshire_crypto_scanner",
        "market": "crypto",
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "15m_1h_4h",
        "direction": "long",
        "status": "candidate",
        "confidence": 0.72,
        "score": 72,
        "grade": "B",
        "action_hint": "OPEN_LONG",
        "mode": "signal_only",
        "time_horizon": "swing_2d_7d",
        "promotion_gate": "eligible_for_draft_ticket",
        "reasons": ["Berkshire scanner found a directional setup."],
        "blockers": [],
        "entry_zone": "99.5000 - 100.5000",
        "invalidation": "95.0000",
        "target_zone": "110.0000",
        "risk_reward": "2.0000",
        "last_price": "100.0000",
        "llm_context": {"role": "advisory_signal_context"},
        "evidence": {
            "provider_source": "okx_public_tickers+okx_confirmed_candles",
            "last_price": "100.0000",
            "spread_bps": "1.50",
            "data_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_age_s": 30.0,
            "regime": "TRENDING_UP",
            "confluence_score": 2.8,
            "feature_snapshot": {"1H": {"atr14": 2.0}},
            "regime_evidence": {"one_hour_adx14": 30.0},
            "setup_quality": {"one_hour_adx14": 30.0},
        },
    }
    payload.update(overrides)
    return payload


def _ticket() -> dict:
    return {
        "decision_id": "dec-signal-demo-001",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
        "thesis": "Signal aligns with crypto trend continuation.",
        "entry_plan": {
            "order_type": "limit",
            "entry_reference": "Berkshire signal entry zone",
            "chase_market": False,
        },
        "risk_plan": {
            "risk_pct_equity": 0.01,
            "stop_logic": "below signal invalidation",
            "take_profit_logic": "target signal target zone",
        },
        "invalidation_conditions": ["signal invalidation level breaks"],
        "confidence": 0.71,
        "data_quality": "A",
        "reasoning_summary": "Retrieved playbook and signal evidence agree.",
        "profile_compliance_score": 0.74,
        "profile_compliance_summary": "The ticket follows the preferred trend continuation profile and avoids chasing.",
        "profile_compliance_flags": ["pullback_required"],
    }


def _decision_lines(journal):
    return [
        json.loads(line)
        for line in journal.DECISIONS_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_signal_pipeline_executes_eligible_signal_in_paper_and_journals_lifecycle(isolated_journal):
    routing_experiment = {
        "approval_id": "approval-1",
        "candidate_fingerprint": "candidate-1",
        "v1_score": 48.0,
        "v2_score": 80.0,
    }
    result = run_signal_to_demo_execution(
        _signal(
            llm_context={
                "role": "advisory_signal_context",
                "routing_experiment": routing_experiment,
            }
        ),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is True
    assert result.promoted is True
    assert result.order_result is not None
    assert result.order_result["status"] == "paper_accepted"
    assert result.open_rationale is not None
    assert result.open_rationale["source_context"]["signal_id"] == "sig-demo-001"
    assert result.open_rationale["market_context"]["regime"] == "TRENDING_UP"
    assert "LLM thesis" in result.open_rationale["opened_because"]
    assert result.pipeline_result is not None
    assert result.pipeline_result["compiled_order"]["position_size_units"] == 20.0

    event_types = [line["type"] for line in _decision_lines(isolated_journal)]
    assert "signal_candidate" in event_types
    assert "market_dossier" in event_types
    assert "rule_retrieval" in event_types
    assert "llm_draft_ticket" in event_types
    assert "critic_review" in event_types
    assert "rule_verification" in event_types
    assert "risk_compilation" in event_types
    assert "trade_open_rationale" in event_types
    assert "execution_result" in event_types

    positions = isolated_journal.read_positions()
    assert positions[0]["source_signal_id"] == "sig-demo-001"
    assert positions[0]["mode"] == "paper"
    assert positions[0]["open_reason"] == result.open_rationale["opened_because"]
    assert positions[0]["market_context"]["candidate_direction"] == "long"
    assert positions[0]["profile_compliance_score"] == 0.74
    assert positions[0]["decision_context"]["profile_compliance_summary"]
    assert positions[0]["routing_experiment"] == routing_experiment


def test_signal_pipeline_preserves_team_metadata_and_allows_cross_team_same_symbol(isolated_journal):
    isolated_journal.add_position(
        {
            "position_id": "sigexec_existing",
            "symbol": "BTC-USDT-SWAP",
            "side": "buy",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "position_size": 1,
            "risk_usd": 5,
            "team_id": "berkshire",
            "team_name": "Berkshire",
        }
    )

    result = run_signal_to_demo_execution(
        _signal(
            signal_id="sig-momentum-001",
            source="team_momentum_scanner",
            team_id="momentum",
            team_name="Momentum",
            strategy_id="crypto_momentum_breakout",
            strategy_name="Momentum Breakout",
            team_capital_usd=200,
            target_risk_pct_equity=0.04,
            preferred_playbook_ids=["PB_CRYPTO_TREND_CONTINUATION_001"],
            required_soft_policy_ids=["SOFT_STRATEGY_TEAM_001"],
            entry_style="Wait for pullback or retest after impulse.",
            avoid_conditions=["late impulse chase"],
            llm_guidance="Prefer HOLD over chasing.",
            risk_personality="trend follower",
        ),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is True
    positions = isolated_journal.read_positions()
    assert len(positions) == 2
    assert positions[1]["team_id"] == "momentum"
    assert positions[1]["team_name"] == "Momentum"
    assert positions[1]["strategy_name"] == "Momentum Breakout"
    assert positions[1]["target_risk_pct_equity"] == 0.04
    assert positions[1]["preferred_playbook_ids"] == ["PB_CRYPTO_TREND_CONTINUATION_001"]
    assert positions[1]["entry_style"] == "Wait for pullback or retest after impulse."
    assert positions[1]["market_context"]["portfolio_exposure"]["required_soft_policy_ids"] == ["SOFT_STRATEGY_TEAM_001"]
    assert positions[1]["profile_compliance_score"] == 0.74


def test_okx_demo_rejects_cross_team_pending_same_symbol(isolated_journal, monkeypatch):
    monkeypatch.setenv("SIGNAL_EXECUTION_ADAPTER", "okx_demo")
    isolated_journal.add_position(
        {
            "symbol": "BTC-USDT-SWAP",
            "side": "buy",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "team_id": "berkshire",
            "status": "pending_entry",
            "position_size": 1,
            "risk_usd": 1,
        }
    )

    result = run_signal_to_demo_execution(
        _signal(
            source="team_momentum_scanner",
            team_id="momentum",
            team_name="Momentum",
            strategy_id="crypto_momentum_breakout",
            strategy_name="Momentum Breakout",
        ),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "pre_execution_guard"
    assert result.reason == "symbol_position_already_open"


def test_signal_pipeline_records_okx_accepted_order_as_pending_entry(isolated_journal):
    class FakeOkxAdapter:
        def place_bracket_order(self, _order, *, idempotency_key=None):
            return OrderResult(
                status="okx_demo_accepted",
                broker_order_id="okx-entry-123",
                raw={
                    "mode": "demo",
                    "idempotency_key": idempotency_key,
                    "proposal": {
                        "position_size_base": 18.0,
                        "contracts": 9,
                        "position_notional": 1_800.0,
                        "actual_risk_usd": 3.0,
                        "actual_risk_pct": 1.5,
                        "margin_required": 600.0,
                        "leverage": 3,
                    },
                },
            )

    result = run_signal_to_demo_execution(
        _signal(),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        execution_adapter=FakeOkxAdapter(),
        journal_module=isolated_journal,
    )

    assert result.executed is True
    assert result.order_result is not None
    assert result.order_result["status"] == "okx_demo_accepted"
    positions = isolated_journal.read_positions()
    assert len(positions) == 1
    assert positions[0]["mode"] == "okx_demo"
    assert positions[0]["status"] == "pending_entry"
    assert positions[0]["entry_filled"] is False
    assert positions[0]["orders"]["entry_id"] == "okx-entry-123"
    assert positions[0]["pending_entry_expires_at"] > positions[0]["opened_at"]
    assert positions[0]["position_size"] == 18.0
    assert positions[0]["broker_contracts"] == 9.0
    assert positions[0]["risk_usd"] == 3.0
    assert positions[0]["actual_risk_pct_equity"] == 0.015
    assert positions[0]["risk_cap_reason"].endswith("broker_contract_rounding")


def test_signal_pipeline_rejects_watchlist_before_llm_or_execution(isolated_journal):
    result = run_signal_to_demo_execution(
        _signal(
            direction="neutral",
            status="watchlist",
            action_hint="HOLD",
            promotion_gate="research_only_or_request_more_data",
            invalidation="wait for directional break",
            target_zone="n/a",
        ),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "signal_gate"
    assert "signal_not_eligible" in result.reason
    assert isolated_journal.read_positions() == []
    assert _decision_lines(isolated_journal)[-1]["type"] == "fail_closed_skip"


def test_signal_pipeline_skips_when_symbol_position_already_open(isolated_journal):
    isolated_journal.add_position(
        {
            "symbol": "BTC-USDT-SWAP",
            "side": "buy",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "position_size": 1,
            "risk_usd": 5,
        }
    )

    result = run_signal_to_demo_execution(
        _signal(symbol="BTC-USDT"),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "pre_execution_guard"
    assert result.reason == "symbol_position_already_open"


def test_signal_pipeline_skips_when_startup_sync_guard_active(isolated_journal):
    isolated_journal.set_startup_sync_guard("exchange_snapshot_failed", {"error": "okx down"})

    result = run_signal_to_demo_execution(
        _signal(symbol="BTC-USDT"),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "pre_execution_guard"
    assert result.reason == "startup_sync_blocked"


def test_signal_pipeline_skips_when_exchange_position_already_open(
    isolated_journal,
    monkeypatch,
):
    monkeypatch.setenv("SIGNAL_EXECUTION_ADAPTER", "okx_demo")

    def fake_exchange_guard(_symbol: str):
        return True, {"symbol": "BTC-USDT", "side": "sell"}, {"positions": [{"symbol": "BTC-USDT"}], "errors": []}

    monkeypatch.setattr(
        signal_pipeline.exchange_reconciler,
        "has_active_exchange_exposure",
        fake_exchange_guard,
    )

    result = run_signal_to_demo_execution(
        _signal(symbol="BTC-USDT"),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "pre_execution_guard"
    assert result.reason == "exchange_position_already_open"


def test_signal_pipeline_fails_closed_when_price_levels_are_missing(isolated_journal):
    result = run_signal_to_demo_execution(
        _signal(invalidation="wait for directional break", target_zone="n/a"),
        ticket_provider=lambda _dossier, _rules: _ticket(),
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "price_levels"
    assert "missing numeric levels" in result.reason
    assert isolated_journal.read_positions() == []


def test_signal_pipeline_fails_closed_when_llm_ticket_provider_fails(isolated_journal):
    def broken_provider(_dossier, _rules):
        raise RuntimeError("llm unavailable")

    result = run_signal_to_demo_execution(
        _signal(),
        ticket_provider=broken_provider,
        journal_module=isolated_journal,
    )

    assert result.executed is False
    assert result.stage == "llm_ticket"
    assert "llm_failed" in result.reason
    assert isolated_journal.read_positions() == []


def test_default_llm_ticket_provider_includes_signal_candidate_context() -> None:
    def fake_client(messages: list[dict[str, str]]) -> dict:
        content = "\n\n".join(message["content"] for message in messages)
        assert "SignalCandidate" in content
        assert "sig-demo-001" in content
        return _ticket()

    provider = build_llm_ticket_provider(
        signal_candidates=[_signal()],
        client=fake_client,
    )
    ticket = provider(
        {
            "symbol": "BTC-USDT-SWAP",
            "market": "crypto",
            "timeframe": "1h",
            "current_price": 100,
            "confluence_score": 4,
            "candidate_direction": "long",
            "regime": "TRENDING_UP",
            "trend_state": "up",
            "volatility_state": "normal",
            "data_source": "okx",
            "data_age_s": 5,
            "data_quality": "A",
        },
        {
            "mandatory_hard_rules": [],
            "candidate_playbooks": [{"id": "PB_CRYPTO_TREND_CONTINUATION_001"}],
            "soft_policies": [],
            "case_memory": [],
            "all_rule_ids": [
                "HARD_RISK_001",
                "HARD_RISK_002",
                "HARD_RISK_003",
                "HARD_DATA_001",
                "HARD_EXECUTION_001",
                "HARD_LLM_001",
                "HARD_MODE_001",
                "SOFT_REGIME_001",
                "PB_CRYPTO_TREND_CONTINUATION_001",
            ],
        },
    )

    assert ticket.decision_id == "dec-signal-demo-001"
