"""Deterministic rulebook retrieval for MarketDossier context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schemas.models import MarketDossier, RetrievedRuleContext, RuleSnippet


TRADING_ROOT = Path(__file__).resolve().parents[1]
COMPILED_DIR = TRADING_ROOT / "rulebook" / "compiled"
RULE_INDEX_PATH = COMPILED_DIR / "rule_index.json"
RETRIEVER_MANIFEST_PATH = COMPILED_DIR / "retriever_manifest.json"
GENERATED_NOTICE_PREFIX = "DO NOT EDIT - generated from trading/rulebook/source"


class RuleRetrievalError(RuntimeError):
    """Raised when rulebook context cannot be retrieved safely."""


def retrieve_rules(
    dossier: MarketDossier | dict[str, Any],
    *,
    rule_index_path: Path = RULE_INDEX_PATH,
    retriever_manifest_path: Path = RETRIEVER_MANIFEST_PATH,
    max_playbooks: int = 3,
    max_cases: int = 3,
) -> RetrievedRuleContext:
    """Retrieve prompt-ready rule context from generated rulebook artifacts."""
    index = _load_generated_json(rule_index_path, "rule index")
    manifest = _load_generated_json(retriever_manifest_path, "retriever manifest")
    index_rules = index.get("rules")
    manifest_rules = manifest.get("rules")
    if not isinstance(index_rules, dict) or not isinstance(manifest_rules, dict):
        raise RuleRetrievalError("compiled rulebook artifacts are malformed")

    missing_from_index = sorted(set(manifest_rules) - set(index_rules))
    if missing_from_index:
        raise RuleRetrievalError(f"manifest IDs missing from rule index: {missing_from_index}")

    market = _dossier_str(dossier, "market").lower()
    direction = _dossier_str(dossier, "candidate_direction").lower()
    regime = _dossier_str(dossier, "regime").upper()
    timeframe = _dossier_str(dossier, "timeframe").lower()

    active_rules = [
        rule for rule in manifest_rules.values()
        if _is_active_market_rule(rule, market)
    ]

    hard_rules = [
        _snippet(rule, score=1.0)
        for rule in sorted(active_rules, key=_hard_rule_sort_key)
        if rule.get("category") == "hard"
    ]

    playbook_candidates: list[tuple[float, dict[str, Any]]] = []
    if direction in {"long", "short"}:
        for rule in active_rules:
            if rule.get("category") != "playbooks":
                continue
            score = _playbook_score(rule, direction, regime, timeframe)
            if score > 0:
                playbook_candidates.append((score, rule))
    playbook_candidates.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    selected_playbooks = playbook_candidates[:max_playbooks]
    selected_playbook_ids = {str(rule["id"]) for _, rule in selected_playbooks}

    related_soft_ids: set[str] = set()
    required_hard_ids: set[str] = set()
    for _, playbook in selected_playbooks:
        related_soft_ids.update(str(item) for item in playbook.get("related_soft_policies", []))
        required_hard_ids.update(str(item) for item in playbook.get("required_hard_rules", []))

    soft_rules = [
        _snippet(rule, score=_soft_score(rule, related_soft_ids, regime))
        for rule in active_rules
        if rule.get("category") == "soft"
    ]
    soft_rules.sort(key=lambda item: (-(item.score or 0.0), item.id))

    case_rules = [
        _snippet(rule, score=_case_score(rule, selected_playbook_ids))
        for rule in active_rules
        if rule.get("category") == "cases"
        and (not selected_playbook_ids or rule.get("playbook_id") in selected_playbook_ids)
    ]
    case_rules.sort(key=lambda item: (-(item.score or 0.0), item.id))

    hard_rules = _promote_required_hard_rules(hard_rules, required_hard_ids)

    return RetrievedRuleContext(
        mandatory_hard_rules=hard_rules,
        candidate_playbooks=[
            _snippet(rule, score=score)
            for score, rule in selected_playbooks
        ],
        soft_policies=soft_rules,
        case_memory=case_rules[:max_cases],
        all_rule_ids=sorted(index_rules),
    )


def list_indexed_paths() -> list[str]:
    """Return the generated artifact paths used by this retriever."""
    return [
        RULE_INDEX_PATH.as_posix(),
        RETRIEVER_MANIFEST_PATH.as_posix(),
    ]


def _load_generated_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleRetrievalError(f"{label} unavailable") from exc
    notice = payload.get("_generated_notice")
    if not isinstance(notice, str) or not notice.startswith(GENERATED_NOTICE_PREFIX):
        raise RuleRetrievalError(f"{label} missing generated marker")
    return payload


def _is_active_market_rule(rule: dict[str, Any], market: str) -> bool:
    return (
        rule.get("status") == "active"
        and isinstance(rule.get("markets"), list)
        and market in {str(item).lower() for item in rule["markets"]}
    )


def _playbook_score(
    rule: dict[str, Any],
    direction: str,
    regime: str,
    timeframe: str,
) -> float:
    directions = {str(item).lower() for item in rule.get("directions", [])}
    regimes = {str(item).upper() for item in rule.get("regimes", [])}
    timeframes = {str(item).lower() for item in rule.get("timeframes", [])}
    if directions and direction not in directions:
        return 0.0
    if regimes and regime not in regimes:
        return 0.0

    score = 0.45
    score += 0.25 if direction in directions else 0.0
    score += 0.2 if regime in regimes else 0.0
    score += 0.1 if not timeframes or timeframe in timeframes else 0.0
    return round(score, 4)


def _soft_score(rule: dict[str, Any], related_soft_ids: set[str], regime: str) -> float:
    score = 0.5
    if rule.get("id") in related_soft_ids:
        score += 0.35
    title = str(rule.get("title", "")).upper()
    description = str(rule.get("description", "")).upper()
    if regime.startswith("TRENDING") and "TREND" in f"{title} {description}":
        score += 0.1
    if regime == "RANGING" and "RANG" in f"{title} {description}":
        score += 0.1
    return round(score, 4)


def _case_score(rule: dict[str, Any], selected_playbook_ids: set[str]) -> float:
    if rule.get("playbook_id") in selected_playbook_ids:
        return 0.9
    return 0.5


def _promote_required_hard_rules(
    hard_rules: list[RuleSnippet],
    required_hard_ids: set[str],
) -> list[RuleSnippet]:
    if not required_hard_ids:
        return hard_rules
    return sorted(
        hard_rules,
        key=lambda item: (
            0 if item.id in required_hard_ids else 1,
            _hard_rule_priority(item.id),
            item.id,
        ),
    )


def _snippet(rule: dict[str, Any], *, score: float | None) -> RuleSnippet:
    return RuleSnippet(
        id=str(rule["id"]),
        title=str(rule.get("title", "")),
        category=str(rule.get("category", "")),
        markdown=str(rule.get("markdown", "")),
        score=score,
        source_path=str(rule.get("source_path", "")),
        metadata={
            "markets": list(rule.get("markets", [])),
            "directions": list(rule.get("directions", [])),
            "regimes": list(rule.get("regimes", [])),
            "timeframes": list(rule.get("timeframes", [])),
        },
    )


def _hard_rule_sort_key(rule: dict[str, Any]) -> tuple[int, str]:
    rule_id = str(rule.get("id", ""))
    return (_hard_rule_priority(rule_id), rule_id)


def _hard_rule_priority(rule_id: str) -> int:
    priority = {
        "HARD_DATA_001": 0,
        "HARD_MODE_001": 1,
        "HARD_LLM_001": 2,
        "HARD_EXECUTION_001": 3,
        "HARD_RISK_001": 4,
        "HARD_RISK_002": 5,
        "HARD_RISK_003": 6,
    }
    return priority.get(rule_id, 99)


def _dossier_str(dossier: MarketDossier | dict[str, Any], key: str) -> str:
    value = dossier.get(key) if isinstance(dossier, dict) else getattr(dossier, key)
    if not isinstance(value, str) or not value.strip():
        raise RuleRetrievalError(f"dossier.{key} is required")
    return value.strip()
