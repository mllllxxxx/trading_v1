# Live Readiness

Live readiness is the canonical gate that decides when Trade_V1 may move from
OKX demo/paper/testnet into any live-money mode. Until this file and the
corresponding reviewed evidence say otherwise, live trading is disabled.

## Current Status

```text
live_status: blocked
default_execution_target: okx_demo_paper_testnet
promotion_allowed: false
```

The system should actively trade demo when paper/demo mode is enabled, but live
promotion requires reviewed evidence.

## Minimum Evidence Before Promotion

Before live can be considered, the system must produce a reviewed demo report
with at least:

- enough closed trades to make winrate meaningful for the active playbooks;
- positive or acceptable expectancy after fees and slippage assumptions;
- profit factor above the configured readiness threshold;
- max drawdown within the configured risk mandate;
- no unresolved journal corruption or missing lifecycle snapshots;
- verifier rejection reasons understood and not caused by schema drift;
- performance breakdown by signal source, playbook, regime, and symbol;
- proof that OKX demo execution uses the same verifier/compiler path intended
  for live.

Numeric thresholds belong in future config/risk profiles and readiness reports,
not in prompts or scheduler code.

## Promotion Workflow

```text
demo closed trades
  -> replay and metrics
  -> outcome review
  -> optimization proposals
  -> source-of-truth updates
  -> fresh demo validation
  -> live readiness report
  -> explicit user approval
  -> limited live pilot
```

Raw winrate alone is not enough. The report must include expectancy, drawdown,
sample size, profit factor, skipped/rejected trade analysis, and execution
quality.

## Live Blockers

Live remains blocked if any of these are true:

- signal sources do not emit `SignalCandidate` records;
- LLM tickets are not schema-valid or cite fake rule IDs;
- verifier/risk compiler can be bypassed;
- journal snapshots cannot replay the decision lifecycle;
- demo trade outcomes are missing or cannot be tied back to signal source and
  playbook;
- live broker adapter behavior differs from paper/demo without documented
  parity gaps;
- the user has not explicitly approved live promotion.

## First Live Shape

The first live mode, when approved, must be a limited pilot:

- small size;
- fewer symbols;
- strict daily loss cap;
- kill switch active;
- no rules-only fallback;
- same LLM, verifier, compiler, journal, and review loop as demo.
