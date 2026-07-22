# LLM Role

The LLM is a contextual review component for ambiguous gray-zone setups. It is
not an executor, a price-level generator, or the final risk authority.

In `adaptive_hybrid_v1`, deterministic code first creates a continuous
`RuleProposal`. Strong proposals do not require an LLM call, reject proposals
do not consume LLM budget, and gray proposals require the LLM to emit a narrow
`LLMContextReview`. Code then builds any `TradeDecisionTicket` from trusted
signal and rule context.

## Adaptive Review Output

For a gray-zone setup the LLM may return:

- `APPROVE` with risk multiplier `0.5` or `1`;
- `VETO` with risk multiplier `0`;
- `WAIT` with risk multiplier `0`.

It may add short conflict flags, evidence references, and a reasoning summary.
It may not create or modify symbol, market, timeframe, side, entry, stop,
target, leverage, quantity, or order timestamps.

## Legacy Full-Ticket Output

The backward-compatible legacy LLM output is a `TradeDecisionTicket` with one
action:

- `HOLD`
- `OPEN_LONG`
- `OPEN_SHORT`
- `CLOSE_POSITION`
- `REDUCE_POSITION`
- `REQUEST_MORE_DATA`

## Required For Non-HOLD Tickets

- Existing `playbook_id`.
- Existing rule citations.
- Thesis.
- Entry plan.
- Risk plan.
- Invalidation conditions.
- Confidence.
- Data quality.
- Source signal reference when the decision was triggered by a signal.

## Not Allowed

- Calling broker/execution tools.
- Choosing final order quantity.
- Overriding hard rules.
- Bypassing verifier or risk/order compiler.
- Changing autonomy mode or live trading state.
- Treating a signal as executable without verifier and compiler approval.

## Signal Handling

In the adaptive gray lane, the LLM may disagree with a rule proposal. It can:

- approve the deterministic side and levels;
- veto when contextual evidence conflicts with the proposal;
- wait when evidence is incomplete;
- reduce risk from `1` to `0.5`.

The LLM may not invent a source signal, hallucinate rule IDs, or use raw
scanner confidence as final trade authority.

## Review Performance Evidence

Resolved shadow outcomes compare the observed `APPROVE/VETO/WAIT` policy with
an approve-all baseline for the exact reviewed subset. Review health requires
minimum approved and declined sample counts plus a confidence interval around
the risk-adjusted per-review contribution. `APPROVE 0.5` is evaluated at half
baseline risk; missing multipliers are excluded rather than assumed to be
full-risk approvals. Reports must show both losses avoided and profitable
setups missed, plus established strategy/regime degradation.

The canonical default is `observe_only`: sparse or degraded review evidence is
visible in status and reports but does not silently reroute gray candidates,
enable rules-only fallback, or mutate policy. Any enforcement change belongs
in `config/decision_policy.json` and requires explicit review.

## Strategy Team Skill Profiles

Momentum, Mean Reversion, and Volatility Breakout signals may include skill
profile metadata sourced from `SOFT_STRATEGY_TEAM_001`. The LLM should use this
metadata to choose among retrieved playbooks and decide whether to HOLD, but it
must not treat a profile as execution permission. If the profile conflicts with
hard rules, data quality, verifier results, or risk compiler limits, the setup
must fail closed or return HOLD.

For team-profile `OPEN_LONG` and `OPEN_SHORT` tickets, the LLM must include:

- `profile_compliance_score`, from `0.0` to `1.0`;
- `profile_compliance_summary`, explaining why the ticket fits the team;
- `profile_compliance_flags`, listing any caveats such as late chase risk,
  missing range quality, or breakout extension risk.

The demo threshold is `0.60`. If the LLM cannot honestly score the setup at or
above that threshold or cannot use one of the team's preferred playbooks, it
must return `HOLD` or `REQUEST_MORE_DATA`.

## Ticket Shape Contract

For `OPEN_LONG` and `OPEN_SHORT`, `entry_plan` and `risk_plan` are JSON objects,
not prose strings. Their exact shapes are:

```json
{"entry_plan":{"order_type":"limit","entry_reference":"short entry reference","chase_market":false},"risk_plan":{"risk_pct_equity":0.03,"stop_logic":"short stop logic","take_profit_logic":"short target logic"}}
```

`order_type` must be lowercase `market` or `limit` for a new position. Risk is
expressed as an equity fraction, so three percent is `0.03`, and must remain
within the compiled hard-rule limit.

For `HOLD` and `REQUEST_MORE_DATA`, both `entry_plan` and `risk_plan` must be
`null`. Their `playbook_id` may be `null`, citations may be empty, and profile
compliance fields may be `null`/empty. These terminal actions are valid tickets,
not malformed OPEN attempts.

## Quota Boundary

All real LLM provider calls must pass the central budget gate before network
I/O. The balanced demo profile uses:

- `AUTO_DAILY_LLM_COST_CAP_USD=0.20`
- `AUTO_DAILY_LLM_CALL_CAP=160`
- `AUTO_HOURLY_LLM_CALL_CAP=16`
- `AUTO_HOURLY_LLM_CALL_CAP_PER_SOURCE=4`
- `AUTO_LLM_OVER_CAP_BEHAVIOR=fail_closed`

The budget gate must resolve the shared journal in both service bootstrap mode
and package/manual scheduler mode. Import topology is not a valid reason to
declare the journal unavailable or skip an otherwise eligible LLM call.

If cost, daily call, or hourly call caps are exhausted, the LLM is unavailable
for gray-zone review and that path must fail closed. A gray proposal must not
be rerouted to the strong lane. Independently qualified strong candidates may
continue without a provider call. Budget skips are journaled as
`llm_budget_skip`; they are not trading signals.

Adaptive reviews use `AUTO_LLM_REVIEW_MAX_TOKENS=500` by default. This smaller
budget applies only to the narrow review schema; the legacy full-ticket budget
remains available during migration.

The per-source hourly cap applies independently to each strategy-team source.
Every provider call, including schema-repair calls, consumes one global slot
and one source slot. This keeps sequential scheduler order from starving a
later team while preserving the global cost and call ceilings.

Compact prompts may reduce token use, but the server-side
`TradeDecisionTicket` schema and rule validation remain authoritative.

The balanced demo token profile keeps prompt mode compact, reasoning effort
low, and `AUTO_LLM_MAX_TOKENS=2400`. Compact prompt text should preserve
mandatory rules, playbook IDs, and hard risk limits while trimming optional
context and asking for short JSON field values. Length guidance is prompt-level
only in this pass; otherwise valid tickets should not be rejected solely for
being a little verbose.

## Ticket Repair

If a provider returns an empty, partial, or schema-invalid
`TradeDecisionTicket`, the runtime may retry with a repair instruction up to
`AUTO_LLM_TICKET_PARSE_ATTEMPTS` attempts. This retry does not bypass the LLM,
verifier, or compiler; if the repaired response is still invalid, the setup
fails closed with no order.

Repair prompts must repeat the exact nested field shapes and terminal-action
null behavior. Schema, JSON, provider, repair-budget, or adapter-infrastructure
failures use the 15-minute operational-error cooldown; valid HOLD and
setup/verifier rejection use the 60-minute decision cooldown.

`HOLD` and `REQUEST_MORE_DATA` are valid terminal tickets. They must be
journaled as no-order outcomes and must not be sent to the order compiler.
