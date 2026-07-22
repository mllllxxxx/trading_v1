# US-DEMO-SIGNAL-LEARNING-001 - Demo-first signal learning direction

## Status

Implemented foundation slice.

## Intent

Redirect Trade_V1 from isolated advisory/research features toward a whole-system
demo trading loop:

```text
signal sources
  -> SignalCandidate
  -> LLM TradeDecisionTicket
  -> critic/verifier
  -> risk/order compiler
  -> OKX demo/paper execution
  -> journaled outcome
  -> review and optimization
  -> live readiness gate
```

## Scope Completed

- Added canonical demo-first system intent.
- Added live readiness source of truth.
- Added signal contract source of truth.
- Added `SignalCandidate` dataclass validation and JSON schema export.
- Updated Berkshire crypto scanner to emit canonical signal fields while
  preserving existing UI aliases.
- Updated journal lifecycle event allowlist for signal, outcome review,
  optimization, and readiness events.
- Updated prompt builder to accept optional signal candidates.
- Added tests for schema, scanner, prompt, journal, and source-of-truth map.

## Follow-Up

- Promote eligible `SignalCandidate` records into LLM `TradeDecisionTicket`
  creation.
- Journal signal candidates during scheduler cycles.
- Execute approved tickets on OKX demo through the existing verifier/compiler
  path.
- Add closed-trade review reports by signal source, playbook, regime, and
  symbol.
- Add live readiness dashboard metrics and approval workflow.
