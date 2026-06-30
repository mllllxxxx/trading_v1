"""LLM brain: call DeepSeek (OpenAI-compatible) and parse the JSON decision.

Uses env vars:
  DEEPSEEK_API_KEY              - required
  DEEPSEEK_BASE_URL             - default https://api.deepseek.com/v1
  AUTO_LLM_MODEL                - default "deepseek-chat"
  AUTO_LLM_TIMEOUT_S            - default 30
  AUTO_LLM_MAX_TOKENS           - default 500
  AUTO_LLM_REASONING_EFFORT     - default "low" (low | medium | high)
                                  Caps reasoning tokens so JSON output always has
                                  budget. v4-flash / v4-pro are reasoning models
                                  that can consume the full max_tokens budget on
                                  thinking alone.

Returns dict: {"action", "symbol", "entry", "stop_loss", "take_profit",
                "position_size_pct", "reasoning"}
Or raises BrainError on failure (logged to journal by caller).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from typing import Any

from schemas.models import (
    SchemaValidationError,
    TradeDecisionTicket,
    validate_trade_decision_ticket,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = os.getenv("AUTO_LLM_MODEL", "deepseek-chat")
DEFAULT_TIMEOUT_S = int(os.getenv("AUTO_LLM_TIMEOUT_S", "30"))
DEFAULT_MAX_TOKENS = int(os.getenv("AUTO_LLM_MAX_TOKENS", "4000"))
DEFAULT_TEMPERATURE = float(os.getenv("AUTO_LLM_TEMPERATURE", "0.2"))
LLMMessage = dict[str, str]
TicketClient = Callable[[list[LLMMessage]], str | dict[str, Any]]


class BrainError(Exception):
    pass


REQUIRED_KEYS = {"action", "symbol", "reasoning", "confidence"}
NON_HOLD_KEYS = {"entry", "stop_loss", "take_profit", "position_size_pct"}


def _get_client():
    """Build OpenAI client. Raises BrainError if no API key."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise BrainError("DEEPSEEK_API_KEY not set")
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    from openai import OpenAI  # type: ignore
    return OpenAI(api_key=api_key, base_url=base_url, timeout=DEFAULT_TIMEOUT_S)


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Extract JSON object from LLM response. Handles ```json fences and prose."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise BrainError("No JSON object found in LLM response")
    text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BrainError(f"Invalid JSON: {exc}")


def _validate_decision(decision: dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - decision.keys()
    if missing:
        raise BrainError(f"Missing required keys: {missing}")
    action = str(decision.get("action", "")).lower()
    if action not in ("long", "short", "hold", "no_trade"):
        raise BrainError(f"Invalid action: {action!r}")
    if action in ("long", "short"):
        for k in NON_HOLD_KEYS:
            if k not in decision:
                raise BrainError(f"Missing key for {action}: {k}")
            try:
                v = float(decision[k])
                if v <= 0:
                    raise BrainError(f"Non-positive value for {k}: {v}")
            except (TypeError, ValueError):
                raise BrainError(f"Non-numeric {k}: {decision[k]!r}")
    # H6: confidence required + in [0,1]
    try:
        conf = float(decision.get("confidence"))
        if not (0.0 <= conf <= 1.0):
            raise BrainError(f"Confidence {conf} not in [0,1]")
    except (TypeError, ValueError):
        raise BrainError(f"Missing or non-numeric confidence: {decision.get('confidence')!r}")


def parse_trade_decision_ticket(
    raw: str | dict[str, Any],
    *,
    known_rule_ids: set[str] | None = None,
    known_playbook_ids: set[str] | None = None,
) -> TradeDecisionTicket:
    """Parse and validate an LLM response as a TradeDecisionTicket.

    Raises BrainError on invalid JSON, schema mismatch, unknown rules, or
    unknown playbooks. Callers should treat BrainError as HOLD/no order.
    """
    if isinstance(raw, str):
        payload = _parse_json_response(raw)
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        raise BrainError("TradeDecisionTicket response must be JSON text or object")

    try:
        return validate_trade_decision_ticket(
            payload,
            known_rule_ids=known_rule_ids,
            known_playbook_ids=known_playbook_ids,
        )
    except SchemaValidationError as exc:
        raise BrainError(f"TradeDecisionTicket validation failed: {exc}") from exc


def call_trade_decision_ticket(
    messages: list[LLMMessage],
    *,
    known_rule_ids: set[str] | None = None,
    known_playbook_ids: set[str] | None = None,
    client: TicketClient | None = None,
    model: str | None = None,
    timeout_s: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> TradeDecisionTicket:
    """Call an LLM client and validate its TradeDecisionTicket response."""
    if not messages:
        raise BrainError("TradeDecisionTicket call requires prompt messages")
    raw = (
        client(messages)
        if client is not None
        else _call_messages_for_json(
            messages,
            model=model,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    )
    return parse_trade_decision_ticket(
        raw,
        known_rule_ids=known_rule_ids,
        known_playbook_ids=known_playbook_ids,
    )


def _call_messages_for_json(
    messages: list[LLMMessage],
    *,
    model: str | None,
    timeout_s: int | None,
    max_tokens: int | None,
    temperature: float | None,
) -> str:
    """Call the configured chat provider and return raw JSON text content."""
    client = _get_client()
    used_model = model or os.getenv("AUTO_LLM_MODEL", DEFAULT_MODEL)
    used_timeout = timeout_s or DEFAULT_TIMEOUT_S
    used_max_tokens = max_tokens or DEFAULT_MAX_TOKENS
    used_temperature = temperature if temperature is not None else DEFAULT_TEMPERATURE
    api_kwargs: dict[str, Any] = {
        "model": used_model,
        "messages": messages,
        "max_tokens": used_max_tokens,
        "temperature": used_temperature,
        "response_format": {"type": "json_object"},
        "timeout": used_timeout,
    }
    reasoning_effort = os.getenv("AUTO_LLM_REASONING_EFFORT", "low").strip().lower()
    if reasoning_effort in ("low", "medium", "high"):
        api_kwargs["reasoning_effort"] = reasoning_effort

    try:
        resp = _call_with_retry(client, api_kwargs)
        content = resp.choices[0].message.content or ""
    except BrainError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrainError(f"LLM TradeDecisionTicket call failed: {exc}") from exc
    if not content.strip():
        raise BrainError("Empty TradeDecisionTicket response")
    return content


def _extract_tokens(usage_obj: Any) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from OpenAI usage object."""
    try:
        inp = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
        out = int(getattr(usage_obj, "completion_tokens", 0) or 0)
        return inp, out
    except Exception:
        return 0, 0


def _call_with_retry(client, api_kwargs: dict[str, Any], max_attempts: int = 3) -> Any:
    """L6: Call the LLM API with exponential backoff on transient errors.

    Retries up to max_attempts times with delays 1s, 2s, 4s. Only retries on
    transient errors (network, rate limit, timeout). Validation errors (e.g.,
    authentication) propagate immediately as BrainError.
    """
    import time as _time
    transient_errors = (ConnectionError, TimeoutError)
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return client.chat.completions.create(**api_kwargs)
        except transient_errors as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                backoff = 2 ** attempt  # 1s, 2s, 4s
                log.warning(f"LLM transient error (attempt {attempt + 1}/{max_attempts}), "
                            f"retrying in {backoff}s: {exc}")
                _time.sleep(backoff)
            continue
        except Exception as exc:
            # Non-transient (auth, parse, etc.) — don't retry
            err_msg = str(exc).lower()
            if any(t in err_msg for t in ("auth", "key", "401", "403", "404")):
                raise BrainError(f"LLM auth/config error: {exc}") from exc
            raise BrainError(f"LLM API call failed: {exc}") from exc
    # All retries exhausted
    raise BrainError(f"LLM API call failed after {max_attempts} attempts: {last_exc}")


def call_brain(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str | None = None,
    timeout_s: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Call the LLM and return parsed + validated decision dict.

    Raises BrainError on any failure (no LLM call, malformed JSON, missing keys, etc.)
    L3: max_tokens and temperature now overridable per call (default from env).
    L6: Transient network/timeout errors retried with exponential backoff.
    """
    client = _get_client()
    used_model = model or os.getenv("AUTO_LLM_MODEL", DEFAULT_MODEL)
    used_timeout = timeout_s or DEFAULT_TIMEOUT_S
    used_max_tokens = max_tokens or DEFAULT_MAX_TOKENS
    used_temperature = temperature if temperature is not None else DEFAULT_TEMPERATURE
    t0 = time.time()
    # Reasoning effort: "low" caps the thinking tokens so we always have
    # budget left for the JSON output. Trading decisions are short & structured
    # — we don't need long chain-of-thought.
    reasoning_effort = os.getenv("AUTO_LLM_REASONING_EFFORT", "low").strip().lower()
    api_kwargs: dict[str, Any] = {
        "model": used_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": used_max_tokens,
        "temperature": used_temperature,
        "response_format": {"type": "json_object"},
        "timeout": used_timeout,
    }
    if reasoning_effort in ("low", "medium", "high"):
        api_kwargs["reasoning_effort"] = reasoning_effort
    try:
        # L6: retry transient errors with exponential backoff.
        resp = _call_with_retry(client, api_kwargs)
    except BrainError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BrainError(f"LLM API call failed: {exc}") from exc
    elapsed = time.time() - t0

    try:
        content = resp.choices[0].message.content or ""
    except (AttributeError, IndexError, KeyError) as exc:
        raise BrainError(f"Malformed LLM response: {exc}") from exc
    if not content.strip():
        # Diagnostic: dump raw response so we can see WHY it's empty.
        try:
            finish_reason = resp.choices[0].finish_reason
        except Exception:
            finish_reason = "?"
        try:
            usage = getattr(resp, "usage", None)
            usage_dict = usage.model_dump() if usage and hasattr(usage, "model_dump") else (
                dict(usage) if usage else {}
            )
        except Exception:
            usage_dict = {}
        raise BrainError(
            f"Empty LLM response (model={used_model}, finish_reason={finish_reason}, "
            f"reasoning_tokens={usage_dict.get('completion_tokens_details', {}).get('reasoning_tokens')}, "
            f"completion_tokens={usage_dict.get('completion_tokens')}, "
            f"total_tokens={usage_dict.get('total_tokens')})"
        )

    decision = _parse_json_response(content)
    _validate_decision(decision)
    decision["_latency_s"] = round(elapsed, 2)
    decision["_model"] = used_model
    # T3F: record token usage + cost for daily cap tracking (best-effort).
    try:
        import journal as _journal  # local import to avoid circular at module load
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is not None:
            inp, out = _extract_tokens(usage_obj)
            cost, state = _journal.add_llm_cost(inp, out)
            decision["_input_tokens"] = inp
            decision["_output_tokens"] = out
            decision["_cost_usd"] = round(cost, 6)
            decision["_daily_cost_usd"] = round(float(state.get("cost_usd", 0.0)), 6)
    except Exception:  # noqa: BLE001
        pass  # cost tracking is observability; never break the trade path
    return decision
