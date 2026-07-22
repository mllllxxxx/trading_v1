# US-SIGNAL-DEMO-EXEC-001 - Signal to demo execution

## Status

Implemented MVP foundation.

## Intent

Promote eligible `SignalCandidate` records into demo/paper execution through
the governed decision stack:

```text
SignalCandidate
  -> MarketDossier
  -> RetrievedRuleContext
  -> LLM TradeDecisionTicket
  -> critic/verifier
  -> risk/order compiler
  -> PaperExecutionAdapter
  -> journal lifecycle
```

## Completed

- Added `trading/auto/signal_pipeline.py`.
- Added default LLM ticket provider using `llm.prompt_builder` and
  `brain.call_trade_decision_ticket`.
- Added signal validation, promotion gate checks, signal-derived dossier, and
  signal-derived price levels.
- Added paper/demo execution via `PaperExecutionAdapter`.
- Added lifecycle journal events for signal, dossier, rules, LLM ticket,
  critic, verifier, compilation, execution, and fail-closed skips.
- Added `auto_promote_demo` support to `POST /api/berkshire/crypto/scan`.
- Added `/berkshire` UI button `Scan + demo`.
- Added tests for execution, fail-closed behavior, prompt signal context, and
  Berkshire route promotion.

## Safety Notes

- Default execution is broker-free paper mode.
- Missing LLM config fails closed.
- No rules-only fallback is introduced.
- No live trading path is enabled.
- Execution adapters still accept `CompiledOrder` only.

## Follow-Up

- Add OKX demo/testnet execution adapter behind the same `ExecutionAdapter`
  interface.
- Wire scheduler cycles to call `run_signal_to_demo_execution` for eligible
  signals.
- Add outcome review jobs that convert closed demo trades into
  `trade_outcome_review` and `optimization_snapshot` events.
- Add UI metrics for winrate, profit factor, drawdown, expectancy, and source
  performance.
