# US-SAFETY-PIPELINE-001 Risk Critic And Compiled Rule Verifier

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must review draft LLM trade tickets with a critic and verify them
against compiled hard rules before future risk compilation or execution. This
batch must not enable broker execution or live trading.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/product/RISK_MANDATE.md`
- `trading/docs/product/AUTONOMY_POLICY.md`
- `trading/docs/product/LLM_ROLE.md`
- `trading/rulebook/compiled/verifier_rules.json`
- `trading/schemas/critic_review.schema.json`
- `trading/schemas/verifier_result.schema.json`

## Acceptance Criteria

- Critic flags draft tickets that violate hard rules.
- Critic returns a journal-friendly `CriticReview` dictionary.
- Critic does not call broker or create an order.
- Verifier loads generated `compiled/verifier_rules.json`.
- Verifier rejects missing playbook for non-HOLD.
- Verifier rejects hallucinated rule IDs.
- Verifier rejects data quality C for non-HOLD.
- Verifier rejects risk above compiled hard-rule max.
- Verifier exceptions fail closed.
- Legacy scheduler and broker behavior are unchanged in this batch.

## Design Notes

- Commands: none.
- Queries: none.
- API: `trading/auto/critic.py` and
  `trading/verifier/rule_verifier.py`.
- Tables: unchanged.
- Domain rules: generated hard-rule artifact and shared schemas.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Critic and verifier tests |
| Integration | Full trading pytest suite |
| E2E | Legacy scheduler unchanged in this batch |
| Platform | Docker build/up and `/health` |
| Release | Final compliance audit later |

## Harness Delta

Story and design doc added before code. Intake #15 recorded.

## Evidence

- Targeted tests passed: `trading/tests/test_critic.py` and
  `trading/tests/test_rule_verifier.py` passed 11 tests.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
  passed schema check, rulebook check, and 209 tests.
- `python -m pytest -x` passed 209 tests.
- `docker compose build` passed from `trading/`.
- `docker compose up -d` started `vibe-trading`; `/health` returned 200 and
  container status was healthy.
- Container smoke import passed for `auto.critic` and
  `verifier.rule_verifier`.
- `git diff --check` passed with Windows CRLF warnings only.
