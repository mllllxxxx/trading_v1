"""Orchestrate the LLM-governed decision path without broker execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Mapping

from schemas.models import CompiledOrder, CriticVerdict, TradeDecisionTicket
from verifier.rule_verifier import verify_trade_ticket
from risk.order_compiler import OrderCompilerError, compile_order

try:
    from .critic import review_ticket
    from .rule_retriever import retrieve_rules
except ImportError:  # pragma: no cover - direct test/script import fallback
    from critic import review_ticket  # type: ignore
    from rule_retriever import retrieve_rules  # type: ignore


TicketProvider = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any] | TradeDecisionTicket]
RulesRetriever = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class DecisionPipelineResult:
    """Journal-friendly result for one decision pipeline run."""

    approved: bool
    stage: str
    reason: str
    dossier: dict[str, Any]
    retrieved_rules: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    critic_review: dict[str, Any] | None = None
    verifier_result: dict[str, Any] | None = None
    compiled_order: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "stage": self.stage,
            "reason": self.reason,
            "dossier": self.dossier,
            "retrieved_rules": self.retrieved_rules,
            "ticket": self.ticket,
            "critic_review": self.critic_review,
            "verifier_result": self.verifier_result,
            "compiled_order": self.compiled_order,
        }


def run_decision_pipeline(
    dossier: Mapping[str, Any],
    *,
    ticket_provider: TicketProvider,
    equity: float,
    price_levels: Mapping[str, Any] | None,
    rules_retriever: RulesRetriever = retrieve_rules,
    critic_fn: Callable[[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | TradeDecisionTicket], Any] = review_ticket,
    verifier_fn: Callable[[Mapping[str, Any] | TradeDecisionTicket, Mapping[str, Any], Mapping[str, Any]], Any] = verify_trade_ticket,
    compiler_fn: Callable[..., CompiledOrder] = compile_order,
) -> DecisionPipelineResult:
    """Run retrieval, LLM ticket, critic, verifier, and compiler in order.

    This function intentionally has no execution adapter argument. Broker calls
    belong after an approved `CompiledOrder` leaves this pipeline.
    """
    dossier_payload = dict(dossier)

    try:
        retrieved = rules_retriever(dossier_payload)
        retrieved_payload = _to_dict(retrieved)
    except Exception as exc:  # noqa: BLE001
        return _failed("rule_retrieval", "rule_retrieval_failed", dossier_payload, error=exc)

    try:
        ticket = ticket_provider(dossier_payload, retrieved_payload)
        ticket_payload = _to_dict(ticket)
    except Exception as exc:  # noqa: BLE001
        return _failed(
            "llm_ticket",
            "llm_failed",
            dossier_payload,
            retrieved_rules=retrieved_payload,
            error=exc,
        )

    try:
        critic_review = critic_fn(dossier_payload, retrieved_payload, ticket)
        critic_payload = _to_dict(critic_review)
    except Exception as exc:  # noqa: BLE001
        return _failed(
            "critic",
            "critic_failed",
            dossier_payload,
            retrieved_rules=retrieved_payload,
            ticket=ticket_payload,
            error=exc,
        )

    if str(critic_payload.get("verdict", "")).upper() != CriticVerdict.APPROVE.value:
        return DecisionPipelineResult(
            approved=False,
            stage="critic",
            reason="critic_reject",
            dossier=dossier_payload,
            retrieved_rules=retrieved_payload,
            ticket=ticket_payload,
            critic_review=critic_payload,
        )

    verification = verifier_fn(ticket, dossier_payload, retrieved_payload)
    verification_payload = _to_dict(verification)
    if not bool(verification_payload.get("passed", False)):
        return DecisionPipelineResult(
            approved=False,
            stage="verifier",
            reason="verifier_reject",
            dossier=dossier_payload,
            retrieved_rules=retrieved_payload,
            ticket=ticket_payload,
            critic_review=critic_payload,
            verifier_result=verification_payload,
        )

    try:
        compiled = compiler_fn(
            ticket,
            dossier_payload,
            equity=equity,
            price_levels=price_levels,
            verifier_result=verification,
        )
        compiled_payload = compiled.to_dict()
    except OrderCompilerError as exc:
        return DecisionPipelineResult(
            approved=False,
            stage="compiler",
            reason=f"order_compiler_failed: {exc}",
            dossier=dossier_payload,
            retrieved_rules=retrieved_payload,
            ticket=ticket_payload,
            critic_review=critic_payload,
            verifier_result=verification_payload,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(
            "compiler",
            "order_compiler_failed",
            dossier_payload,
            retrieved_rules=retrieved_payload,
            ticket=ticket_payload,
            error=exc,
        )

    return DecisionPipelineResult(
        approved=True,
        stage="compiled_order",
        reason="approved",
        dossier=dossier_payload,
        retrieved_rules=retrieved_payload,
        ticket=ticket_payload,
        critic_review=critic_payload,
        verifier_result=verification_payload,
        compiled_order=compiled_payload,
    )


def _failed(
    stage: str,
    reason: str,
    dossier: dict[str, Any],
    *,
    retrieved_rules: dict[str, Any] | None = None,
    ticket: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> DecisionPipelineResult:
    message = reason if error is None else f"{reason}: {error}"
    return DecisionPipelineResult(
        approved=False,
        stage=stage,
        reason=message,
        dossier=dossier,
        retrieved_rules=retrieved_rules,
        ticket=ticket,
    )


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"pipeline value is not serializable: {type(value).__name__}")
