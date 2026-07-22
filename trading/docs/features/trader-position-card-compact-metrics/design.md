# Trader Position Card Compact Metrics

## Intent

The `/trader` position card should be easier to scan during live monitoring.
The card face prioritizes operator metrics and removes duplicated labels that
make active positions look busier than the data actually is.

## UI Rules

- Combine USD PnL and PnL percent into one primary `P&L` metric.
- Do not show a separate `Profit` metric when it repeats the same value as PnL.
- Keep entry, TP, and SL visible, but visually smaller than the primary PnL
  block.
- Keep open time and timeframe visible, but smaller than entry, TP, and SL.
- Show confidence as a horizontal 0-100 meter with color bands:
  - red below 45
  - yellow from 45 to 69
  - green from 70 and above
- Show the numeric confidence score next to the meter.
- Timeframe appears once on the card face. Details can keep deeper context, but
  the scan view must not repeat timeframe chips.

## Data Rules

- Confidence prefers `decision_context.confidence`.
- Numeric confidence values in `0..1` are normalized to `0..100`.
- Numeric confidence values over `1` are treated as already using a 100-point
  scale.
- If confidence is missing, use `confluence_score / 8` as a fallback and scale
  it to 100.
- PnL USD keeps the existing exchange-first behavior: use
  `position.unrealized_pnl` when present, otherwise compute from mark, entry,
  and size.

## Boundaries

- This is a frontend display change only.
- No exchange behavior, journal behavior, order execution, or risk policy is
  changed.
- The dark terminal theme remains the active visual language.

## Validation

- Unit tests cover the confidence meter, the single combined PnL metric, and
  de-duplicated timeframe display.
- Frontend build must pass before the change is considered complete.
