# trading_v1

Role: repository entrypoint

This repository contains an LLM-governed trading system.

The active trading application lives in:

- `trading/`

The active source-of-truth and architecture specifications live in:

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `docs/specs/trading_v1_harness_docs_source_of_truth_addendum.md`
- `trading/docs/product/`
- `trading/docs/architecture/`
- `trading/rulebook/source/`
- `trading/schemas/`
- `trading/config/`

Harness documents are retained only as development-process guidance for coding
agents. They are not trading policy, runtime configuration, LLM trading
context, broker policy, or rulebook source of truth.

Process-only Harness docs live in:

- `docs/harness/`

Compatibility pointers:

- `docs/ARCHITECTURE.md`
- `docs/ARCHITECTURE_V2.md`

Do not add trading policy to this root README. Add or update the canonical
source first, then compile or render it for runtime consumers.
