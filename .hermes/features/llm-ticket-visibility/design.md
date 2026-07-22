# LLM Ticket Visibility

## Goal

Expose Berkshire signal-pipeline LLM tickets in the trader brain log so operators can verify whether an opened demo position came from a real LLM decision or from exchange reconciliation.

## Current Problem

`/api/trader/status` filters `llm_decisions` to legacy event types such as `llm`, `llm_override_no_trade`, and `llm_error`. Berkshire signal execution writes the real LLM decision as the lifecycle event `llm_draft_ticket` with a ticket snapshot. Those tickets are present under `/data/journal/snapshots`, but the trader UI timeline does not surface them.

This makes valid LLM-driven positions look like the LLM did nothing.

## Contract

- Keep execution behavior unchanged.
- Treat `llm_draft_ticket` as LLM activity for observability.
- Normalize lifecycle tickets into brain-log-friendly events:
  - `type`
  - `ts`
  - `decision_id`
  - `ticket_decision_id`
  - `symbol`
  - `action`
  - `confidence`
  - `playbook_id`
  - `reasoning`
- Continue to include legacy LLM decision events.
- If a ticket snapshot cannot be loaded, include the lifecycle event with available payload fields instead of failing the status API.

## Verification

- Unit test journal normalization for `llm_draft_ticket`.
- Run targeted backend tests for journal and signal pipeline.
- Run frontend test/build for brain log rendering.
- Rebuild Docker local and verify `/api/trader/status.llm_decisions` includes ticket events.
