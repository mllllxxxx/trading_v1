# US-JOURNAL-REPLAY-001 Journal Lifecycle And Replay Harness

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must record enough decision lifecycle evidence to replay a trade or
reject later. Replay must run without broker keys and must never submit orders.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/JOURNAL_CONTRACTS.md`
- `trading/schemas/journal_event.schema.json`

## Acceptance Criteria

- Journal can append lifecycle event types:
  `market_dossier`, `rule_retrieval`, `llm_draft_ticket`, `critic_review`,
  `final_ticket`, `rule_verification`, `risk_compilation`,
  `execution_result`, and `fail_closed_skip`.
- Lifecycle events include stable `decision_id`.
- Journal can write and reload snapshots for dossier, rules, ticket, verifier
  result, compiler output, and execution result.
- Dashboard-compatible decision log parsing does not crash on new event types.
- Replay mock mode runs without broker credentials.
- Replay never places real orders.
- Replay report writes JSON and Markdown.
- Replay metrics are covered by tests.

## Design Notes

- Commands: none.
- Queries: none.
- API: `trading/auto/journal.py`, `trading/replay/*`.
- Tables: unchanged.
- Domain rules: journal schema and journal contract docs.
- UI surfaces: dashboard data endpoint should tolerate the new event entries.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Journal lifecycle and replay metrics tests |
| Integration | Full trading pytest suite |
| E2E | Broker-free replay report smoke |
| Platform | Docker build/up and `/health` |
| Release | Final compliance audit later |

## Harness Delta

Design doc and story added before code. Intake #17 recorded.

## Evidence

- Targeted tests passed: `trading/tests/test_journal_lifecycle.py` and
  `trading/tests/test_replay_metrics.py` passed 9 tests.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
  passed schema check, rulebook check, and 234 tests.
- `python -m pytest -x` passed 234 tests.
- `docker compose build` passed from `trading/`.
- `docker compose up -d` started `vibe-trading`; `/health` returned 200 and
  container status was healthy.
- Container smoke import passed for journal lifecycle helpers and replay
  metrics/mock runner.
- `git diff --check` passed with Windows CRLF warnings only.
- Harness `story verify US-JOURNAL-REPLAY-001` passed.
