# Continuous Conflict Shadow Score

## Status

Approved for shadow-only measurement. `continuous_conflict_v2` cannot route a
trade, change risk, call the LLM, or mutate active policy.

## Problem

The active V1 score quantizes several setup features to integer steps and
subtracts `12` points for every soft conflict. It is transparent and safe, but
a setup that misses a numeric boundary by `0.01` can receive the same penalty
as one that misses it materially. Replacing V1 directly would make an
unvalidated scoring formula operational.

## Canonical Experiment Contract

`trading/config/decision_policy.json` owns the experiment mode, score version,
penalty ceilings, and severity scales. Runtime accepts only:

- experiment ID `continuous_conflict_v2`;
- mode `shadow_only`;
- score version `continuous_base_and_severity_v2`;
- `active_for_routing=false`;
- positive penalty limits no greater than the V1 total ceiling of `48`.

Invalid or missing experiment config fails canonical policy loading. The
experiment must never be recovered by silently activating code defaults.

## Score Formula

The V2 base score preserves each strategy's V1 scale while removing integer
quantization:

- Berkshire: `74 + min(12, ADX / 5)`;
- momentum: `76 + clamp((ADX - 25) / 3, 0, 12) + 4 when reclaim=true`;
- mean reversion: `78 + min(12, max(abs(BB z) - 1.8, 0) * 10) + 4 when returning=true`;
- volatility breakout: `78 + min(10, max(volume z - 1, 0) * 4)`.

Each numeric conflict receives severity in `[0, 1]` from its distance beyond
the boundary divided by the canonical severity scale. Its penalty is
`severity * max_penalty_per_conflict`. Binary regime, trend, direction, and
confirmation conflicts retain severity `1`. Total penalty is capped by
`max_total_penalty`; final score is clamped to `[0, 100]`.

The output records base score, final score, total penalty, and one component
per conflict with observed value, boundary, severity, and penalty where
available. The score is not calibrated probability or confidence.

## Runtime And Journal Boundary

The active fields `score`, `rule_score`, `confidence`, `decision_zone`, route,
LLM lane, risk multiplier, and order parameters continue to use V1 only.
Scanner records add a backward-compatible `experimental_scores` object to the
signal and evidence. Shadow candidates copy that object, while `shadow_id`
continues to use the V1 score and existing entry/stop/target identity.

Resolved and ineligible shadow outcomes already inherit candidate evidence, so
V2 survives restart and resolution without a new journal schema. Older rows
without V2 remain valid.

## Evaluation

The adaptive evaluator compares V1 and V2 on the exact same eligible outcomes
at the current strong/gray thresholds and separately calibrates V2's own
thresholds under `continuous-conflict-v2-calibration/design.md`. It reports:

- valid V2 coverage and exclusion reasons;
- score delta and absolute delta summaries;
- V1-to-V2 zone transition counts;
- overall, calibration, and validation metrics by zone for both scores.

Both comparisons are descriptive and return `auto_apply=false`. V2 threshold
search may produce a reviewed shadow recommendation, but not an activation
recommendation. A future activation requires a separate reviewed contract with
minimum sample, validation, rollback, and demo-only rollout gates.

## Review Readiness

The evaluator may mark V2 `eligible_for_review`; this is evidence readiness,
not an activation recommendation. Canonical gates are owned by the experiment
config and initially require:

- at least `120` valid V2 scores with at least `90%` score coverage;
- at least `4` observed strategies and `30` valid outcomes per observed
  strategy;
- an isolated chronological holdout with at least `8` validation outcomes per
  strategy, where no strategy's V2 objective regresses more than `0.05` versus
  its V1 baseline;
- at least `20` V2 outcomes in both strong and gray calibration zones;
- at least `8` V2 outcomes in both strong and gray validation zones;
- calibration objective gain versus V1 of at least `0.02`;
- validation objective gain versus V1 of at least `0.0`;
- V2 validation strong average-R 90% lower bound above `0`;
- V2 validation strong profit factor at least `1.0`;
- no established negative strong segment in complete or validation evidence,
  using at least `8` outcomes per evaluated segment.

Readiness states are:

- `collecting_evidence`: one or more sample, coverage, strategy, or zone gates
  are missing;
- `not_eligible`: sample gates pass but one or more performance/robustness
  gates fail;
- `eligible_for_review`: every gate passes.

The report includes every gate, blocking reason, objective delta, strategy
coverage, isolated per-strategy V1/V2 holdout comparisons, and segment
failures. Aggregate gains cannot hide one degraded strategy. The report keeps
`activation_recommendation=null` and `auto_apply=false`. Any route activation
still requires a new reviewed policy contract and guarded demo rollout.

An eligible candidate may enter the separate evidence-confirmation lifecycle
defined by `continuous-conflict-v2-review-staging/design.md`. `review_ready`
still cannot change active V1 or approve a canary.

`/api/trader/status.adaptive_evaluation` may expose the compact experiment
comparison through the existing stale-while-revalidate worker. `/trader` may
append `V2 valid/total` to its existing adaptive badge and place score delta,
coverage exclusions, readiness state, and zone transitions in the badge
tooltip. It must not add a polling request or present V2 as an active policy.

## Acceptance Criteria

- crossing a numeric boundary by a small amount changes V2 smoothly;
- binary conflicts still receive the full per-conflict penalty;
- active V1 score and decision zone are byte-for-byte unchanged by V2;
- scanner and shadow outcomes retain V2 evidence without changing identity;
- missing or malformed V2 evidence reduces coverage instead of changing V1;
- no experiment path can submit an order, alter risk, or invoke an LLM.
