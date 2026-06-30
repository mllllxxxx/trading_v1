# Source-of-Truth Map

Governance priority:

```text
1. docs/specs/trading_v1_source_of_truth_governance_plan.md
2. docs/specs/trading_v1_llm_governed_refactor_spec.md
3. docs/specs/trading_v1_harness_docs_source_of_truth_addendum.md
4. Current code
5. Legacy README/comments
```

## Canonical Sources

| Domain | Canonical source | Consumers |
| --- | --- | --- |
| Product intent | `trading/docs/product/TRADING_SYSTEM_INTENT.md` | README, prompts summary |
| Autonomy policy | `trading/docs/product/AUTONOMY_POLICY.md`, future `trading/config/autonomy.yaml` | scheduler, verifier, execution router |
| Risk mandate | `trading/docs/product/RISK_MANDATE.md`, future `trading/config/risk_profiles.yaml`, `trading/rulebook/source/hard/HARD_RISK_*.yaml` | verifier, risk/order compiler |
| LLM role | `trading/docs/product/LLM_ROLE.md`, schemas, model policies | prompt builder, LLM client, evaluator |
| Runtime context boundaries | `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md` | runtime modules, retrievers, prompt builders |
| RAG indexing policy | `trading/docs/architecture/RAG_INDEXING_POLICY.md` | rule retrievers, prompt builders, critics |
| Execution contracts | `trading/docs/architecture/EXECUTION_CONTRACTS.md`, `trading/rulebook/source/hard/HARD_EXECUTION_*.json`, `trading/schemas/compiled_order.schema.json` | risk/order compiler, execution adapters |
| Journal contracts | `trading/docs/architecture/JOURNAL_CONTRACTS.md`, `trading/schemas/journal_event.schema.json` | journal, replay, dashboards |
| Hard rules | `trading/rulebook/source/hard/*.json` | compiled verifier rules |
| Soft policies | `trading/rulebook/source/soft/*.json` | rendered LLM context, retriever |
| Playbooks | `trading/rulebook/source/playbooks/*.json` | retriever, prompt builder, journal |
| Case memory | `trading/rulebook/source/cases/*.json` | retriever, prompt builder, evals |
| Schemas | `trading/schemas/*.schema.json` | LLM, verifier, compiler, journal |
| Retrieved rule context | `trading/rulebook/source/**`, `trading/rulebook/compile_rulebook.py` | `trading/rulebook/compiled/retriever_manifest.json`, rule retriever |
| Runtime evidence | journal files under runtime data dirs | dashboards, replay, curated future cases |

## Generated Artifacts

Compiled and rendered rulebook artifacts must be generated and marked as
generated. They are not policy sources:

- `trading/rulebook/compiled/*`
- `trading/rulebook/rendered/*`
- future compatibility `trading/auto/skills.json`

## Code Ownership Rule

Code may enforce, compile, render, retrieve, route, or journal policy. Code must
not become the only canonical source for trading policy.

## Process Docs Boundary

Development-process docs under `docs/harness/`, root `README.md`, and
`AGENTS.md` may guide coding work. They must not be indexed as trading runtime
context or used as rulebook source.
