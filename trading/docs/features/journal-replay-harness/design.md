# Journal Lifecycle And Replay Harness

## Goal

Implement workflow steps 17-18:

- add journal lifecycle events and replayable snapshots for the LLM-governed
  decision path;
- add a broker-free replay/eval harness that can summarize historical or mock
  decision results.

## Scope

- Add `trading/docs/architecture/JOURNAL_CONTRACTS.md`.
- Extend `trading/auto/journal.py` with lifecycle event and snapshot helpers.
- Add `trading/replay/` package with snapshot loading, metrics, and mock replay
  report writing.
- Add tests for lifecycle snapshots, dashboard-compatible event shape, replay
  metrics, and report generation.

## Non-Goals

- Do not call broker or execution adapters.
- Do not replay live orders.
- Do not convert journal evidence into rulebook policy automatically.
- Do not rewrite dashboard UI in this batch.
- Do not require real LLM calls for replay MVP.

## Design

Journal remains append-only via `decisions.jsonl`. New lifecycle events are
written as normal decision entries for dashboard compatibility, with additional
fields:

- `event_id`
- `event_type`
- `decision_id`
- `payload`

The runtime can snapshot large lifecycle artifacts under
`journal/snapshots/YYYY-MM-DD/` using names like
`decision_id.market_dossier.json`. The decision log stores relative snapshot
references, while tests and replay code can load the bundle by `decision_id`.

The replay package starts with deterministic mock mode. It accepts replay result
records or loaded snapshot bundles, computes quality and performance metrics,
and writes JSON/Markdown reports. It has no broker dependency and no order
placement path.

## Validation Plan

- `trading/tests/test_journal_lifecycle.py`
- `trading/tests/test_replay_metrics.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
- `python -m pytest -x`
- Docker build/up and `/health`
