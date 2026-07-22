# Agent Instructions - trading_v1

Role: coding-agent routing and safety instructions

## Communication

Respond in Vietnamese, casual and friendly. Xung "toi", goi Ben la "fen".
Be direct and action-oriented. Roast nhe loi ngo ngan neu can, dung toxic.

## Read First

Read in this order before changing trading behavior:

1. `docs/specs/trading_v1_source_of_truth_governance_plan.md`
2. `docs/specs/trading_v1_llm_governed_refactor_spec.md`
3. `docs/specs/trading_v1_harness_docs_source_of_truth_addendum.md`
4. `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
5. `trading/docs/architecture/DECISION_FLOW.md`
6. `trading/docs/product/RISK_MANDATE.md`
7. `trading/docs/product/AUTONOMY_POLICY.md`
8. `trading/docs/product/LLM_ROLE.md`
9. `trading/README.md`

Harness docs under `docs/harness/` are process guidance only.

Do not treat Harness docs as:

- trading policy
- risk policy
- prompt policy
- runtime configuration
- broker or execution policy
- rulebook source of truth
- LLM trading context

Before changing trading behavior, identify the canonical source-of-truth
domain. If no canonical source exists, create or update the canonical source
first.

## Governance Priority

1. Source-of-truth governance plan
2. LLM-governed refactor spec
3. Harness-docs demotion addendum
4. Canonical trading docs, rulebook, schemas, and config
5. Current code
6. Legacy README/comments

Do not place new trading policy only in prompts, scheduler, validator, README,
AGENTS, or env files. Put policy in the canonical source first, then compile or
render it for runtime consumers.

## Development Rules

- Design before code: create or update `trading/docs/features/{name}/design.md`
  before development.
- Contract-first: update canonical docs or specs before code when behavior
  changes.
- Test-driven: add automated tests for new or changed logic.
- Run `pytest -x` after code changes when feasible, and report any blocker.
- Keep backward compatibility for JSON schemas, databases, and trade journals.
- Use Docker Compose for runtime deployment work.
- Keep secrets in environment files or secret stores, never in repo docs or
  chat.
- Do not enable live trading or weaken paper, sandbox, or testnet guards.

## Harness

Use the Rust Harness CLI at `scripts/bin/harness-cli` on macOS/Linux or
`scripts/bin/harness-cli.exe` on Windows as the main operational tool.

Before a step that could use an external tool, run:

```powershell
.\scripts\bin\harness-cli.exe query tools --capability <name> --status present
```

An absent capability is a clean skip.
