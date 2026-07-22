# Signal To Demo Execution

## Goal

Promote eligible `SignalCandidate` records into demo/paper executions through
the existing LLM-governed decision stack:

```text
SignalCandidate
  -> MarketDossier from signal evidence
  -> RetrievedRuleContext
  -> LLM TradeDecisionTicket
  -> critic
  -> verifier
  -> risk/order compiler
  -> PaperExecutionAdapter or OKXDemoExecutionAdapter
  -> journal lifecycle
```

This feature does not enable live trading and does not let scanners or the LLM
call broker APIs directly.

## Scope

- Add a generic `auto.signal_pipeline` module for all signal sources.
- Validate `SignalCandidate` before promotion.
- Reject watchlist, blocked, neutral, or blocked-by-evidence signals.
- Build a market dossier from signal evidence for the LLM path.
- Derive numeric entry, stop, and target references from the signal when
  present.
- Use the existing decision pipeline for rule retrieval, LLM ticket, critic,
  verifier, and risk compiler.
- Execute approved compiled orders through `PaperExecutionAdapter` by default.
- Allow `SIGNAL_EXECUTION_ADAPTER=okx_demo` to route approved compiled orders to
  OKX demo/testnet after the same verifier/compiler path.
- Journal signal, dossier, rule retrieval, LLM ticket, critic, verifier,
  compilation, execution result, and fail-closed skips.

## Safety

- Default adapter is broker-free paper execution.
- Execution adapters accept only `CompiledOrder`.
- OKX demo execution requires `OKX_TESTNET=true` and `OKX_SANDBOX=true`.
- Default ticket provider calls the LLM; missing LLM config becomes a
  fail-closed skip.
- Tests inject a fake ticket provider and paper adapter, never broker keys.

## Non-Goals

- No live trading.
- No scheduler rewrite in this slice.
- No rules-only fallback.
- No automatic rulebook updates from outcomes.

## Verification

- Unit tests for eligible signal promotion to paper execution.
- Unit tests for blocked/watchlist signals failing closed.
- Unit tests for LLM/ticket failures not executing.
- Journal lifecycle assertions for signal, dossier, verification, compilation,
  and execution events.
