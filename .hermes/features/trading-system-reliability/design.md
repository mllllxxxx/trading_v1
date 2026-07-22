# Trading System Reliability And Strategy Evidence

Feature ID: trading-system-reliability
Status: implementation

## Intent

The four demo teams must compete on independent, replayable market evidence.
The LLM remains the decision maker, but it may only decide from confirmed OKX
candles, strategy-specific setup evidence, canonical playbooks, and the shared
verifier/risk compiler path.

## Market Evidence Contract

- OKX public candles are the primary crypto signal source.
- Only confirmed, closed `15m`, `1H`, and `4H` candles are valid.
- Freshness is measured from the close time of the latest confirmed trigger
  candle. The default maximum age is 1,080 seconds (one 15-minute bar plus a
  three-minute provider allowance); older snapshots fail closed.
- Runtime features include EMA20/50/200, ADX14, ATR14, RSI14, Bollinger
  position/width, Donchian20, volume z-score, and volatility percentile.
- Regime and confluence are computed from candle evidence. They must never be
  inferred from the scanner's chosen direction or score.

## Strategy Contracts

- Berkshire requires liquidity/spread quality plus aligned 4H trend and 1H
  confirmation.
- Momentum requires 4H trend, 1H ADX >= 25, and a 15m/1H pullback or reclaim;
  entries farther than 0.5 ATR from the reference are late chases.
- Mean Reversion requires `RANGING`, 1H ADX <= 20, an RSI/Bollinger stretch,
  and a 15m return toward the range. It may not fade a strong trend.
- Volatility Breakout requires prior compression, a Donchian break with volume
  z-score >= 1, and a 15m retest. Raw overextended breaks are HOLD.

Stops and targets are derived from ATR and observed structure. A candidate
without a numeric entry, stop, target, or minimum canonical reward/risk is not
eligible for the LLM draft-ticket stage.

## Runtime Reliability

LLM attempt cooldown is outcome-aware:

| Outcome | Cooldown |
| --- | ---: |
| executed or active exposure | 240 minutes |
| valid HOLD or setup/verifier rejection | 60 minutes |
| provider, stale-data, JSON, schema, or adapter-infrastructure failure | 15 minutes |

Schema validation failures include nested-field errors such as invalid
`entry_plan`, `risk_plan`, or `order_type`. Budget exhaustion during a bounded
repair attempt is also an operational failure and uses the 15-minute cooldown;
it must not be misclassified as a 60-minute setup rejection.

Execution failures caused by unavailable broker metadata or other adapter
infrastructure also use the operational cooldown. Broker rejection of an
otherwise valid submitted order remains auditable and must not be retried by
bypassing the scheduler.

Compact and repair prompts render the generated ticket contract with explicit
OPEN object shapes. Runtime validation errors journal field types and key names,
not raw provider text, so malformed responses remain diagnosable without
dumping arbitrary model output.

Exchange/API exceptions are normalized before journaling. HTML gateway bodies
and other oversized provider payloads are omitted while the HTTP method, URL,
status, and short error summary remain available for operations.

Dynamic OKX swap sizing resolves exact-symbol contract metadata from CCXT
markets first. Because OKX demo/sandbox market catalogs may omit otherwise
tradable swaps, the runtime may fall back to the public instruments endpoint
for the exact `instId`. The fallback must validate response code, symbol,
positive `ctVal`, and positive `minSz`/`lotSz`; otherwise execution fails closed.

The semantic fingerprint includes team, symbol, direction, regime, preferred
playbook, and a price bucket measured in 0.5 ATR. A material fingerprint change
allows a fresh decision before the previous TTL expires.

## Risk Contract

Team risk values of 3%, 4%, 3%, and 5% are targets and a hard 5% ceiling, not
a promise that every order reaches that risk. The compiler records requested,
target, and actual risk. Actual risk is reduced by stop distance, contract
metadata, 3x leverage, 20% margin, and 60% gross-notional caps. It must never be
increased merely to force the target.

During the initial tournament each team may have one active or pending
position. Live trading remains blocked.

OKX demo exposure is not a team-isolated subaccount. Therefore only one team
may own active or pending exposure for a symbol at a time; paper adapters may
keep separate same-symbol team positions. Scheduler team priority rotates each
cycle so symbol ownership is not permanently biased toward catalog order.

## Competition Contract

The leaderboard uses a sample-adjusted composite score:

- 35% Wilson lower-bound winrate;
- 30% expectancy in R;
- 20% profit factor, capped at 2.0;
- 15% drawdown score, reaching zero at 20% drawdown;
- multiplied by `min(closed_trades / 30, 1)`.

Percentage drawdown is measured against the running equity peak that existed
when each drawdown occurred; later gains must not dilute an earlier loss event.

Teams with fewer than 30 closed trades are `provisional`. Historical records
without team/profile/regime attribution remain visible but do not prove a
strategy edge.

Only filled exposure may create a performance record. Canceled, expired, or
rejected pending entries are archived as non-performance lifecycle events.
Closed-trade PnL is net of the configured demo fee estimate and retains actual
risk, regime, and profile metadata for expectancy and replay metrics.

## Verification

- Deterministic unit tests cover features, regimes, setups, brackets, cooldown,
  risk caps, ranking, and schema compatibility.
- Backtests are chronological, include fees/slippage, and never read future
  candles.
- Runtime deployment remains OKX demo only and is smoke-tested on port 8000.
