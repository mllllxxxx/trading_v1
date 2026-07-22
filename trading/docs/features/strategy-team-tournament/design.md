# Strategy Team Tournament

Feature ID: strategy-team-tournament
Status: design-first implementation

## Intent

Trade_V1 should evaluate multiple demo trading methods side by side. Berkshire
becomes the first strategy team instead of the whole system. Three additional
teams run through the same signal, LLM, verifier, risk compiler, demo adapter,
and journal flow so outcomes can be compared fairly.

## Teams

Each team receives an independent `$200` demo capital allocation for reporting
and sizing context. Team records are runtime metadata, not live account
sub-accounts.

| Team ID | Team | Method | Target risk |
| --- | --- | --- | --- |
| `berkshire` | Berkshire | quality and liquidity filtered directional setups | 3% |
| `momentum` | Momentum | MTF trend continuation after a confirmed pullback/reclaim | 4% target |
| `mean_reversion` | Mean Reversion | range-only fade after RSI/Bollinger stretch | 3% target |
| `volatility_breakout` | Volatility Breakout | compression, breakout, volume, and retest | 5% target |

The tournament hard ceiling is 5% risk per team trade. Targets are reduced when
margin, leverage, notional, contract-size, or market-structure caps bind. The
runtime records target and actual risk separately. The live readiness gate
remains blocked; this feature does not enable live trading.

## Skill Profiles

The three non-Berkshire teams must expose canonical skill profile metadata to
the scanner, LLM prompt, rule retriever, journal, and cockpit. The source policy
is `SOFT_STRATEGY_TEAM_001`; runtime profile fields are rendered into signals
and dossiers so each team has a distinct trading personality without bypassing
the shared verifier or compiler.

| Team ID | Preferred playbook | Entry style | Avoid conditions |
| --- | --- | --- | --- |
| `momentum` | `PB_CRYPTO_TREND_CONTINUATION_001` | pullback or retest after confirmed impulse | late chase, thin liquidity, crowded funding |
| `mean_reversion` | `PB_CRYPTO_MEAN_REVERSION_001` | fade stretched move near range boundary | strong trend, disorderly range, missing range structure |
| `volatility_breakout` | `PB_CRYPTO_BREAKOUT_PULLBACK_001` | breakout retest after range expansion | failed expansion, overextended breakout, wide spread |

## Profile Compliance Gate

When a team-tagged market dossier includes `preferred_playbook_ids`, any LLM
ticket that opens a new position must prove it fits the team profile. The demo
threshold is `profile_compliance_score >= 0.60`.

Open tickets must include:

- `profile_compliance_score`
- `profile_compliance_summary`
- `profile_compliance_flags`

The verifier rejects `OPEN_LONG` and `OPEN_SHORT` tickets when the score is
missing, below `0.60`, or when the selected `playbook_id` is not one of the
team's preferred playbooks. `HOLD` and `REQUEST_MORE_DATA` remain valid without
profile compliance fields.

## Contract Changes

SignalCandidate records may carry optional team metadata:

- `team_id`
- `team_name`
- `strategy_id`
- `strategy_name`
- `team_capital_usd`
- `risk_min_pct_equity`
- `risk_max_pct_equity`
- `target_risk_pct_equity`
- `preferred_playbook_ids`
- `required_soft_policy_ids`
- `entry_style`
- `avoid_conditions`
- `llm_guidance`
- `risk_personality`

Positions and closed trades should retain the same fields after execution and
close so dashboard metrics can group by team. Approved positions and closed
trades should also retain ticket profile compliance fields so replay can group
performance by skill profile and regime.

## Runtime Flow

```text
team config
  -> team-specific crypto scan
  -> SignalCandidate with team metadata
  -> shared LLM/verifier/risk compiler pipeline
  -> demo/paper adapter
  -> position/journal with team metadata
  -> cockpit leaderboard
```

The same symbol may be held by different teams in paper journal mode. The OKX
demo adapter still respects exchange exposure guards because one OKX account
cannot safely represent isolated per-team positions on the same instrument.

## Cockpit

The cockpit should show:

- team capital and target risk;
- open position count;
- closed trade count;
- winrate;
- realized PnL;
- unrealized PnL when available;
- max drawdown from the team equity curve;
- sample-adjusted competition score using Wilson winrate, expectancy R, profit
  factor, drawdown, and a 30-trade reliability threshold.

Open position cards and closed trade rows should display the team marker so
operators can distinguish orders during the competition.

## Runtime Reliability And Fairness

The tournament must not let team execution order consume the shared LLM quota
before later teams can be evaluated. The demo quota contract is:

- global hourly provider-call cap: `12`;
- per-source hourly provider-call cap: `3`;
- team provider sources are isolated as `berkshire_signal`,
  `momentum_signal`, `mean_reversion_signal`, and
  `volatility_breakout_signal`;
- daily cost and call caps remain global and fail closed;
- a repair call counts against both the global and source-specific caps.

`HOLD` and `REQUEST_MORE_DATA` are successful no-order decisions. The signal
pipeline journals the ticket and stops before the order compiler. Only
`OPEN_LONG` and `OPEN_SHORT` may reach new-order compilation.

Ticker prices must preserve enough decimal precision for low-priced contracts.
Serializing a positive provider price as zero is a data-contract violation and
must be covered by scanner regression tests.

Accepted OKX demo limit entries are pending, not filled exposure. A pending
entry expires after `3600` seconds by default. The monitor/reconciler must
cancel an expired broker order when it is still open, then remove the pending
journal row without creating a closed trade or PnL observation. Broker-status
uncertainty preserves the row and fails closed for that pending order.
When OKX confirms the entry filled but a clean snapshot confirms there is no
current exposure, archive the row as an unresolved outcome, exclude it from
tournament metrics, and retain the broker fill evidence without inventing an
exit price or PnL.

## Tests

- Strategy team catalog and leaderboard metrics.
- Scanner emits valid team-tagged signals for the three new methods.
- Signal pipeline preserves team metadata into positions.
- Verifier rejects team-profile open tickets below the compliance threshold.
- Different teams may hold the same symbol in paper journal mode.
- Position card renders the team marker.
