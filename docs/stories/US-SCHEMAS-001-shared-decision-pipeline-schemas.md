# US-SCHEMAS-001 Shared Decision Pipeline Schemas

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must define shared contracts for market context, retrieved rule
context, LLM trade tickets, critic reviews, verifier results, order compilation,
broker results, and journal events before runtime wiring begins.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/product/LLM_ROLE.md`

## Acceptance Criteria

- `TradeDecisionTicket` action is an enum, not free text.
- Confidence is constrained to `0.0..1.0`.
- Data quality is constrained to `A`, `B`, `C`, or `UNKNOWN`.
- Non-HOLD tickets require `playbook_id`, `rule_citations`, `entry_plan`,
  `risk_plan`, and `invalidation_conditions`.
- Non-HOLD tickets require at least one `HARD_` rule citation.
- Known rule/playbook IDs can be supplied to reject hallucinated citations.
- JSON schema artifacts are exported and freshness-checked.

## Design Notes

- Commands: none.
- Queries: none.
- API: dataclass validation helpers in `trading/schemas/models.py`.
- Tables: unchanged.
- Domain rules: schema-level contract only.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | `scripts/verify-trading-tests.ps1` |
| Integration | JSON schema export check and rulebook compile check |
| E2E | Not changed in this slice |
| Platform | Docker build attempted if daemon is available |
| Release | Final compliance audit later |

## Harness Delta

Added a story record and feature design for shared schemas.

## Evidence

- `python trading/schemas/export_json_schemas.py --check` passed with 9 schema
  artifacts.
- `python trading/rulebook/compile_rulebook.py --check` passed with 21 source
  records.
- `scripts/verify-trading-tests.ps1` passed 163 tests.
- `docker compose build` passed with workspace `DOCKER_CONFIG`.
- `docker compose up -d` started `vibe-trading`; `http://127.0.0.1:8000/health`
  returned 200 and container status was healthy.
