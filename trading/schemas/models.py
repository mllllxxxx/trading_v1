"""Dataclass contracts for the LLM-governed decision pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when a schema payload violates the shared contract."""


class TradeAction(str, Enum):
    """Allowed LLM decision actions."""

    HOLD = "HOLD"
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_POSITION = "CLOSE_POSITION"
    REDUCE_POSITION = "REDUCE_POSITION"
    REQUEST_MORE_DATA = "REQUEST_MORE_DATA"


class DataQuality(str, Enum):
    """Allowed market data quality grades."""

    A = "A"
    B = "B"
    C = "C"
    UNKNOWN = "UNKNOWN"


class CriticVerdict(str, Enum):
    """Allowed critic review outcomes."""

    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


@dataclass(frozen=True)
class EntryPlan:
    """LLM-proposed entry intent, not executable broker parameters."""

    order_type: str
    entry_reference: str
    chase_market: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EntryPlan":
        _require_mapping(payload, "entry_plan")
        order_type = _require_str(payload, "order_type")
        if order_type not in {"market", "limit", "none"}:
            raise SchemaValidationError("entry_plan.order_type must be market, limit, or none")
        return cls(
            order_type=order_type,
            entry_reference=_require_str(payload, "entry_reference"),
            chase_market=bool(payload.get("chase_market", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskPlan:
    """LLM-proposed risk intent, later compiled by code."""

    risk_pct_equity: float
    stop_logic: str
    take_profit_logic: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RiskPlan":
        _require_mapping(payload, "risk_plan")
        risk_pct = _require_number(payload, "risk_pct_equity")
        if risk_pct < 0:
            raise SchemaValidationError("risk_plan.risk_pct_equity must be >= 0")
        return cls(
            risk_pct_equity=risk_pct,
            stop_logic=_require_str(payload, "stop_logic"),
            take_profit_logic=_require_str(payload, "take_profit_logic"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketDossier:
    """Normalized market context supplied to the LLM and verifier."""

    symbol: str
    market: str
    timeframe: str
    current_price: float
    confluence_score: float
    candidate_direction: str
    regime: str
    trend_state: str
    volatility_state: str
    data_source: str
    data_age_s: float
    data_quality: DataQuality
    spread_state: str | None = None
    funding_state: str | None = None
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    portfolio_exposure: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["data_quality"] = self.data_quality.value
        return data


@dataclass(frozen=True)
class RuleSnippet:
    """Prompt-ready rulebook context selected by the retriever."""

    id: str
    markdown: str
    title: str | None = None
    category: str | None = None
    score: float | None = None
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievedRuleContext:
    """Rulebook context retrieved for one decision cycle."""

    mandatory_hard_rules: list[RuleSnippet]
    candidate_playbooks: list[RuleSnippet]
    soft_policies: list[RuleSnippet]
    case_memory: list[RuleSnippet]
    all_rule_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mandatory_hard_rules": [_snippet_to_dict(item) for item in self.mandatory_hard_rules],
            "candidate_playbooks": [_snippet_to_dict(item) for item in self.candidate_playbooks],
            "soft_policies": [_snippet_to_dict(item) for item in self.soft_policies],
            "case_memory": [_snippet_to_dict(item) for item in self.case_memory],
            "all_rule_ids": list(self.all_rule_ids),
        }


@dataclass(frozen=True)
class TradeDecisionTicket:
    """LLM-produced trade intent contract."""

    decision_id: str
    timestamp_utc: str
    action: TradeAction
    market: str
    symbol: str
    timeframe: str
    playbook_id: str | None
    rule_citations: list[str]
    thesis: str
    entry_plan: EntryPlan | None
    risk_plan: RiskPlan | None
    invalidation_conditions: list[str]
    confidence: float
    data_quality: DataQuality
    reasoning_summary: str

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        known_rule_ids: set[str] | None = None,
        known_playbook_ids: set[str] | None = None,
    ) -> "TradeDecisionTicket":
        """Parse and validate a ticket payload."""
        _require_mapping(payload, "ticket")
        action = _parse_enum(TradeAction, _require_str(payload, "action"), "action")
        data_quality = _parse_enum(
            DataQuality,
            _require_str(payload, "data_quality"),
            "data_quality",
        )
        confidence = _require_number(payload, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise SchemaValidationError("confidence must be between 0.0 and 1.0")

        timestamp_utc = _require_str(payload, "timestamp_utc")
        _parse_timestamp(timestamp_utc)

        rule_citations = _string_list(payload.get("rule_citations", []), "rule_citations")
        playbook_id = payload.get("playbook_id")
        if playbook_id is not None and not isinstance(playbook_id, str):
            raise SchemaValidationError("playbook_id must be a string or null")

        entry_payload = payload.get("entry_plan")
        risk_payload = payload.get("risk_plan")
        entry_plan = EntryPlan.from_dict(entry_payload) if entry_payload is not None else None
        risk_plan = RiskPlan.from_dict(risk_payload) if risk_payload is not None else None
        invalidation_conditions = _string_list(
            payload.get("invalidation_conditions", []),
            "invalidation_conditions",
        )

        if action != TradeAction.HOLD:
            if not playbook_id:
                raise SchemaValidationError("non-HOLD ticket requires playbook_id")
            if not rule_citations:
                raise SchemaValidationError("non-HOLD ticket requires rule_citations")
            if not any(rule_id.startswith("HARD_") for rule_id in rule_citations):
                raise SchemaValidationError("non-HOLD ticket requires at least one HARD_ rule citation")
            if entry_plan is None:
                raise SchemaValidationError("non-HOLD ticket requires entry_plan")
            if risk_plan is None:
                raise SchemaValidationError("non-HOLD ticket requires risk_plan")
            if not invalidation_conditions:
                raise SchemaValidationError("non-HOLD ticket requires invalidation_conditions")

        if known_rule_ids is not None:
            unknown_rules = sorted(rule_id for rule_id in rule_citations if rule_id not in known_rule_ids)
            if unknown_rules:
                raise SchemaValidationError(
                    f"unknown rule citations: {', '.join(unknown_rules)}"
                )

        if known_playbook_ids is not None and playbook_id:
            if playbook_id not in known_playbook_ids:
                raise SchemaValidationError(f"unknown playbook_id: {playbook_id}")

        return cls(
            decision_id=_require_str(payload, "decision_id"),
            timestamp_utc=timestamp_utc,
            action=action,
            market=_require_str(payload, "market"),
            symbol=_require_str(payload, "symbol"),
            timeframe=_require_str(payload, "timeframe"),
            playbook_id=playbook_id,
            rule_citations=rule_citations,
            thesis=_require_str(payload, "thesis"),
            entry_plan=entry_plan,
            risk_plan=risk_plan,
            invalidation_conditions=invalidation_conditions,
            confidence=confidence,
            data_quality=data_quality,
            reasoning_summary=_require_str(payload, "reasoning_summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["data_quality"] = self.data_quality.value
        return data


@dataclass(frozen=True)
class CriticReview:
    """Risk critic review of a draft ticket."""

    verdict: CriticVerdict
    concerns: list[str] = field(default_factory=list)
    cited_rules: list[str] = field(default_factory=list)
    suggested_changes: dict[str, Any] = field(default_factory=dict)
    confidence_adjustment: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        return data


@dataclass(frozen=True)
class VerifierResult:
    """Structured verifier outcome."""

    passed: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    checked_rule_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderIntent:
    """Pre-compiled order intent from an approved ticket."""

    source_decision_id: str
    action: TradeAction
    market: str
    symbol: str
    side: str
    entry_plan: EntryPlan
    risk_plan: RiskPlan

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        return data


@dataclass(frozen=True)
class CompiledOrder:
    """Executable order parameters computed by code."""

    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_pct_equity: float
    risk_amount_usd: float
    position_size_units: float
    position_notional_usd: float
    source: str = "risk_compiler.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderResult:
    """Broker or paper-adapter result."""

    status: str
    broker_order_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JournalEvent:
    """Replayable lifecycle journal event."""

    event_id: str
    timestamp_utc: str
    event_type: str
    decision_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_trade_decision_ticket(
    payload: dict[str, Any],
    *,
    known_rule_ids: set[str] | None = None,
    known_playbook_ids: set[str] | None = None,
) -> TradeDecisionTicket:
    """Validate a raw LLM payload as a TradeDecisionTicket."""
    return TradeDecisionTicket.from_dict(
        payload,
        known_rule_ids=known_rule_ids,
        known_playbook_ids=known_playbook_ids,
    )


def _snippet_to_dict(value: RuleSnippet | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, RuleSnippet):
        return value.to_dict()
    return dict(value)


def _require_mapping(payload: Any, label: str) -> None:
    if not isinstance(payload, dict):
        raise SchemaValidationError(f"{label} must be an object")


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{key} must be a non-empty string")
    return value


def _require_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{key} must be a number")
    return float(value)


def _string_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SchemaValidationError(f"{key} must be a list of non-empty strings")
    return list(value)


def _parse_enum(enum_cls: type[Enum], value: str, key: str) -> Any:
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise SchemaValidationError(f"{key} must be one of: {allowed}") from exc


def _parse_timestamp(value: str) -> None:
    normalized = value.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SchemaValidationError("timestamp_utc must be ISO-8601") from exc
