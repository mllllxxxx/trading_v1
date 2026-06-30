# LLM Decision Contract

## Goal

Add the next source-of-truth slice for the LLM-governed pipeline:

- build prompt messages from generated rulebook context and JSON schema;
- keep prompt policy out of hardcoded text;
- validate LLM output as `TradeDecisionTicket`;
- fail closed on invalid JSON, schema errors, fake rule IDs, or fake playbooks.

## Scope

- Add `trading/llm/prompt_builder.py`.
- Add `trading/llm/__init__.py`.
- Extend `trading/auto/brain.py` with TradeDecisionTicket parsing helpers.
- Add prompt and brain contract tests.
- Update RAG indexing policy to allow the generated decision schema as prompt
  context.
- Keep legacy scheduler behavior compatible in this slice.

## Non-Goals

- Do not route scheduler execution through critic, verifier, or compiler yet.
- Do not enable live trading.
- Do not change broker guards or execution behavior.
- Do not let the LLM choose executable quantity.
- Do not move canonical policy into prompt text.

## Design

`prompt_builder.build_trader_prompt(...)` accepts a normalized market dossier and
retrieved rule context. It reads:

- `trading/schemas/trade_decision_ticket.schema.json`;
- generated prompt-safe files under `trading/rulebook/rendered/llm/`.

The system message states the LLM role and output boundary. The user message
contains the schema, market dossier, retrieved rules, and rendered rulebook
context. Numeric risk limits and policy thresholds remain in canonical docs,
rulebook source, compiled artifacts, and future compiler/verifier logic.

`brain.parse_trade_decision_ticket(...)` accepts raw model text or a payload and
returns a validated `TradeDecisionTicket`. Validation uses the existing shared
schema model and rejects unknown rule citations or playbook IDs when known IDs
are supplied. This is a fail-closed helper for the future scheduler pipeline.

## Validation Plan

- Prompt builder tests:
  - prompt reads the schema artifact;
  - prompt includes generated rendered rulebook context and concrete rule IDs;
  - allowed context roots exclude process docs;
  - prompt text does not redefine legacy risk constants.
- Brain tests:
  - valid HOLD passes;
  - valid OPEN_LONG passes with known IDs;
  - invalid JSON fails closed;
  - hallucinated rule ID fails closed;
  - missing non-HOLD risk plan fails closed.
- Full verification:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
  - Docker build/up and `/health`.
