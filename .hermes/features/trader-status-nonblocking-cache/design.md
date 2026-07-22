# Trader Status Nonblocking Cache

## Intent

The `/trader` UI must render quickly even when OKX demo/testnet reads are slow.
Exchange state remains the preferred truth for open futures exposure and current
account equity, but the dashboard request path must not block the FastAPI event
loop on every frontend poll.

## Runtime Rules

- `/api/trader/status` reads local journal state synchronously and returns it
  immediately.
- OKX demo position/account reads run in a background thread and update a small
  in-memory cache.
- Dashboard status responses reuse the latest cached exchange snapshot when it
  is available.
- If the exchange cache is empty or currently refreshing, the status response
  falls back to journal account state and labels the sync state as refreshing.
- A stale exchange cache is still better than blocking the UI; the response
  marks cache age/status while a refresh runs.
- Startup and resume reconciliation remain mandatory before the scheduler can
  open new demo orders. This cache changes only the dashboard read path.
- Ticker polling uses the same pattern: return cached prices quickly and refresh
  OKX prices in the background.

## Config

- `TRADER_STATUS_EXCHANGE_CACHE_TTL_S` controls how long dashboard exchange
  snapshots are considered fresh.
- `TRADER_STATUS_EXCHANGE_STALE_TTL_S` controls when stale labels become
  explicit.
- `TRADER_TICKER_CACHE_TTL_S` controls dashboard ticker freshness.
- `OKX_HTTP_TIMEOUT_MS` caps dashboard OKX client calls.

## Boundaries

- No live trading is enabled.
- Demo/testnet guards are unchanged.
- This does not replace startup reconciliation, monitor reconciliation, or
  same-symbol exposure checks.
- Cache metadata is optional and backward-compatible for existing consumers.

## Validation

- Unit tests cover cache freshness/age helpers.
- Frontend build must still pass.
- Docker rebuild must smoke `/trader`, `/api/trader/status`, and ticker latency.
