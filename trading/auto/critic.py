"""Rule-based risk critic for draft TradeDecisionTicket payloads."""

from __future__ import annotations

from typing import Any, Mapping

from schemas.models import CriticReview, CriticVerdict
from verifier.rule_verifier import verify_trade_ticket


def review_ticket(
    dossier: Mapping[str, Any],
    retrieved_rules: Mapping[str, Any],
    draft_ticket: Mapping[str, Any],
) -> CriticReview:
    """Review a draft ticket without broker calls or order creation."""
    verification = verify_trade_ticket(draft_ticket, dossier, retrieved_rules)
    if verification.passed:
        return CriticReview(
            verdict=CriticVerdict.APPROVE,
            concerns=[],
            cited_rules=[],
            suggested_changes={"recommended_action": "KEEP"},
        )

    violations = verification.violations
    cited_rules = sorted(
        {
            str(item.get("rule_id"))
            for item in violations
            if isinstance(item, Mapping) and item.get("rule_id")
        }
    )
    concerns = [
        str(item.get("message", "critic concern"))
        for item in violations
        if isinstance(item, Mapping)
    ]
    hard_violation = any(
        str(item.get("severity", "")).lower() in {"reject", "reject_order", "hard_violation"}
        for item in violations
        if isinstance(item, Mapping)
    )
    return CriticReview(
        verdict=CriticVerdict.REJECT if hard_violation else CriticVerdict.REVISE,
        concerns=concerns,
        cited_rules=cited_rules,
        suggested_changes={
            "recommended_action": "HOLD" if hard_violation else "REDUCE_RISK",
            "violations": violations,
        },
    )
