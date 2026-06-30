# Journal Contracts

Journal data is runtime evidence. It is not trading policy and must not become
an automatic rulebook source without human curation.

## Lifecycle Events

The LLM-governed decision path may append these lifecycle event types:

- `market_dossier`
- `rule_retrieval`
- `llm_draft_ticket`
- `critic_review`
- `final_ticket`
- `rule_verification`
- `risk_compilation`
- `execution_result`
- `fail_closed_skip`

Each lifecycle event must carry:

- stable `decision_id`;
- generated `event_id`;
- ISO `timestamp_utc`;
- `event_type`;
- JSON payload safe for replay.

## Snapshot Artifacts

Large lifecycle artifacts should be written under:

```text
journal/snapshots/YYYY-MM-DD/
  decision_id.market_dossier.json
  decision_id.rules_context.json
  decision_id.ticket.json
  decision_id.verifier_result.json
```

The decision log should store references to snapshot files instead of relying
on chat logs or dashboard state.

## Replay Boundary

Replay may read journal snapshots, compute metrics, and simulate outcomes. It
must not call broker APIs or submit orders. Replay reports are derived evidence,
not policy source.
