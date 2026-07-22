# Telegram Observability Contract

Role: canonical runtime observability contract

Telegram is a read-only presentation and notification surface for Trade_V1.
It consumes broker, journal, decision-lifecycle, and tournament evidence. It is
not a policy source, risk authority, scheduler, verifier, or executor.

## Data Authority

Telegram dashboards must use these sources in priority order:

1. The shared trader-status read model used by `/api/trader/status`.
2. Exchange-reconciled demo/testnet account state for current equity, margin,
   available balance, mark data, and unrealized PnL.
3. Journal positions, closed trades, stats, lifecycle decisions, and strategy
   team attribution.
4. A clearly labelled journal fallback when the shared status read fails.

Missing broker facts must render as unavailable. Telegram must not estimate a
mark price, exchange balance, order fill, or unrealized PnL from stale values.

## Dashboard Views

The private operator dashboard exposes:

- overview and trading-block state;
- open and pending order tracking;
- LLM decision and verifier/compiler/execution lifecycle;
- fee-aware performance windows;
- strategy-team leaderboard and `30`-trade qualification progress;
- exchange sync/cache freshness, runtime errors, and LLM budget status.

All team-tagged positions, decisions, and outcomes retain `team_id`, team name,
strategy identity, and source/decision IDs when available.

## Delivery Contract

- One dashboard message is persisted, pinned, and edited in place.
- Long polling accepts `message` and `callback_query` updates.
- Inline callback actions are read-only and namespaced under `dash:`.
- Refreshes are event-driven plus periodic, coalesced to avoid duplicate edits.
- Critical alerts are separate messages; routine HOLD/skip events are dashboard
  evidence only.
- Telegram API failures are journaled as delivery evidence and never interrupt
  schedulers, monitor reconciliation, or execution safety gates.
- Snapshot, render, state-store, and delivery exceptions are contained at the
  dashboard-worker boundary. A single failure must not terminate refresh or
  command handling; retries use the configured periodic cadence.
- Authorized unsupported text receives a short `/help` response. Unauthorized
  updates remain silent.
- Typed read-only view commands must synchronously attempt the pinned-message
  refresh and send a concise success/failure acknowledgement. Inline callback
  navigation acknowledges through `answerCallbackQuery` and must not create a
  second dashboard message.
- Authorized commands emit sanitized `telegram_command` receipt/outcome
  evidence. Command telemetry excludes chat IDs, user IDs, free-form message
  text, tokens, and API URLs.
- The bot registers its supported command menu on startup; registration failure
  is delivery evidence but does not terminate polling.

## Authorization

Every command and callback must match the configured chat ID and user ID.
Private-chat compatibility may derive user ID from chat ID only when the update
is explicitly a private chat. Tokens, credentials, and unredacted API URLs must
not appear in journal payloads or error messages.

## Pause Boundary

The manual kill switch is a new-entry gate, not a reason to kill observability.
While paused:

- no scheduler or signal pipeline may open a new position;
- Telegram, web status, journal reads, exchange reconciliation, and protective
  position monitoring remain alive;
- `/resume` must reconcile exchange state before clearing the manual guard;
- inline dashboard controls remain read-only.

## Formatting And Degraded State

Dynamic content must be HTML-escaped. Views must paginate within Telegram
limits. Each view exposes its snapshot timestamp and source/freshness. Stale or
fallback states must be visible instead of silently presented as current.

Journal fallback reads are isolated per component. If `positions.json` is
corrupt or unavailable, Telegram must label positions as unavailable and must
not render zero positions or imply that the broker book is flat. Component
errors are observability evidence only and do not weaken the scheduler's
fail-closed corrupt-journal behavior.
