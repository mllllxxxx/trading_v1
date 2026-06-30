# US-LLM-CONTRACT-001 Prompt Builder And TradeDecisionTicket Validation

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must provide an LLM prompt path that reads generated rulebook context
and the shared `TradeDecisionTicket` schema instead of defining policy directly
inside prompt text. LLM output must validate against the shared ticket contract
and fail closed when JSON, schema, rule citation, or playbook validation fails.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`
- `trading/docs/product/LLM_ROLE.md`
- `trading/schemas/trade_decision_ticket.schema.json`
- `trading/rulebook/rendered/llm/`

## Acceptance Criteria

- Prompt builder reads `trading/schemas/trade_decision_ticket.schema.json`.
- Prompt builder reads generated files under `trading/rulebook/rendered/llm/`.
- Prompt context includes concrete rule IDs and playbook IDs.
- Prompt builder exposes allowlisted context roots and excludes process docs.
- Prompt text does not define legacy risk constants manually.
- Brain helper validates valid HOLD and valid non-HOLD tickets.
- Brain helper rejects invalid JSON.
- Brain helper rejects hallucinated rule IDs.
- Brain helper rejects missing non-HOLD risk plan.
- Legacy scheduler and broker execution behavior are unchanged in this slice.

## Design Notes

- Commands: none.
- Queries: none.
- API: `trading/llm/prompt_builder.py` and
  `trading/auto/brain.py`.
- Tables: unchanged.
- Domain rules: schema and generated rulebook artifacts only.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Prompt builder and brain ticket tests |
| Integration | Full trading pytest suite |
| E2E | Legacy scheduler unchanged in this slice |
| Platform | Docker build/up and `/health` |
| Release | Final source-of-truth compliance audit later |

## Harness Delta

Story and design doc added before code. Intake #14 recorded.

## Evidence

- Targeted tests passed: `trading/tests/test_prompt_builder.py` and
  `trading/tests/test_brain_trade_decision_ticket.py` passed 9 tests.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
  passed schema check, rulebook check, and 198 tests.
- `python -m pytest -x` passed 198 tests.
- `docker compose build` passed from `trading/`.
- `docker compose up -d` started `vibe-trading`; `/health` returned 200 and
  container status was healthy.
- Container smoke import passed for `llm.prompt_builder` and
  `auto.brain.parse_trade_decision_ticket`.
