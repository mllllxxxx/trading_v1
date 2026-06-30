# US-SOT-GOV-001 Source-of-Truth Governance Foundation

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must carry its accepted governance and LLM-governed refactor
specifications in-repo. Future agents must be directed to the trading runtime
under `trading/` and must treat `trading/rulebook/source`, schemas, config, and
product docs as the canonical source hierarchy before changing trading behavior.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/product/TRADING_SYSTEM_INTENT.md`
- `trading/docs/product/AUTONOMY_POLICY.md`
- `trading/docs/product/RISK_MANDATE.md`
- `trading/docs/product/LLM_ROLE.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`

## Acceptance Criteria

- The two accepted specs exist under `docs/specs`.
- Root and trading README files identify the real trading app under `trading/`.
- `AGENTS.md` instructs future agents to read governance before runtime edits.
- Source-of-truth skeleton directories exist for product docs, architecture,
  config, schemas, and rulebook source/compiled/rendered artifacts.
- Runtime behavior is unchanged in this slice.

## Design Notes

- Commands: none.
- Queries: none.
- API: unchanged.
- Tables: unchanged.
- Domain rules: documented only, not yet enforced by new code.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | `pytest -x` |
| Integration | Not changed in this slice |
| E2E | Not changed in this slice |
| Platform | Docker not required because no runtime code changed |
| Release | Final governance audit after later PRs |

## Harness Delta

Added a story packet and durable story record for this high-risk governance
initiative.

## Evidence

- `pytest -x` from repo root fails before app tests on the existing loose
  `trading/auto/test_hold.py` import pattern (`ModuleNotFoundError: brain`).
- `pytest -x` from `trading/` passed 132 tests.
- `pytest -x trading/tests` from repo root passed 132 tests and is the durable
  story verification command.
