"""Verify TradeDecisionTicket payloads against compiled hard rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from schemas.models import (
    DataQuality,
    SchemaValidationError,
    TradeAction,
    TradeDecisionTicket,
    VerifierResult,
    validate_trade_decision_ticket,
)


TRADING_ROOT = Path(__file__).resolve().parents[1]
COMPILED_ROOT = TRADING_ROOT / "rulebook" / "compiled"
VERIFIER_RULES_PATH = COMPILED_ROOT / "verifier_rules.json"
RETRIEVER_MANIFEST_PATH = COMPILED_ROOT / "retriever_manifest.json"
GENERATED_NOTICE_PREFIX = "DO NOT EDIT - generated from trading/rulebook/source"
NON_HOLD_ACTIONS = {
    TradeAction.OPEN_LONG,
    TradeAction.OPEN_SHORT,
    TradeAction.CLOSE_POSITION,
    TradeAction.REDUCE_POSITION,
}


class RuleVerifierError(RuntimeError):
    """Raised when verifier inputs or compiled artifacts are unsafe."""


def load_verifier_rules(path: Path = VERIFIER_RULES_PATH) -> dict[str, dict[str, Any]]:
    """Load generated hard rules keyed by rule ID."""
    payload = _load_generated_json(path, "verifier rules")
    hard_rules = payload.get("hard_rules")
    if not isinstance(hard_rules, list):
        raise RuleVerifierError("verifier rules missing hard_rules list")
    rules: dict[str, dict[str, Any]] = {}
    for item in hard_rules:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise RuleVerifierError("verifier rule item is malformed")
        rules[item["id"]] = item
    return rules


def verify_trade_ticket(
    ticket: Mapping[str, Any] | TradeDecisionTicket,
    dossier: Mapping[str, Any],
    retrieved_rules: Mapping[str, Any],
    *,
    verifier_rules_path: Path = VERIFIER_RULES_PATH,
    retriever_manifest_path: Path = RETRIEVER_MANIFEST_PATH,
) -> VerifierResult:
    """Return a fail-closed verifier result for a draft trade ticket."""
    try:
        hard_rules = load_verifier_rules(verifier_rules_path)
        manifest = _load_manifest(retriever_manifest_path)
        checked_rule_ids = sorted(hard_rules)
        violations: list[dict[str, Any]] = []

        ticket_obj = _coerce_ticket(ticket, manifest, violations)
        if ticket_obj is None:
            return VerifierResult(
                passed=False,
                violations=violations,
                checked_rule_ids=checked_rule_ids,
            )

        if ticket_obj.action in {TradeAction.HOLD, TradeAction.REQUEST_MORE_DATA}:
            return VerifierResult(
                passed=True,
                violations=[],
                checked_rule_ids=checked_rule_ids,
            )

        _check_context_binding(ticket_obj, dossier, violations)
        _check_market_data(ticket_obj, dossier, violations)
        _check_playbook_scope(ticket_obj, dossier, retrieved_rules, manifest, violations)
        _check_required_hard_citations(ticket_obj, manifest, violations)
        _check_profile_compliance(ticket_obj, dossier, hard_rules, violations)
        _check_risk_plan(ticket_obj, hard_rules, violations)

        return VerifierResult(
            passed=not violations,
            violations=violations,
            checked_rule_ids=checked_rule_ids,
        )
    except Exception as exc:  # noqa: BLE001
        return VerifierResult(
            passed=False,
            violations=[
                _violation(
                    "SYSTEM_VERIFIER",
                    "reject_order",
                    f"verifier failed closed: {exc}",
                    repair_allowed=False,
                )
            ],
            checked_rule_ids=[],
        )


def _coerce_ticket(
    ticket: Mapping[str, Any] | TradeDecisionTicket,
    manifest: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, Any]],
) -> TradeDecisionTicket | None:
    if isinstance(ticket, TradeDecisionTicket):
        return ticket
    payload = dict(ticket)
    known_rule_ids = set(manifest)
    known_playbook_ids = {
        rule_id
        for rule_id, meta in manifest.items()
        if meta.get("category") == "playbooks"
    }
    try:
        return validate_trade_decision_ticket(
            payload,
            known_rule_ids=known_rule_ids,
            known_playbook_ids=known_playbook_ids,
        )
    except SchemaValidationError as exc:
        message = str(exc)
        rule_id = "HARD_LLM_001" if "rule" in message or "playbook" in message else "HARD_LLM_002"
        violations.append(_violation(rule_id, "reject_order", message))
        return None


def _check_market_data(
    ticket: TradeDecisionTicket,
    dossier: Mapping[str, Any],
    violations: list[dict[str, Any]],
) -> None:
    dossier_quality = str(dossier.get("data_quality", "")).upper()
    if ticket.data_quality in {DataQuality.C, DataQuality.UNKNOWN} or dossier_quality in {"C", "UNKNOWN"}:
        violations.append(
            _violation("HARD_DATA_001", "reject_order", "non-HOLD ticket requires acceptable data quality")
        )

    try:
        current_price = float(dossier.get("current_price", 0))
    except (TypeError, ValueError):
        current_price = 0.0
    if current_price <= 0:
        violations.append(
            _violation("HARD_DATA_001", "reject_order", "market dossier current_price must be positive")
        )


def _check_context_binding(
    ticket: TradeDecisionTicket,
    dossier: Mapping[str, Any],
    violations: list[dict[str, Any]],
) -> None:
    """Bind order identity and direction to the trusted market dossier."""
    comparisons = (
        ("symbol", ticket.symbol, dossier.get("symbol")),
        ("market", ticket.market, dossier.get("market")),
        ("timeframe", ticket.timeframe, dossier.get("timeframe")),
    )
    for label, ticket_value, dossier_value in comparisons:
        if str(ticket_value).strip().lower() != str(dossier_value or "").strip().lower():
            violations.append(
                _violation(
                    "HARD_LLM_002",
                    "reject_order",
                    f"ticket {label} does not match market dossier",
                )
            )
    ticket_direction = _ticket_direction(ticket)
    dossier_direction = str(dossier.get("candidate_direction") or "").strip().lower()
    if ticket_direction and ticket_direction != dossier_direction:
        violations.append(
            _violation(
                "HARD_LLM_002",
                "reject_order",
                "ticket opening direction does not match market dossier",
            )
        )


def _check_playbook_scope(
    ticket: TradeDecisionTicket,
    dossier: Mapping[str, Any],
    retrieved_rules: Mapping[str, Any],
    manifest: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, Any]],
) -> None:
    if not ticket.playbook_id:
        violations.append(_violation("HARD_LLM_001", "reject_order", "non-HOLD ticket requires playbook_id"))
        return

    candidate_ids = _candidate_playbook_ids(retrieved_rules)
    if candidate_ids and ticket.playbook_id not in candidate_ids:
        violations.append(
            _violation("HARD_LLM_001", "reject_order", "playbook_id was not retrieved for this dossier")
        )

    playbook = manifest.get(ticket.playbook_id)
    if not playbook:
        violations.append(_violation("HARD_LLM_001", "reject_order", "playbook_id does not exist"))
        return

    market = str(dossier.get("market", "")).lower()
    markets = {str(item).lower() for item in playbook.get("markets", [])}
    if markets and market not in markets:
        violations.append(_violation("HARD_LLM_001", "reject_order", "playbook market does not match dossier"))

    direction = _ticket_direction(ticket) or str(dossier.get("candidate_direction", "")).lower()
    directions = {str(item).lower() for item in playbook.get("directions", [])}
    if direction in {"long", "short"} and directions and direction not in directions:
        violations.append(_violation("HARD_LLM_001", "reject_order", "playbook direction does not match action"))

    regime = str(dossier.get("regime", "")).upper()
    regimes = {str(item).upper() for item in playbook.get("regimes", [])}
    if regimes and regime not in regimes:
        violations.append(_violation("HARD_LLM_001", "reject_order", "playbook regime does not match dossier"))

    timeframe = str(dossier.get("timeframe", "")).lower()
    timeframes = {str(item).lower() for item in playbook.get("timeframes", [])}
    if timeframes and timeframe not in timeframes:
        violations.append(_violation("HARD_LLM_001", "reject_order", "playbook timeframe does not match dossier"))


def _check_required_hard_citations(
    ticket: TradeDecisionTicket,
    manifest: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, Any]],
) -> None:
    if not ticket.playbook_id:
        return
    playbook = manifest.get(ticket.playbook_id, {})
    required = {
        str(rule_id)
        for rule_id in playbook.get("required_hard_rules", [])
        if isinstance(rule_id, str)
    }
    missing = sorted(required - set(ticket.rule_citations))
    if missing:
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                f"missing required hard rule citations: {', '.join(missing)}",
            )
        )


def _check_profile_compliance(
    ticket: TradeDecisionTicket,
    dossier: Mapping[str, Any],
    hard_rules: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, Any]],
) -> None:
    if ticket.action not in {TradeAction.OPEN_LONG, TradeAction.OPEN_SHORT}:
        return

    exposure = dossier.get("portfolio_exposure", {})
    exposure_map = exposure if isinstance(exposure, Mapping) else {}
    preferred_playbooks = _string_set(exposure_map.get("preferred_playbook_ids"))
    if not preferred_playbooks:
        return

    if not ticket.playbook_id or ticket.playbook_id not in preferred_playbooks:
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                "team-profile open ticket must use a preferred playbook_id",
            )
        )

    min_score = _field(
        hard_rules,
        "HARD_LLM_001",
        "min_profile_compliance_score",
        default=0.6,
    )
    score = ticket.profile_compliance_score
    if score is None:
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                "team-profile open ticket requires profile_compliance_score",
            )
        )
    elif not 0.0 <= float(score) <= 1.0:
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                "profile_compliance_score must be between 0.0 and 1.0",
            )
        )
    elif float(score) < min_score:
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                f"profile_compliance_score {float(score):.2f} is below minimum {min_score:.2f}",
            )
        )

    if not (ticket.profile_compliance_summary or "").strip():
        violations.append(
            _violation(
                "HARD_LLM_001",
                "reject_order",
                "team-profile open ticket requires profile_compliance_summary",
            )
        )


def _check_risk_plan(
    ticket: TradeDecisionTicket,
    hard_rules: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, Any]],
) -> None:
    if ticket.action not in {TradeAction.OPEN_LONG, TradeAction.OPEN_SHORT}:
        return
    if ticket.risk_plan is None:
        violations.append(_violation("HARD_RISK_002", "reject_order", "risk_plan is required"))
        return
    risk_pct = float(ticket.risk_plan.risk_pct_equity)
    max_risk = _field(hard_rules, "HARD_RISK_001", "max_risk_pct_equity", default=0.0)
    if max_risk > 0 and risk_pct > max_risk:
        violations.append(
            _violation(
                "HARD_RISK_001",
                "reject_order",
                f"risk_pct_equity {risk_pct:.4f} exceeds compiled max {max_risk:.4f}",
            )
        )
    if not ticket.risk_plan.stop_logic.strip() or not ticket.risk_plan.take_profit_logic.strip():
        violations.append(
            _violation("HARD_RISK_002", "reject_order", "stop and take-profit logic are required")
        )


def _candidate_playbook_ids(retrieved_rules: Mapping[str, Any]) -> set[str]:
    values = retrieved_rules.get("candidate_playbooks", [])
    if not isinstance(values, list):
        return set()
    return {
        str(item.get("id"))
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def _ticket_direction(ticket: TradeDecisionTicket) -> str | None:
    if ticket.action is TradeAction.OPEN_LONG:
        return "long"
    if ticket.action is TradeAction.OPEN_SHORT:
        return "short"
    return None


def _string_set(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value if isinstance(item, str) and item.strip()}
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    return set()


def _field(
    hard_rules: Mapping[str, Mapping[str, Any]],
    rule_id: str,
    field: str,
    *,
    default: float,
) -> float:
    rule = hard_rules.get(rule_id, {})
    enforcement = rule.get("enforcement", {})
    fields = enforcement.get("fields", {}) if isinstance(enforcement, Mapping) else {}
    value = fields.get(field, default) if isinstance(fields, Mapping) else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_generated_json(path, "retriever manifest")
    rules = payload.get("rules")
    if not isinstance(rules, dict):
        raise RuleVerifierError("retriever manifest missing rules")
    return {
        str(rule_id): dict(meta)
        for rule_id, meta in rules.items()
        if isinstance(meta, Mapping)
    }


def _load_generated_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuleVerifierError(f"{label} unavailable") from exc
    notice = payload.get("_generated_notice")
    if not isinstance(notice, str) or not notice.startswith(GENERATED_NOTICE_PREFIX):
        raise RuleVerifierError(f"{label} missing generated marker")
    return payload


def _violation(
    rule_id: str,
    severity: str,
    message: str,
    *,
    repair_allowed: bool = False,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "repair_allowed": repair_allowed,
    }
