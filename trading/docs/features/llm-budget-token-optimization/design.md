# LLM Budget And Token Optimization

## Intent

Raise the demo/testnet LLM daily budget to `$0.20` while reducing token burn per
decision. The runtime remains LLM-governed and fail-closed when cost, daily call,
or hourly call limits are exhausted.

## Contract

- Daily LLM cost cap defaults to `AUTO_DAILY_LLM_COST_CAP_USD=0.20`.
- Compact prompt mode remains the default runtime profile.
- `AUTO_LLM_MAX_TOKENS` defaults to `800` for JSON ticket calls.
- LLM ticket repair remains enabled with `AUTO_LLM_TICKET_PARSE_ATTEMPTS=2`.
- Over-cap behavior remains `fail_closed`; no rules-only execution fallback is
  introduced here.

## Token Controls

- Compact prompts should keep schema-critical context: primary signal, market
  identifiers, current price, mandatory hard rules, playbook IDs, and compiled
  hard risk limits.
- Optional context should be bounded: recent trades, open positions, news,
  reasons, blockers, and non-mandatory snippets are trimmed before provider I/O.
- Compact prompt JSON context should be minified rather than pretty-printed.
- The LLM is instructed to return concise JSON values:
  - `thesis` up to about 160 characters.
  - `reasoning_summary` up to about 220 characters.
  - `risk_plan.stop_logic` and `risk_plan.take_profit_logic` up to about 140
    characters each.
  - `invalidation_conditions` up to three short items.
  - `profile_compliance_summary` up to about 160 characters.

## Non-Goals

- Do not change the `TradeDecisionTicket` schema.
- Do not add hard schema length validation in this pass; rejecting otherwise
  valid tickets can trigger repair retries and spend more tokens.
- Do not enable rules-only fallback when the LLM budget is exhausted.

## Verification

- Prompt tests assert concise-output instructions and minified compact context.
- Brain tests assert the new default max token cap and shorter repair preview.
- Journal tests assert the new default daily cost cap.
- Runtime smoke checks `/api/trader/status` after Docker recreate and verifies
  `daily_llm_cost.cap_usd` is `0.2`.
