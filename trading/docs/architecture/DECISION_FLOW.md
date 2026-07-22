# Decision Flow

Target flow for adaptive rulebook-grounded trading decisions:

```text
runtime config
  -> market data, portfolio state, journal state
  -> signal sources produce SignalCandidate records
  -> MarketDossier
  -> RetrievedRuleContext
  -> deterministic RuleProposal with active score and conflicts
  -> capture blocker-free directional proposal as broker-free shadow evidence
  -> reject zone: journal no-order; no LLM call
  -> strong zone: deterministic ticket proposal; no LLM call
  -> gray zone: LLM budget gate and narrow ContextReview
  -> LLM APPROVE/VETO/WAIT controls only approval and 0/0.5/1 risk multiplier
  -> code constructs TradeDecisionTicket from trusted signal/rule context
  -> HOLD / REQUEST_MORE_DATA terminate as journaled no-order decisions
  -> risk critic reviews ticket
  -> verifier enforces compiled hard rules
  -> risk/order compiler computes safe order parameters
  -> journal trade_open_rationale with market context and open reason
  -> execution adapter submits demo/paper/testnet order when allowed
  -> journal records signal, decision, execution, and outcome lifecycle
  -> replay/review computes win/loss and optimizer evidence
  -> confirmed public candles resolve pending shadow outcomes without broker execution
  -> adaptive evaluator uses chronological calibration/validation evidence and reports reviewed threshold proposals
  -> observe-only strategy/conflict diagnostics test score-scale and fixed-penalty associations without changing routes
  -> continuous_conflict_v2 records a continuous shadow score and compares it with active V1 on identical outcomes
  -> shadow-only V2 threshold search calibrates its score distribution on chronological holdout before any canary review
  -> an unchanged eligible V2 candidate needs evidence-separated confirmations before becoming review-ready
  -> exact-fingerprint operator approval may enable a bounded V2 disagreement canary on demo/testnet only
  -> demo policy controller requires evidence-separated confirmations before activating a bounded runtime zone override
  -> post-activation validation may atomically roll back to the previous zone revision
  -> live readiness gate remains blocked until approved
```

## Signal Layer

Scanners do not create broker orders. They emit `SignalCandidate` records that
can be reviewed, shown in UI, journaled, and passed into the LLM as advisory
context.

When a broad universe requires a bounded multi-timeframe enrichment shortlist,
the shortlist must combine high quote-liquidity anchor instruments with
strategy-specific movers. Ranking solely by absolute 24-hour change or range
is not allowed because noisy tail instruments can starve liquid, executable
setups before the strategy rules are evaluated.

Initial signal sources:

- Berkshire crypto scanner;
- existing confluence/regime pipeline;
- alpha-zoo and backtest outputs when promoted through the same contract.

Future signal sources, including forex, must use the same contract before they
can feed the decision path.

## Fail-Closed Points

- Missing/stale market data: HOLD/no order.
- Missing rulebook context: HOLD/no order.
- Gray-zone LLM quota exhaustion: HOLD/no order; journal `llm_budget_skip`.
- LLM invalid JSON after repair: HOLD/no order.
- LLM provider error: HOLD/no order.
- Hallucinated rule ID: verifier reject.
- Missing stop or risk plan for open-position ticket: verifier reject.
- Risk compiler cannot produce a safe order: no execution.
- Broker uncertainty: halt or reconcile.
- Signal source failure: block or mark signal as `REQUEST_MORE_DATA`, not a
  silent trade.
- Demo outcome missing from journal: exclude the trade from optimizer metrics
  until reconciled.

The strong lane is explicitly authorized by the canonical
`adaptive_hybrid_v1` policy. It is not a fallback. A gray candidate must never
be promoted through the strong lane after an LLM budget, provider, or schema
failure. Reject candidates do not consume LLM quota.

The demo adaptive controller may adjust only strong/gray routing zones through
the persisted, versioned override contract. It cannot weaken hard rules,
change risk ceilings, enable live mode, bypass LLM review for gray candidates,
or mutate the packaged canonical policy. One effective snapshot is shared by
the complete multi-team scheduler cycle.

`continuous_conflict_v2` is a separate shadow scoring experiment. It may add
evidence to signals and shadow outcomes, but active V1 remains the sole source
for route, LLM lane, confidence display, risk, and orders. The experiment must
declare `active_for_routing=false`; any other value fails policy loading.
Its threshold search is also shadow-only. It requires full counterfactual
capture, calibrates on the initial chronological window, validates on the final
holdout, and cannot mutate routes or runtime policy.
Review staging persists only candidate identity and evidence milestones. It
cannot approve a candidate, enable canary routing, or replace active V1.
A separate canary controller requires the exact review-ready fingerprint,
manual approval, demo adapter, deterministic allocation, reduced risk, and one
concurrent canary position. Any contract drift, readiness loss, or rollback
breach disables V2 routing and restores V1-only behavior.

## Runtime Boundary

Scheduler should orchestrate the flow. It should not define canonical risk
thresholds, prompt policy, broker policy, symbol universe, or playbook logic.

Runtime modules and future retrievers must follow:

- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`
- `trading/docs/architecture/SIGNAL_CONTRACTS.md`

The budget gate is centralized in `auto.brain` so legacy `call_brain` and
strategy-team `call_trade_decision_ticket` calls share the same daily/global
hourly quota contract. Team sources also receive an independent hourly call
cap so sequential scheduler order cannot starve later teams. Repair calls count
against both caps. Runtime callers must not silently downgrade a gray candidate
to rules-only execution when `AUTO_LLM_OVER_CAP_BEHAVIOR=fail_closed`.

The balanced demo LLM profile uses `160` daily calls, `16` global hourly calls,
and `4` hourly calls per team source. This matches the four 15-minute scheduler
cycles per hour while preserving the daily cost ceiling. Repair calls still
consume quota.

The profile uses compact prompts, low reasoning effort, and a bounded JSON
output budget (`AUTO_LLM_MAX_TOKENS=2400`). Prompt builders should
trim optional context before provider I/O but must preserve the mandatory hard
rule IDs, playbook IDs, and compiled hard-risk limits needed by verifier and
risk compiler.

Compact and repair prompts must render exact object shapes for `entry_plan` and
`risk_plan`; terminal HOLD/REQUEST_MORE_DATA tickets use null for both. JSON,
schema, provider, stale-data, and repair-budget failures receive the short
15-minute operational cooldown rather than the 60-minute setup cooldown.
