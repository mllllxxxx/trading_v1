# US-OKX-DEMO-SCHED-001 - OKX Demo Signal Loop

## Status

Implemented MVP.

## User Intent

Run the system demo-first: scan crypto markets, promote eligible signals through
LLM decision and verifier gates, execute approved orders in OKX demo/testnet,
then journal enough evidence to review wins/losses and optimize later.

## Scope Completed

- Added `OKXDemoExecutionAdapter` under `trading/execution/`.
- Added scheduled Berkshire crypto scan loop under `trading/auto/`.
- Added `trade_open_rationale` journal lifecycle event before execution.
- Added open-reason and market context metadata to recorded demo positions.
- Added demo-only env settings to `.env.template` and Docker Compose.
- Kept live trading blocked by `OKX_TESTNET=true` and `OKX_SANDBOX=true`
  requirements.

## Runtime Flow

```text
Berkshire scheduler
  -> scan_crypto_market
  -> run_signal_to_demo_execution
  -> MarketDossier + RetrievedRuleContext
  -> LLM TradeDecisionTicket
  -> critic + verifier + risk compiler
  -> trade_open_rationale
  -> OKX demo adapter
  -> execution_result + position journal
```

## Follow-Ups

- Add dashboard panels for `trade_open_rationale` snapshots.
- Add periodic outcome review jobs after monitor closes trades.
- Add optimizer metrics by signal source, playbook, regime, and adapter.
- Replace file journal with database tables when trade count grows.
