# Autonomy Policy

## Modes

Trade_V1 must treat autonomous trading modes as fail-closed.

- Research mode may scan markets, create `SignalCandidate` records, and run
  replay without broker execution.
- Review mode may produce `TradeDecisionTicket` records but requires human
  approval before demo execution.
- Paper/demo mode is the default executable target. Under
  `adaptive_hybrid_v1`, it may submit strong-zone deterministic proposals or
  gray-zone LLM-approved proposals only after critic/verifier and risk/order
  compiler approval.
- Optimization mode may analyze closed demo trades, replay snapshots, and
  propose source-of-truth changes, but raw journal output cannot rewrite
  rulebook policy without review.
- Research/optimization may capture and resolve broker-free shadow outcomes
  from confirmed public candles. Shadow records are not positions, do not
  consume LLM budget, and cannot submit broker orders.
- Live mode is blocked until live readiness is explicitly proven, documented,
  and approved by the user.

An operator may explicitly approve a review-ready V2 candidate for a bounded
demo/testnet canary. Approval is valid only for the exact candidate and
canonical contract fingerprints. The canary remains subject to deterministic
allocation, reduced risk, all hard rules, LLM review in its gray lane, and
automatic rollback. There is no live-mode approval path.

## Demo-First Objective

The active system objective is not to avoid trading forever. It is to trade in
demo safely enough to create usable evidence:

- generate signals across the configured market universe;
- route eligible signals into strong, gray, or reject decision zones;
- execute approved tickets only in demo/paper/testnet;
- log why each approved demo order was opened, including the market context,
  LLM thesis, cited rules/playbook, and compiled risk context;
- record wins, losses, rejects, skips, and execution quality;
- review closed trades by signal source, playbook, regime, and risk profile;
- optimize the system only through reviewed source-of-truth changes;
- keep live money disabled until readiness gates pass.

## Required Safety Behavior

- LLM failure results in HOLD/no new order for gray-zone candidates where an
  LLM review is required.
- Rule retrieval failure results in HOLD/no new order.
- Data quality failure results in HOLD/no new order.
- Verifier failure results in HOLD/no new order.
- Risk/order compiler failure prevents execution.
- Broker uncertainty must halt or reconcile, not blindly retry.
- Rules-only fallback is not allowed for gray-zone candidates when
  `REQUIRE_LLM_DECISION=true`.
- The strong rules lane is allowed only when the canonical decision profile is
  `adaptive_hybrid_v1`. It is an explicit lane selected before provider I/O,
  not a fallback after LLM failure.
- Demo execution still requires journal and verifier evidence. Demo money is
  allowed to lose, but unverifiable decisions are not allowed to pollute the
  learning dataset.
- Demo orders without a `trade_open_rationale` journal event must be treated as
  incomplete evidence for review and optimizer metrics.
- LLM quota exhaustion is a hard autonomy guard for gray-zone candidates. When
  a cap is reached, scanning, candidate journaling, and independently qualified
  strong-zone processing may continue, but gray candidates cannot open a new
  position.
- Strategy-team provider calls must also respect a per-source hourly cap so one
  team cannot consume the complete global hourly allowance before later teams
  are evaluated.
- The over-cap behavior is fail-closed for gray-zone review; no candidate may
  change zones because the LLM budget is unavailable.
- `HOLD` and `REQUEST_MORE_DATA` are terminal no-order decisions. They are
  journaled and must not be sent to the new-order compiler.

## Non-Negotiable Boundaries

- LLM output cannot call broker/execution directly.
- LLM output cannot decide final quantity.
- Scheduler cannot submit orders before verifier and risk/order compiler pass.
- Live trading guards must not be weakened by refactor work.
- No runtime path may switch from demo/paper to live without the live readiness
  gate and explicit user approval.

## Operator Observability While Paused

The manual kill switch blocks new entries. It must not terminate read-only
operator surfaces or remove access to exchange reconciliation evidence.
Telegram and web dashboards remain available while paused, and protective
position monitoring may continue under the execution contract. Resume must
reconcile broker state before clearing the manual guard.

Pending shadow outcomes may continue resolving from confirmed public market
data while paused because this is read-only evidence processing. Manual pause
still blocks new broker entries and does not authorize new live behavior.
