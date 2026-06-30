from __future__ import annotations

import json
from pathlib import Path

from rulebook.compile_rulebook import (
    AUTO_SKILLS_PATH,
    COMPILED_DIR,
    RENDERED_DIR,
    build_artifacts,
    check_artifacts,
    load_records,
)
from rulebook.schema import GENERATED_NOTICE


def test_rulebook_compiles() -> None:
    records = load_records()
    assert len(records) >= 16
    artifacts = build_artifacts(records)
    assert COMPILED_DIR / "rule_index.json" in artifacts
    assert COMPILED_DIR / "verifier_rules.json" in artifacts
    assert COMPILED_DIR / "retriever_manifest.json" in artifacts
    assert COMPILED_DIR / "skills.json" in artifacts
    assert AUTO_SKILLS_PATH in artifacts


def test_rule_ids_unique() -> None:
    records = load_records()
    ids = [record.rule_id for record in records]
    assert len(ids) == len(set(ids))


def test_playbooks_reference_existing_rules() -> None:
    records = load_records()
    ids = {record.rule_id for record in records}
    playbooks = [record for record in records if record.category == "playbooks"]
    assert playbooks
    for playbook in playbooks:
        for hard_rule in playbook.data["required_hard_rules"]:
            assert hard_rule in ids


def test_compiled_files_have_do_not_edit_header() -> None:
    compiled_files = [
        COMPILED_DIR / "rule_index.json",
        COMPILED_DIR / "verifier_rules.json",
        COMPILED_DIR / "retriever_manifest.json",
        COMPILED_DIR / "skills.json",
        AUTO_SKILLS_PATH,
    ]
    for path in compiled_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["_generated_notice"] == GENERATED_NOTICE

    rendered_files = [
        RENDERED_DIR / "llm" / "hard_rules.md",
        RENDERED_DIR / "llm" / "soft_policies.md",
        RENDERED_DIR / "llm" / "playbooks.md",
        RENDERED_DIR / "llm" / "cases.md",
        RENDERED_DIR / "human" / "rulebook.md",
        RENDERED_DIR / "human" / "playbook_catalog.md",
    ]
    for path in rendered_files:
        assert path.read_text(encoding="utf-8").startswith(GENERATED_NOTICE)


def test_generated_artifacts_are_fresh() -> None:
    records = load_records()
    stale = check_artifacts(build_artifacts(records))
    assert stale == []


def test_retriever_manifest_contains_filter_metadata_and_markdown() -> None:
    manifest = json.loads((COMPILED_DIR / "retriever_manifest.json").read_text(encoding="utf-8"))
    trend = manifest["rules"]["PB_CRYPTO_TREND_CONTINUATION_001"]
    assert trend["category"] == "playbooks"
    assert "crypto" in trend["markets"]
    assert "short" in trend["directions"]
    assert "TRENDING_DOWN" in trend["regimes"]
    assert "HARD_RISK_001" in trend["required_hard_rules"]
    assert trend["markdown"].startswith("## PB_CRYPTO_TREND_CONTINUATION_001")


def test_auto_skills_is_generated_from_rulebook() -> None:
    compiled = json.loads((COMPILED_DIR / "skills.json").read_text(encoding="utf-8"))
    auto = json.loads(Path(AUTO_SKILLS_PATH).read_text(encoding="utf-8"))
    assert auto == compiled
    assert auto["_do_not_edit"] is True
    assert auto["hard"]["rr_minimum"] == 1.2
    assert auto["hard"]["max_position_pct"] == 0.2
    assert "avoid_overbought_long" in auto["soft"]
