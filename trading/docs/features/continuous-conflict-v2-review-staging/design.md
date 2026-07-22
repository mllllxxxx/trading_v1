# Continuous Conflict V2 Review Staging

## Status

Approved for demo/testnet review staging only. Active V1 remains the sole score
for ranking, routing, LLM use, risk, and orders.

## Problem

One `eligible_for_review` report can still be a transient result. A V2
candidate needs evidence-separated confirmation and a stable identity before
an operator should consider a future canary. The evaluator must remain pure,
so this lifecycle belongs to a separate scheduler-owned state controller.

## Canonical Contract

`trading/config/decision_policy.json` owns `review_staging`:

- `mode=review_only`;
- at least two confirmations;
- at least 20 new eligible outcomes between confirmations;
- adapters limited to `paper` and `okx_demo`;
- operator approval is mandatory.

The V2 experiment must remain `shadow_only` and
`active_for_routing=false`. Invalid or weaker settings fail policy loading.

## State Contract

`$VIBE_TRADING_HOME/journal/continuous_conflict_v2_review_state.json` uses
schema `continuous_conflict_v2_review_state.v1` and contains:

- status `baseline`, `staged`, `review_ready`, `invalidated`, or `error`;
- monotonic revision;
- score version and canonical experiment fingerprint;
- one candidate fingerprint and strong/gray thresholds;
- confirmation count and first/last confirmed eligible evidence counts;
- last evaluator status, action, reason, and UTC timestamps;
- explicit `operator_approval_required=true`, `operator_approved=false`,
  `active_for_routing=false`, and `canary_enabled=false`.

Writes are atomic. Corrupt, incompatible, stale-version, or stale-contract
state fails closed and is never silently replaced.

## Lifecycle

1. The scheduler resolves pending shadow outcomes and runs the active V1 policy
   controller.
2. The review controller evaluates at most the latest 5,000 outcomes against
   the cycle's effective V1 zones.
3. An unchanged evidence fingerprint performs no new confirmation.
4. A new eligible candidate starts at confirmation one.
5. The same candidate reaches `review_ready` only after the configured number
   of confirmations and evidence milestones.
6. A changed candidate resets confirmation to one.
7. A previously staged or review-ready candidate becomes `invalidated` when
   calibration/readiness no longer passes.

## Safety Boundary

The review controller has no approval mutation endpoint and makes no broker or
LLM call. The separately governed demo canary CLI may consume an exact
`review_ready` fingerprint under
`continuous-conflict-v2-canary/design.md`; review readiness by itself is not
canary permission.

## Observability

The scheduler journals lifecycle actions. `/api/trader/status` may expose a
compact optional `shadow_score_review_controller` object, and `/trader` may add
its status and confirmation count to the existing adaptive badge tooltip.
Neither adds a polling request.

## Acceptance Criteria

- unchanged evidence cannot manufacture confirmations;
- changed thresholds or score contract reset staging;
- two evidence-separated confirmations become review-ready;
- loss of readiness invalidates the candidate;
- non-demo adapters do not evaluate or write state;
- corrupt state is reported without overwrite;
- state always reports approval false, canary false, and routing false.
