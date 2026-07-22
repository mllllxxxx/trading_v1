# Continuous Conflict V2 Demo Canary

## Status

Approved as an inactive-by-default demo/testnet capability. It becomes active
only after an exact-fingerprint operator approval of a `review_ready` V2
candidate. Live execution remains prohibited.

## Purpose

Shadow evidence validates counterfactual ranking, but it cannot prove broker
execution behavior, realized slippage, or the operational cost of moving a
candidate between reject, gray, and strong lanes. The canary measures those
effects with bounded demo risk while V1 remains the default policy.

## Canonical Contract

`trading/config/decision_policy.json` owns the canary policy:

- `mode=manual_demo`;
- adapters exactly `paper` and `okx_demo`;
- deterministic allocation rate `0.20`;
- canary risk multiplier `0.50`;
- at most one concurrent canary position globally;
- only V1/V2 zone disagreements are eligible;
- rollback evaluation starts after 12 closed canary trades;
- rollback when one-sided 90% average-R lower bound is at or below `0`, profit
  factor is below `1.0`, or cumulative R is at or below `-3.0`.

Invalid, weaker, live-capable, or non-manual settings fail policy loading.

## Approval State

`$VIBE_TRADING_HOME/journal/continuous_conflict_v2_canary_state.json` uses
schema `continuous_conflict_v2_canary_state.v1` and atomic writes. Approval
requires:

- review state status `review_ready`;
- exact candidate fingerprint supplied by the operator;
- matching score version and canonical experiment/canary contract fingerprint;
- explicit operator identity and demo-only acknowledgement;
- no existing active approval for another candidate.

The CLI supports `status`, `approve`, and `revoke`. There is no HTTP mutation
endpoint and no environment variable that can bypass approval.

## Runtime Routing

The scheduler loads one immutable V1 policy and one immutable canary snapshot
per cycle. For each blocker-free directional signal it computes both zones.
Only disagreements are eligible. Selection hashes candidate fingerprint,
strategy, symbol, side, and signal ID into a stable bucket; a bucket below the
canonical allocation rate enters canary.

For a selected candidate:

- V2 score and calibrated V2 thresholds determine reject/gray/strong;
- V2 reject journals a canary veto and submits no order;
- V2 gray still requires the normal fail-closed LLM context review;
- V2 strong uses the existing deterministic lane;
- the signal's target risk is multiplied by `0.5` before verifier/compiler;
- every decision, position, and closed trade retains V1 score/zone, V2
  score/zone, candidate fingerprint, allocation bucket, and canary risk.

Signals not selected by the deterministic bucket follow V1 byte-for-byte.
Canary selection never bypasses hard blockers, portfolio limits, cooldowns,
budget gates, verifier, risk compiler, or exchange reconciliation.

## Rollback

Before each scan cycle, the canary controller verifies review state, approval
fingerprints, adapter, and canonical policy. Any mismatch atomically changes
state to `rolled_back` before routing.

After at least 12 canary-attributed closed trades, realized R is computed as
fee-aware `pnl_usd / risk_usd`. The controller rolls back when any canonical
performance floor fails. Missing/invalid risk or PnL metadata is excluded and
reported; it cannot count toward the rollback sample.

Revocation and automatic rollback are one-way for that approval. A new canary
requires a fresh explicit approval of the current review-ready candidate.

## Observability

Controller state decisions use prefix `shadow_score_canary_controller_`.
Scheduler selection and veto decisions use prefix `shadow_score_canary_route_`.
Position and closed-trade attribution lives in `routing_experiment`. `/api/trader/status`
may expose compact canary state and `/trader` may show status, sample count,
candidate zones, and rollback reason in the existing adaptive tooltip. No new
polling request is allowed.

## Acceptance Criteria

- missing approval preserves byte-for-byte V1 routing;
- wrong/stale fingerprint cannot activate canary;
- live/non-demo adapters cannot approve or route canary;
- deterministic selection is stable for the same signal identity;
- V1 reject/V2 promote signals can enter canary without weakening blockers;
- V1 promote/V2 reject signals submit no order and are journaled;
- canary risk is at most half target risk and one canary position globally;
- attribution survives position close and restart reconciliation;
- rollback disables canary before the next scan;
- all existing V1, LLM, verifier, compiler, and journal consumers remain
  backward compatible.
