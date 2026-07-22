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
| Live readiness | `trading/docs/product/LIVE_READINESS.md`, future readiness reports/config | dashboards, release gates, execution router |
| Risk mandate | `trading/docs/product/RISK_MANDATE.md`, `trading/config/risk_profiles.json`, `trading/rulebook/source/hard/HARD_RISK_*.yaml` | verifier, risk/order compiler, dashboard equity cap |
| Strategy-team tournament | `trading/docs/product/RISK_MANDATE.md`, `trading/config/risk_profiles.json`, `trading/rulebook/source/soft/SOFT_STRATEGY_TEAM_001.json` | team scanners, signal scheduler, journal, cockpit dashboard |
| LLM role | `trading/docs/product/LLM_ROLE.md`, schemas, model policies | prompt builder, LLM client, evaluator |
| Adaptive decision routing | `trading/config/decision_policy.json`, `trading/docs/features/adaptive-hybrid-decision-routing/design.md` | scanner scoring, scheduler routing, review provider, journal |
| Adaptive threshold evaluation | `trading/docs/features/adaptive-hybrid-evaluation/design.md` | replay metrics, threshold proposal reports, status observability |
| Adaptive policy controller | `trading/config/decision_policy.json`, `trading/docs/features/adaptive-policy-controller/design.md` | demo scheduler, effective policy loader, journal, status observability |
| Adaptive strategy calibration | `trading/config/decision_policy.json`, `trading/docs/features/adaptive-strategy-calibration/design.md` | adaptive evaluator, replay reports, status observability |
| Adaptive conflict penalty evaluation | `trading/config/decision_policy.json`, `trading/docs/features/adaptive-conflict-penalty-evaluation/design.md` | adaptive evaluator, replay reports, status observability |
| Continuous conflict shadow score | `trading/config/decision_policy.json`, `trading/docs/features/continuous-conflict-shadow-score/design.md` | feature engine shadow score, scanner evidence, shadow journal, adaptive evaluator |
| Continuous conflict V2 calibration | `trading/config/decision_policy.json`, `trading/docs/features/continuous-conflict-v2-calibration/design.md` | adaptive evaluator, replay reports, status observability |
| Continuous conflict V2 review staging | `trading/config/decision_policy.json`, `trading/docs/features/continuous-conflict-v2-review-staging/design.md` | demo scheduler, review state, status observability |
| Continuous conflict V2 canary | `trading/config/decision_policy.json`, `trading/docs/features/continuous-conflict-v2-canary/design.md` | operator CLI, demo scheduler, signal pipeline, journal, status observability |
| Adaptive shadow evidence | `trading/docs/architecture/JOURNAL_CONTRACTS.md`, `trading/docs/features/adaptive-shadow-outcomes/design.md` | signal scheduler, shadow resolver, adaptive evaluator |
| Signal contract | `trading/docs/architecture/SIGNAL_CONTRACTS.md`, `trading/schemas/signal_candidate.schema.json` | scanners, prompt builder, journal, dashboards |
| Runtime context boundaries | `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md` | runtime modules, retrievers, prompt builders |
| RAG indexing policy | `trading/docs/architecture/RAG_INDEXING_POLICY.md` | rule retrievers, prompt builders, critics |
| Execution contracts | `trading/docs/architecture/EXECUTION_CONTRACTS.md`, `trading/rulebook/source/hard/HARD_EXECUTION_*.json`, `trading/schemas/compiled_order.schema.json` | risk/order compiler, execution adapters, OKX demo adapter |
| Journal contracts | `trading/docs/architecture/JOURNAL_CONTRACTS.md`, `trading/schemas/journal_event.schema.json` | journal, replay, dashboards |
| Telegram observability | `trading/docs/architecture/TELEGRAM_OBSERVABILITY_CONTRACT.md` | Telegram dashboard, alerts, operator commands |
| Hard rules | `trading/rulebook/source/hard/*.json` | compiled verifier rules |
| Soft policies | `trading/rulebook/source/soft/*.json` | rendered LLM context, retriever |
| Playbooks | `trading/rulebook/source/playbooks/*.json` | retriever, prompt builder, journal |
| Case memory | `trading/rulebook/source/cases/*.json` | retriever, prompt builder, evals |
| Schemas | `trading/schemas/*.schema.json`, including `llm_context_review.schema.json` | LLM, verifier, compiler, journal |
| Retrieved rule context | `trading/rulebook/source/**`, `trading/rulebook/compile_rulebook.py` | `trading/rulebook/compiled/retriever_manifest.json`, rule retriever |
| Signal sources | `trading/docs/architecture/SIGNAL_CONTRACTS.md`, scanner implementation docs/designs | Berkshire, confluence, regime, alpha-zoo, future forex scanners |
| Runtime evidence | journal files under runtime data dirs | dashboards, replay, curated future cases |

## Generated Artifacts

Compiled and rendered rulebook artifacts must be generated and marked as
generated. They are not policy sources:

- `trading/rulebook/compiled/*`
- `trading/rulebook/rendered/*`
- future compatibility `trading/auto/skills.json`

## Feature Design Boundary

Implementation designs live under `trading/docs/features/`. They are tracked
project artifacts for planning, review, and delivery history, but they are not
canonical trading policy. A design that changes product, risk, autonomy, model,
execution, or journal behavior must update the canonical source listed above
before runtime code changes.

## Code Ownership Rule

Code may enforce, compile, render, retrieve, route, or journal policy. Code must
not become the only canonical source for trading policy.

## Process Docs Boundary

Development-process docs under `docs/harness/`, root `README.md`, and
`AGENTS.md` may guide coding work. They must not be indexed as trading runtime
context or used as rulebook source.
