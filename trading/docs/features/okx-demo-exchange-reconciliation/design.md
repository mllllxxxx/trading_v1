# OKX Demo Exchange Reconciliation

## Intent

Make OKX demo/testnet exchange state the authoritative source for currently
open broker exposure, while keeping the journal as the replayable local ledger.

The previous monitor path could close journal positions locally when symbol
normalization drifted between canonical symbols (`BTC-USDT`), OKX native swap
symbols (`BTC-USDT-SWAP`), and CCXT swap symbols (`BTC/USDT:USDT`). That made
`/trader` show no open position even while OKX demo still held exposure.

## Required Flow

```text
OKX demo account
  -> ExchangeSnapshot(active positions, pending algo orders)
  -> journal reconciliation
  -> /api/trader/status
  -> /trader
```

## Rules

- Live mode remains blocked. Reconciliation may read OKX demo/testnet only.
- Open exposure is exchange-truth-first. Journal positions are derived runtime
  evidence and may be repaired from the exchange snapshot.
- Symbol normalization must compare all of these forms safely:
  - canonical: `BTC-USDT`
  - OKX swap: `BTC-USDT-SWAP`
  - CCXT swap: `BTC/USDT:USDT`
- Monitor must not close a local futures position only because symbol text does
  not match. It may close locally only after the exchange snapshot confirms no
  active exposure for the normalized symbol.
- Scheduler pre-execution guard must check exchange exposure as well as the
  journal before opening a new demo order.
- API status should expose sync health so the UI can distinguish journal data
  from exchange data.
- Reconciled positions imported from exchange must be marked
  `source="exchange_reconciler"` and `status="exchange_open"` when the original
  decision context is missing.

## Current Repair

- Add shared `auto.exchange_reconciler`.
- Use exchange snapshots in monitor futures reconciliation.
- Use exchange snapshots in signal pre-execution guard.
- Include `exchange_positions` and `sync_status` in `/api/trader/status`.
- Provide a manual one-shot repair path by calling the reconciler from Python
  with `VIBE_TRADING_HOME` pointed at the active runtime directory.

## `/trader` Display Contract

The `/trader` route must not depend only on `positions.json` when the backend
also returns active `exchange_positions`. The UI should:

- merge journal positions with exchange positions by canonical symbol;
- prefer journal positions when both exist, but enrich them with exchange
  metadata such as `broker_sync_at`, `mark_price`, `unrealized_pnl`,
  `protective_orders`, `instId`, and `ccxt_symbol`;
- fall back to exchange positions when the journal is empty or not yet repaired;
- show sync/order metadata on the position card so operators can see whether
  an open exposure came from the decision lifecycle or from exchange repair;
- keep the fields optional for older journal entries.

## Validation

- Unit tests for symbol normalization and snapshot matching.
- Unit tests for importing exchange positions when the journal is empty.
- Unit tests proving futures monitor does not close positions when OKX still
  reports active exposure.
- Unit tests proving scheduler guard blocks duplicate exchange exposure.
- Frontend test proving exchange/order metadata renders on `/trader` position
  cards.
- Full backend suite with `pytest -x`.
