# Journal Contracts

Journal data is runtime evidence. It is not trading policy and must not become
an automatic rulebook source without human curation.

## Durable Mutable Snapshots

Mutable JSON snapshots such as `positions.json`, `stats.json`, and
`shadow_positions.json` must be replaced atomically. A reader must observe the
complete previous snapshot or the complete next snapshot, never an interleaved
or partially rewritten file.

`positions.json` corruption remains fail-closed: readers raise a journal
corruption error and new entries stay blocked until the journal is repaired or
exchange reconciliation restores a valid snapshot. The corrupt bytes are
backed up by content fingerprint. Re-reading the same corrupt bytes must reuse
the same backup instead of creating an unbounded timestamped backup stream.
Dashboard/status consumers must surface the journal error explicitly; they
must not present an empty book as healthy state.

## Lifecycle Events

The adaptive decision path may append these lifecycle event types:

- `signal_candidate`
- `market_dossier`
- `rule_retrieval`
- `rule_proposal`
- `hybrid_route`
- `llm_context_review`
- `llm_draft_ticket`
- `critic_review`
- `final_ticket`
- `rule_verification`
- `risk_compilation`
- `trade_open_rationale`
- `execution_result`
- `fail_closed_skip`
- `trade_outcome_review`
- `optimization_snapshot`
- `live_readiness_snapshot`
- `shadow_candidate`
- `shadow_outcome`

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

## Demo Learning Events

The demo-first system must be able to connect every closed trade back to its
source signal and decision path. At minimum:

- `signal_candidate` records the source engine, symbol, direction, confidence,
  blockers, action hint, and promotion gate.
- `rule_proposal` records the deterministic baseline score, components,
  conflicts, hard blockers, and proposed risk before LLM review.
- `hybrid_route` records policy profile, strong/gray/reject zone, selected lane,
  and whether an LLM call is required.
- `llm_context_review` records APPROVE/VETO/WAIT, risk multiplier, evidence
  references, and conflict flags only when a gray provider response exists.
- `trade_open_rationale` records why an approved demo order was opened, the
  market context at entry time, the ticket thesis, rule/playbook citations, and
  compiled risk context.
- `execution_result` records the paper/testnet adapter result and broker/order
  references when present.
- `trade_outcome_review` records closed-trade outcome, win/loss, R multiple,
  PnL, execution quality, and reviewer notes.
- `optimization_snapshot` records aggregate metrics such as winrate, profit
  factor, drawdown, expectancy, and breakdown by source/playbook/regime.
- `live_readiness_snapshot` records whether demo evidence passes the current
  live readiness gate.

Raw outcome evidence must not rewrite rulebook policy automatically. Reviewed
optimization proposals must update canonical docs, config, rulebook, or schemas
before permanent policy changes. The separately approved demo adaptive
controller may activate a bounded, versioned runtime zone override without
editing canonical files, subject to
`trading/docs/features/adaptive-policy-controller/design.md`.

Adaptive threshold evaluation must label each input as `observational`,
`shadow`, or `backtest`. Only rows explicitly marked
`counterfactual_eligible=true` with source `shadow` or `backtest` may support a
threshold proposal. Demo closed trades remain observational unless separate
counterfactual evidence exists.

## Shadow Outcome Evidence

Broker-free adaptive shadow evidence is persisted separately from real/demo
position accounting:

```text
journal/shadow_positions.json
journal/shadow_outcomes.jsonl
```

`shadow_positions.json` contains unresolved counterfactual setups and must not
be merged into `positions.json`, exchange reconciliation, account capital, open
position counts, or risk exposure. `shadow_outcomes.jsonl` is append-only and
may feed replay/evaluation only.

Each shadow candidate requires a deterministic ID, source signal/scan/team,
symbol, side, rule score, route metadata, confirmed trigger timestamp, valid
entry/stop/target, bounded horizon, and explicit cost assumptions. Repeated
capture of the same setup is idempotent and restart must preserve pending rows.
Optional `experimental_scores` are copied as replay evidence but are excluded
from the deterministic ID, route metadata, account state, and exposure. Outcome
resolution preserves them unchanged; older rows without experiments remain
valid.

Resolution uses chronological confirmed public candles. TP, SL, and bounded
timeout outcomes may be `counterfactual_eligible=true`. A candle touching both
stop and target, missing history, invalid levels, or incomplete outcome must be
marked ineligible with an exclusion reason. Shadow outcomes never update trade
stats or create account-sized PnL.

## Adaptive Policy State

The demo controller persists runtime evidence at:

```text
journal/adaptive_policy_state.json
```

The state is atomically replaced and uses schema `adaptive_policy_state.v1`.
It records canonical/active zones, monotonic revision, staged confirmations,
evidence milestones, previous zones, and the latest action/reason. It is not a
rulebook source and must not enable live trading or weaken hard rules.

Decision events use the prefix `adaptive_policy_controller_` with actions
`skipped`, `observed`, `staged`, `activated`, `rolled_back`, or `error`.
Activation and rollback events must include revision, effective zones,
eligible evidence count, and reason. Replaying unchanged evidence cannot
create another confirmation.

## V2 Review State

The review-only continuous-conflict controller persists candidate evidence at:

```text
journal/continuous_conflict_v2_review_state.json
```

The state is atomically replaced and uses schema
`continuous_conflict_v2_review_state.v1`. It records the canonical experiment
fingerprint, candidate thresholds, evidence-separated confirmation milestones,
and the latest review action. It must always retain
`operator_approved=false`, `active_for_routing=false`, and
`canary_enabled=false`; it is not execution permission.

Decision events use prefix `shadow_score_review_controller_` with actions
`skipped`, `observed`, `staged`, `review_ready`, `invalidated`, or `error`.
Unchanged evidence cannot add a confirmation, and corrupt or stale-contract
state must be reported without overwrite.

## V2 Demo Canary State

An operator-approved continuous-conflict V2 canary persists operational state
separately at:

```text
journal/continuous_conflict_v2_canary_state.json
```

The state uses schema `continuous_conflict_v2_canary_state.v1` and is valid
only for the exact review-ready candidate fingerprint, score version, canonical
canary contract, approval id, and demo execution adapter recorded at approval.
Missing, stale, corrupt, revoked, or rolled-back state disables canary routing
without changing the V1 route. No environment variable may synthesize an
approval.

Canary-routed positions and closed trades retain `routing_experiment`, including
the approval id, candidate fingerprint, V1/V2 scores and zones, stable allocation
bucket, selected thresholds, and risk multiplier. Closed canary trades also
retain fee-aware `r_multiple` when positive opening `risk_usd` is available.
These fields are optional for older journal rows.

After the configured minimum number of attributable closed trades, the canary
controller evaluates its one-sided average-R lower bound, profit factor, and
cumulative R. Breaching any canonical floor atomically rolls the approval back;
the same approval id cannot reactivate itself.

Controller lifecycle decisions use prefix `shadow_score_canary_controller_`.
Every selected scheduler route is journaled before downstream guards with
prefix `shadow_score_canary_route_`; a V2 reject has an explicit veto event and
must retain `executed=false`.

## Rationale Retention

Open positions created from an approved demo decision may carry optional
review metadata from `trade_open_rationale`:

- `position_id`
- `team_id`
- `team_name`
- `strategy_id`
- `strategy_name`
- `team_capital_usd`
- `target_risk_pct_equity`
- `preferred_playbook_ids`
- `required_soft_policy_ids`
- `entry_style`
- `avoid_conditions`
- `llm_guidance`
- `risk_personality`
- `profile_compliance_score`
- `profile_compliance_summary`
- `profile_compliance_flags`
- `source_signal_id`
- `decision_id`
- `open_reason`
- `market_context`
- `decision_context`
- `decision_policy`
- `decision_lane`
- `rule_score`
- `score_components`
- `rule_conflicts`
- `llm_context_review`

When a position is closed, the monitor must retain those fields on the
closed-trade record. Dashboards and review jobs should read the retained
metadata from the journal so a closed trade can be reviewed as:

```text
source signal -> decision rationale -> execution -> outcome
```

Performance-eligible closed trades must also retain `risk_usd`, requested and
actual risk percentages, risk cap reason, notional/margin/leverage, regime,
and confluence. Runtime demo PnL records `gross_pnl_usd`, `fees_usd`, and net
`pnl_usd`; the default conservative fee estimate is 5 bps per filled leg.

The fields are optional for backward compatibility with older journal entries.

Strategy-team metrics are derived from journal evidence. They must not rewrite
team methods or risk policy without a reviewed source-of-truth change.

## LLM Budget Telemetry

`stats.json` may include `daily_llm_cost`. The object is backward compatible
with the original daily spend fields and may include:

- `date`, `cost_usd`, `calls`, `cap_usd`, `remaining_usd`, `pct_of_cap`;
- `call_cap`, `remaining_calls`;
- `hourly_key`, `hourly_calls`, `hourly_call_cap`, `remaining_hourly_calls`;
- `hourly_call_cap_per_source` and source-specific hourly remaining calls;
- `source_breakdown`, including provider calls and current-hour calls by source;
- `budget_skips`, `last_budget_skip`.

Budget denials are also appended to `decisions.jsonl` as `llm_budget_skip` with
the source, reason, behavior, and current budget state.

## Pending Entry Positions

For OKX demo/testnet futures, an accepted broker order may exist before the
entry is filled. Such records may remain in `positions.json` as pending runtime
state, but they are not active exchange exposure until OKX reports a matching
position.

Pending entry records must include:

- `status="pending_entry"`;
- `entry_filled=false`;
- broker entry reference such as `orders.entry_id`;
- the same rationale metadata as filled demo orders when available.

Exchange reconciliation should not mark pending entries as
`missing_on_exchange` while waiting for fill or cancel evidence. Once OKX
reports active exposure, reconciliation may set `entry_filled=true`,
`status="open"`, and broker sync metadata.

Pending entries have a bounded lifetime. New rows should retain
`pending_entry_expires_at`; older rows may derive expiration from `opened_at`
and `AUTO_PENDING_ENTRY_TTL_S` (default `3600` seconds). When an expired broker
entry is canceled or already absent/canceled, the runtime removes the pending
row and appends `pending_entry_resolved` evidence. This cleanup must not append
a closed trade, increment wins/losses, or manufacture zero-PnL performance.
If broker status is uncertain, the row remains pending and the error is
journaled.

If the broker confirms the entry order was filled but a clean exchange snapshot
confirms no active exposure remains, the row is no longer a pending or open
position. The runtime removes it from `positions.json` and appends
`pending_entry_resolved` with `outcome_status="unresolved"` and
`performance_eligible=false`. Broker fill evidence is retained, but no closed
trade, win/loss, exit price, or PnL is created until reliable exit evidence is
available.

## Exchange-Reconciled Positions

When OKX demo/testnet reports active futures exposure that is missing from the
local journal, the reconciler may create an open journal position from the
exchange snapshot. Such entries are runtime repair evidence, not a substitute
for the original decision lifecycle.

Restart and resume flows must preserve `positions.json`. Startup setup may
create the file when it is missing, but it must not overwrite existing open
positions. If the journal is empty or stale after a restart, exchange
reconciliation repairs it from active OKX demo futures exposure before new demo
entries are allowed.

Exchange-reconciled positions must include:

- `source="exchange_reconciler"`;
- `status="exchange_open"`;
- canonical `symbol` plus broker identifiers such as `instId` and
  `ccxt_symbol`;
- broker quantity, average entry, mark price, leverage, margin mode, and
  unrealized PnL when available;
- `broker_sync_at` and `sync_status`.

Dashboards should display these positions as open exposure and surface the sync
status so the operator knows whether the full decision rationale is present.

When a local futures position is missing from a clean exchange snapshot, the
monitor must record reconciliation drift before closing it locally. A first
startup or retry snapshot is not enough evidence to delete local open-position
state.

## Account State Boundary

Journal stats record realized local evidence such as closed-trade PnL, win/loss
counts, and replayable capital progression. They are not the only source for
current dashboard capital when an exchange account snapshot is available.

Dashboards that show current capital, available balance, margin use, or open
unrealized PnL should prefer the exchange account state supplied by execution
reconciliation. If that read fails, the dashboard may fall back to journal stats
and must label the fallback source.

Dashboard polling must not be the authority that makes trading safe. Startup,
resume, monitor reconciliation, and same-symbol exposure checks remain the
runtime safety gates. Dashboard routes may serve cached exchange account and
position snapshots with cache metadata so UI rendering does not block on broker
network latency.

## Replay Boundary

Replay may read journal snapshots, compute metrics, and simulate outcomes. It
must not call broker APIs or submit orders. Replay reports are derived evidence,
not policy source.

## Telegram Delivery Evidence

Telegram dashboard state is runtime presentation state and is not part of the
decision journal. It may be stored under `telegram/dashboard_state.json` with a
message ID, active view/page, content hash, and timestamps.

Delivery failures may be appended to `decisions.jsonl` as
`telegram_delivery_error` with a sanitized method, status, and description.
Tokens, raw API URLs, credentials, and message bodies containing sensitive
account context must not be journaled.
