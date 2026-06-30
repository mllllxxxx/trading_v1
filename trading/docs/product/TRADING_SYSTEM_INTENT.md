# Trading System Intent

Trade_V1 is a hybrid agentic trading system for crypto futures paper/testnet
operation, with a path toward carefully gated live-like operation only after
source-of-truth governance, verifier, risk compiler, journal, and replay proof
exist.

The system is not a pure rules bot and not a free-form LLM trader.

The intended architecture is:

```text
trusted product docs/config/rulebook/schemas
  -> market dossier
  -> retrieved rulebook/playbook context
  -> LLM TradeDecisionTicket
  -> critic/verifier
  -> risk/order compiler
  -> execution adapter
  -> journal/replay evidence
```

Runtime code must not become the canonical home for trading policy. Code may
enforce compiled policy, render prompt context, or record evidence.

