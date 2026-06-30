# Source-of-Truth Drift Audit - 2026-06-28

## Summary

This audit is the workflow Step 0 checkpoint for the LLM-governed refactor.
The governance plan is the highest-priority source, followed by the refactor
spec, then current code, then legacy README/comments.

No runtime behavior changes were made for this audit.

## Current Drift

Policy is currently duplicated across documentation, prompt text, runtime
validation, scheduler gates, and editable JSON.

## Files Currently Containing Trading Policy

- `AGENTS.md`: project vision, risk bands, max exposure, leverage, review loop.
- `trading/README.md`: safety rules, hybrid rules + LLM flow, risk thresholds,
  R:R values, position caps, confluence threshold language.
- `trading/auto/skills.json`: editable hard/soft rule definitions.
- `trading/auto/skills.py`: default fallback hard/soft rules when skills JSON is
  missing or malformed.
- `trading/auto/prompts.py`: hard rules, soft skills, output schema, confidence
  thresholds, position sizing guidance.
- `trading/auto/validator.py`: hardcoded leverage, liquidation buffer,
  confidence, R:R, SL/TP, and position size checks.
- `trading/auto/scheduler.py`: confluence gates, bearish skip behavior, cost-cap
  rules-only fallback, runtime orchestration, and execution gating.
- `trading/confluence/README.md`: score interpretation.
- `trading/regime/README.md`: regime interpretation.
- `trading/.env.template`: operational profile and provider behavior hints.
- `trading/brackets/okx_bracket.py` and
  `trading/brackets/okx_futures_bracket.py`: execution safety checks.

## Generated Files Currently Edited Manually

- `trading/auto/skills.json` should become a generated compatibility artifact
  from `trading/rulebook/source`.
- Future compiled and rendered rulebook files must be generated and marked
  "DO NOT EDIT".

## Runtime Files Mixing Orchestration And Policy

- `trading/auto/scheduler.py` currently combines data collection, pre-filters,
  LLM dispatch, fallback policy, validation, journaling, and execution routing.
- `trading/auto/prompts.py` assembles prompts but also defines policy.
- `trading/auto/validator.py` enforces rules but also owns hardcoded policy.
- `trading/auto/skills.py` loads policy and silently supplies fallback policy.

## Highest-Risk Findings

1. `trading/auto/skills.py` silently falls back to default rules if
   `skills.json` is missing or malformed. This is unsafe for paper/live-like
   autonomous modes.
2. `trading/auto/scheduler.py` uses `score < min_confluence` and then skips
   `score <= -min_confluence`, which blocks bearish/short candidates before
   they can become LLM-governed short decisions.
3. `trading/auto/prompts.py` duplicates hard rules and position sizing
   thresholds that can drift from validator behavior.
4. `trading/auto/validator.py` contains hardcoded thresholds that should be
   loaded from compiled rulebook/config.
5. Cost-cap behavior in `scheduler.py` includes rules-only fallback language;
   future paper/live-like modes must fail closed when LLM decisions are
   required.

## Prioritized PR Plan

1. Governance foundation: copy specs, fix identity docs, add product/architecture
   source maps, and record this audit.
2. Rulebook seed: add source hard rules, soft policies, playbooks, and cases.
3. Rulebook compiler: validate source IDs/references and generate compiled and
   rendered artifacts.
4. Skills compatibility: make `trading/auto/skills.json` generated and make
   missing/malformed compiled rules fail closed in paper/live-like modes.
5. Shared schemas: add `MarketDossier`, `TradeDecisionTicket`,
   `VerifierResult`, `OrderIntent`, and `JournalEvent` contracts.
6. Market dossier + short path: normalize confluence direction and fix bearish
   candidate handling with tests.
7. Rule retriever: deterministic retrieval from compiled rulebook metadata.
8. Prompt builder: read rendered rulebook/schema instead of hardcoding policy.
9. LLM trader contract: validate `TradeDecisionTicket`, repair invalid JSON once,
   and reject hallucinated rule IDs.
10. Verifier + risk/order compiler: enforce compiled hard rules and compute
    quantity from account/risk/stop.
11. Scheduler orchestration: wire dossier, retriever, LLM, critic, verifier,
    compiler, execution adapter, and fail-closed journaling.
12. Lifecycle journal + replay/eval + final compliance audit.

## Safest First PR

The safest first PR is this governance foundation. It changes only repository
truth and agent orientation, leaving all runtime behavior untouched.

