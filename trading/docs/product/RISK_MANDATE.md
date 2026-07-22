# Risk Mandate

Risk policy must be authored in canonical product docs, config profiles, and
rulebook hard rules. Prompt text, scheduler code, validator code, and `.env`
files must not be the only place risk limits live.

## Current Target Mandate

- Crypto futures via OKX paper/testnet first.
- Demo/paper trading is allowed to produce wins and losses so the system can
  learn from real execution outcomes before live money.
- Tournament exposure target: one active or pending position per team, four in
  aggregate while the first 30-trade sample is collected.
- If a Berkshire scan or other signal source finds more eligible candidates
  than the remaining open-position slots, only the top candidates by the
  canonical signal confidence ranking may be promoted.
- Maximum tournament leverage: 3x.
- Every non-HOLD open-position decision requires a stop-loss and risk plan.
- Risk per trade is based on account equity and stop distance, not raw LLM
  quantity.
- Position sizing must be computed by the risk/order compiler.
- Demo loss is acceptable evidence. Unjournaled, unverifiable, or
  compiler-bypassing loss is not acceptable.

## Demo Small-Capital Profile

`demo_small_200` is the canonical demo profile for evaluating system behavior
as if available account equity is only `$200`, even when the OKX demo account
reports a larger exchange balance.

- Profile config: `trading/config/risk_profiles.json`.
- Runtime selector: `TRADING_RISK_PROFILE=demo_small_200`.
- Equity cap: `TRADING_EQUITY_CAP_USD=200`.
- New signal/execution sizing capital: `AUTO_CAPITAL=200` and
  `BERKSHIRE_SIGNAL_EQUITY_USD=200`.
- Max concurrent exposure target remains 10 open positions.
- Max risk per new trade is 1% of capped equity: `$2`.
- Max notional per new trade is 20% of capped equity: `$40`.
- Daily loss cap is 3% of capped equity: `$6`.

Existing exchange positions opened under a larger demo-equity profile remain
visible and reconciled. They must be closed, resolved, or excluded via a new
performance window before treating the next report as a clean `$200` study.
The local runtime may store a non-policy baseline at
`/data/journal/equity_study_baseline.json` so capped-equity dashboard PnL starts
from zero without deleting historical journal evidence.

## Strategy Team Tournament Profile

The strategy-team tournament treats Berkshire and three additional crypto
methods as separate demo teams. Each team receives a `$200` reporting and sizing
allocation so winrate, PnL, and drawdown can be compared without mixing methods.

- Canonical profile: `demo_team_tournament_200`.
- Team capital: `$200` per team.
- Team risk band: 3% to 5% of team capital per new demo trade.
- Hard tournament ceiling: 5% of capped team equity per trade.
- The 3% to 5% values are targets, not forced position sizes. Actual risk is
  reduced when stop distance, broker contract size, 20% margin, 60% gross
  notional, or 3x leverage caps bind.
- Target team risks:
  - Berkshire: 3%.
  - Momentum: 4%.
  - Mean Reversion: 3%.
  - Volatility Breakout: 5%.
- Position and closed-trade journal records should retain `team_id`,
  `team_name`, `strategy_id`, and `strategy_name`.
- Team-tagged signals and dossiers should retain skill profile metadata
  including preferred playbooks, entry style, avoid conditions, LLM guidance,
  and risk personality.
- The cockpit ranks teams by a sample-adjusted competition score: 35% Wilson
  winrate, 30% expectancy R, 20% profit factor, and 15% drawdown score,
  multiplied by `min(closed_trades / 30, 1)`.
- Teams remain `provisional` until 30 closed trades.

This profile is demo-only. It does not approve live trading and does not weaken
the live readiness gate.

## V2 Demo Canary Risk

An operator-approved `continuous_conflict_v2` canary is limited to paper or
OKX demo/testnet. It may hold at most one canary-attributed position globally
and must multiply the strategy team's target risk by at most `0.5` before the
normal compiler ceilings apply. The lower of canary risk and all existing hard
risk limits always wins. Canary approval cannot enable live execution or
weaken stop-loss, leverage, notional, daily-loss, or exposure guards.

## Future Canonical Inputs

- `trading/config/risk_profiles.json`
- `trading/rulebook/source/hard/HARD_RISK_*.json`
- `trading/schemas/order_intent.schema.json`
- `trading/schemas/trade_decision_ticket.schema.json`

