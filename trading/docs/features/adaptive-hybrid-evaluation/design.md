# Adaptive Hybrid Evaluation

## Status

Approved for evidence collection and reviewed threshold proposals. The
evaluator never mutates runtime or canonical policy. The separately governed
demo controller may consume an eligible report under
`trading/docs/features/adaptive-policy-controller/design.md`.

## Problem

`adaptive_hybrid_v1` starts with canonical strong/gray thresholds of `80/60`.
Those values are routing priors, not proven optimal parameters. Executed trade
history alone is selection-biased: gray VETO/WAIT and reject proposals have no
realized trade outcome, so comparing only opened trades cannot prove that a
different threshold would have performed better.

## Evidence Classes

- `observational`: real demo/testnet closed trades. Valid for lane health,
  execution quality, and realized performance reporting.
- `shadow`: broker-free counterfactual outcomes recorded from a complete rule
  proposal using the same entry/stop/target and bounded holding horizon.
- `backtest`: chronological, no-lookahead simulations using the runtime feature
  engine and fee/slippage assumptions.

Only `shadow` and `backtest` records are threshold-calibration eligible.
Observational trades must never be silently treated as counterfactual evidence.

## Required Record Fields

Calibration-eligible rows require:

- `rule_score` from `0` to `100`;
- `r_multiple` or enough trusted fields to derive it;
- `evaluation_source` equal to `shadow` or `backtest`;
- `counterfactual_eligible=true`;
- stable `symbol`, `strategy_id`/`team_id`, regime, and timestamp where known.

Backtest or shadow runs that only simulate candidates above an existing score
threshold must also record `counterfactual_score_floor`. The evaluator may
raise that floor or reclassify outcomes above it, but it must not recommend a
lower gray threshold than the evidence floor. A full-candidate shadow run can
set the floor to `0`.

Rows missing those fields remain useful for general replay metrics but are
excluded from threshold recommendations.

## Metrics

The evaluator reports:

- evidence coverage by source and decision lane;
- score buckets (`0-59`, `60-69`, `70-79`, `80-89`, `90-100`);
- sample count, win rate, average R, profit factor, cumulative R, and maximum
  drawdown R;
- current-policy strong/gray/reject baseline metrics;
- threshold proposal readiness and explicit insufficiency reasons.

Outcome rows are ordered chronologically before drawdown or holdout metrics are
computed. Shadow evidence uses its trigger/resolution timestamps; backtests use
entry/exit indices when timestamps are unavailable. Input order is only a
declared fallback, and the report exposes ordering quality instead of silently
pretending unordered rows are chronological.

Each zone additionally reports sample standard deviation, standard error, a
one-sided 90% lower confidence bound for average R, worst outcome, and lower
tail average R. These are robustness diagnostics, not claims that trading
returns are normally distributed.

The evaluator also reports observed LLM review outcomes where shadow evidence
contains an `APPROVE`, `VETO`, or `WAIT` review. This comparison must show
approved outcomes, losses avoided by VETO/WAIT, and profitable outcomes missed
by VETO/WAIT. Sparse review evidence is observability only and may not be
extrapolated to candidates that were never reviewed.

When outcomes contain `continuous_conflict_v2` evidence, the evaluator also
reports an observe-only V1/V2 comparison governed by
`trading/docs/features/continuous-conflict-shadow-score/design.md`. It uses the
same eligible rows and chronological split, excludes malformed experiment
rows with reasons, and cannot produce an activation recommendation. A compact
`review_eligibility` may report whether canonical sample and holdout gates are
ready for human review; it remains non-operational and cannot mutate policy.
Before that readiness decision, V2 may search its own canonical threshold grid
under `trading/docs/features/continuous-conflict-v2-calibration/design.md`.
The search requires full counterfactual capture and must pass the final
chronological holdout; active V1 thresholds and routing remain unchanged.

### LLM Review Health

For each reviewed shadow outcome, the evaluator compares two policies:

- `approve_all_baseline`: execute every reviewed candidate;
- `observed_review_policy`: execute `APPROVE` at its recorded risk multiplier,
  assign zero R to `VETO/WAIT`.

Per-review contribution is `R * (risk_multiplier - 1)`: `APPROVE 1.0` has zero
contribution, `APPROVE 0.5` gives up half of a win or halves a loss, and
`VETO/WAIT 0` contributes `-R`. Positive contribution means review/sizing
improved the approve-all baseline; negative contribution means it reduced
baseline performance. The report shows mean contribution and a two-sided 90%
confidence interval.

Default review-health evidence gates are canonical in
`trading/config/decision_policy.json`:

- at least `30` reviewed outcomes;
- at least `10` approved outcomes;
- at least `10` declined outcomes.
- valid risk-multiplier metadata on at least `90%` of recognized reviews;
- at least `10` reviews before a strategy/regime segment can independently
  mark aggregate health degraded.

Health states are:

- `insufficient_evidence`: one or more sample gates are missing;
- `healthy`: contribution lower confidence bound is above zero and approved
  outcomes have positive average R, with no established degraded segment;
- `degraded`: contribution upper confidence bound is below zero, or approved
  outcomes have non-positive average R, or an established strategy/regime
  segment has a negative contribution interval;
- `inconclusive`: sample gates pass but the confidence interval crosses zero.

The initial enforcement mode is `observe_only`. Health reporting must not
silently bypass LLM, route gray candidates into the strong lane, or mutate
thresholds. Any later `shadow_only`/blocking action requires a separately
reviewed canonical policy change and must remain fail-closed.

Missing/invalid multipliers are never silently treated as `1.0` for health
calibration. Such rows remain visible in raw review counts but are excluded
from policy-value calculations and reduce metadata coverage. They also cannot
claim losses avoided or profitable outcomes missed; status directs operators
to repair review-multiplier metadata before interpreting policy value.

## Chronological Validation

Calibration-eligible rows are split chronologically into an initial 70%
calibration window and a final 30% validation window. Candidate thresholds are
ranked from calibration metrics and must independently pass validation gates.
The current policy is evaluated on the same windows so a changed threshold is
not recommended merely because it overfits the complete sample.

Strategy-specific diagnostics reuse this evaluator in isolated, non-recursive
observe-only runs under
`trading/docs/features/adaptive-strategy-calibration/design.md`. They cannot
activate runtime overrides in this phase.

The report includes:

- calibration and validation counts;
- ordering method and fallback count;
- metrics for both windows and the complete evidence set;
- coverage by source, strategy/team, regime, and symbol;
- established-segment stability for the proposed strong lane.

## Proposal Gate

A proposal requires, by default:

- at least `120` calibration-eligible outcomes total;
- at least `30` outcomes in the proposed strong zone;
- at least `30` outcomes in the proposed gray zone;
- positive strong-zone expectancy;
- strong-zone profit factor at least `1.10`;
- positive one-sided 90% lower confidence bound for strong-zone average R in
  both the complete and validation samples;
- at least `8` validation outcomes in both proposed strong and gray zones;
- validation strong-zone profit factor at least `1.00`;
- no established source/strategy/regime segment with materially negative
  strong-zone expectancy;
- enough positive outcomes in the gray zone to justify spending LLM review
  capacity instead of treating the entire band as noise;
- candidate thresholds satisfy `0 <= gray < strong <= 100`.
- proposed gray threshold is not below the available counterfactual score
  floor.

The grid search may compare threshold pairs but must retain sample counts,
penalize normalized drawdown/tail loss and expected gray-lane review load, and
record objective components. A changed threshold must improve the calibration
objective by a minimum margin without materially regressing validation versus
the current policy. A higher in-sample return with insufficient or unstable
evidence is not a valid recommendation.

## Output Contract

The evaluator returns `AdaptiveThresholdEvaluation` with:

- `status`: `ready` or `insufficient_evidence`;
- current policy thresholds and metrics;
- eligible/excluded counts and exclusion reasons;
- optional recommended thresholds;
- candidate ranking with calibration/validation/complete metrics, robustness
  gates, objective components, and delta versus current policy;
- chronological split, segment coverage, and LLM review-effectiveness evidence;
- compact `llm_review_health` for status consumers without candidate-ranking
  payload;
- optional shadow-score experiment coverage, score deltas, zone transitions,
  V2 threshold calibration, and V1/V2 metrics on
  complete/calibration/validation windows;
- `auto_apply=false` and canonical policy path.

The evaluator may write a JSON/Markdown report under replay output directories.
It must not edit `trading/config/decision_policy.json`, env files, rulebook, or
runtime policy.

## Runtime Observability

`/api/trader/status` may expose a backward-compatible optional
`adaptive_evaluation` summary computed from journal evidence. It must clearly
label observational coverage and must show `insufficient_evidence` until the
proposal gate is proven.

`/api/trader/status.llm_review_health` is an optional compact mirror of the
review-health summary. It must not perform provider or broker calls and must
not change routing behavior.

Status polling uses stale-while-revalidate caching. A cold cache returns a
compact `refreshing` state immediately; a stale cache remains readable while
evaluation runs in a worker thread. Adaptive replay work must not block the
API event loop or delay position/account status rendering.

## Acceptance Criteria

- Replay reports performance by adaptive lane and rule-score bucket.
- Observational records alone cannot produce a threshold recommendation.
- Invalid/missing scores or outcomes are excluded with reasons.
- Calibration-eligible synthetic/backtest records can produce a reviewed
  proposal when all sample and performance gates pass.
- A threshold that looks strong in calibration but fails the final
  chronological validation window cannot be recommended.
- A strong-zone average with a non-positive confidence lower bound cannot be
  recommended even when its raw mean is positive.
- Input ordering quality and review decision outcomes are visible in reports.
- Evaluation never mutates canonical policy.
- Existing replay/status consumers remain backward compatible.
