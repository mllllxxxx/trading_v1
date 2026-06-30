from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

import skills


def _generated_payload() -> dict:
    return {
        "_generated": True,
        "_generated_notice": "DO NOT EDIT - generated from trading/rulebook/source by compile_rulebook.py",
        "_source": "trading/rulebook/source",
        "_do_not_edit": True,
        "hard": {
            "rr_minimum": 1.2,
            "max_position_pct": 0.2,
            "max_leverage": 3.0,
            "stop_loss_required": True,
            "take_profit_required": True,
        },
        "soft": {
            "avoid_overbought_long": "fixture",
        },
    }


@pytest.fixture
def temp_policy_dir():
    workspace_root = Path(__file__).resolve().parents[2]
    root = workspace_root / ".test-tmp" / f"skills-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_load_skills_reads_compiled_rulebook_by_default() -> None:
    data = skills.load_skills()
    assert data["_generated"] is True
    assert data["_source"] == "trading/rulebook/source"
    assert data["hard"]["rr_minimum"] == 1.2
    assert "avoid_overbought_long" in data["soft"]


def test_load_skills_accepts_generated_compiled_file(temp_policy_dir) -> None:
    path = temp_policy_dir / "skills.json"
    path.write_text(json.dumps(_generated_payload()), encoding="utf-8")
    data = skills.load_skills(path=path, mode="paper")
    assert data["hard"]["max_position_pct"] == 0.2


def test_missing_skills_fails_closed_in_paper_mode(temp_policy_dir) -> None:
    missing = temp_policy_dir / "missing.json"
    with pytest.raises(skills.SkillsLoadError):
        skills.load_skills(path=missing, mode="paper")


def test_malformed_skills_fails_closed_in_paper_mode(temp_policy_dir) -> None:
    path = temp_policy_dir / "skills.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(skills.SkillsLoadError):
        skills.load_skills(path=path, mode="paper")


def test_non_generated_skills_fails_closed_in_paper_mode(temp_policy_dir) -> None:
    path = temp_policy_dir / "skills.json"
    path.write_text(
        json.dumps(
            {
                "hard": {
                    "rr_minimum": 1.2,
                    "max_position_pct": 0.2,
                    "max_leverage": 3.0,
                },
                "soft": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(skills.SkillsLoadError):
        skills.load_skills(path=path, mode="paper")


def test_explicit_test_fixture_fallback_allowed_only_in_test_mode(temp_policy_dir) -> None:
    missing = temp_policy_dir / "missing.json"
    data = skills.load_skills(
        path=missing,
        mode="test",
        allow_test_fallback=True,
    )
    assert data["_test_fixture_fallback"] is True
    assert data["hard"]["rr_minimum"] == 1.2


def test_explicit_test_fixture_fallback_blocked_in_live_mode(temp_policy_dir) -> None:
    missing = temp_policy_dir / "missing.json"
    with pytest.raises(skills.SkillsLoadError):
        skills.load_skills(
            path=missing,
            mode="live",
            allow_test_fallback=True,
        )


def test_getters_keep_legacy_api() -> None:
    hard = skills.get_hard_skills()
    soft = skills.get_soft_skills()
    assert hard["rr_minimum"] == 1.2
    assert "avoid_overbought_long" in soft
