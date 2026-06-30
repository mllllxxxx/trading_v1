# Decision Flow

Target flow for LLM-governed trading decisions:

```text
runtime config
  -> market data, portfolio state, journal state
  -> MarketDossier
  -> RetrievedRuleContext
  -> LLM trader creates TradeDecisionTicket
  -> risk critic reviews ticket
  -> verifier enforces compiled hard rules
  -> risk/order compiler computes safe order parameters
  -> execution adapter submits paper/testnet order when allowed
  -> journal records full lifecycle
```

## Fail-Closed Points

- Missing/stale market data: HOLD/no order.
- Missing rulebook context: HOLD/no order.
- LLM invalid JSON after repair: HOLD/no order.
- Hallucinated rule ID: verifier reject.
- Missing stop or risk plan for open-position ticket: verifier reject.
- Risk compiler cannot produce a safe order: no execution.
- Broker uncertainty: halt or reconcile.

## Runtime Boundary

Scheduler should orchestrate the flow. It should not define canonical risk
thresholds, prompt policy, broker policy, symbol universe, or playbook logic.

Runtime modules and future retrievers must follow:

- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`
