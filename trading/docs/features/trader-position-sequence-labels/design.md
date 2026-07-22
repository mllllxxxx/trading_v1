# Trader Position Sequence Labels

## Intent

Operators should be able to quickly tell which open or historical trade they
are looking at, and how many trades are visible in the current view.

## UI Rules

- Open position cards show a compact sequence badge formatted as `#n/total`.
- Sequence numbering is based on the order currently rendered by the frontend.
- The sequence badge is visual-only metadata and does not become a broker id or
  journal id.
- Closed trade tables show a leading `#` column.
- Paginated history uses `offset + rowIndex + 1` so numbering remains stable
  across pages and filters.
- The sequence label must stay compact and must not compete with PnL, symbol,
  entry, TP, SL, or confidence.

## Boundaries

- No backend schema change is required.
- No journal or exchange reconciliation behavior is changed.
- Sorting and filtering semantics remain unchanged.

## Validation

- Position card tests cover the open-position sequence badge.
- Frontend tests/build should pass after the display change.
