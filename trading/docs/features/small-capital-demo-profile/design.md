# Small Capital Demo Profile

## Goal

Run the demo trading loop as if the account only has a small equity balance, starting with a `$200` profile, so signal selection, LLM tickets, risk compiler sizing, execution validation, dashboard capital, and performance review are aligned.

## Problem

The OKX demo account can report a much larger exchange balance than the amount the operator wants to simulate. If runtime sizing reads `$200` but dashboard/account state reads the full OKX demo balance, operators cannot trust performance or risk metrics.

Existing open positions from a larger demo-equity run also pollute the new small-capital performance sample.

## Contract

- `TRADING_RISK_PROFILE=demo_small_200` names the selected profile.
- `TRADING_EQUITY_CAP_USD=200` caps the account equity used by dashboards and runtime sizing.
- `AUTO_CAPITAL=200` and `BERKSHIRE_SIGNAL_EQUITY_USD=200` size new scheduler and Berkshire promotions from `$200`.
- `FUTURES_MAX_POSITION_PCT=0.20` matches `HARD_RISK_001.max_position_pct`.
- With the default hard rule of 1% risk and 20% max notional:
  - max risk per new trade is `$2`;
  - max notional per new trade is `$40`;
  - daily loss cap at 3% is `$6`.
- Dashboard capped equity starts from `$200` and then applies journal realized
  PnL plus synced unrealized PnL, while preserving actual OKX demo equity in
  separate diagnostic fields.
- `/data/journal/equity_study_baseline.json` may record the pre-study PnL
  baseline. When present, capped dashboard PnL is computed after subtracting
  that baseline, so a new `$200` study can start at `$200` without deleting old
  journal evidence.
- Existing OKX demo positions remain visible and reconciled. They are not closed automatically.

## Operational Note

For a clean `$200` performance study, close or otherwise resolve existing large-cap demo positions, then start a new journal/performance window. The profile prevents new orders from being sized with old large equity, but it cannot make old positions become `$200` trades.

## Verification

- Unit test equity cap parsing/account-state capping.
- Unit test order compiler sizing with `$200` equity.
- Targeted backend tests for scheduler, execution, futures bracket, exchange reconciler.
- Frontend build and Docker local rebuild.
