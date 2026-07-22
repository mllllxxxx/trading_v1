# Continuous Conflict V2 Threshold Calibration

## Status

Approved for shadow-only calibration. This feature cannot change routing,
risk, LLM usage, orders, or the active adaptive-policy state.

## Problem

`continuous_conflict_v2` preserves the broad V1 score scale but smooths its
base score and conflict penalties. Comparing V2 only at V1's active `80/60`
thresholds can misjudge a useful score because its empirical distribution may
shift. V2 therefore needs its own calibration before a testnet canary can be
reviewed.

## Canonical Contract

`trading/config/decision_policy.json` owns the shadow-only search mode, strong
and gray candidate grids, sample gates, full-capture requirement, and report
size. Runtime accepts only `mode=shadow_only`; the scoring experiment must keep
`active_for_routing=false`.

The initial grid is bounded to strong candidates `70,75,80,85,90` and gray
candidates `50,55,60,65,70,75`. Every pair must preserve `gray < strong`.

## Evidence And Validation

- Use only the same valid `shadow` or `backtest` outcomes already admitted by
  the adaptive evaluator.
- Require at least `120` valid V2 scores.
- Require broker-free full candidate capture with counterfactual score floor
  `0`; threshold-limited evidence cannot calibrate V2.
- Split evidence chronologically: initial 70% calibration, final 30% holdout.
- Require at least `30` complete outcomes in both candidate strong and gray
  zones, and at least `8` validation outcomes in both zones.
- Reuse the existing risk-adjusted objective, confidence-bound, profit-factor,
  tail/drawdown, review-load, and segment-stability gates.
- Compare the selected V2 candidate against active V1 on identical outcomes.
- Re-run isolated strategy holdouts using active V1 thresholds versus the
  calibrated V2 thresholds so aggregate improvement cannot hide degradation.

## Output

The shadow experiment adds `threshold_calibration` with status, insufficiency
reasons, current V2-at-V1-threshold baseline, at most five ranked candidates,
an optional reviewed V2 threshold recommendation, and calibration/validation
objective deltas versus active V1.

`review_eligibility` consumes the calibrated V2 candidate when one passes all
search gates. Without a valid candidate it remains `collecting_evidence` or
`not_eligible`. `activation_recommendation` remains null and `auto_apply`
remains false.

`/trader` keeps the adaptive badge compact and may expose calibration status,
candidate thresholds, holdout objective delta, and blockers in its existing
tooltip. It must reuse the current status poll and add no API request.

## Safety Boundary

The evaluator is broker-free and read-only. It must not edit canonical config,
adaptive runtime state, journal outcomes, environment files, or live-readiness
state. Any later demo canary requires a separate approval and rollback
contract.

Evidence-separated candidate confirmations are handled by
`continuous-conflict-v2-review-staging/design.md`; calibration itself remains
pure and does not write that state.

## Acceptance Criteria

- a shifted V2 distribution can select a robust threshold pair different from
  V1's active pair;
- calibration-only gains that fail final holdout produce no recommendation;
- non-zero or unknown counterfactual capture floor blocks calibration;
- one degraded strategy blocks V2 review even when aggregate metrics improve;
- active V1 route, score, risk, and orders remain unchanged.
