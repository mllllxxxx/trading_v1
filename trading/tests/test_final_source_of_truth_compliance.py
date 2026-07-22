from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRADING_ROOT = REPO_ROOT / "trading"


def test_final_steps_13_20_audit_document_exists() -> None:
    audit = REPO_ROOT / "docs" / "audits" / "trading_v1_steps_13_20_source_of_truth_compliance.md"
    content = audit.read_text(encoding="utf-8")

    assert "Steps 13-20" in content
    assert "Execution adapter interface accepts `CompiledOrder` only" in content
    assert "Replay mock mode reports `broker_calls=0`" in content


def test_execution_and_journal_contracts_are_in_source_map() -> None:
    source_map = (TRADING_ROOT / "docs" / "architecture" / "SOURCE_OF_TRUTH_MAP.md").read_text(
        encoding="utf-8"
    )

    assert "EXECUTION_CONTRACTS.md" in source_map
    assert "JOURNAL_CONTRACTS.md" in source_map
    assert "SIGNAL_CONTRACTS.md" in source_map
    assert "LIVE_READINESS.md" in source_map
    assert "compiled_order.schema.json" in source_map
    assert "journal_event.schema.json" in source_map
    assert "signal_candidate.schema.json" in source_map


def test_generated_artifacts_remain_generated() -> None:
    generated_paths = [
        TRADING_ROOT / "rulebook" / "compiled" / "skills.json",
        TRADING_ROOT / "rulebook" / "compiled" / "rule_index.json",
        TRADING_ROOT / "rulebook" / "compiled" / "verifier_rules.json",
        TRADING_ROOT / "auto" / "skills.json",
    ]
    for path in generated_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        notice = payload.get("_generated_notice", "")
        assert notice.startswith("DO NOT EDIT - generated from trading/rulebook/source"), path


def test_new_runtime_modules_do_not_use_process_docs_as_context() -> None:
    forbidden = ["docs/harness", "AGENTS.md", "README.md", "FEATURE_INTAKE.md"]
    runtime_files = [
        TRADING_ROOT / "auto" / "critic.py",
        TRADING_ROOT / "auto" / "decision_pipeline.py",
        TRADING_ROOT / "verifier" / "rule_verifier.py",
        TRADING_ROOT / "risk" / "order_compiler.py",
        TRADING_ROOT / "replay" / "metrics.py",
        TRADING_ROOT / "replay" / "run_replay.py",
        TRADING_ROOT / "execution" / "base.py",
        TRADING_ROOT / "execution" / "paper_adapter.py",
        TRADING_ROOT / "execution" / "stubs.py",
    ]

    offenders: list[str] = []
    for path in runtime_files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in content:
                offenders.append(f"{path.relative_to(REPO_ROOT)} references {token}")

    assert offenders == []


def test_execution_interface_is_broker_free_in_this_batch() -> None:
    execution_files = sorted((TRADING_ROOT / "execution").glob("*.py"))
    forbidden = ["ccxt", "OKX_API_KEY", "OANDA_API_KEY", "MT5_LOGIN", "place_orders_spot"]
    offenders: list[str] = []
    for path in execution_files:
        if path.name == "okx_demo_adapter.py":
            continue
        content = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in content:
                offenders.append(f"{path.name} contains {token}")

    assert offenders == []


def test_okx_demo_adapter_is_documented_as_demo_only() -> None:
    contract = (TRADING_ROOT / "docs" / "architecture" / "EXECUTION_CONTRACTS.md").read_text(
        encoding="utf-8"
    )
    adapter = (TRADING_ROOT / "execution" / "okx_demo_adapter.py").read_text(encoding="utf-8")

    assert "OKX demo" in contract
    assert "OKX_TESTNET=true" in contract
    assert "OKX_SANDBOX=true" in contract
    assert "OKXDemoExecutionAdapter only supports demo/testnet mode" in adapter
