# Autonomy Policy

## Modes

Trade_V1 must treat autonomous trading modes as fail-closed.

- Research mode may run analysis and replay without broker execution.
- Review mode may produce decisions but requires human approval for action.
- Paper mode may submit only paper/testnet orders after verifier and order
  compiler approval.
- Live mode is out of scope until live readiness is explicitly proven and
  approved.

## Required Safety Behavior

- LLM failure results in HOLD/no new order when an LLM decision is required.
- Rule retrieval failure results in HOLD/no new order.
- Data quality failure results in HOLD/no new order.
- Verifier failure results in HOLD/no new order.
- Risk/order compiler failure prevents execution.
- Broker uncertainty must halt or reconcile, not blindly retry.
- Rules-only fallback is not allowed when `REQUIRE_LLM_DECISION=true`.

## Non-Negotiable Boundaries

- LLM output cannot call broker/execution directly.
- LLM output cannot decide final quantity.
- Scheduler cannot submit orders before verifier and risk/order compiler pass.
- Live trading guards must not be weakened by refactor work.

