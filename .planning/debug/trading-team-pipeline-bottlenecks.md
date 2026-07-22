# Debug Session: Trading Team Pipeline Bottlenecks

Status: resolved in code; final unresolved-fill archive awaits container rebuild
Started: 2026-07-18

## Expected

All four demo teams receive a fair opportunity to call the LLM. Positive
ticker prices remain positive in `MarketDossier`. Valid no-order tickets stop
before compilation. Accepted but unfilled demo entries expire and stop
occupying tournament slots.

## Actual

- Latest cycle scanned 200 signals and executed zero orders.
- Berkshire and Momentum hit invalid/empty LLM ticket responses.
- Mean Reversion returned `HOLD`, then reached the order compiler.
- Low-priced candidates reached dossier construction with `current_price=0`.
- The six-call global hourly cap was consumed before Volatility Breakout made a
  provider call.
- Two July 2 OKX entries remained `pending_entry` and unfilled on July 18.

## Confirmed Root Causes

1. `berkshire_scanner._dec` quantized every price to four decimal places;
   `0.00001234` became `0.0000`.
2. `run_decision_pipeline` compiled every verifier-passing action, including
   `HOLD`.
3. Runtime failures consumed exactly the configured 800 output tokens per call;
   the reasoning model exhausted the short completion budget before returning
   a complete ticket, and repair retried with the same limit.
4. Budget accounting had only a six-call global hourly cap. Sequential team
   processing allowed earlier teams and their repair calls to starve later
   sources.
5. Futures pending-entry polling used the canonical symbol plus
   `ordType=conditional` for a regular limit entry. Fetch failures were ignored,
   and no pending-entry TTL existed.

## Fix Contract

- Preserve low-price decimal precision.
- Stop terminal no-order actions before compiler.
- Raise bounded ticket output to 1600 tokens and improve empty-response
  diagnostics; repair remains fail closed.
- Use global 12/hour plus per-source 3/hour provider-call caps.
- Expire pending entries after 3600 seconds, cancel demo orders when needed,
  and remove them without creating closed-trade performance.

## Verification

- Seven focused root-cause tests passed.
- Affected-module regression suite passed: 81 tests.
- Full repository suite passed: 343 tests.
- Ruff passed for all touched Python modules and tests.
- Rulebook compiler check passed with 22 source records.
- JSON schema freshness check passed with 10 artifacts.
- `http://127.0.0.1:8000/health` is healthy and the team status endpoint returns
  all four teams.
- The first rebuild loaded the new global `12` and per-source `3` hourly caps;
  runtime decisions now show `source_hourly_call_cap` fairness enforcement.
- Runtime then proved both stale rows have broker status `filled` but no active
  exchange exposure. A follow-up patch now archives that state as unresolved
  and performance-ineligible instead of retaining noisy pending rows.
- The follow-up rebuild could not run because every Docker Desktop named pipe
  returned access denied from this Codex session. Until that image is rebuilt,
  the current container will retain the two rows and log
  `filled_order_without_active_position` on monitor cycles.
