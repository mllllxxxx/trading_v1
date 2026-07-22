# Trading System Intent

Trade_V1 is a demo-first agentic trading system. Its active product goal is to
scan markets, generate real trading signals, route deterministic rule proposals
through strong/gray/reject zones, use the LLM for ambiguous gray-zone review,
execute approved tickets only on OKX
demo/paper/testnet, journal wins and losses, review outcomes, and improve the
system before any live-money approval exists.

The system is not a pure rules bot and not a free-form LLM trader.

The intended architecture is:

```text
trusted product docs/config/rulebook/schemas
  -> market scanners and signal engines
  -> SignalCandidate
  -> market dossier
  -> retrieved rulebook/playbook context
  -> deterministic RuleProposal
  -> strong rules lane / gray LLM review / reject no-trade lane
  -> deterministic TradeDecisionTicket
  -> critic/verifier
  -> risk/order compiler
  -> demo/paper execution adapter
  -> journaled outcome and replay evidence
  -> review and optimization
  -> live readiness gate
```

Runtime code must not become the canonical home for trading policy. Code may
enforce compiled policy, render prompt context, or record evidence.

## Active Direction

- Crypto execution is first and uses OKX demo/paper/testnet only.
- Berkshire is one signal and research engine, not the whole system and not an
  executor.
- The strategy-team tournament may run Berkshire, Momentum, Mean Reversion, and
  Volatility Breakout as separate demo teams with independent `$200` reporting
  capital so outcomes can be compared by method.
- Confluence, regime, alpha-zoo, funding, spread, news, and future forex
  scanners should converge on the shared `SignalCandidate` contract.
- Rules-lane and LLM-reviewed decisions should be attributed separately and
  evaluated by actual demo outcomes, not only by prompt quality.
- Live trading remains blocked until the live readiness source of truth says
  the demo evidence is sufficient and the user explicitly approves promotion.

