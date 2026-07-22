# Trader Startup Position Reconciliation

## Intent

Open demo futures positions must survive process, container, and UI restarts.
The local journal is replay evidence, but OKX demo/testnet is the current
source of truth for active futures exposure.

## Contract

- Shutdown must never flatten, delete, or rewrite open journal positions.
- Startup must reconcile OKX demo futures exposure before any scheduler can
  open new orders.
- Resume from a manual pause must run the same reconciliation before clearing
  the pause.
- If OKX reconciliation fails, the system must preserve local positions and
  block new entries until a later reconciliation succeeds.
- A successful exchange snapshot may import missing exchange positions into
  the journal with `source="exchange_reconciler"` and
  `sync_status="exchange_reconciled"`.
- A local position missing from the first clean exchange snapshot must be
  logged as drift and confirmed on a later clean snapshot before it is closed
  locally.

## Runtime Shape

- `journal.STARTUP_SYNC_GUARD` blocks new trade entries independently from the
  manual `/data/STOP` kill switch.
- `journal.is_trading_blocked()` is the entry guard for schedulers and manual
  force-trade paths.
- `journal.is_killed()` remains the manual STOP state so the orchestrator does
  not exit just because startup sync is retrying.
- `exchange_reconciler.run_startup_reconciliation()` performs read-only OKX
  snapshot reconciliation and clears the startup guard only after a successful
  snapshot.

## Verification

- Empty journal plus active OKX demo position imports the position before
  scheduler execution.
- Existing journal positions are preserved by restart setup.
- Startup sync failure leaves positions unchanged and blocks entries.
- Resume from STOP succeeds only after reconciliation succeeds.
- Futures monitor requires a second clean missing-on-exchange confirmation
  before locally closing a journal position.
