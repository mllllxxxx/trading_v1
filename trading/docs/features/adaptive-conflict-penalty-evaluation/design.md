# Adaptive Conflict Penalty Evaluation

## Status

Approved for observe-only diagnostics. Runtime conflict penalties remain
unchanged in this phase.

## Problem

The current feature engine subtracts a fixed `12` score points for each soft
conflict. That is transparent but rigid: different conflicts and strategies
may have materially different outcome impact. Replacing the penalty without
counterfactual evidence would merely exchange one arbitrary number for another.

## Evidence

Use calibration-eligible shadow/backtest outcomes because shadow capture occurs
before route thresholds. Diagnostics are isolated by `strategy_id`; a
conflicted setup is compared with that strategy's no-conflict outcomes, never
with another strategy's baseline.

For each conflict ID with at least `10` outcomes and a no-conflict baseline of
at least `10` outcomes, report:

- sample count, win rate, average R, and cumulative R;
- delta average R versus the strategy no-conflict baseline;
- two-sided 90% confidence interval for the independent mean difference;
- association label:
  - `harmful`: delta upper bound is below zero;
  - `over_penalized_candidate`: delta lower bound is above zero;
  - `uncertain`: interval crosses zero;
  - `insufficient_evidence`: either sample gate is missing.

Also report outcome metrics by conflict count so operators can inspect whether
stacking multiple fixed penalties behaves monotonically.

## Interpretation Boundary

Conflicts can co-occur and market regimes can confound outcomes. These labels
are associations, not causal penalty estimates. They may justify a shadow-only
continuous score candidate, but cannot directly change `12`, route a trade,
alter risk, or mutate canonical policy.

## Output

`conflict_penalty_diagnostics` is compact and keyed by strategy. Status/API
payloads include at most the highest-sample conflict rows plus counts by label;
full replay reports may retain all rows. No LLM or broker call is allowed.

## Tests

- one strategy cannot borrow another strategy's baseline;
- a clearly negative conflict is labeled harmful;
- a clearly positive conflicted subset is labeled over-penalized candidate;
- sparse baseline/conflict evidence stays insufficient;
- co-occurring conflicts are documented as associations and remain separate;
- diagnostics do not change thresholds or controller state.
