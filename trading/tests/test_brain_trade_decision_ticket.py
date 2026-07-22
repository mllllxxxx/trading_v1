from __future__ import annotations

import builtins
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

import brain
from brain import (
    BrainBudgetError,
    BrainError,
    call_llm_context_review,
    call_trade_decision_ticket,
    parse_trade_decision_ticket,
)
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


def test_trade_decision_ticket_llm_call_records_token_cost(monkeypatch, isolated_journal) -> None:
    monkeypatch.setenv("AUTO_LLM_INPUT_PRICE_PER_M", "1")
    monkeypatch.setenv("AUTO_LLM_OUTPUT_PRICE_PER_M", "2")

    class Usage:
        prompt_tokens = 1000
        completion_tokens = 500

    class Message:
        content = json.dumps(_open_ticket())

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]
        usage = Usage()

    class Completions:
        def create(self, **_kwargs):
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(brain, "_get_client", lambda: Client())

    raw = brain._call_messages_for_json(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        model="deepseek-v4-flash",
        timeout_s=5,
        max_tokens=200,
        temperature=0,
    )

    assert json.loads(raw)["decision_id"] == "dec-ticket-001"
    cost_state = isolated_journal.read_stats()["daily_llm_cost"]
    assert cost_state["calls"] == 1
    assert cost_state["cost_usd"] == 0.002
    assert cost_state["source_breakdown"]["trade_decision_ticket"]["calls"] == 1


def test_trade_decision_ticket_call_uses_2400_default_max_tokens(monkeypatch, isolated_journal) -> None:
    captured: dict[str, object] = {}

    class Message:
        content = json.dumps(_open_ticket())

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return Response()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    monkeypatch.setattr(brain, "_get_client", lambda: Client())

    raw = brain._call_messages_for_json(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        model="deepseek-v4-flash",
        timeout_s=5,
        max_tokens=None,
        temperature=0,
    )

    assert json.loads(raw)["decision_id"] == "dec-ticket-001"
    assert brain.DEFAULT_MAX_TOKENS == 2400
    assert captured["max_tokens"] == 2400


def test_context_review_uses_500_token_output_budget(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_call(_messages, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return json.dumps(
            {
                "schema_version": "llm_context_review.v1",
                "review_id": "review-budget-001",
                "timestamp_utc": "2026-06-29T00:00:00Z",
                "decision": "APPROVE",
                "risk_multiplier": 0.5,
                "conflict_flags": [],
                "evidence_refs": ["signal:test"],
                "reasoning_summary": "Approve the deterministic proposal at reduced risk.",
            }
        )

    monkeypatch.setattr(brain, "_call_messages_for_json", fake_call)

    review = call_llm_context_review([{"role": "user", "content": "review"}])

    assert review.risk_multiplier == 0.5
    assert captured["max_tokens"] == 500


def test_llm_budget_default_cap_is_twenty_cents(monkeypatch, isolated_journal) -> None:
    monkeypatch.delenv("AUTO_DAILY_LLM_COST_CAP_USD", raising=False)

    status = isolated_journal.daily_cost_status()

    assert status["cap_usd"] == 0.2
    assert status["call_cap"] == 160
    assert status["hourly_call_cap"] == 16
    assert status["hourly_call_cap_per_source"] == 4


def test_package_brain_resolves_package_journal_when_top_level_import_is_absent(monkeypatch) -> None:
    package_name = "_brain_package_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(Path("trading/auto").resolve())]
    monkeypatch.setitem(sys.modules, package_name, package)
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.brain",
        Path("trading/auto/brain.py"),
    )
    assert spec is not None and spec.loader is not None
    package_brain = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, package_brain)
    spec.loader.exec_module(package_brain)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "journal" and level == 0:
            raise ImportError("top-level journal intentionally unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    journal_module = package_brain._load_journal_module()

    assert journal_module.__name__ == f"{package_name}.journal"


def test_llm_budget_source_cap_does_not_starve_other_team(monkeypatch, isolated_journal) -> None:
    monkeypatch.setenv("AUTO_DAILY_LLM_COST_CAP_USD", "999")
    monkeypatch.setenv("AUTO_DAILY_LLM_CALL_CAP", "120")
    monkeypatch.setenv("AUTO_HOURLY_LLM_CALL_CAP", "12")
    monkeypatch.setenv("AUTO_HOURLY_LLM_CALL_CAP_PER_SOURCE", "3")

    for _ in range(3):
        isolated_journal.add_llm_cost(0, 0, source="berkshire_signal")

    berkshire = isolated_journal.check_llm_budget(source="berkshire_signal")
    volatility = isolated_journal.check_llm_budget(source="volatility_breakout_signal")

    assert berkshire["allowed"] is False
    assert berkshire["reason"] == "source_hourly_call_cap"
    assert berkshire["source_hourly_calls"] == 3
    assert berkshire["remaining_source_hourly_calls"] == 0
    assert volatility["allowed"] is True
    assert volatility["source_hourly_calls"] == 0
    assert volatility["remaining_source_hourly_calls"] == 3


@pytest.mark.parametrize(
    ("env", "seed_kwargs", "expected_reason"),
    [
        (
            {
                "AUTO_DAILY_LLM_COST_CAP_USD": "0.001",
                "AUTO_DAILY_LLM_CALL_CAP": "120",
                "AUTO_HOURLY_LLM_CALL_CAP": "100",
                "AUTO_LLM_INPUT_PRICE_PER_M": "1",
                "AUTO_LLM_OUTPUT_PRICE_PER_M": "0",
            },
            {"input_tokens": 1000, "output_tokens": 0},
            "daily_cost_cap",
        ),
        (
            {
                "AUTO_DAILY_LLM_COST_CAP_USD": "999",
                "AUTO_DAILY_LLM_CALL_CAP": "1",
                "AUTO_HOURLY_LLM_CALL_CAP": "100",
            },
            {"input_tokens": 0, "output_tokens": 0},
            "daily_call_cap",
        ),
        (
            {
                "AUTO_DAILY_LLM_COST_CAP_USD": "999",
                "AUTO_DAILY_LLM_CALL_CAP": "120",
                "AUTO_HOURLY_LLM_CALL_CAP": "1",
            },
            {"input_tokens": 0, "output_tokens": 0},
            "hourly_call_cap",
        ),
    ],
)
def test_llm_budget_gate_blocks_before_provider_call(
    monkeypatch,
    isolated_journal,
    env: dict[str, str],
    seed_kwargs: dict[str, int],
    expected_reason: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    isolated_journal.add_llm_cost(**seed_kwargs, source="seed")
    called = {"client": False}

    def fail_get_client():
        called["client"] = True
        raise AssertionError("provider should not be constructed after budget denial")

    monkeypatch.setattr(brain, "_get_client", fail_get_client)

    with pytest.raises(BrainBudgetError, match=expected_reason):
        brain._call_messages_for_json(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
            model="deepseek-v4-flash",
            timeout_s=5,
            max_tokens=200,
            temperature=0,
            budget_source="berkshire_signal",
        )

    assert called["client"] is False
    cost_state = isolated_journal.read_stats()["daily_llm_cost"]
    assert cost_state["budget_skips"] == 1
    assert cost_state["last_budget_skip"]["reason"] == expected_reason
    lines = [json.loads(line) for line in isolated_journal.DECISIONS_LOG.read_text().splitlines()]
    assert lines[-1]["type"] == "llm_budget_skip"
    assert lines[-1]["reason"] == expected_reason


def test_call_brain_legacy_path_uses_same_budget_gate(monkeypatch, isolated_journal) -> None:
    monkeypatch.setenv("AUTO_DAILY_LLM_COST_CAP_USD", "999")
    monkeypatch.setenv("AUTO_DAILY_LLM_CALL_CAP", "1")
    monkeypatch.setenv("AUTO_HOURLY_LLM_CALL_CAP", "100")
    isolated_journal.add_llm_cost(0, 0, source="seed")
    called = {"client": False}

    def fail_get_client():
        called["client"] = True
        raise AssertionError("legacy provider should not be constructed after budget denial")

    monkeypatch.setattr(brain, "_get_client", fail_get_client)

    with pytest.raises(BrainBudgetError, match="daily_call_cap"):
        brain.call_brain("system", "user")

    assert called["client"] is False
    assert isolated_journal.read_stats()["daily_llm_cost"]["last_budget_skip"]["source"] == "legacy_scheduler"


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


def test_parse_trade_decision_ticket_reports_safe_response_shape() -> None:
    payload = _open_ticket()
    payload["entry_plan"] = "buy the pullback"

    with pytest.raises(BrainError) as exc_info:
        parse_trade_decision_ticket(payload)

    message = str(exc_info.value)
    assert "entry_plan must be an object" in message
    assert '"entry_plan":"str"' in message
    assert "buy the pullback" not in message


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


def test_call_trade_decision_ticket_repairs_empty_or_invalid_response(monkeypatch) -> None:
    known_rules, known_playbooks = _known_ids()
    calls: list[list[dict[str, str]]] = []

    def flaky_client(messages: list[dict[str, str]]) -> str:
        calls.append(messages)
        if len(calls) == 1:
            return ""
        assert "previous TradeDecisionTicket response was rejected" in messages[-1]["content"]
        return json.dumps(_open_ticket())

    ticket = call_trade_decision_ticket(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        known_rule_ids=known_rules,
        known_playbook_ids=known_playbooks,
        client=flaky_client,
    )

    assert ticket.action is TradeAction.OPEN_LONG
    assert len(calls) == 2


def test_ticket_repair_prompt_limits_previous_response_preview() -> None:
    messages = brain._ticket_repair_messages(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        "x" * 1000,
        BrainError("bad json"),
    )
    content = messages[-1]["content"]

    assert "x" * 600 in content
    assert "x" * 601 not in content
    assert "concise JSON object" in content
    assert '"order_type":"limit"' in content
    assert '"risk_pct_equity":0.03' in content
    assert "set entry_plan and risk_plan to null" in content
