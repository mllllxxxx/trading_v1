# Risk Order Compiler And Scheduler Orchestration

## Goal

Implement workflow steps 15-16:

- add a deterministic risk/order compiler that converts an approved
  `TradeDecisionTicket` into a `CompiledOrder`;
- make scheduler LLM fallback policy explicit and fail closed when LLM
  decisions are required;
- add a pipeline orchestration seam for dossier, retriever, LLM ticket, critic,
  verifier, and compiler without calling broker directly.

## Scope

- Add canonical execution contract docs.
- Update canonical hard risk source with max risk percentage used by compiler.
- Add `trading/risk/order_compiler.py`.
- Add `trading/auto/decision_pipeline.py`.
- Update `trading/auto/scheduler.py` LLM fallback policy gates.
- Add tests for compiler, pipeline fail-closed behavior, and scheduler fallback
  policy.
- Update Dockerfile so the new risk package is available in the container.

## Non-Goals

- Do not enable live trading.
- Do not weaken OKX testnet/sandbox guards.
- Do not let the LLM set executable quantity.
- Do not call broker from the new decision pipeline.
- Do not rewrite the whole legacy scheduler in this batch.
- Do not move policy into prompts, scheduler-only constants, or env-only
  defaults.

## Design

The compiler accepts a schema-valid non-HOLD `TradeDecisionTicket`, a
`MarketDossier`, price levels, account equity, and a passed verifier result. It
loads generated hard rules and computes:

- side from ticket action;
- entry, stop-loss, and take-profit levels;
- effective risk percentage after hard-rule clamp;
- risk amount from equity and stop distance;
- position size from risk amount divided by stop distance;
- max notional clamp from `HARD_RISK_001`;
- reward-to-risk check from `HARD_RISK_003`.

The compiler ignores any raw quantity fields on the ticket payload. A missing
stop-loss, malformed price level, failed verifier result, or RR violation raises
`OrderCompilerError`; callers must treat that as HOLD/no order.

The new pipeline function is a pure orchestration seam. It calls retrieval,
LLM ticket creation, critic, verifier, and compiler in order. It returns a
journal-friendly result object with `approved=False` and a clear fail-closed
reason if any stage fails. It does not call execution.

The legacy scheduler keeps existing execution behavior, but its LLM fallback
policy becomes explicit:

- `REQUIRE_LLM_DECISION=true` means LLM unavailability or cost cap skips;
- `ENABLE_RULES_ONLY_FALLBACK=true` allows legacy fallback only when LLM is not
  required and mode is not live-like;
- otherwise LLM failure skips with a clear journal reason.

## Validation Plan

- `trading/tests/test_order_compiler.py`
- `trading/tests/test_decision_pipeline.py`
- `trading/tests/test_scheduler_safety.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
- `python -m pytest -x`
- Docker build/up and `/health`
