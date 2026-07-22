# Adaptive Policy Controller

## Status

Approved for guarded demo/testnet closed-loop operation. Live execution remains
prohibited.

## Problem

The adaptive evaluator can identify a threshold pair that outperforms the
current strong/gray zones, but `decision_policy.json` remains a static prior.
Applying every new recommendation immediately would overfit a single report;
never applying a robust recommendation leaves the rule layer permanently
rigid.

## Source Of Truth

- `trading/config/decision_policy.json` owns controller mode and guardrails.
- `trading/docs/features/adaptive-hybrid-evaluation/design.md` owns evaluator
  evidence and robustness gates.
- Runtime state is evidence, not canonical policy, and lives at
  `$VIBE_TRADING_HOME/journal/adaptive_policy_state.json`.

The controller never edits the packaged canonical config. The effective
runtime policy is the canonical policy plus a validated active zone override.

## Runtime Modes

- `observe_only`: evaluate and journal recommendations without activating an
  override.
- `demo_auto`: stage, activate, and roll back zone overrides only when the
  execution adapter is `paper` or `okx_demo` and canonical `live_enabled=false`.

An operational environment switch may disable the controller, but may not
enable a mode weaker than the canonical policy.

## State Contract

`adaptive_policy_state.v1` contains:

- monotonic `revision`;
- canonical and active strong/gray zones;
- `status`: `baseline`, `staged`, `active`, `rolled_back`, or `error`;
- one staged candidate with confirmation/evidence counters;
- previous zones for one-step rollback;
- last evaluated, activation, and rollback evidence counts;
- compact evidence and reason metadata;
- UTC update timestamp.

Writes are atomic. Missing state starts from canonical zones. Corrupt,
incompatible, out-of-bounds, or non-monotonic state fails closed to canonical
zones and is reported; it is never silently trusted.

## Activation Gate

The evaluator remains broker-free and `auto_apply=false`. The controller may
activate its reviewed recommendation only when all conditions hold:

1. Evaluation status is `ready` and a changed recommendation exists.
2. Evaluator calibration, chronological validation, confidence-bound,
   profit-factor, tail/drawdown, and segment-stability gates already passed.
3. Every strategy team enabled for the runtime has at least `20`
   calibration-eligible outcomes, so a dominant team cannot move global zones
   on behalf of an under-sampled team.
4. The report explicitly marks the recommendation eligible for this guarded
   demo controller. Raw `requires_human_review` still applies outside it.
5. A candidate that expands either edge of the gray lane requires aggregate
   `llm_review_health=healthy`; insufficient, inconclusive, or degraded review
   evidence may not increase LLM routing exposure.
6. The same bounded candidate is confirmed at least twice.
7. At least `20` new calibration-eligible outcomes exist between confirmations.
8. Each activation moves either threshold by at most `5` points.
9. Active zones remain within configured bounds and preserve at least a
   `10`-point strong/gray gap.

A changed candidate replaces the staged candidate and resets confirmations.
Repeated scheduler cycles over unchanged evidence do not count as additional
confirmation.

## Rollback Gate

After activation, rollback evaluation waits for at least `20` new eligible
outcomes. The controller restores the previous zones when the active policy's
validation strong lane has enough samples and either:

- one-sided 90% average-R lower bound is not positive; or
- validation strong profit factor is below `1.0`.

Rollback increments revision, clears staging, records the reason, and requires
new evidence before another activation. It never changes live readiness or
broker mode.

## Scheduler Boundary

At the beginning of one Berkshire scheduler cycle:

1. resolve pending shadow outcomes;
2. run one controller decision over persisted shadow outcomes;
3. load one effective policy snapshot;
4. share that immutable snapshot across every team, scanner, shadow record,
   route, and promotion in the cycle.

Controller failure journals an error and uses canonical zones for that cycle.
No LLM or broker call is made by the controller.

## Observability

Journal lifecycle events distinguish `skipped`, `staged`, `activated`,
`rolled_back`, and `error`. `/api/trader/status.adaptive_policy_controller`
returns compact state, current effective zones, revision, evidence milestone,
and last action without including full evaluator candidate rankings.

`/trader` shows a compact effective-policy badge with strong/gray zones,
revision, and state tone. Details remain in the hover title; the badge reuses
the existing status poll and must not add another request or render full
evaluation payloads.

## Tests

- unchanged evidence cannot manufacture confirmations;
- changed candidates reset staging;
- two evidence-separated confirmations activate a bounded step;
- invalid/corrupt state falls back to canonical policy;
- live/non-demo adapter cannot activate;
- degraded post-activation validation rolls back;
- one scheduler cycle uses exactly one post-controller policy snapshot;
- controller path makes zero LLM and broker calls.
