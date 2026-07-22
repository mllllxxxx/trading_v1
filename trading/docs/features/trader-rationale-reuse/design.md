# Trader Rationale Reuse

## Goal

Reuse the existing `/trader` screen as the operational surface for trade-open
rationale instead of creating a separate dashboard.

Open positions should show why the demo order was opened and the market context
that existed at entry time. Closed trades should retain the same rationale so
the history table can connect:

```text
opened because X -> closed with result Y -> review/optimize
```

## Source Of Truth Domains

- Journal contract: `trading/docs/architecture/JOURNAL_CONTRACTS.md`
- Decision flow: `trading/docs/architecture/DECISION_FLOW.md`
- Autonomy: `trading/docs/product/AUTONOMY_POLICY.md`

## Scope

- Keep `/trader` as the main view.
- Render `open_reason`, `market_context`, and `decision_context` on open
  position cards when present.
- Preserve rationale metadata when the monitor moves an open position into the
  closed-trade journal.
- Show the retained open reason in both `/trader` history and the full history
  table.
- Keep all new fields optional so existing journal data remains compatible.

## Non-Goals

- No new dashboard route.
- No new trading policy.
- No live trading enablement.
- No optimizer automation in this slice.

## Validation

- Backend test verifies closed trades preserve source signal, decision ID,
  open reason, market context, and decision context.
- Frontend test verifies `PositionCard` renders rationale context for open
  positions.
- Existing backend and frontend suites must continue to pass.
