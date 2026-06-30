from __future__ import annotations

import json

import pytest


def test_append_lifecycle_event_writes_dashboard_compatible_event(isolated_journal):
    journal = isolated_journal

    event = journal.append_lifecycle_event(
        "market_dossier",
        decision_id="2026-06-29T00:00:00Z/BTC-USDT",
        payload={"symbol": "BTC-USDT", "stage": "dossier"},
        snapshots={
            "market_dossier": {"symbol": "BTC-USDT", "current_price": 100.0},
            "rules_context": {"all_rule_ids": ["HARD_RISK_001"]},
        },
    )

    assert event.event_type == "market_dossier"
    assert event.decision_id == "2026-06-29T00:00:00Z/BTC-USDT"

    lines = [
        json.loads(line)
        for line in journal.DECISIONS_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[-1]["type"] == "market_dossier"
    assert lines[-1]["event_id"] == event.event_id
    assert lines[-1]["event_type"] == "market_dossier"
    assert lines[-1]["decision_id"] == event.decision_id
    assert lines[-1]["payload"]["snapshot_refs"]["market_dossier"].startswith("snapshots/")

    bundle = journal.read_lifecycle_snapshots(event.decision_id)
    assert bundle["market_dossier"]["current_price"] == 100.0
    assert bundle["rules_context"]["all_rule_ids"] == ["HARD_RISK_001"]


def test_lifecycle_event_rejects_unknown_type(isolated_journal):
    with pytest.raises(ValueError, match="unknown lifecycle"):
        isolated_journal.append_lifecycle_event(
            "made_up_event",
            decision_id="dec-unknown",
            payload={},
        )


def test_lifecycle_snapshot_corruption_fails_closed(isolated_journal):
    journal = isolated_journal
    journal.write_lifecycle_snapshots(
        "dec-corrupt",
        {"ticket": {"action": "HOLD"}},
        date_key="2026-06-29",
    )
    path = journal.SNAPSHOTS_DIR / "2026-06-29" / "dec-corrupt.ticket.json"
    path.write_text("{bad-json", encoding="utf-8")

    with pytest.raises(journal.JournalCorruptError, match="snapshot corrupt"):
        journal.read_lifecycle_snapshots("dec-corrupt", date_key="2026-06-29")


def test_dashboard_style_decision_parsing_tolerates_lifecycle_events(isolated_journal):
    journal = isolated_journal
    journal.append_lifecycle_event(
        "fail_closed_skip",
        decision_id="dec-skip",
        payload={"reason": "verifier_reject"},
    )

    decisions = [
        json.loads(line)
        for line in journal.DECISIONS_LOG.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][-200:]
    llm_decisions = [
        decision
        for decision in decisions
        if decision.get("type") in {"llm", "llm_decision_used", "llm_override_hold"}
    ]

    assert decisions[-1]["type"] == "fail_closed_skip"
    assert llm_decisions == []
