# LLM Quota Optimization

## Intent

Keep the demo trading loop able to produce real LLM-governed signals while
bounding provider spend under the balanced profile:

- Daily cost cap: `AUTO_DAILY_LLM_COST_CAP_USD=0.20`
- Daily call cap: `AUTO_DAILY_LLM_CALL_CAP=160`
- Hourly call cap: `AUTO_HOURLY_LLM_CALL_CAP=16`
- Per-team hourly call cap: `AUTO_HOURLY_LLM_CALL_CAP_PER_SOURCE=4`
- Over-cap behavior: `fail_closed`

When any LLM budget cap is reached, no new LLM-governed order may be opened.
The system may continue scanning and journaling market candidates.

## Runtime Contract

All real provider calls must pass through the central LLM budget gate in
`auto.brain` before network I/O. The gate applies to:

- Legacy `call_brain`
- Berkshire `call_trade_decision_ticket`

Budget skips are journaled as `llm_budget_skip` with source, cap state, and
reason. There is no rules-only fallback while `REQUIRE_LLM_DECISION=true` and
`ENABLE_RULES_ONLY_FALLBACK=false`.

## Berkshire Throttle

Berkshire remains the primary LLM trading source for the crypto demo loop.
It scans the top 50 symbols but only sends bounded candidates to the LLM:

- At most `BERKSHIRE_SIGNAL_MAX_LLM_ATTEMPTS_PER_CYCLE=3`
- Candidate confidence must be at least `BERKSHIRE_LLM_MIN_CONFIDENCE=0.72`
- Candidate score must be at least `BERKSHIRE_LLM_MIN_SCORE=70`
- Symbols already open or pending are skipped by the signal pipeline guard
- Per-symbol LLM cooldown: `BERKSHIRE_LLM_SYMBOL_COOLDOWN_MINUTES=240`
- Fingerprint cache TTL: `BERKSHIRE_LLM_CACHE_TTL_S=21600`

The cache fingerprint uses symbol, direction, status, confidence band, and
price band so similar repeated signals do not burn quota.

## Prompt Mode

`AUTO_LLM_PROMPT_MODE=compact` sends a compact decision contract, one primary
signal candidate, reduced market dossier, mandatory rule IDs, playbook IDs, and
compiled hard-rule limits. Server-side schema validation remains authoritative;
malformed tickets still fail closed.

The compact contract and repair prompt must show the exact nested object shape
for `entry_plan` and `risk_plan`. `HOLD` and `REQUEST_MORE_DATA` must use null
for both fields. The demo output budget is `AUTO_LLM_MAX_TOKENS=2400` so a low
reasoning effort response still has room to emit the JSON object.

## Legacy Scheduler

When Berkshire is active locally, the legacy confluence scheduler is disabled
with `AUTO_LEGACY_SCHEDULER_ENABLED=false` so it does not compete for LLM quota.
Monitor and exchange reconciliation continue running.

## Verification

- Unit tests cover central budget caps, Berkshire attempt limits, cooldown,
  cache behavior, compact prompts, and legacy scheduler startup gating.
- `/api/trader/status` exposes daily and hourly budget telemetry in
  `stats.daily_llm_cost`.
- `/trader` renders LLM spend, call cap, hourly cap, and last budget skip.
