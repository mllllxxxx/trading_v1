"""Promote SignalCandidate records into demo/paper executions."""

from __future__ import annotations

import re
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from execution import OKXDemoExecutionAdapter, PaperExecutionAdapter
from execution.base import ExecutionAdapter
from schemas.models import (
    CompiledOrder,
    SchemaValidationError,
    SignalCandidate,
    SignalDirection,
    SignalStatus,
    TradeAction,
    TradeDecisionTicket,
    validate_signal_candidate,
)
from strategy_teams import infer_team_id, resolve_team

try:
    from . import alerts, brain, exchange_reconciler, journal
    from .adaptive_hybrid import (
        AdaptiveTicketProvider,
        DecisionPolicy,
        build_adaptive_ticket_provider,
    )
    from .decision_pipeline import DecisionPipelineResult, TicketProvider, run_decision_pipeline
    from .market_dossier import MarketDossierBuildError, build_market_dossier
except ImportError:  # pragma: no cover - direct script/test import fallback
    import alerts  # type: ignore
    import brain  # type: ignore
    import exchange_reconciler  # type: ignore
    import journal  # type: ignore
    from adaptive_hybrid import (  # type: ignore
        AdaptiveTicketProvider,
        DecisionPolicy,
        build_adaptive_ticket_provider,
    )
    from decision_pipeline import DecisionPipelineResult, TicketProvider, run_decision_pipeline  # type: ignore
    from market_dossier import MarketDossierBuildError, build_market_dossier  # type: ignore

from llm.prompt_builder import build_trader_prompt
from market_features import max_confirmed_candle_age_s


JournalModule = Any
TicketClient = Callable[[list[dict[str, str]]], str | dict[str, Any]]


class SignalPipelineError(RuntimeError):
    """Raised when signal promotion cannot proceed safely."""


@dataclass(frozen=True)
class SignalDemoExecutionResult:
    """Journal-friendly result for one signal-to-demo attempt."""

    signal_id: str | None
    promoted: bool
    executed: bool
    stage: str
    reason: str
    decision_id: str
    signal: dict[str, Any] | None = None
    dossier: dict[str, Any] | None = None
    price_levels: dict[str, float] | None = None
    open_rationale: dict[str, Any] | None = None
    pipeline_result: dict[str, Any] | None = None
    order_result: dict[str, Any] | None = None
    decision_policy: str | None = None
    decision_lane: str | None = None
    rule_proposal: dict[str, Any] | None = None
    llm_review: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "promoted": self.promoted,
            "executed": self.executed,
            "stage": self.stage,
            "reason": self.reason,
            "decision_id": self.decision_id,
            "signal": self.signal,
            "dossier": self.dossier,
            "price_levels": self.price_levels,
            "open_rationale": self.open_rationale,
            "pipeline_result": self.pipeline_result,
            "order_result": self.order_result,
            "decision_policy": self.decision_policy,
            "decision_lane": self.decision_lane,
            "rule_proposal": self.rule_proposal,
            "llm_review": self.llm_review,
        }


def build_llm_ticket_provider(
    *,
    signal_candidates: list[Mapping[str, Any]],
    autonomy_mode: str = "paper",
    client: TicketClient | None = None,
) -> TicketProvider:
    """Return a ticket provider that asks the configured LLM for a ticket."""

    def _provider(dossier: dict[str, Any], retrieved_rules: dict[str, Any]) -> TradeDecisionTicket:
        messages = build_trader_prompt(
            market_dossier=dossier,
            retrieved_rules=retrieved_rules,
            signal_candidates=signal_candidates,
            autonomy_mode=autonomy_mode,
        )
        return brain.call_trade_decision_ticket(
            messages,
            known_rule_ids=_known_rule_ids(retrieved_rules),
            known_playbook_ids=_known_playbook_ids(retrieved_rules),
            client=client,
            budget_source=_budget_source(signal_candidates),
        )

    return _provider


def run_signal_to_demo_execution(
    signal_payload: Mapping[str, Any],
    *,
    ticket_provider: TicketProvider | None = None,
    ticket_client: TicketClient | None = None,
    execution_adapter: ExecutionAdapter | None = None,
    equity: float = 10_000,
    autonomy_mode: str = "paper",
    promotion_timeframe: str = "1h",
    max_signal_age_s: float = 3600.0,
    journal_module: JournalModule = journal,
    record_position: bool = True,
    decision_policy: DecisionPolicy | None = None,
) -> SignalDemoExecutionResult:
    """Run one eligible signal through LLM, verifier, compiler, and paper execution."""

    raw_signal = dict(signal_payload)
    decision_id = _decision_id(raw_signal)
    try:
        signal = validate_signal_candidate(raw_signal)
    except SchemaValidationError as exc:
        return _fail(
            decision_id=decision_id,
            signal_id=str(raw_signal.get("signal_id", "")) or None,
            stage="signal_validation",
            reason=f"signal_invalid: {exc}",
            journal_module=journal_module,
            signal=raw_signal,
        )

    signal_dict = signal.to_dict()
    _append_event(
        journal_module,
        "signal_candidate",
        decision_id,
        {
            "signal_id": signal.signal_id,
            "source": signal.source,
            "symbol": signal.symbol,
            "team_id": signal.team_id,
            "team_name": signal.team_name,
            "strategy_id": signal.strategy_id,
            "strategy_name": signal.strategy_name,
            "target_risk_pct_equity": signal.target_risk_pct_equity,
            "preferred_playbook_ids": list(signal.preferred_playbook_ids),
            "required_soft_policy_ids": list(signal.required_soft_policy_ids),
            "entry_style": signal.entry_style,
            "avoid_conditions": list(signal.avoid_conditions),
            "llm_guidance": signal.llm_guidance,
            "risk_personality": signal.risk_personality,
            "status": signal.status.value,
            "action_hint": signal.action_hint.value,
            "promotion_gate": signal.promotion_gate,
        },
        snapshots={"signal_candidate": signal_dict},
    )

    eligible, reason = _promotion_eligibility(signal)
    if not eligible:
        return _fail(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            stage="signal_gate",
            reason=reason,
            journal_module=journal_module,
            signal=signal_dict,
        )

    guard_ok, guard_reason = _pre_execution_guard(
        signal.symbol,
        journal_module,
        team_id=signal.team_id,
    )
    if not guard_ok:
        return _fail(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            stage="pre_execution_guard",
            reason=guard_reason,
            journal_module=journal_module,
            signal=signal_dict,
        )

    try:
        dossier = build_market_dossier_from_signal(
            signal,
            promotion_timeframe=promotion_timeframe,
            max_signal_age_s=max_signal_age_s,
            journal_module=journal_module,
        )
    except (MarketDossierBuildError, SignalPipelineError) as exc:
        return _fail(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            stage="market_dossier",
            reason=f"market_dossier_failed: {exc}",
            journal_module=journal_module,
            signal=signal_dict,
        )
    dossier_payload = dossier.to_dict()
    _append_event(
        journal_module,
        "market_dossier",
        decision_id,
        {"signal_id": signal.signal_id, "symbol": signal.symbol},
        snapshots={"market_dossier": dossier_payload},
    )

    try:
        price_levels = price_levels_from_signal(signal)
    except SignalPipelineError as exc:
        return _fail(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            stage="price_levels",
            reason=f"price_levels_failed: {exc}",
            journal_module=journal_module,
            signal=signal_dict,
            dossier=dossier_payload,
        )

    if ticket_provider is not None:
        provider = ticket_provider
    elif _decision_policy_name() == "adaptive_hybrid_v1":
        provider = build_adaptive_ticket_provider(
            signal,
            autonomy_mode=autonomy_mode,
            client=ticket_client,
            policy=decision_policy,
        )
    else:
        provider = build_llm_ticket_provider(
            signal_candidates=[signal_dict],
            autonomy_mode=autonomy_mode,
            client=ticket_client,
        )
    pipeline = run_decision_pipeline(
        dossier_payload,
        ticket_provider=provider,
        equity=equity,
        price_levels=price_levels,
    )
    if isinstance(provider, AdaptiveTicketProvider):
        metadata = provider.metadata
        pipeline = replace(
            pipeline,
            stage=_adaptive_pipeline_stage(pipeline.stage, metadata),
            decision_policy=metadata["decision_policy"],
            decision_lane=metadata["decision_lane"],
            rule_proposal=metadata["rule_proposal"],
            llm_review=metadata["llm_review"],
            reason=_adaptive_pipeline_reason(pipeline.reason, metadata),
        )
    _journal_pipeline_result(journal_module, decision_id, signal, pipeline)

    pipeline_payload = pipeline.to_dict()
    if not pipeline.approved or pipeline.compiled_order is None:
        return _fail(
            decision_id=decision_id,
            signal_id=signal.signal_id,
            stage=pipeline.stage,
            reason=pipeline.reason,
            journal_module=journal_module,
            signal=signal_dict,
            dossier=dossier_payload,
            price_levels=price_levels,
            pipeline_result=pipeline_payload,
            decision_policy=pipeline.decision_policy,
            decision_lane=pipeline.decision_lane,
            rule_proposal=pipeline.rule_proposal,
            llm_review=pipeline.llm_review,
        )

    compiled_order = CompiledOrder(**pipeline.compiled_order)
    open_rationale = build_trade_open_rationale(
        signal=signal,
        dossier=dossier_payload,
        price_levels=price_levels,
        pipeline=pipeline,
        compiled_order=compiled_order,
    )
    _append_event(
        journal_module,
        "trade_open_rationale",
        decision_id,
        {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "opened_because": open_rationale["opened_because"],
            "playbook_id": open_rationale["decision_context"].get("playbook_id"),
            "rule_citations": open_rationale["decision_context"].get("rule_citations", []),
            "profile_compliance_score": open_rationale["decision_context"].get("profile_compliance_score"),
        },
        snapshots={"trade_open_rationale": open_rationale},
    )

    adapter = execution_adapter or select_execution_adapter()
    try:
        order_result = adapter.place_bracket_order(
            compiled_order,
            idempotency_key=decision_id,
        )
        order_payload = order_result.to_dict()
    except Exception as exc:  # noqa: BLE001
        order_payload = {"status": "execution_failed", "error": str(exc), "raw": {}}
        _append_event(
            journal_module,
            "execution_result",
            decision_id,
            {"signal_id": signal.signal_id, "result": order_payload},
            snapshots={"execution_result": order_payload},
        )
        alerts.emit(
            "execution_failed",
            {
                "decision_id": decision_id,
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "team_id": signal.team_id,
                "team_name": signal.team_name,
                "where": "signal_pipeline",
                "error": str(exc),
            },
        )
        return SignalDemoExecutionResult(
            signal_id=signal.signal_id,
            promoted=True,
            executed=False,
            stage="execution",
            reason=f"execution_failed: {exc}",
            decision_id=decision_id,
            signal=signal_dict,
            dossier=dossier_payload,
            price_levels=price_levels,
            open_rationale=open_rationale,
            pipeline_result=pipeline_payload,
            order_result=order_payload,
            decision_policy=pipeline.decision_policy,
            decision_lane=pipeline.decision_lane,
            rule_proposal=pipeline.rule_proposal,
            llm_review=pipeline.llm_review,
        )

    _append_event(
        journal_module,
        "execution_result",
        decision_id,
        {"signal_id": signal.signal_id, "result": order_payload},
        snapshots={"execution_result": order_payload},
    )
    if record_position:
        _record_demo_position(
            journal_module,
            decision_id,
            signal.signal_id,
            compiled_order,
            order_payload,
            open_rationale,
        )
    execution_risk = _execution_risk_metrics(compiled_order, order_payload)
    alerts.emit(
        "trade_opened",
        {
            "decision_id": decision_id,
            "signal_id": signal.signal_id,
            "symbol": compiled_order.symbol,
            "side": compiled_order.side,
            "entry": compiled_order.entry,
            "stop_loss": compiled_order.stop_loss,
            "take_profit": compiled_order.take_profit,
            "position_size": execution_risk["position_size"],
            "risk_usd": execution_risk["risk_usd"],
            "team_id": signal.team_id,
            "team_name": signal.team_name,
            "status": "pending_entry" if _is_okx_demo_accepted(order_payload) else "open",
        },
    )

    return SignalDemoExecutionResult(
        signal_id=signal.signal_id,
        promoted=True,
        executed=True,
        stage="execution",
        reason=_execution_reason(order_payload),
        decision_id=decision_id,
        signal=signal_dict,
        dossier=dossier_payload,
        price_levels=price_levels,
        open_rationale=open_rationale,
        pipeline_result=pipeline_payload,
        order_result=order_payload,
        decision_policy=pipeline.decision_policy,
        decision_lane=pipeline.decision_lane,
        rule_proposal=pipeline.rule_proposal,
        llm_review=pipeline.llm_review,
    )


def select_execution_adapter(adapter_name: str | None = None) -> ExecutionAdapter:
    """Select the configured demo execution adapter."""
    raw = (
        adapter_name
        or os.getenv("SIGNAL_EXECUTION_ADAPTER")
        or os.getenv("BERKSHIRE_EXECUTION_ADAPTER")
        or "paper"
    )
    name = raw.strip().lower()
    if name in {"paper", "paper_demo", "dry_run", "replay"}:
        mode = "paper" if name in {"paper", "paper_demo"} else name
        return PaperExecutionAdapter(mode=mode)
    if name in {"okx_demo", "okx_testnet", "okx-paper", "okx_paper"}:
        return OKXDemoExecutionAdapter(dry_run=_env_bool("OKX_DEMO_ADAPTER_DRY_RUN", False))
    raise SignalPipelineError(f"unknown signal execution adapter: {raw}")


def build_trade_open_rationale(
    *,
    signal: SignalCandidate,
    dossier: Mapping[str, Any],
    price_levels: Mapping[str, float],
    pipeline: DecisionPipelineResult,
    compiled_order: CompiledOrder,
) -> dict[str, Any]:
    """Build replayable context explaining why an order is being opened."""
    ticket = pipeline.ticket or {}
    rule_ids = list(ticket.get("rule_citations") or [])
    market_context = {
        "symbol": dossier.get("symbol"),
        "market": dossier.get("market"),
        "timeframe": dossier.get("timeframe"),
        "current_price": dossier.get("current_price"),
        "candidate_direction": dossier.get("candidate_direction"),
        "confluence_score": dossier.get("confluence_score"),
        "regime": dossier.get("regime"),
        "trend_state": dossier.get("trend_state"),
        "volatility_state": dossier.get("volatility_state"),
        "data_quality": dossier.get("data_quality"),
        "data_source": dossier.get("data_source"),
        "data_age_s": dossier.get("data_age_s"),
        "spread_state": dossier.get("spread_state"),
        "funding_state": dossier.get("funding_state"),
        "portfolio_exposure": dossier.get("portfolio_exposure", {}),
    }
    risk_context = {
        "price_levels": dict(price_levels),
        "compiled_order": compiled_order.to_dict(),
        "rr_ratio": _rr(compiled_order),
        "entry_plan": ticket.get("entry_plan"),
        "risk_plan": ticket.get("risk_plan"),
        "invalidation_conditions": ticket.get("invalidation_conditions", []),
    }
    decision_context = {
        "ticket_decision_id": ticket.get("decision_id"),
        "action": ticket.get("action"),
        "thesis": ticket.get("thesis"),
        "reasoning_summary": ticket.get("reasoning_summary"),
        "confidence": ticket.get("confidence"),
        "playbook_id": ticket.get("playbook_id"),
        "rule_citations": rule_ids,
        "profile_compliance_score": ticket.get("profile_compliance_score"),
        "profile_compliance_summary": ticket.get("profile_compliance_summary"),
        "profile_compliance_flags": ticket.get("profile_compliance_flags", []),
        "critic_verdict": (pipeline.critic_review or {}).get("verdict"),
        "verifier_passed": (pipeline.verifier_result or {}).get("passed"),
        "checked_rule_ids": (pipeline.verifier_result or {}).get("checked_rule_ids", []),
        "decision_policy": pipeline.decision_policy,
        "decision_lane": pipeline.decision_lane,
        "rule_proposal": pipeline.rule_proposal,
        "llm_context_review": pipeline.llm_review,
    }
    source_context = {
        "signal_id": signal.signal_id,
        "source": signal.source,
        "team_id": signal.team_id,
        "team_name": signal.team_name,
        "strategy_id": signal.strategy_id,
        "strategy_name": signal.strategy_name,
        "team_capital_usd": signal.team_capital_usd,
        "target_risk_pct_equity": signal.target_risk_pct_equity,
        "preferred_playbook_ids": list(signal.preferred_playbook_ids),
        "required_soft_policy_ids": list(signal.required_soft_policy_ids),
        "entry_style": signal.entry_style,
        "avoid_conditions": list(signal.avoid_conditions),
        "llm_guidance": signal.llm_guidance,
        "risk_personality": signal.risk_personality,
        "status": signal.status.value,
        "direction": signal.direction.value,
        "score": signal.score,
        "confidence": signal.confidence,
        "grade": signal.grade.value,
        "reasons": list(signal.reasons),
        "blockers": list(signal.blockers),
        "evidence": dict(signal.evidence),
        "routing_experiment": (
            dict(signal.llm_context.get("routing_experiment"))
            if isinstance(signal.llm_context.get("routing_experiment"), Mapping)
            else None
        ),
    }
    opened_because = _opened_because(source_context, decision_context, market_context, risk_context)
    return {
        "schema_version": "trade_open_rationale.v1",
        "opened_because": opened_because,
        "source_context": source_context,
        "market_context": market_context,
        "decision_context": decision_context,
        "risk_context": risk_context,
    }


def build_market_dossier_from_signal(
    signal: SignalCandidate,
    *,
    promotion_timeframe: str = "1h",
    max_signal_age_s: float = 3600.0,
    journal_module: JournalModule = journal,
) -> Any:
    """Build a MarketDossier from signal evidence."""
    price = signal.last_price or signal.evidence.get("last_price")
    if price in (None, ""):
        raise SignalPipelineError("signal last_price is required")
    data_age_s = _market_data_age_s(signal)
    max_data_age_s = min(max_signal_age_s, max_confirmed_candle_age_s())
    if data_age_s > max_data_age_s:
        raise SignalPipelineError(f"confirmed candle evidence is stale: {data_age_s:.1f}s")
    return build_market_dossier(
        symbol=signal.symbol,
        market=signal.market,
        timeframe=promotion_timeframe,
        current_price=price,
        confluence=_confluence_from_signal(signal),
        regime=_regime_from_signal(signal),
        data_source=str(signal.evidence.get("provider_source") or signal.source),
        data_age_s=data_age_s,
        data_timestamp_utc=_optional_text(signal.evidence.get("data_timestamp_utc")),
        max_data_age_s=max_data_age_s,
        spread_state=_spread_state(signal),
        funding_state=str(signal.evidence.get("funding_state", "")) or None,
        open_positions_reader=getattr(journal_module, "read_positions", None),
        recent_trades_reader=getattr(journal_module, "read_closed_trades", None),
        portfolio_exposure={
            "source_signal_id": signal.signal_id,
            "source": signal.source,
            "team_id": signal.team_id,
            "team_name": signal.team_name,
            "strategy_id": signal.strategy_id,
            "strategy_name": signal.strategy_name,
            "target_risk_pct_equity": signal.target_risk_pct_equity,
            "preferred_playbook_ids": list(signal.preferred_playbook_ids),
            "required_soft_policy_ids": list(signal.required_soft_policy_ids),
            "entry_style": signal.entry_style,
            "avoid_conditions": list(signal.avoid_conditions),
            "llm_guidance": signal.llm_guidance,
            "risk_personality": signal.risk_personality,
        },
        feature_snapshot=_mapping(signal.evidence.get("feature_snapshot")),
        regime_evidence=_mapping(signal.evidence.get("regime_evidence")),
        setup_quality=_mapping(signal.evidence.get("setup_quality")),
    )


def price_levels_from_signal(signal: SignalCandidate) -> dict[str, float]:
    """Resolve numeric entry, stop, and target levels from signal evidence."""
    entry = _first_number(signal.last_price) or _midpoint(signal.entry_zone)
    stop_loss = _first_number(signal.invalidation)
    take_profit = _first_number(signal.target_zone)
    missing = [
        label
        for label, value in (
            ("entry", entry),
            ("stop_loss", stop_loss),
            ("take_profit", take_profit),
        )
        if value is None
    ]
    if missing:
        raise SignalPipelineError(f"missing numeric levels: {', '.join(missing)}")
    return {
        "entry": float(entry),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
    }


def _promotion_eligibility(signal: SignalCandidate) -> tuple[bool, str]:
    if signal.status not in {SignalStatus.STRONG_CANDIDATE, SignalStatus.CANDIDATE}:
        return False, f"signal_not_eligible: {signal.status.value}"
    if signal.direction not in {SignalDirection.LONG, SignalDirection.SHORT}:
        return False, "signal_not_directional"
    expected_action = TradeAction.OPEN_LONG if signal.direction is SignalDirection.LONG else TradeAction.OPEN_SHORT
    if signal.action_hint is not expected_action:
        return False, "signal_action_hint_mismatch"
    if signal.blockers:
        return False, "signal_has_blockers"
    if signal.promotion_gate != "eligible_for_draft_ticket":
        return False, f"promotion_gate_closed: {signal.promotion_gate}"
    return True, "eligible"


def _fail(
    *,
    decision_id: str,
    signal_id: str | None,
    stage: str,
    reason: str,
    journal_module: JournalModule,
    signal: dict[str, Any] | None = None,
    dossier: dict[str, Any] | None = None,
    price_levels: dict[str, float] | None = None,
    open_rationale: dict[str, Any] | None = None,
    pipeline_result: dict[str, Any] | None = None,
    decision_policy: str | None = None,
    decision_lane: str | None = None,
    rule_proposal: dict[str, Any] | None = None,
    llm_review: dict[str, Any] | None = None,
) -> SignalDemoExecutionResult:
    _append_event(
        journal_module,
        "fail_closed_skip",
        decision_id,
        {
            "signal_id": signal_id,
            "stage": stage,
            "reason": reason,
        },
    )
    alerts.emit(
        "fail_closed_skip",
        {
            "decision_id": decision_id,
            "signal_id": signal_id,
            "symbol": (signal or {}).get("symbol"),
            "team_id": (signal or {}).get("team_id"),
            "team_name": (signal or {}).get("team_name"),
            "stage": stage,
            "reason": reason,
        },
    )
    return SignalDemoExecutionResult(
        signal_id=signal_id,
        promoted=False,
        executed=False,
        stage=stage,
        reason=reason,
        decision_id=decision_id,
        signal=signal,
        dossier=dossier,
        price_levels=price_levels,
        open_rationale=open_rationale,
        pipeline_result=pipeline_result,
        decision_policy=decision_policy,
        decision_lane=decision_lane,
        rule_proposal=rule_proposal,
        llm_review=llm_review,
    )


def _journal_pipeline_result(
    journal_module: JournalModule,
    decision_id: str,
    signal: SignalCandidate,
    pipeline: DecisionPipelineResult,
) -> None:
    signal_id = signal.signal_id
    if pipeline.rule_proposal is not None:
        _append_event(
            journal_module,
            "rule_proposal",
            decision_id,
            {
                "signal_id": signal_id,
                "policy": pipeline.decision_policy,
                "zone": pipeline.rule_proposal.get("decision_zone"),
                "rule_score": pipeline.rule_proposal.get("rule_score"),
            },
            snapshots={"rule_proposal": pipeline.rule_proposal},
        )
        _append_event(
            journal_module,
            "hybrid_route",
            decision_id,
            {
                "signal_id": signal_id,
                "policy": pipeline.decision_policy,
                "lane": pipeline.decision_lane,
                "zone": pipeline.rule_proposal.get("decision_zone"),
                "llm_required": pipeline.rule_proposal.get("decision_zone") == "gray",
            },
        )
    if pipeline.llm_review is not None:
        _append_event(
            journal_module,
            "llm_context_review",
            decision_id,
            {
                "signal_id": signal_id,
                "decision": pipeline.llm_review.get("decision"),
                "risk_multiplier": pipeline.llm_review.get("risk_multiplier"),
            },
            snapshots={"llm_context_review": pipeline.llm_review},
        )
    if pipeline.retrieved_rules is not None:
        _append_event(
            journal_module,
            "rule_retrieval",
            decision_id,
            {"signal_id": signal_id, "stage": pipeline.stage},
            snapshots={"rules_context": pipeline.retrieved_rules},
        )
    if pipeline.ticket is not None and pipeline.decision_policy is None:
        _append_event(
            journal_module,
            "llm_draft_ticket",
            decision_id,
            {
                "signal_id": signal_id,
                "team_id": signal.team_id,
                "team_name": signal.team_name,
                "strategy_id": signal.strategy_id,
                "strategy_name": signal.strategy_name,
                "ticket_decision_id": pipeline.ticket.get("decision_id"),
                "profile_compliance_score": pipeline.ticket.get("profile_compliance_score"),
                "profile_compliance_summary": pipeline.ticket.get("profile_compliance_summary"),
                "profile_compliance_flags": pipeline.ticket.get("profile_compliance_flags", []),
            },
            snapshots={"ticket": pipeline.ticket},
        )
    if pipeline.ticket is not None:
        final_payload = {
            "signal_id": signal_id,
            "symbol": signal.symbol,
            "team_id": signal.team_id,
            "team_name": signal.team_name,
            "strategy_id": signal.strategy_id,
            "strategy_name": signal.strategy_name,
            "action": pipeline.ticket.get("action"),
            "confidence": pipeline.ticket.get("confidence"),
            "playbook_id": pipeline.ticket.get("playbook_id"),
            "stage": pipeline.stage,
            "reason": pipeline.reason,
        }
        _append_event(
            journal_module,
            "final_ticket",
            decision_id,
            final_payload,
            snapshots={"final_ticket": pipeline.ticket},
        )
        alerts.emit("final_ticket", final_payload)
    if pipeline.critic_review is not None:
        _append_event(
            journal_module,
            "critic_review",
            decision_id,
            {"signal_id": signal_id, "verdict": pipeline.critic_review.get("verdict")},
            snapshots={"critic_review": pipeline.critic_review},
        )
    if pipeline.verifier_result is not None:
        _append_event(
            journal_module,
            "rule_verification",
            decision_id,
            {"signal_id": signal_id, "passed": pipeline.verifier_result.get("passed")},
            snapshots={"verifier_result": pipeline.verifier_result},
        )
    if pipeline.compiled_order is not None:
        _append_event(
            journal_module,
            "risk_compilation",
            decision_id,
            {"signal_id": signal_id, "compiled": True},
            snapshots={"compiled_order": pipeline.compiled_order},
        )


def _record_demo_position(
    journal_module: JournalModule,
    decision_id: str,
    signal_id: str,
    order: CompiledOrder,
    order_result: dict[str, Any],
    open_rationale: dict[str, Any],
) -> None:
    is_okx_pending = _is_okx_demo_accepted(order_result)
    execution_risk = _execution_risk_metrics(order, order_result)
    opened_at = datetime.now(timezone.utc)
    pending_entry_expires_at = (
        opened_at + timedelta(seconds=max(1, _env_int("AUTO_PENDING_ENTRY_TTL_S", 3600)))
        if is_okx_pending
        else None
    )
    journal_module.add_position(
        {
            "position_id": decision_id,
            "symbol": order.symbol,
            "side": order.side,
            "entry": order.entry,
            "stop_loss": order.stop_loss,
            "take_profit": order.take_profit,
            "position_size": execution_risk["position_size"],
            "broker_contracts": execution_risk["broker_contracts"],
            "notional": execution_risk["gross_notional_usd"],
            "risk_usd": execution_risk["risk_usd"],
            "requested_risk_pct_equity": order.requested_risk_pct_equity,
            "actual_risk_pct_equity": execution_risk["actual_risk_pct_equity"],
            "risk_cap_reason": execution_risk["risk_cap_reason"],
            "margin_used_usd": execution_risk["margin_used_usd"],
            "gross_notional_usd": execution_risk["gross_notional_usd"],
            "leverage": execution_risk["leverage"],
            "rr_ratio": _rr(order),
            "confluence_score": open_rationale["market_context"].get("confluence_score"),
            "regime": open_rationale["market_context"].get("regime"),
            "source_signal_id": signal_id,
            "decision_id": decision_id,
            "team_id": open_rationale["source_context"].get("team_id"),
            "team_name": open_rationale["source_context"].get("team_name"),
            "strategy_id": open_rationale["source_context"].get("strategy_id"),
            "strategy_name": open_rationale["source_context"].get("strategy_name"),
            "team_capital_usd": open_rationale["source_context"].get("team_capital_usd"),
            "target_risk_pct_equity": open_rationale["source_context"].get("target_risk_pct_equity"),
            "preferred_playbook_ids": open_rationale["source_context"].get("preferred_playbook_ids", []),
            "required_soft_policy_ids": open_rationale["source_context"].get("required_soft_policy_ids", []),
            "entry_style": open_rationale["source_context"].get("entry_style"),
            "avoid_conditions": open_rationale["source_context"].get("avoid_conditions", []),
            "llm_guidance": open_rationale["source_context"].get("llm_guidance"),
            "risk_personality": open_rationale["source_context"].get("risk_personality"),
            "profile_compliance_score": open_rationale["decision_context"].get("profile_compliance_score"),
            "profile_compliance_summary": open_rationale["decision_context"].get("profile_compliance_summary"),
            "profile_compliance_flags": open_rationale["decision_context"].get("profile_compliance_flags", []),
            "decision_policy": open_rationale["decision_context"].get("decision_policy"),
            "decision_lane": open_rationale["decision_context"].get("decision_lane"),
            "rule_score": (open_rationale["decision_context"].get("rule_proposal") or {}).get("rule_score"),
            "score_components": (open_rationale["decision_context"].get("rule_proposal") or {}).get("score_components", {}),
            "rule_conflicts": (open_rationale["decision_context"].get("rule_proposal") or {}).get("conflicts", []),
            "llm_context_review": open_rationale["decision_context"].get("llm_context_review"),
            "routing_experiment": open_rationale["source_context"].get("routing_experiment"),
            "mode": _position_mode(order_result),
            "status": "pending_entry" if is_okx_pending else "open",
            "entry_filled": not is_okx_pending,
            "orders": _position_orders(order_result),
            "open_reason": open_rationale["opened_because"],
            "market_context": open_rationale["market_context"],
            "decision_context": open_rationale["decision_context"],
            "opened_at": opened_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "pending_entry_expires_at": (
                pending_entry_expires_at.isoformat(timespec="seconds").replace("+00:00", "Z")
                if pending_entry_expires_at is not None
                else None
            ),
        }
    )


def _execution_risk_metrics(
    order: CompiledOrder,
    order_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Prefer broker-sized risk metrics after contract rounding when available."""
    metrics: dict[str, Any] = {
        "position_size": order.position_size_units,
        "broker_contracts": None,
        "gross_notional_usd": order.gross_notional_usd,
        "risk_usd": order.risk_amount_usd,
        "actual_risk_pct_equity": order.actual_risk_pct_equity,
        "margin_used_usd": order.margin_used_usd,
        "leverage": order.leverage,
        "risk_cap_reason": order.risk_cap_reason,
    }
    raw = order_result.get("raw")
    proposal = raw.get("proposal") if isinstance(raw, Mapping) else None
    if not isinstance(proposal, Mapping):
        return metrics

    metrics.update(
        {
            "position_size": _positive_number(proposal.get("position_size_base"), metrics["position_size"]),
            "broker_contracts": _nonnegative_number(proposal.get("contracts")),
            "gross_notional_usd": _positive_number(
                proposal.get("position_notional"),
                metrics["gross_notional_usd"],
            ),
            "risk_usd": _positive_number(proposal.get("actual_risk_usd"), metrics["risk_usd"]),
            "margin_used_usd": _positive_number(
                proposal.get("margin_required"),
                metrics["margin_used_usd"],
            ),
            "leverage": _positive_number(proposal.get("leverage"), metrics["leverage"]),
        }
    )
    actual_risk_pct = _nonnegative_number(proposal.get("actual_risk_pct"))
    if actual_risk_pct is not None:
        metrics["actual_risk_pct_equity"] = actual_risk_pct / 100.0

    broker_risk = float(metrics["risk_usd"])
    if broker_risk + 1e-9 < float(order.risk_amount_usd):
        reasons = [reason for reason in str(order.risk_cap_reason or "").split(",") if reason]
        reasons.append("broker_contract_rounding")
        metrics["risk_cap_reason"] = ",".join(dict.fromkeys(reasons))
    return metrics


def _positive_number(value: Any, default: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed > 0 else float(default)


def _nonnegative_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _append_event(
    journal_module: JournalModule,
    event_type: str,
    decision_id: str,
    payload: dict[str, Any],
    *,
    snapshots: dict[str, Any] | None = None,
) -> None:
    journal_module.append_lifecycle_event(
        event_type,
        decision_id=decision_id,
        payload=payload,
        snapshots=snapshots,
    )


def _decision_id(signal: Mapping[str, Any]) -> str:
    raw_id = str(signal.get("signal_id", "")).strip() or "unknown"
    return f"sigexec_{raw_id}"


def _pre_execution_guard(
    symbol: str,
    journal_module: JournalModule,
    *,
    team_id: str | None = None,
) -> tuple[bool, str]:
    block_reason_fn = getattr(journal_module, "trading_block_reason", None)
    block_reason_raw = block_reason_fn() if callable(block_reason_fn) else ""
    block_reason = block_reason_raw if isinstance(block_reason_raw, str) else ""
    killed_fn = getattr(journal_module, "is_killed", lambda: False)
    if not block_reason and killed_fn() is True:
        block_reason = "kill_switch_active"
    if block_reason:
        return False, block_reason
    try:
        positions = list(getattr(journal_module, "read_positions")())
    except Exception as exc:  # noqa: BLE001
        return False, f"positions_guard_failed: {exc}"
    global_symbol_lock = _uses_okx_demo_adapter()
    if any(
        _same_symbol(str(position.get("symbol", "")), symbol)
        and (global_symbol_lock or _same_team_or_unknown(position, team_id))
        for position in positions
    ):
        return False, "symbol_position_already_open"
    if team_id:
        team_open = sum(1 for position in positions if infer_team_id(position) == team_id)
        team_max = _env_int("STRATEGY_TEAM_MAX_OPEN_POSITIONS", 1)
        if team_open >= team_max:
            return False, f"team_max_open_positions: {team_open} >= {team_max}"
    if _uses_okx_demo_adapter() and _env_bool("EXCHANGE_EXPOSURE_GUARD", True):
        try:
            active, _, snapshot = exchange_reconciler.has_active_exchange_exposure(symbol)
        except Exception as exc:  # noqa: BLE001
            return False, f"exchange_guard_failed: {exc}"
        if snapshot.get("errors"):
            return False, f"exchange_guard_failed: {'; '.join(str(item) for item in snapshot.get('errors', []))}"
        if active:
            return False, "exchange_position_already_open"
    max_positions = _env_int("AUTO_MAX_POSITIONS", 10)
    if len(positions) >= max_positions:
        return False, f"max_open_positions: {len(positions)} >= {max_positions}"
    return True, "ok"


def _same_team_or_unknown(position: Mapping[str, Any], team_id: str | None) -> bool:
    """Return whether an existing same-symbol position conflicts with a new team."""
    incoming = (team_id or "").strip()
    existing = str(position.get("team_id") or "").strip()
    if not incoming or not existing:
        return True
    return incoming == existing


def _uses_okx_demo_adapter() -> bool:
    raw = (
        os.getenv("SIGNAL_EXECUTION_ADAPTER")
        or os.getenv("BERKSHIRE_EXECUTION_ADAPTER")
        or ""
    ).strip().lower()
    return raw in {"okx_demo", "okx_testnet", "okx-paper", "okx_paper"}


def _same_symbol(left: str, right: str) -> bool:
    return _symbol_base(left) == _symbol_base(right)


def _symbol_base(symbol: str) -> str:
    raw = symbol.strip().upper()
    if raw.endswith("-SWAP"):
        raw = raw[: -len("-SWAP")]
    return raw.split("-", 1)[0] if "-" in raw else raw


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _position_mode(order_result: Mapping[str, Any]) -> str:
    status_value = str(order_result.get("status", ""))
    if status_value.startswith("okx_demo"):
        return "okx_demo"
    raw = order_result.get("raw")
    if isinstance(raw, Mapping):
        mode = raw.get("mode")
        if isinstance(mode, str) and mode:
            return mode
    return "paper"


def _is_okx_demo_accepted(order_result: Mapping[str, Any]) -> bool:
    return str(order_result.get("status", "")) == "okx_demo_accepted"


def _position_orders(order_result: Mapping[str, Any]) -> dict[str, Any]:
    """Return monitor-friendly order metadata for a journal position."""
    payload = dict(order_result)
    if _is_okx_demo_accepted(order_result):
        broker_id = order_result.get("broker_order_id")
        if broker_id:
            payload.setdefault("entry_id", str(broker_id))
    return payload


def _execution_reason(order_result: Mapping[str, Any]) -> str:
    status_value = str(order_result.get("status", ""))
    if status_value.startswith("okx_demo"):
        return "okx_demo_executed"
    return "paper_demo_executed"


def _opened_because(
    source_context: Mapping[str, Any],
    decision_context: Mapping[str, Any],
    market_context: Mapping[str, Any],
    risk_context: Mapping[str, Any],
) -> str:
    signal_reason = "; ".join(str(item) for item in source_context.get("reasons", [])[:2])
    thesis = str(decision_context.get("thesis") or decision_context.get("reasoning_summary") or "").strip()
    playbook = str(decision_context.get("playbook_id") or "unknown_playbook")
    regime = str(market_context.get("regime") or "unknown_regime")
    direction = str(market_context.get("candidate_direction") or source_context.get("direction") or "unknown")
    rr_ratio = risk_context.get("rr_ratio")
    team = str(source_context.get("team_name") or "Signal")
    compliance = decision_context.get("profile_compliance_score")
    compliance_text = ""
    if isinstance(compliance, (int, float)) and not isinstance(compliance, bool):
        compliance_text = f" Profile compliance {float(compliance):.2f}."
    thesis_label = "Decision thesis" if decision_context.get("decision_policy") else "LLM thesis"
    return (
        f"{team} {direction} setup promoted from {source_context.get('source')} because {signal_reason}. "
        f"{thesis_label}: {thesis}. Playbook {playbook}; regime {regime}; compiled R/R {rr_ratio}."
        f"{compliance_text}"
    )


def _decision_policy_name() -> str:
    """Return the selected operational profile; adaptive is the demo default."""
    return os.getenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1").strip().lower()


def _adaptive_pipeline_reason(reason: str, metadata: Mapping[str, Any]) -> str:
    """Replace legacy LLM labels with accurate adaptive route outcomes."""
    proposal = metadata.get("rule_proposal")
    proposal_map = proposal if isinstance(proposal, Mapping) else {}
    if reason == "llm_hold" and proposal_map.get("decision_zone") == "reject":
        return "adaptive_rule_reject"
    review = metadata.get("llm_review")
    review_map = review if isinstance(review, Mapping) else {}
    decision = str(review_map.get("decision") or "").upper()
    if reason == "llm_hold" and decision == "VETO":
        return "adaptive_llm_veto"
    if reason == "llm_request_more_data" and decision == "WAIT":
        return "adaptive_llm_wait"
    return reason


def _adaptive_pipeline_stage(stage: str, metadata: Mapping[str, Any]) -> str:
    """Name gray provider failures accurately without changing legacy stages."""
    proposal = metadata.get("rule_proposal")
    proposal_map = proposal if isinstance(proposal, Mapping) else {}
    if stage == "llm_ticket" and proposal_map.get("decision_zone") == "gray":
        return "llm_context_review"
    return stage


def _budget_source(signal_candidates: list[Mapping[str, Any]]) -> str:
    """Return a team-specific LLM budget bucket for the primary signal."""
    if not signal_candidates:
        return "strategy_team_signal"
    team_id = infer_team_id(signal_candidates[0])
    if team_id == "unassigned":
        return "strategy_team_signal"
    return f"{resolve_team(team_id).team_id}_signal"


def _confluence_from_signal(signal: SignalCandidate) -> float:
    raw = signal.evidence.get("confluence_score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SignalPipelineError("independent confluence_score evidence is required")
    score = float(raw)
    if not -5.0 <= score <= 5.0:
        raise SignalPipelineError("confluence_score must be between -5 and 5")
    return score


def _regime_from_signal(signal: SignalCandidate) -> str:
    raw = signal.evidence.get("regime")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raise SignalPipelineError("independent regime evidence is required")


def _market_data_age_s(signal: SignalCandidate) -> float:
    raw = signal.evidence.get("data_age_s")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, float(raw))
    timestamp = _optional_text(signal.evidence.get("data_timestamp_utc"))
    if timestamp:
        return _signal_age_s(timestamp)
    raise SignalPipelineError("confirmed candle data age is required")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _signal_age_s(generated_at: str) -> float:
    parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def _spread_state(signal: SignalCandidate) -> str | None:
    raw = signal.evidence.get("spread_bps")
    try:
        spread = float(raw)
    except (TypeError, ValueError):
        return None
    if spread <= 5:
        return "tight"
    if spread <= 15:
        return "normal"
    return "wide"


def _first_number(value: Any) -> float | None:
    if value is None:
        return None
    matches = _number_matches(str(value))
    return matches[0] if matches else None


def _midpoint(value: Any) -> float | None:
    matches = _number_matches(str(value or ""))
    if len(matches) >= 2:
        return (matches[0] + matches[1]) / 2.0
    return matches[0] if matches else None


def _number_matches(value: str) -> list[float]:
    numbers: list[float] = []
    for match in re.finditer(r"-?\d+(?:\.\d+)?", value):
        try:
            numbers.append(float(match.group(0)))
        except ValueError:
            continue
    return numbers


def _known_rule_ids(retrieved_rules: Mapping[str, Any]) -> set[str]:
    values = retrieved_rules.get("all_rule_ids", [])
    if isinstance(values, list):
        return {str(item) for item in values if str(item).strip()}
    return set()


def _known_playbook_ids(retrieved_rules: Mapping[str, Any]) -> set[str]:
    values = retrieved_rules.get("candidate_playbooks", [])
    if not isinstance(values, list):
        return set()
    return {
        str(item.get("id"))
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def _rr(order: CompiledOrder) -> float:
    risk = abs(order.entry - order.stop_loss)
    if risk <= 0:
        return 0.0
    return round(abs(order.take_profit - order.entry) / risk, 4)
