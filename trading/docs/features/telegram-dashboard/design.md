# Telegram Trading Cockpit

Feature ID: `telegram-dashboard`
Status: design-first implementation

## Intent

Turn the existing Telegram notifier into a private, read-only operating
cockpit. One pinned message provides current account, PnL, order, decision,
strategy-team, and system-health views. Important lifecycle events remain
separate push alerts.

Telegram is an observability consumer. It must not define trading policy,
recompute broker truth independently, or create a new execution path.

## Product Decisions

- Private chat for one operator.
- Pinned hybrid dashboard using long polling, callback queries, inline
  keyboards, message edits, and separate critical alerts.
- Inline controls are read-only.
- Existing typed `/pause` and `/resume` commands remain available, but are not
  exposed as dashboard buttons.
- Vietnamese copy, USD values, and `Asia/Ho_Chi_Minh` timestamps.

## Source Data

The primary snapshot is the same read model served by `/api/trader/status`:

- exchange-truth account state and sync/cache metadata;
- journal positions, closed trades, stats, and LLM decisions;
- strategy-team leaderboard derived by `strategy_teams.build_team_dashboard`;
- kill switch and startup reconciliation guards.

The bot may fall back to local journal reads when the loopback API is
unavailable. Fallback values must be labelled and missing prices/PnL must show
`N/A`; the bot must not invent exchange data.

## Views

| View | Required content |
| --- | --- |
| Overview | runtime/block state, equity source, realized/unrealized PnL, fees, open/pending count, winrate, drawdown, LLM budget |
| Positions | team, symbol, side, status, entry/mark, SL/TP, size/contracts, leverage, margin, risk, unrealized PnL |
| Decisions | legacy and lifecycle tickets with team/signal, action, confidence, thesis, verifier/compiler/execution state |
| Performance | today/7d/30d/all-time gross, fees, net PnL, W/L, winrate, expectancy R, profit factor, drawdown, streak |
| Teams | rank, `$200` allocation, equity, PnL, trades, winrate, expectancy R, profit factor, drawdown, score, `n/30` status |
| System | broker sync/cache freshness, trading guards, scheduler activity, LLM quota, recent errors/fail-closed events |

## Refresh And State

- Persist `message_id`, active view/page, detail key, content hash, and last
  update under `/data/telegram/dashboard_state.json` using atomic replacement.
- Coalesce event-driven refreshes for five seconds.
- Refresh the snapshot every 60 seconds and force a heartbeat edit every five
  minutes.
- Only edit when content changes or the heartbeat is due.
- Recreate and repin the dashboard when its stored message can no longer be
  edited.

## Failure Containment

- The shared status API remains primary. A failed API snapshot may fall back
  to journal components, but every component read is isolated independently.
- A corrupt or unavailable `positions.json` must render positions as
  **unavailable**. It must never be presented as an empty/flat book.
- Fallback component errors are attached to `_telegram_source.component_errors`
  and surfaced in the System view without leaking credentials.
- The dashboard refresh loop owns a top-level exception boundary. One failed
  snapshot, render, state write, or Telegram edit is journaled and retried on a
  bounded cadence; it must not terminate the worker thread.
- Authorized unknown text or unsupported commands receive a concise `/help`
  response. Read-only view commands continue to update the pinned message
  rather than creating a second dashboard message.
- Typed view commands refresh the selected pinned view synchronously and send
  one concise success/failure acknowledgement. Callback navigation uses the
  callback toast and does not create acknowledgement-message noise.
- Authorized command receipt and outcome are journaled as sanitized
  `telegram_command` evidence without chat IDs, user IDs, or message text.
- Supported commands are registered with Telegram at bot startup so the
  private operator sees the current command menu.

## Alerts

Push separate alerts for order accepted/opened/filled/closed, TP/SL,
execution/reconciliation failure, kill switch/daily-loss guard, and LLM budget
at 80% or 100%. HOLD, REQUEST_MORE_DATA, routine skips, and ordinary decisions
remain visible in the dashboard instead of spamming chat.

## Safety And Security

- Authorize both chat ID and Telegram user ID. In a private chat, an omitted
  user ID may safely inherit the configured chat ID for compatibility.
- Escape every dynamic HTML value and paginate before Telegram's message limit.
- Journal delivery errors without tokens, raw credentials, or unredacted
  Telegram API URLs.
- Kill switch blocks new entries but must not terminate the Telegram control
  plane or read-only observability. Exchange reconciliation and protective
  position monitoring remain available.
- Demo/paper/testnet guards and live-readiness boundaries remain unchanged.

## Tests

- Snapshot normalization and fallback labelling.
- Corrupt-position fallback renders unknown state and never kills refresh.
- Refresh exceptions are contained and the next refresh can recover.
- Renderers for full, empty, stale, malformed, and oversized data.
- PnL windows, fee-aware metrics, team attribution, and leaderboard parity.
- Callback auth/routing, pagination, HTML escaping, and dashboard recovery.
- Signal lifecycle to dashboard refresh/alert integration.
- Kill switch keeps the bot alive while blocking new entries.
