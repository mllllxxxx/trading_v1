"""JSON schema export for shared trading pipeline contracts."""

from __future__ import annotations

from typing import Any


GENERATED_NOTICE = "DO NOT EDIT - generated from trading/schemas/models.py"


def schemas_for_export() -> dict[str, dict[str, Any]]:
    """Return JSON schemas keyed by output filename."""
    return {
        "market_dossier.schema.json": _schema(
            "MarketDossier",
            {
                "symbol": {"type": "string"},
                "market": {"type": "string"},
                "timeframe": {"type": "string"},
                "current_price": {"type": "number", "exclusiveMinimum": 0},
                "confluence_score": {"type": "number"},
                "candidate_direction": {"type": "string", "enum": ["long", "short", "none"]},
                "regime": {"type": "string"},
                "trend_state": {"type": "string"},
                "volatility_state": {"type": "string"},
                "data_source": {"type": "string"},
                "data_age_s": {"type": "number", "minimum": 0},
                "data_quality": _data_quality_ref(),
                "spread_state": {"type": ["string", "null"]},
                "funding_state": {"type": ["string", "null"]},
                "open_positions": {"type": "array", "items": {"type": "object"}},
                "portfolio_exposure": {"type": "object"},
            },
            [
                "symbol",
                "market",
                "timeframe",
                "current_price",
                "confluence_score",
                "candidate_direction",
                "regime",
                "trend_state",
                "volatility_state",
                "data_source",
                "data_age_s",
                "data_quality",
            ],
        ),
        "retrieved_rule_context.schema.json": _schema(
            "RetrievedRuleContext",
            {
                "mandatory_hard_rules": _rule_snippet_array(),
                "candidate_playbooks": _rule_snippet_array(),
                "soft_policies": _rule_snippet_array(),
                "case_memory": _rule_snippet_array(),
                "all_rule_ids": _string_array(),
            },
            [
                "mandatory_hard_rules",
                "candidate_playbooks",
                "soft_policies",
                "case_memory",
                "all_rule_ids",
            ],
        ),
        "trade_decision_ticket.schema.json": _schema(
            "TradeDecisionTicket",
            {
                "decision_id": {"type": "string"},
                "timestamp_utc": {"type": "string", "format": "date-time"},
                "action": {
                    "type": "string",
                    "enum": [
                        "HOLD",
                        "OPEN_LONG",
                        "OPEN_SHORT",
                        "CLOSE_POSITION",
                        "REDUCE_POSITION",
                        "REQUEST_MORE_DATA",
                    ],
                },
                "market": {"type": "string"},
                "symbol": {"type": "string"},
                "timeframe": {"type": "string"},
                "playbook_id": {"type": ["string", "null"]},
                "rule_citations": _string_array(),
                "thesis": {"type": "string"},
                "entry_plan": {
                    "type": ["object", "null"],
                    "properties": _entry_plan_properties(),
                    "required": ["order_type", "entry_reference", "chase_market"],
                    "additionalProperties": False,
                },
                "risk_plan": {
                    "type": ["object", "null"],
                    "properties": _risk_plan_properties(),
                    "required": ["risk_pct_equity", "stop_logic", "take_profit_logic"],
                    "additionalProperties": False,
                },
                "invalidation_conditions": _string_array(),
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "data_quality": _data_quality_ref(),
                "reasoning_summary": {"type": "string"},
            },
            [
                "decision_id",
                "timestamp_utc",
                "action",
                "market",
                "symbol",
                "timeframe",
                "playbook_id",
                "rule_citations",
                "thesis",
                "confidence",
                "data_quality",
                "reasoning_summary",
            ],
        ),
        "critic_review.schema.json": _schema(
            "CriticReview",
            {
                "verdict": {"type": "string", "enum": ["APPROVE", "REVISE", "REJECT"]},
                "concerns": _string_array(),
                "cited_rules": _string_array(),
                "suggested_changes": {"type": "object"},
                "confidence_adjustment": {"type": ["number", "null"]},
            },
            ["verdict"],
        ),
        "verifier_result.schema.json": _schema(
            "VerifierResult",
            {
                "passed": {"type": "boolean"},
                "violations": {"type": "array", "items": {"type": "object"}},
                "checked_rule_ids": _string_array(),
            },
            ["passed"],
        ),
        "order_intent.schema.json": _schema(
            "OrderIntent",
            {
                "source_decision_id": {"type": "string"},
                "action": {"type": "string"},
                "market": {"type": "string"},
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "entry_plan": {"type": "object", "properties": _entry_plan_properties()},
                "risk_plan": {"type": "object", "properties": _risk_plan_properties()},
            },
            ["source_decision_id", "action", "market", "symbol", "side", "entry_plan", "risk_plan"],
        ),
        "compiled_order.schema.json": _schema(
            "CompiledOrder",
            {
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "entry": {"type": "number"},
                "stop_loss": {"type": "number"},
                "take_profit": {"type": "number"},
                "risk_pct_equity": {"type": "number"},
                "risk_amount_usd": {"type": "number"},
                "position_size_units": {"type": "number"},
                "position_notional_usd": {"type": "number"},
                "source": {"type": "string"},
            },
            [
                "symbol",
                "side",
                "entry",
                "stop_loss",
                "take_profit",
                "risk_pct_equity",
                "risk_amount_usd",
                "position_size_units",
                "position_notional_usd",
                "source",
            ],
        ),
        "order_result.schema.json": _schema(
            "OrderResult",
            {
                "status": {"type": "string"},
                "broker_order_id": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
                "raw": {"type": "object"},
            },
            ["status"],
        ),
        "journal_event.schema.json": _schema(
            "JournalEvent",
            {
                "event_id": {"type": "string"},
                "timestamp_utc": {"type": "string", "format": "date-time"},
                "event_type": {"type": "string"},
                "decision_id": {"type": ["string", "null"]},
                "payload": {"type": "object"},
            },
            ["event_id", "timestamp_utc", "event_type", "payload"],
        ),
    }


def _schema(title: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "_generated_notice": GENERATED_NOTICE,
        "title": title,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _rule_snippet_array() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "markdown": {"type": "string"},
                "title": {"type": ["string", "null"]},
                "category": {"type": ["string", "null"]},
                "score": {"type": ["number", "null"]},
                "source_path": {"type": ["string", "null"]},
                "metadata": {"type": "object"},
            },
            "required": ["id", "markdown"],
            "additionalProperties": False,
        },
    }


def _data_quality_ref() -> dict[str, Any]:
    return {"type": "string", "enum": ["A", "B", "C", "UNKNOWN"]}


def _entry_plan_properties() -> dict[str, Any]:
    return {
        "order_type": {"type": "string", "enum": ["market", "limit", "none"]},
        "entry_reference": {"type": "string"},
        "chase_market": {"type": "boolean"},
    }


def _risk_plan_properties() -> dict[str, Any]:
    return {
        "risk_pct_equity": {"type": "number", "minimum": 0},
        "stop_logic": {"type": "string"},
        "take_profit_logic": {"type": "string"},
    }
