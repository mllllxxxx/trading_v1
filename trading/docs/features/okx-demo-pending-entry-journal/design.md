# OKX Demo Pending Entry Journal

## Problem

OKX demo bracket submission can return an accepted order before the exchange
reports an active filled position. The runtime currently writes that accepted
order into `positions.json` as an open filled position, which makes `/trader`
show journal exposure that may not exist on OKX yet.

## Contract

- Broker order acceptance is execution evidence, not fill evidence.
- OKX demo accepted orders enter the journal as `status="pending_entry"` with
  `entry_filled=false` and a broker `entry_id`.
- Exchange reconciliation promotes pending entries to active filled positions
  only after OKX reports matching exposure.
- Pending entries do not count as `missing_on_exchange` drift while they wait
  for fill/cancel evidence.
- Paper adapter behavior remains unchanged because paper acceptance is the
  simulated fill boundary.

## Verification

- Unit test signal pipeline OKX accepted order journaling.
- Unit test exchange reconciler ignores pending entries in drift status.
- Run targeted scheduler/signal/reconciler tests.
