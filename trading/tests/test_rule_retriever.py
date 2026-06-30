from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_dossier import build_market_dossier
from rule_retriever import RuleRetrievalError, retrieve_rules


def _crypto_dossier(score: float = 4, regime: str = "TRENDING_UP", timeframe: str = "1h") -> dict:
    return build_market_dossier(
        symbol="BTC-USDT-SWAP",
        market="crypto",
        timeframe=timeframe,
        current_price=65000,
        confluence=score,
        regime=regime,
        data_source="okx",
        data_age_s=5,
    ).to_dict()


def _ids(items: list[dict]) -> set[str]:
    return {str(item["id"]) for item in items}


def test_crypto_trend_dossier_retrieves_crypto_playbook_not_forex() -> None:
    context = retrieve_rules(_crypto_dossier()).to_dict()
    playbooks = _ids(context["candidate_playbooks"])

    assert "PB_CRYPTO_TREND_CONTINUATION_001" in playbooks
    assert not any(rule_id.startswith("PB_FX_") for rule_id in playbooks)
    assert "HARD_DATA_001" in _ids(context["mandatory_hard_rules"])


def test_short_trend_retrieves_short_capable_playbook() -> None:
    context = retrieve_rules(_crypto_dossier(score=-4, regime="TRENDING_DOWN")).to_dict()
    trend = next(
        item for item in context["candidate_playbooks"]
        if item["id"] == "PB_CRYPTO_TREND_CONTINUATION_001"
    )

    assert trend["score"] > 0
    assert "short" in trend["metadata"]["directions"]


def test_ranging_dossier_retrieves_mean_reversion_playbook() -> None:
    context = retrieve_rules(_crypto_dossier(score=-3, regime="RANGING", timeframe="15m")).to_dict()
    assert "PB_CRYPTO_MEAN_REVERSION_001" in _ids(context["candidate_playbooks"])


def test_weak_candidate_returns_hard_rules_but_no_playbooks() -> None:
    context = retrieve_rules(_crypto_dossier(score=1)).to_dict()
    assert context["mandatory_hard_rules"]
    assert context["candidate_playbooks"] == []


def test_all_returned_ids_exist_in_rule_index() -> None:
    context = retrieve_rules(_crypto_dossier()).to_dict()
    known = set(context["all_rule_ids"])
    returned = set()
    for key in ("mandatory_hard_rules", "candidate_playbooks", "soft_policies", "case_memory"):
        returned.update(_ids(context[key]))

    assert returned
    assert returned <= known


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(RuleRetrievalError, match="retriever manifest"):
        retrieve_rules(_crypto_dossier(), retriever_manifest_path=missing)


def test_malformed_manifest_fails_closed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"_generated_notice": "DO NOT EDIT - generated from trading/rulebook/source"}))
    with pytest.raises(RuleRetrievalError, match="malformed"):
        retrieve_rules(_crypto_dossier(), retriever_manifest_path=bad)
