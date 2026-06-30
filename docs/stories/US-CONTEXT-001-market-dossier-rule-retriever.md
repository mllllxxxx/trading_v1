# US-CONTEXT-001 Market Dossier And Rule Retriever

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must construct a normalized market dossier before asking the LLM and
must retrieve only relevant rulebook context from generated rulebook artifacts.
Missing core market data or rulebook context must fail closed and must not place
orders.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`
- `trading/schemas/market_dossier.schema.json`
- `trading/schemas/retrieved_rule_context.schema.json`

## Acceptance Criteria

- `build_market_dossier(...)` returns JSON-serializable dossier output.
- Missing or invalid current price, confluence score, or regime fails closed.
- Stale data is marked as `data_quality=C`.
- Candidate direction is `long`, `short`, or `none` from signed confluence.
- Rule retrieval always includes active mandatory hard rules for the market.
- Crypto trend dossiers retrieve crypto trend playbooks and not forex-only
  playbooks.
- Short trend dossiers can retrieve playbooks that support short direction.
- Missing or malformed compiled retriever artifacts fail closed.
- All returned IDs exist in `compiled/rule_index.json`.
- Scheduler and broker execution behavior are not changed in this slice.

## Design Notes

- Commands: none.
- Queries: none.
- API: `trading/auto/market_dossier.py` and
  `trading/auto/rule_retriever.py`.
- Tables: unchanged.
- Domain rules: generated rulebook context only; no prompt/scheduler policy.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Market dossier and rule retriever tests |
| Integration | schema export check and rulebook compile check |
| E2E | Not changed in this slice |
| Platform | Docker build/up and `/health` |
| Release | Final compliance audit later |

## Harness Delta

Story and design doc added before code.

## Evidence

- `python trading/rulebook/compile_rulebook.py --check` passed with 21 source
  records and generated `retriever_manifest.json`.
- `python trading/schemas/export_json_schemas.py --check` passed with 9 schema
  artifacts.
- Targeted tests passed: `test_market_dossier.py` and `test_rule_retriever.py`
  passed 18 tests.
- `scripts/verify-trading-tests.ps1` passed 182 tests.
- `docker compose build` passed.
- `docker compose up -d` started `vibe-trading`; `http://127.0.0.1:8000/health`
  returned 200 and container status was healthy.
- Container smoke import passed for `auto.market_dossier` and
  `auto.rule_retriever`.
