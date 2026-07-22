# Adaptive Shadow Outcomes

## Status

Approved for demo/testnet evidence collection. Shadow records are research
evidence and never represent broker exposure.

## Problem

Executed trades are selection-biased because reject candidates, gray-zone
VETO/WAIT decisions, quota skips, and portfolio-cap skips have no realized
outcome. Threshold calibration must observe what would have happened to the
same deterministic entry, stop, and target without submitting another order.

## Runtime Boundary

The scheduler may capture a shadow candidate when all of these are true:

- confirmed market data exists;
- direction is `long` or `short`;
- entry, stop, and target are positive and structurally valid for the side;
- no hard data, liquidity, risk, or execution blocker exists;
- `rule_score` is between `0` and `100`.

Capture happens before promotion limits, LLM budget, cooldown, open-position,
and current strong/gray thresholds are applied. This gives the evaluator a
complete blocker-free directional score population. Such records use
`counterfactual_score_floor=0`.

Shadow capture and resolution must not:

- call an execution adapter or authenticated broker endpoint;
- create `positions.json` exposure;
- affect account capital, PnL, win/loss, cooldown, or risk limits;
- consume LLM budget;
- bypass the demo/testnet or live-readiness guards.

## Persistent Records

Pending records live in `journal/shadow_positions.json`. Resolved records are
append-only in `journal/shadow_outcomes.jsonl`.

Each pending record includes:

- deterministic `shadow_id` for team, symbol, confirmed trigger candle, score,
  and price levels;
- source signal/scan/team/strategy identifiers;
- the scheduler cycle's canonical decision-policy snapshot;
- symbol, side, rule score, route zone/lane, conflicts, and regime;
- entry, stop, target, confirmed trigger timestamp, and `15m` bar;
- bounded holding horizon and fee/slippage assumptions;
- `evaluation_source=shadow`, `counterfactual_eligible=true`, and
  `counterfactual_score_floor`.

The deterministic ID makes repeated scans of the same confirmed setup
idempotent across scheduler cycles and process restarts.

## Outcome Resolution

Resolution reads only confirmed public OKX `15m` candles after the trigger
candle. It evaluates candles chronologically:

- first stop touch resolves `stop_loss`;
- first target touch resolves `take_profit`;
- no touch by the bounded horizon resolves `timeout` at the final close;
- a candle touching stop and target is sequence-ambiguous and resolves as
  `ambiguous_both_touched` with `counterfactual_eligible=false`;
- missing required history resolves as `history_gap` with
  `counterfactual_eligible=false` only when reliable recovery is no longer
  possible; transient provider failures leave the record pending.

Outcomes record exit price/reason, holding bars, fee-aware net PnL per unit,
risk per unit, and net `r_multiple`. They do not manufacture account-sized USD
PnL.

## Operational Limits

Defaults for the demo profile:

- enabled: `true`;
- timeframe: confirmed `15m` candles;
- maximum hold: `192` bars (48 hours), matching the chronological strategy
  backtest default;
- fee estimate: `5` bps per filled leg;
- slippage estimate: `2` bps at entry and exit;
- maximum symbols resolved per scheduler cycle: `12`;
- maximum pending records: `2000`.

Symbols are ordered by the oldest `last_checked_at` so a bounded cycle cannot
starve later records. One public candle fetch resolves every pending team record
for the same symbol.

The scheduler starts resolution as a single-flight background worker. Public
candle latency must not delay the primary scan, review, verifier, compiler, or
demo execution path, and a later scheduler cycle must not start a second
resolver while the previous worker is still active.

## Evaluator Integration

Only clean resolved outcomes are calibration-eligible. Observed route metadata
is retained so reports can compare rules baseline, LLM APPROVE, LLM VETO/WAIT,
and operational skips without pretending that a shadow trade was executed.

`/api/trader/status.adaptive_evaluation` may combine observational closed
trades and resolved shadow outcomes. The evaluator itself remains responsible
for excluding observational, ambiguous, incomplete, or malformed rows.

## Acceptance Criteria

- Directional score-below-threshold candidates can be captured without an
  order or LLM call.
- Duplicate scheduler scans do not duplicate pending records.
- Pending records survive restart.
- Confirmed candles resolve TP, SL, timeout, and ambiguous outcomes
  deterministically.
- Ambiguous/history-gap outcomes cannot calibrate thresholds.
- Evaluator status includes eligible shadow outcomes without mutating policy.
- No shadow path imports or invokes an execution adapter.
