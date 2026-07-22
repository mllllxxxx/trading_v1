"""Deterministic risk and order compiler for approved trade tickets."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from schemas.models import (
    CompiledOrder,
    MarketDossier,
    SchemaValidationError,
    TradeAction,
    TradeDecisionTicket,
    VerifierResult,
    validate_trade_decision_ticket,
)
from verifier.rule_verifier import load_verifier_rules


class OrderCompilerError(RuntimeError):
    """Raised when an order cannot be compiled safely."""


OPEN_ACTIONS = {TradeAction.OPEN_LONG, TradeAction.OPEN_SHORT}


def compile_order(
    ticket: Mapping[str, Any] | TradeDecisionTicket,
    dossier: Mapping[str, Any] | MarketDossier,
    *,
    equity: float,
    price_levels: Mapping[str, Any] | None,
    verifier_result: Mapping[str, Any] | VerifierResult,
    hard_rules: Mapping[str, Mapping[str, Any]] | None = None,
    source: str = "risk_compiler.v1",
) -> CompiledOrder:
    """Compile approved trade intent into executable order parameters.

    The LLM may propose risk intent, but executable quantity is computed here
    from equity and stop distance. Any raw quantity field on the ticket payload
    is ignored.
    """
    ticket_obj = _coerce_ticket(ticket)
    dossier_map = _coerce_mapping(dossier, "dossier")
    _require_verifier_passed(verifier_result)

    if ticket_obj.action not in OPEN_ACTIONS:
        raise OrderCompilerError("only OPEN_LONG or OPEN_SHORT can compile to a new order")
    if ticket_obj.risk_plan is None or ticket_obj.entry_plan is None:
        raise OrderCompilerError("entry_plan and risk_plan are required")

    rules = dict(hard_rules or load_verifier_rules())
    max_risk_pct = _rule_field(rules, "HARD_RISK_001", "max_risk_pct_equity", default=0.01)
    max_position_pct = _rule_field(rules, "HARD_RISK_001", "max_position_pct", default=0.2)
    max_margin_pct = _rule_field(rules, "HARD_RISK_001", "max_margin_pct", default=0.2)
    max_gross_notional_pct = _rule_field(
        rules,
        "HARD_RISK_001",
        "max_gross_notional_pct",
        default=max_position_pct,
    )
    max_leverage = _rule_field(rules, "HARD_RISK_001", "max_leverage", default=3.0)
    rr_minimum = _rule_field(rules, "HARD_RISK_003", "rr_minimum", default=1.2)

    equity_dec = _positive_decimal(equity, "equity")
    levels = _resolve_price_levels(ticket_obj, dossier_map, price_levels)
    side = "buy" if ticket_obj.action is TradeAction.OPEN_LONG else "sell"

    entry = levels["entry"]
    stop_loss = levels["stop_loss"]
    take_profit = levels["take_profit"]
    _validate_directional_levels(side, entry, stop_loss, take_profit)

    stop_distance = abs(entry - stop_loss)
    reward_distance = abs(take_profit - entry)
    if stop_distance <= 0:
        raise OrderCompilerError("stop distance must be positive")
    rr_ratio = reward_distance / stop_distance
    if rr_ratio < Decimal(str(rr_minimum)):
        raise OrderCompilerError(
            f"reward-to-risk {float(rr_ratio):.4f} below minimum {rr_minimum:.4f}"
        )

    requested_risk_pct = _positive_decimal(ticket_obj.risk_plan.risk_pct_equity, "risk_pct_equity")
    target_risk_pct = _target_risk_pct(dossier_map, requested_risk_pct)
    cap_reasons: list[str] = []
    effective_risk_pct = min(requested_risk_pct, target_risk_pct, Decimal(str(max_risk_pct)))
    if effective_risk_pct < requested_risk_pct:
        cap_reasons.append("risk_target_or_hard_ceiling")
    risk_amount = equity_dec * effective_risk_pct
    units = risk_amount / stop_distance
    notional = units * entry

    max_notional_pct = min(
        Decimal(str(max_position_pct)),
        Decimal(str(max_gross_notional_pct)),
        Decimal(str(max_margin_pct)) * Decimal(str(max_leverage)),
    )
    max_notional = equity_dec * max_notional_pct
    if max_notional <= 0:
        raise OrderCompilerError("max position notional must be positive")
    if notional > max_notional:
        units = max_notional / entry
        notional = max_notional
        risk_amount = units * stop_distance
        effective_risk_pct = risk_amount / equity_dec
        cap_reasons.append("margin_or_gross_notional_cap")

    margin_used = notional / Decimal(str(max_leverage))

    return CompiledOrder(
        symbol=ticket_obj.symbol,
        side=side,
        entry=_price_float(entry),
        stop_loss=_price_float(stop_loss),
        take_profit=_price_float(take_profit),
        risk_pct_equity=_ratio_float(effective_risk_pct),
        risk_amount_usd=_money_float(risk_amount),
        position_size_units=_unit_float(units),
        position_notional_usd=_money_float(notional),
        source=source,
        requested_risk_pct_equity=_ratio_float(requested_risk_pct),
        target_risk_pct_equity=_ratio_float(target_risk_pct),
        actual_risk_pct_equity=_ratio_float(effective_risk_pct),
        risk_cap_reason=",".join(cap_reasons) or None,
        margin_used_usd=_money_float(margin_used),
        gross_notional_usd=_money_float(notional),
        leverage=_ratio_float(Decimal(str(max_leverage))),
    )


def _target_risk_pct(dossier: Mapping[str, Any], fallback: Decimal) -> Decimal:
    exposure = dossier.get("portfolio_exposure")
    if isinstance(exposure, Mapping):
        raw = exposure.get("target_risk_pct_equity")
        if raw is not None:
            try:
                parsed = Decimal(str(raw))
            except (InvalidOperation, ValueError):
                return fallback
            if parsed > 0:
                return parsed
    return fallback


def _coerce_ticket(ticket: Mapping[str, Any] | TradeDecisionTicket) -> TradeDecisionTicket:
    if isinstance(ticket, TradeDecisionTicket):
        return ticket
    try:
        return validate_trade_decision_ticket(dict(ticket))
    except SchemaValidationError as exc:
        raise OrderCompilerError(f"ticket schema invalid: {exc}") from exc


def _coerce_mapping(value: Mapping[str, Any] | MarketDossier, label: str) -> dict[str, Any]:
    if isinstance(value, MarketDossier):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise OrderCompilerError(f"{label} must be a mapping")


def _require_verifier_passed(result: Mapping[str, Any] | VerifierResult) -> None:
    if isinstance(result, VerifierResult):
        passed = result.passed
    elif isinstance(result, Mapping):
        passed = bool(result.get("passed", False))
    else:
        passed = False
    if not passed:
        raise OrderCompilerError("verifier_result.passed is required before compilation")


def _resolve_price_levels(
    ticket: TradeDecisionTicket,
    dossier: Mapping[str, Any],
    price_levels: Mapping[str, Any] | None,
) -> dict[str, Decimal]:
    levels = dict(price_levels or {})
    entry_raw = levels.get("entry")
    if entry_raw is None and ticket.entry_plan and ticket.entry_plan.order_type == "market":
        entry_raw = dossier.get("current_price")
    if entry_raw is None:
        raise OrderCompilerError("numeric entry is required")
    if levels.get("stop_loss") is None:
        raise OrderCompilerError("numeric stop_loss is required")
    if levels.get("take_profit") is None:
        raise OrderCompilerError("numeric take_profit is required")
    return {
        "entry": _positive_decimal(entry_raw, "entry"),
        "stop_loss": _positive_decimal(levels["stop_loss"], "stop_loss"),
        "take_profit": _positive_decimal(levels["take_profit"], "take_profit"),
    }


def _validate_directional_levels(
    side: str,
    entry: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
) -> None:
    if side == "buy":
        if not stop_loss < entry < take_profit:
            raise OrderCompilerError("long order requires stop_loss < entry < take_profit")
        return
    if not take_profit < entry < stop_loss:
        raise OrderCompilerError("short order requires take_profit < entry < stop_loss")


def _rule_field(
    rules: Mapping[str, Mapping[str, Any]],
    rule_id: str,
    field: str,
    *,
    default: float,
) -> float:
    rule = rules.get(rule_id, {})
    enforcement = rule.get("enforcement", {})
    fields = enforcement.get("fields", {}) if isinstance(enforcement, Mapping) else {}
    value = fields.get(field, default) if isinstance(fields, Mapping) else default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed <= 0:
        raise OrderCompilerError(f"{rule_id}.{field} must be positive")
    return parsed


def _positive_decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OrderCompilerError(f"{label} must be numeric") from exc
    if parsed <= 0:
        raise OrderCompilerError(f"{label} must be positive")
    return parsed


def _money_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _price_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _unit_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def _ratio_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
