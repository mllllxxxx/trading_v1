# OKX Demo Signal Scheduler

## Intent

Turn the existing Berkshire crypto scanner and signal promotion path into an
operational demo loop:

```text
scheduled scan
  -> SignalCandidate
  -> LLM TradeDecisionTicket
  -> critic / verifier
  -> risk compiler
  -> trade_open_rationale journal event
  -> OKX demo/testnet adapter or paper adapter
  -> execution_result + position journal
```

The loop is allowed to win and lose in demo. It is not allowed to bypass the
LLM, verifier, risk compiler, or live-readiness gate.

## Source Of Truth Domains

- Autonomy: `trading/docs/product/AUTONOMY_POLICY.md`
- Risk: `trading/docs/product/RISK_MANDATE.md`
- Execution: `trading/docs/architecture/EXECUTION_CONTRACTS.md`
- Journal: `trading/docs/architecture/JOURNAL_CONTRACTS.md`
- Signal: `trading/docs/architecture/SIGNAL_CONTRACTS.md`

## Runtime Decisions

- Default signal execution adapter is selected by `SIGNAL_EXECUTION_ADAPTER`.
- `paper` keeps the old broker-free adapter.
- `okx_demo` uses OKX demo/testnet only and refuses live-like env.
- OKX futures opens positions through `/api/v5/trade/order` with a limit
  entry and `attachAlgoOrds` TP/SL legs. It must not use `/api/v5/trade/order-algo`
  as the opening order because OKX validates standalone SL triggers before the
  position exists.
- Missing OKX credentials fail closed with journal evidence.
- The scheduled scan is controlled by `BERKSHIRE_SIGNAL_SCHEDULER_ENABLED`.
- Every accepted order must journal `trade_open_rationale` before execution.

## Trade Open Rationale Payload

The rationale event must explain why the order was opened and include market
context:

- source signal id, source, scanner reasons, blockers;
- LLM action, thesis, reasoning summary, confidence;
- cited playbook and rule IDs;
- market context: symbol, market, timeframe, regime, confluence, direction,
  data quality, data source, data age, spread, funding;
- risk context: entry, stop, take profit, risk percent, risk dollars, notional,
  risk/reward, invalidation, entry plan, risk plan.

## Safety

- No live execution adapter is introduced.
- OKX demo adapter requires `OKX_TESTNET=true` and `OKX_SANDBOX=true`.
- Scheduler respects kill switch, same-symbol position guard, and max position
  guard before execution.
- LLM failure, rule retrieval failure, verifier rejection, compiler rejection,
  and adapter rejection all produce fail-closed journal events.

## Validation

- Unit tests cover OKX demo adapter guards and bracket mapping.
- Signal pipeline tests cover rationale journaling and position metadata.
- Scheduler tests cover one scan/promote cycle and kill-switch skip.
- Full verification runs backend tests, schema checks, rulebook checks,
  frontend tests/build, and Docker build/up health when feasible.
