# Demo-First Signal Learning System

## Goal

Redirect Trade_V1 from isolated research surfaces into a whole-system demo
trading loop:

```text
market scanners
  -> SignalCandidate
  -> LLM TradeDecisionTicket
  -> critic/verifier
  -> risk/order compiler
  -> OKX demo/paper execution
  -> journaled outcome
  -> review and optimization
  -> live readiness gate
```

The current target is not live money. The current target is a replayable OKX
demo system that generates real trading signals, records wins and losses, and
uses reviewed outcomes to improve the rulebook, prompts, risk profiles, and
signal sources before any live approval exists.

## Source-of-Truth Changes

Canonical docs must state the system direction directly:

- `trading/docs/product/TRADING_SYSTEM_INTENT.md` defines demo-first learning
  as the active product intent.
- `trading/docs/product/AUTONOMY_POLICY.md` defines paper/demo as the default
  executable mode.
- `trading/docs/product/LIVE_READINESS.md` defines the gate before live.
- `trading/docs/architecture/SIGNAL_CONTRACTS.md` defines the shared signal
  contract.
- `trading/docs/architecture/DECISION_FLOW.md` includes signal generation
  before LLM tickets.
- `trading/docs/architecture/JOURNAL_CONTRACTS.md` includes signal, outcome,
  review, optimization, and readiness events.
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md` maps the new domains.

## Runtime Contract

All signal sources should emit `SignalCandidate` records. A signal may suggest
direction and action intent, but it cannot execute and cannot bypass the LLM,
verifier, risk compiler, or journal.

The first runtime source is the Berkshire crypto scanner. Later sources can
include confluence, regime, alpha-zoo, funding, spread, news, and forex
scanners.

## Non-Goals For This Slice

- Do not enable live trading.
- Do not bypass OKX demo/testnet guards.
- Do not make Berkshire place orders directly.
- Do not auto-promote every signal to execution.
- Do not implement full optimizer logic yet.

## Verification

- Schema export includes `signal_candidate.schema.json`.
- Backend tests validate `SignalCandidate` rules.
- Berkshire scanner tests assert emitted signals follow the shared contract.
- Existing source-of-truth and route tests continue to pass.
