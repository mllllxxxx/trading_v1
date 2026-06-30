# Execution Contracts

Execution policy is authored in canonical product docs, config profiles, hard
rulebook records, and schemas. Runtime code may enforce these contracts, but it
must not become the only source of policy.

## Decision Boundary

The LLM may produce a `TradeDecisionTicket`. It may not:

- call broker APIs;
- choose final executable quantity;
- bypass verifier or compiler;
- override hard rules;
- switch paper/testnet mode to live mode.

## Required Order Path

New executable orders must follow this sequence:

```text
MarketDossier
  -> RetrievedRuleContext
  -> TradeDecisionTicket
  -> CriticReview
  -> VerifierResult(passed=true)
  -> CompiledOrder
  -> execution adapter
```

Broker execution is allowed only after both verifier and compiler succeed.

## Compiler Responsibilities

The risk/order compiler must:

- derive side from `TradeDecisionTicket.action`;
- require numeric entry, stop-loss, and take-profit levels before execution;
- calculate risk amount from equity and stop distance;
- calculate executable quantity itself;
- clamp risk and notional to hard-rule limits;
- reject orders below the hard-rule reward-to-risk minimum;
- fail closed if compiled hard rules are missing or malformed.

## Execution Adapter Responsibilities

Adapters receive `CompiledOrder` only. They must keep broker-specific behavior
outside scheduler and outside LLM prompts. Paper/testnet guards remain active
until a separate live-readiness approval exists.

The adapter interface lives under `trading/execution/`. Paper and replay
adapters may simulate acceptance, but live broker adapters must remain inert
until explicitly implemented and approved.

## Runtime Evidence

Every future execution path must journal enough lifecycle data to replay the
decision: dossier, retrieved rules, ticket, critic result, verifier result,
compiled order, and execution result.
