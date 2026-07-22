# Adaptive Hybrid Decision Routing

## Status

Approved for demo/testnet implementation as `adaptive_hybrid_v1`.

## Problem

The current pipeline turns strategy thresholds into binary blockers and then
asks an LLM to reproduce a complete trade ticket. That makes strategy rules
brittle, wastes tokens on obvious setups, and gives the LLM control over fields
that should remain deterministic. It also makes it hard to measure whether the
LLM improved a decision or merely narrated the rule result.

## Goals

- Keep hard safety, data, broker, exposure, and risk limits deterministic.
- Convert strategy quality into continuous, inspectable scores.
- Call the LLM only where contextual judgment can change the result.
- Keep symbol, side, price levels, size, leverage, and timestamps outside LLM
  control.
- Record enough baseline and review evidence to compare rules-only proposals
  with LLM-reviewed outcomes.
- Keep all executable behavior restricted to paper/demo/testnet.

## Non-Goals

- Enabling live trading.
- Allowing silent rules-only fallback after an LLM failure.
- Letting runtime journal evidence rewrite policy automatically.
- Claiming that a raw scanner score is a calibrated win probability.

## Decision Model

Every fresh candidate first receives a deterministic `RuleProposal`:

- `rule_score`: continuous score from `0` to `100`.
- `score_components`: normalized evidence and component weights.
- `conflicts`: soft strategy disagreements that reduce quality but do not act
  as hard safety blockers.
- `hard_blockers`: stale/missing data, invalid levels, spread/liquidity safety,
  exposure, or other compiled hard-rule failures.
- `decision_zone`: `strong`, `gray`, or `reject`.

Default zones are:

```text
strong: rule_score >= 80 and no hard blockers
gray:   60 <= rule_score < 80 and no hard blockers
reject: rule_score < 60 or any hard blocker
```

Thresholds are canonical configuration. Runtime env may select the policy
profile but must not silently redefine these thresholds.

The scheduler loads one immutable policy snapshot after runtime block guards
and before the first team scan. That exact object is injected through every
team scanner that supports it, shadow capture/annotation, route proposal, and
promotion provider in the cycle. A policy file change takes effect on the next
cycle; it must not split one cycle across different thresholds.

Cycle summaries, scan envelopes, and shadow records retain a JSON-safe policy
snapshot containing profile, zone thresholds, lanes, and review-health
enforcement. Dependency-injected legacy scan/promotion callbacks remain
compatible: the scheduler passes `decision_policy` only when the callable
declares that keyword or accepts `**kwargs`.

The feature engine computes score/components and may accept explicit thresholds
for deterministic routing, but it does not own runtime threshold values.
Scanner and chronological backtest entrypoints must load
`trading/config/decision_policy.json` and inject its strong/gray values. Missing
or invalid canonical policy fails closed; scanner labels, promotion gates,
shadow capture, scheduler routing, and backtest metadata must not retain an
independent hardcoded `60/80` routing boundary.

## Routing

```text
SignalCandidate
  -> deterministic RuleProposal
  -> reject: journal no-order; do not call LLM
  -> strong: deterministic ticket proposal; no LLM call
  -> gray: LLM ContextReview is required
       -> APPROVE: deterministic ticket with approved risk multiplier
       -> VETO: HOLD/no order
       -> WAIT: REQUEST_MORE_DATA/no order
  -> critic consistency review
  -> hard-rule verifier
  -> deterministic risk/order compiler
  -> demo/testnet execution adapter
```

The strong lane is an explicitly authorized policy lane, not a fallback. If a
gray-zone LLM call fails, returns invalid output, or is denied by budget, the
candidate fails closed and may not be rerouted to the strong lane.

## LLM Contract

The gray-zone LLM returns a narrow `LLMContextReview`:

```json
{
  "schema_version": "llm_context_review.v1",
  "review_id": "review-id",
  "timestamp_utc": "ISO-8601",
  "decision": "APPROVE | VETO | WAIT",
  "risk_multiplier": 0.5,
  "conflict_flags": ["short flag"],
  "evidence_refs": ["signal:...", "rule:..."],
  "reasoning_summary": "short context-grounded explanation"
}
```

`risk_multiplier` must be one of `0`, `0.5`, or `1`. `VETO` and `WAIT` require
`0`. The LLM cannot emit or modify symbol, market, timeframe, side, entry,
stop, target, leverage, quantity, or timestamps used by an order.

## Deterministic Ticket Construction

For an approved strong or gray proposal, code constructs the existing
`TradeDecisionTicket` from the signal, dossier, retrieved rulebook, and
canonical risk profile. Numeric entry/stop/target values remain signal evidence
and final quantity remains compiler-owned. The verifier must bind ticket
symbol, market, timeframe, and opening direction back to the dossier.

`HOLD` and `REQUEST_MORE_DATA` are valid terminal tickets with null entry/risk
plans. They are journaled and never sent to the order compiler.

## Observability And Evaluation

The journal records:

- `rule_proposal` for the deterministic baseline;
- `hybrid_route` for zone and selected lane;
- `llm_context_review` only for gray-zone provider responses;
- existing verifier, compiler, rationale, execution, and outcome events.

Open and closed trade metadata retain policy profile, decision lane, rule score,
score components, conflicts, and LLM review when present. Replay groups outcomes
by lane and stores the baseline proposal so later evaluation can compare:

- strong rules lane outcome;
- gray rules proposal before review;
- LLM approve/veto/wait behavior;
- risk multiplier effect;
- net PnL, drawdown, expectancy, and execution quality.

No threshold or playbook is changed automatically from these observations.
Threshold evaluation follows
`trading/docs/features/adaptive-hybrid-evaluation/design.md` and must separate
observational outcomes from calibration-eligible shadow/backtest evidence.

## Safety And Failure Behavior

- Hard blocker: reject before any provider call.
- Gray-zone budget/provider/schema failure: fail closed, journal the reason.
- Missing rulebook context: fail closed.
- Critic/verifier/compiler rejection: no order.
- Broker uncertainty: halt/reconcile.
- Live execution remains disabled.
- Legacy full-ticket LLM mode remains available for backward-compatible tests
  and controlled migration, but is not the default adaptive policy.

## Configuration

Canonical thresholds live in `trading/config/decision_policy.json`.
Operational selection uses:

```text
AUTO_DECISION_POLICY=adaptive_hybrid_v1
AUTO_LLM_REVIEW_MAX_TOKENS=500
```

## Acceptance Criteria

- Strong candidates can reach verifier/compiler without an LLM call.
- Gray candidates cannot execute without a valid LLM review.
- Reject candidates do not consume LLM budget.
- Strategy disagreements appear as score/conflict evidence instead of arbitrary
  binary blocks unless they are true hard-safety failures.
- The verifier rejects ticket/dossier identity or direction mismatch.
- Journal/UI evidence can identify policy, lane, baseline, review, and outcome.
- Existing explicit legacy ticket-provider tests remain backward compatible.
- Alternate reviewed canonical thresholds propagate through scanner status,
  promotion eligibility, scheduler lane, shadow metadata, and backtest output.
- One scheduler cycle loads the canonical policy once and journals the same
  snapshot across every team, shadow candidate, and promotion attempt.
- Docker runtime remains demo/testnet-only.
