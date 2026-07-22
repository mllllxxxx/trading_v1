# Trader Real Capital And Compact Position Details

## Intent

The `/trader` route should show the operator's current broker/account state
instead of relying only on the local journal. The journal remains replayable
runtime evidence, while OKX demo/testnet account state is the preferred source
for current capital, open unrealized PnL, and available margin.

Position cards should stay compact. The default card face must show the
numbers an operator needs while scanning active exposure. Rationale, market
context, exchange metadata, and broker order ids belong behind an inline
`Details` disclosure.

## Data Contract

`/api/trader/status` keeps the existing `stats` object for compatibility and
adds `account_state`:

```json
{
  "account_state": {
    "source": "okx_demo",
    "mode": "demo",
    "synced_at": "2026-07-01T00:00:00Z",
    "starting_capital_usd": 10000.0,
    "current_capital_usd": 10023.45,
    "total_pnl_usd": 23.45,
    "unrealized_pnl_usd": -7.86,
    "journal_realized_pnl_usd": 31.31,
    "available_balance_usd": 9980.12,
    "margin_used_usd": 43.33,
    "errors": []
  }
}
```

If account fetch fails or exchange reconciliation is disabled, the backend
returns a `journal_fallback` account state built from journal stats.

## UI Rules

- `TopBar` and `LeftPanel` prefer `account_state` for displayed capital/PnL.
- The UI still falls back to `stats` so older responses and offline tests work.
- Position card main face shows symbol, side, PnL USD, PnL %, entry, TP, SL,
  profit/UPL, open time, timeframe, confidence, R/R, size, and leverage.
- `Details` opens inline and contains open rationale, thesis, rule citations,
  market context, exchange sync fields, broker ids, protective orders, and mark
  source.
- Styling stays in the current dark terminal system. The visual reference is a
  hierarchy reference, not a request to switch to a light theme.

## Safety Boundaries

- No live trading is enabled.
- No paper/testnet guards are weakened.
- Account reads are read-only and use the same OKX demo/testnet boundary as
  exchange position reconciliation.
- Journal values are preserved for history/replay and do not become policy.

## Validation

- Backend tests cover account normalization, account fallback, and exchange
  position sync compatibility.
- Frontend tests cover account metric derivation and the position `Details`
  disclosure.
- Runtime validation rebuilds the Docker image and smokes `/trader`.
