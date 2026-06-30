# US-PIPELINE-COMPILER-001 Risk Order Compiler And Scheduler Orchestration

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must turn approved LLM intent into executable order parameters with
deterministic code, not with LLM-provided quantity. Scheduler fallback from LLM
to rules-only execution must be explicit and fail closed when LLM decisions are
required.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/EXECUTION_CONTRACTS.md`
- `trading/docs/product/RISK_MANDATE.md`
- `trading/docs/product/AUTONOMY_POLICY.md`
- `trading/docs/product/LLM_ROLE.md`
- `trading/rulebook/source/hard/HARD_RISK_001.json`
- `trading/rulebook/source/hard/HARD_RISK_003.json`
- `trading/schemas/compiled_order.schema.json`

## Acceptance Criteria

- Compiler requires a passed verifier result before producing `CompiledOrder`.
- LLM raw quantity fields are ignored.
- No compiled order is produced without numeric stop-loss.
- No compiled order is produced when RR is below compiled hard-rule minimum.
- Compiler clamps risk/notional using canonical hard rules.
- Pipeline fails closed on rule retrieval, LLM, critic, verifier, or compiler
  failure.
- Pipeline does not call broker/execution.
- Scheduler skips instead of falling back when `REQUIRE_LLM_DECISION=true`.
- Scheduler cost-cap skip is explicit when LLM is required.
- Docker still builds/runs and health check passes.

## Design Notes

- Commands: none.
- Queries: none.
- API: `trading/risk/order_compiler.py`,
  `trading/auto/decision_pipeline.py`, and scheduler fallback helpers.
- Tables: unchanged.
- Domain rules: generated hard-rule artifact and execution contract docs.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Compiler, pipeline, scheduler fallback tests |
| Integration | Full trading pytest suite |
| E2E | Scheduler policy path prevents broker calls before fallback |
| Platform | Docker build/up and `/health` |
| Release | Final compliance audit later |

## Harness Delta

Design doc and story added before code. Intake #16 recorded.

## Evidence

- Targeted tests passed: `trading/tests/test_order_compiler.py`,
  `trading/tests/test_decision_pipeline.py`, and
  `trading/tests/test_scheduler_safety.py` passed 44 tests.
- Related verifier/rulebook boundary tests passed 23 tests before full run.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
  passed schema check, rulebook check, and 225 tests.
- `python -m pytest -x` passed 225 tests.
- `docker compose build` passed from `trading/`.
- `docker compose up -d` started `vibe-trading`; `/health` returned 200 and
  container status was healthy.
- Container smoke import passed for `risk.order_compiler`,
  `auto.decision_pipeline`, and scheduler LLM fallback policy.
- `git diff --check` passed with Windows CRLF warnings only.
- Harness `story verify US-PIPELINE-COMPILER-001` passed after pointing the
  verify command at the repo venv.
