"""Rule-based risk critic for draft TradeDecisionTicket payloads."""

from __future__ import annotations

from typing import Any, Mapping

from schemas.models import CriticReview, CriticVerdict, TradeAction, TradeDecisionTicket
from verifier.rule_verifier import load_verifier_rules


def review_ticket(
    dossier: Mapping[str, Any],
    retrieved_rules: Mapping[str, Any],
    draft_ticket: Mapping[str, Any] | TradeDecisionTicket,
) -> CriticReview:
    """Review contextual consistency without duplicating the final verifier."""
    ticket = draft_ticket.to_dict() if isinstance(draft_ticket, TradeDecisionTicket) else dict(draft_ticket)
    concerns: list[str] = []
    cited_rules: list[str] = []
    action = str(ticket.get("action") or "").upper()
    if action in {TradeAction.HOLD.value, TradeAction.REQUEST_MORE_DATA.value}:
        return CriticReview(
            verdict=CriticVerdict.APPROVE,
            concerns=[],
            cited_rules=[],
            suggested_changes={"recommended_action": "KEEP"},
        )

    for field in ("symbol", "market", "timeframe"):
        if str(ticket.get(field) or "").strip().lower() != str(dossier.get(field) or "").strip().lower():
            concerns.append(f"ticket {field} does not match dossier")
            cited_rules.append("HARD_LLM_002")
    expected_direction = str(dossier.get("candidate_direction") or "").lower()
    ticket_direction = "long" if action == TradeAction.OPEN_LONG.value else "short" if action == TradeAction.OPEN_SHORT.value else ""
    if ticket_direction and ticket_direction != expected_direction:
        concerns.append("ticket action direction conflicts with dossier")
        cited_rules.append("HARD_LLM_002")

    known_ids = {
        str(item)
        for item in retrieved_rules.get("all_rule_ids", [])
        if isinstance(item, str)
    }
    unknown_ids = sorted(
        str(item)
        for item in ticket.get("rule_citations", [])
        if isinstance(item, str) and item not in known_ids
    )
    if unknown_ids:
        concerns.append(f"unknown rule citations: {', '.join(unknown_ids)}")
        cited_rules.append("HARD_LLM_001")

    risk_plan = ticket.get("risk_plan")
    risk_map = risk_plan if isinstance(risk_plan, Mapping) else {}
    try:
        requested_risk = float(risk_map.get("risk_pct_equity", 0))
        hard_rules = load_verifier_rules()
        max_risk = float(
            hard_rules.get("HARD_RISK_001", {})
            .get("enforcement", {})
            .get("fields", {})
            .get("max_risk_pct_equity", 0)
        )
    except (TypeError, ValueError):
        requested_risk = 0.0
        max_risk = 0.0
    if max_risk > 0 and requested_risk > max_risk:
        concerns.append(f"risk_pct_equity {requested_risk:.4f} exceeds {max_risk:.4f}")
        cited_rules.append("HARD_RISK_001")

    if not concerns:
        return CriticReview(
            verdict=CriticVerdict.APPROVE,
            concerns=[],
            cited_rules=[],
            suggested_changes={"recommended_action": "KEEP"},
        )
    return CriticReview(
        verdict=CriticVerdict.REJECT,
        concerns=concerns,
        cited_rules=sorted(set(cited_rules)),
        suggested_changes={
            "recommended_action": "HOLD",
            "context_conflicts": concerns,
        },
    )
