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


class SignalDirection(str, Enum):
    """Allowed market-signal directions."""

    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class SignalStatus(str, Enum):
    """Allowed signal promotion states."""

    STRONG_CANDIDATE = "strong_candidate"
    CANDIDATE = "candidate"
    WATCHLIST = "watchlist"
    BLOCKED = "blocked"


class SignalGrade(str, Enum):
    """Allowed signal quality grades."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


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


class ContextReviewDecision(str, Enum):
    """Allowed gray-zone LLM review outcomes."""

    APPROVE = "APPROVE"
    VETO = "VETO"
    WAIT = "WAIT"


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
    recent_trades: list[dict[str, Any]] = field(default_factory=list)
    portfolio_exposure: dict[str, Any] = field(default_factory=dict)
    data_timestamp_utc: str | None = None
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    regime_evidence: dict[str, Any] = field(default_factory=dict)
    setup_quality: dict[str, Any] = field(default_factory=dict)

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
class SignalCandidate:
    """Shared scanner output before LLM ticket promotion."""

    signal_id: str
    generated_at: str
    source: str
    market: str
    symbol: str
    timeframe: str
    direction: SignalDirection
    status: SignalStatus
    confidence: float
    score: int
    grade: SignalGrade
    action_hint: TradeAction
    mode: str
    time_horizon: str
    promotion_gate: str
    reasons: list[str]
    blockers: list[str]
    confidence_components: dict[str, float] = field(default_factory=dict)
    rule_score: float | None = None
    score_components: dict[str, float] = field(default_factory=dict)
    experimental_scores: dict[str, Any] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    hard_blockers: list[str] = field(default_factory=list)
    decision_zone: str | None = None
    confidence_calibrated: bool = False
    entry_zone: str | None = None
    invalidation: str | None = None
    target_zone: str | None = None
    risk_reward: str | None = None
    last_price: str | None = None
    llm_context: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    team_id: str | None = None
    team_name: str | None = None
    strategy_id: str | None = None
    strategy_name: str | None = None
    team_capital_usd: float | None = None
    risk_min_pct_equity: float | None = None
    risk_max_pct_equity: float | None = None
    target_risk_pct_equity: float | None = None
    preferred_playbook_ids: list[str] = field(default_factory=list)
    required_soft_policy_ids: list[str] = field(default_factory=list)
    entry_style: str | None = None
    avoid_conditions: list[str] = field(default_factory=list)
    llm_guidance: str | None = None
    risk_personality: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SignalCandidate":
        """Parse and validate a scanner signal payload."""
        _require_mapping(payload, "signal_candidate")
        generated_at = _require_str(payload, "generated_at")
        _parse_timestamp(generated_at)
        direction = _parse_enum(
            SignalDirection,
            _require_str(payload, "direction"),
            "direction",
        )
        status_value = payload.get("status", payload.get("signal"))
        if not isinstance(status_value, str):
            raise SchemaValidationError("status must be a non-empty string")
        status = _parse_enum(SignalStatus, status_value, "status")
        grade = _parse_enum(SignalGrade, _require_str(payload, "grade"), "grade")
        action_hint = _parse_enum(
            TradeAction,
            _require_str(payload, "action_hint"),
            "action_hint",
        )

        confidence = _require_number(payload, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise SchemaValidationError("confidence must be between 0.0 and 1.0")
        raw_score = _require_number(payload, "score")
        if raw_score < 0 or raw_score > 100:
            raise SchemaValidationError("score must be between 0 and 100")
        score = int(raw_score)

        reasons = _string_list(payload.get("reasons", payload.get("why", [])), "reasons")
        blockers = _string_list(payload.get("blockers", []), "blockers")
        hard_blockers = _string_list(payload.get("hard_blockers", blockers), "hard_blockers")
        if not reasons:
            raise SchemaValidationError("signal candidate requires reasons")

        eligible_statuses = {SignalStatus.STRONG_CANDIDATE, SignalStatus.CANDIDATE}
        if status in eligible_statuses:
            if direction is SignalDirection.NEUTRAL:
                raise SchemaValidationError("candidate signal requires long or short direction")
            expected_action = TradeAction.OPEN_LONG if direction is SignalDirection.LONG else TradeAction.OPEN_SHORT
            if action_hint is not expected_action:
                raise SchemaValidationError("candidate action_hint must match direction")
            if blockers or hard_blockers:
                raise SchemaValidationError("candidate signal cannot include blockers")

        if status is SignalStatus.BLOCKED and action_hint not in {TradeAction.HOLD, TradeAction.REQUEST_MORE_DATA}:
            raise SchemaValidationError("blocked signal action_hint must be HOLD or REQUEST_MORE_DATA")

        return cls(
            signal_id=_require_str(payload, "signal_id"),
            generated_at=generated_at,
            source=_require_str(payload, "source"),
            market=_require_str(payload, "market"),
            symbol=_require_str(payload, "symbol"),
            timeframe=_require_str(payload, "timeframe"),
            direction=direction,
            status=status,
            confidence=confidence,
            score=score,
            grade=grade,
            action_hint=action_hint,
            mode=_require_str(payload, "mode"),
            time_horizon=_require_str(payload, "time_horizon"),
            promotion_gate=_require_str(payload, "promotion_gate"),
            reasons=reasons,
            blockers=blockers,
            confidence_components=_number_mapping(
                payload.get("confidence_components", {}),
                "confidence_components",
            ),
            rule_score=_optional_number(payload, "rule_score"),
            score_components=_number_mapping(payload.get("score_components", {}), "score_components"),
            experimental_scores=_object_mapping(
                payload.get("experimental_scores", {}),
                "experimental_scores",
            ),
            conflicts=_string_list(payload.get("conflicts", []), "conflicts"),
            hard_blockers=hard_blockers,
            decision_zone=_decision_zone(payload.get("decision_zone")),
            confidence_calibrated=bool(payload.get("confidence_calibrated", False)),
            entry_zone=payload.get("entry_zone"),
            invalidation=payload.get("invalidation"),
            target_zone=payload.get("target_zone"),
            risk_reward=payload.get("risk_reward"),
            last_price=payload.get("last_price"),
            llm_context=dict(payload.get("llm_context", {})),
            evidence=dict(payload.get("evidence", {})),
            team_id=_optional_str(payload, "team_id"),
            team_name=_optional_str(payload, "team_name"),
            strategy_id=_optional_str(payload, "strategy_id"),
            strategy_name=_optional_str(payload, "strategy_name"),
            team_capital_usd=_optional_number(payload, "team_capital_usd"),
            risk_min_pct_equity=_optional_number(payload, "risk_min_pct_equity"),
            risk_max_pct_equity=_optional_number(payload, "risk_max_pct_equity"),
            target_risk_pct_equity=_optional_number(payload, "target_risk_pct_equity"),
            preferred_playbook_ids=_string_list(payload.get("preferred_playbook_ids", []), "preferred_playbook_ids"),
            required_soft_policy_ids=_string_list(payload.get("required_soft_policy_ids", []), "required_soft_policy_ids"),
            entry_style=_optional_str(payload, "entry_style"),
            avoid_conditions=_string_list(payload.get("avoid_conditions", []), "avoid_conditions"),
            llm_guidance=_optional_str(payload, "llm_guidance"),
            risk_personality=_optional_str(payload, "risk_personality"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction.value
        data["status"] = self.status.value
        data["grade"] = self.grade.value
        data["action_hint"] = self.action_hint.value
        return data


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
    profile_compliance_score: float | None = None
    profile_compliance_summary: str | None = None
    profile_compliance_flags: list[str] = field(default_factory=list)

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

        terminal_actions = {TradeAction.HOLD, TradeAction.REQUEST_MORE_DATA}
        if action not in terminal_actions:
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
            profile_compliance_score=_optional_number(payload, "profile_compliance_score"),
            profile_compliance_summary=_optional_str(payload, "profile_compliance_summary"),
            profile_compliance_flags=_string_list(
                payload.get("profile_compliance_flags", []),
                "profile_compliance_flags",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["data_quality"] = self.data_quality.value
        return data


@dataclass(frozen=True)
class LLMContextReview:
    """Narrow LLM judgment for an adaptive gray-zone rule proposal."""

    schema_version: str
    review_id: str
    timestamp_utc: str
    decision: ContextReviewDecision
    risk_multiplier: float
    conflict_flags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    reasoning_summary: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LLMContextReview":
        """Parse and validate a gray-zone context review."""
        _require_mapping(payload, "llm_context_review")
        schema_version = _require_str(payload, "schema_version")
        if schema_version != "llm_context_review.v1":
            raise SchemaValidationError("schema_version must be llm_context_review.v1")
        timestamp_utc = _require_str(payload, "timestamp_utc")
        _parse_timestamp(timestamp_utc)
        decision = _parse_enum(
            ContextReviewDecision,
            _require_str(payload, "decision"),
            "decision",
        )
        risk_multiplier = _require_number(payload, "risk_multiplier")
        if risk_multiplier not in {0.0, 0.5, 1.0}:
            raise SchemaValidationError("risk_multiplier must be one of: 0, 0.5, 1")
        if decision in {ContextReviewDecision.VETO, ContextReviewDecision.WAIT} and risk_multiplier != 0.0:
            raise SchemaValidationError("VETO and WAIT require risk_multiplier=0")
        if decision is ContextReviewDecision.APPROVE and risk_multiplier == 0.0:
            raise SchemaValidationError("APPROVE requires risk_multiplier 0.5 or 1")
        return cls(
            schema_version=schema_version,
            review_id=_require_str(payload, "review_id"),
            timestamp_utc=timestamp_utc,
            decision=decision,
            risk_multiplier=risk_multiplier,
            conflict_flags=_string_list(payload.get("conflict_flags", []), "conflict_flags"),
            evidence_refs=_string_list(payload.get("evidence_refs", []), "evidence_refs"),
            reasoning_summary=_require_str(payload, "reasoning_summary"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
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
    requested_risk_pct_equity: float | None = None
    target_risk_pct_equity: float | None = None
    actual_risk_pct_equity: float | None = None
    risk_cap_reason: str | None = None
    margin_used_usd: float | None = None
    gross_notional_usd: float | None = None
    leverage: float | None = None

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


def validate_signal_candidate(payload: dict[str, Any]) -> SignalCandidate:
    """Validate a raw scanner payload as a SignalCandidate."""
    return SignalCandidate.from_dict(payload)


def validate_llm_context_review(payload: dict[str, Any]) -> LLMContextReview:
    """Validate a raw LLM response as an adaptive context review."""
    return LLMContextReview.from_dict(payload)


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


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaValidationError(f"{key} must be a string")
    text = value.strip()
    return text or None


def _optional_number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{key} must be a number")
    return float(value)


def _string_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SchemaValidationError(f"{key} must be a list of non-empty strings")
    return list(value)


def _number_mapping(value: Any, key: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{key} must be an object")
    parsed: dict[str, float] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key:
            raise SchemaValidationError(f"{key} keys must be non-empty strings")
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise SchemaValidationError(f"{key}.{item_key} must be a number")
        parsed[item_key] = float(item_value)
    return parsed


def _object_mapping(value: Any, key: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{key} must be an object")
    parsed: dict[str, Any] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not item_key:
            raise SchemaValidationError(f"{key} keys must be non-empty strings")
        if not isinstance(item_value, dict):
            raise SchemaValidationError(f"{key}.{item_key} must be an object")
        parsed[item_key] = dict(item_value)
    return parsed


def _decision_zone(value: Any) -> str | None:
    if value is None:
        return None
    if value not in {"strong", "gray", "reject"}:
        raise SchemaValidationError("decision_zone must be strong, gray, reject, or null")
    return str(value)


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
