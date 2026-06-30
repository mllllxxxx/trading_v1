# Execution Adapter Interface And Compliance Audit

## Goal

Implement workflow steps 19-20:

- add a clean execution adapter interface so future broker integrations receive
  verified `CompiledOrder` objects only;
- run and document a final source-of-truth compliance audit for steps 13-20.

## Scope

- Add `trading/execution/` package with base protocol, paper adapter, and
  non-live forex stubs.
- Update execution/source-of-truth architecture docs.
- Add tests for adapter safety and final source-of-truth boundaries.
- Add final audit report under `docs/audits/`.
- Update Dockerfile so the execution package is available in the container.

## Non-Goals

- Do not route scheduler execution through the new adapter yet.
- Do not enable live OKX, OANDA, MT5, or forex execution.
- Do not remove existing OKX testnet/live guards.
- Do not let adapters accept raw LLM tickets or broker-like payloads.

## Design

The adapter contract is intentionally small. `ExecutionAdapter` exposes account,
positions, quotes, bracket placement, and close-position methods. The only
concrete adapter in this batch is `PaperExecutionAdapter`, which accepts a
`CompiledOrder` and returns an `OrderResult` with `broker_order_id=None` and
`broker_calls=0`.

OANDA and MT5 adapters are stubs that raise `NotImplementedError` for order
placement and position closing. This gives future forex work an interface
without any accidental live path.

The compliance audit verifies that:

- source-of-truth docs exist for execution and journal;
- generated artifacts still carry generated markers;
- runtime modules added in steps 13-20 do not reference process docs as trading
  context;
- replay and paper adapter paths are broker-free;
- tests and Docker verification passed.

## Validation Plan

- `trading/tests/test_execution_adapter.py`
- `trading/tests/test_final_source_of_truth_compliance.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
- `python -m pytest -x`
- Docker build/up and `/health`
