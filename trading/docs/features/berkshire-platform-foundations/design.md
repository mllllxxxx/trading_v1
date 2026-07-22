# Berkshire Platform Foundations Plan

## Goal

Turn `/berkshire` from a local deterministic research desk into the foundation
for a production-grade advisory layer that can run beside crypto trading and
prepare a separate Forex lane without weakening existing trade-safety
boundaries.

The system must preserve the canonical Trade_V1 decision flow:

```text
trusted product docs/config/rulebook/schemas
  -> market dossier
  -> retrieved rulebook/playbook context
  -> LLM TradeDecisionTicket or research-only advisory output
  -> critic/verifier
  -> risk/order compiler
  -> execution adapter
  -> journal/replay evidence
```

AI Berkshire output remains advisory unless it enters the normal ticket,
critic, verifier, compiler, and adapter path.

## Current Baseline

Implemented foundations already available:

- `/berkshire` route with live UI, lane switch, research form, report/audit tabs,
  and explicit Forex readiness gaps.
- `GET /api/berkshire/state` and `POST /api/berkshire/research`.
- Local persisted research runs under `$VIBE_TRADING_HOME/berkshire/state.json`.
- Deterministic four-lens Berkshire report, checklist, and Decimal risk/reward
  audit.
- Shared schemas, rulebook compiler, market dossier, rule retriever, prompt
  contract, critic/verifier, risk/order compiler, execution adapter audit, and
  journal/replay harness already exist in the broader Trade_V1 roadmap.

## Non-Negotiable Boundaries

- No broker call can originate from Berkshire routes or UI.
- Forex is research-only until its broker adapter, data contracts, journal
  contract, spread/session guards, and shared exposure ledger are implemented.
- LLM output cannot choose final executable quantity.
- Berkshire research cannot override hard rules, verifier failures, compiler
  failures, kill switches, or mode guards.
- Runtime prompt/context retrieval must use only approved sources from
  `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md` and
  `trading/docs/architecture/RAG_INDEXING_POLICY.md`.
- Development-process docs, feature designs, root README, and Harness docs are not
  trading runtime context.

## Phase 1 - Berkshire Research Job Engine

Build a durable research orchestration layer behind the existing API.

Deliverables:

- `trading/berkshire/` package with service, store, workers, prompt templates,
  and report audit modules.
- Replace direct deterministic creation with a job model:
  `queued -> running -> complete | failed | blocked`.
- Add typed models for `ResearchRun`, `ResearchLens`, `EvidenceBundle`,
  `ChecklistResult`, and `ReportAudit`.
- Keep deterministic fallback for tests, but add provider interface for real
  LLM calls.
- Persist research runs in a real store compatible with future PostgreSQL.
  Short-term SQLite/JSON migration is acceptable only if wrapped by a repository
  interface.

Acceptance criteria:

- Existing `/api/berkshire/research` remains backward compatible.
- API can create, poll, and retrieve a run by ID.
- Failed LLM/tool calls produce `failed` or `blocked`, never fake success.
- Unit tests cover job lifecycle, persistence, idempotency, and fail-closed
  behavior.

## Phase 2 - Live Evidence Provider Layer

Add source-aware evidence intake before any LLM research call.

Provider categories:

- Crypto market data: OHLCV, funding, open interest, volume/liquidity, spreads.
- Crypto context: major news, exchange incidents, ETF/flows if provider exists,
  on-chain signals when configured.
- Macro/Forex: economic calendar, rates events, central-bank events, session
  state, holidays, rollover windows.
- Portfolio context: open exposure, recent losses, correlated positions,
  pending orders, drawdown state.

Deliverables:

- `EvidenceBundle` schema with source, timestamp, freshness, confidence, and
  red/yellow flags.
- Provider registry with clean skip when capability or credentials are absent.
- Freshness policy: stale or missing mandatory data blocks trade promotion and
  downgrades research confidence.
- UI provider-health panel on `/berkshire`.

Acceptance criteria:

- Missing mandatory evidence results in `REQUEST_MORE_DATA` or `research_blocked`.
- Provider outputs are stored as journal snapshots or research snapshots.
- Tests simulate stale data, provider failure, partial data, and clean skip.

## Phase 3 - Multi-Agent LLM Research Workers

Replace deterministic lens synthesis with real independent research workers.

Worker roles:

- Quality lens: moat/liquidity/durability.
- Valuation/risk lens: price setup, stop distance, reward/risk, carry/funding.
- Inversion lens: what kills the thesis.
- Certainty lens: regime survival, cross-market conflict, time horizon.
- Audit lens: source quality, stale evidence, unsupported claims.

Deliverables:

- Role-specific prompts loaded from allowed runtime sources and local templates.
- Strict structured output validation.
- Independent worker outputs plus a synthesis step.
- Report audit that flags missing citations, stale evidence, unsupported
  claims, bad math, and overconfident language.

Acceptance criteria:

- Invalid JSON or missing required fields fails closed.
- Worker disagreement is surfaced in UI and journal, not hidden.
- Synthesis can only produce advisory research or a candidate ticket; it cannot
  execute.
- Tests cover malformed LLM output, disagreement, blocked evidence, and audit
  failures.

## Phase 4 - Forex Foundation Contracts

Prepare Forex as a first-class lane without enabling execution.

Deliverables:

- Add canonical Forex policy under rulebook source:
  hard data rules, spread/session rules, rollover guards, event-risk guards,
  and initial FX playbooks.
- Extend schemas to support `market="forex"` and FX symbols without breaking
  crypto schemas.
- Add Forex market dossier builder inputs: session, spread, event calendar,
  ATR/volatility, trend, regime, and liquidity warnings.
- Add FX journal event payload compatibility.
- Add UI readiness checklist for each required Forex gate.

Acceptance criteria:

- Forex research can produce advisory reports and `REQUEST_MORE_DATA`, but
  cannot produce executable orders.
- Macro event risk and missing spread/session data block promotion.
- Rulebook compile and schema export checks pass.
- Tests prove Forex is still execution-blocked.

## Phase 5 - Shared Exposure Ledger

Add one global risk ledger across crypto and future Forex.

Ledger responsibilities:

- Total open positions and market-specific counts.
- Gross/net USD exposure.
- Directional USD, risk-on, and correlated exposure.
- Drawdown and consecutive-loss state.
- Per-symbol and per-cluster limits.
- Kill-switch and daily risk budget state.

Deliverables:

- `trading/risk/exposure_ledger.py` or equivalent service.
- Canonical config/rulebook entries for global and per-market limits.
- Integration into market dossier, verifier, compiler, Berkshire state, and UI.
- Journal snapshots for ledger state per decision.

Acceptance criteria:

- Compiler rejects any order that would breach ledger limits.
- Berkshire reports display exposure pressure but cannot override it.
- Tests cover crypto-only, Forex-only planned lane, and combined exposure
  scenarios.

## Phase 6 - Advisory-To-Ticket Promotion Gate

Allow Berkshire research to optionally feed the normal trading pipeline without
skipping safety.

Deliverables:

- `promote_research_to_ticket` service that creates a draft
  `TradeDecisionTicket` only when evidence, report audit, confidence, and
  rule context pass.
- Human-review option for review mode.
- Journal event linking research run ID to ticket ID.
- UI control that says "Promote to draft ticket", not "Trade".

Acceptance criteria:

- Promotion can create only draft tickets.
- Verifier/compiler still decide whether anything can reach adapter.
- All promotion failures become explicit audit events.
- Tests prove no broker adapter is called by Berkshire promotion.

## Phase 7 - Forex Adapter Planning And Paper Harness

Design the Forex adapter interface, but keep live execution out of scope.

Deliverables:

- Broker adapter selection doc with required capabilities:
  paper/testnet support, symbol mapping, min lot, pip value, margin, spread,
  slippage, rollover, order types, reconciliation.
- `ForexOrderIntent` mapping draft behind feature flag.
- Paper/replay adapter only, if needed for validation.
- No live credentials in code, tests, docs, or chat.

Acceptance criteria:

- Adapter interface accepts compiled orders only.
- FX paper adapter can be replay-tested without network credentials.
- Live mode remains blocked by config and tests.

## Phase 8 - UI Operations Layer

Make `/berkshire` useful as an operator desk.

Deliverables:

- Run history and detail drawer.
- Provider health and stale evidence indicators.
- Job progress states.
- Analyst disagreement view.
- Report audit checklist.
- Exposure ledger panel.
- Forex readiness checklist.
- Research-to-ticket promotion audit trail.

Acceptance criteria:

- User can see why a run is blocked.
- User can distinguish research, draft ticket, paper-eligible, and execution
  states.
- Mobile and desktop route smoke tests pass.

## Recommended Story Order

1. `US-BERKSHIRE-JOBS-001`: durable research jobs and typed store.
2. `US-BERKSHIRE-EVIDENCE-001`: provider registry and evidence bundle.
3. `US-BERKSHIRE-LLM-001`: multi-agent LLM workers and report audit.
4. `US-FOREX-CONTRACTS-001`: Forex rulebook, schemas, dossier, and journal
   compatibility.
5. `US-RISK-LEDGER-001`: shared exposure ledger across markets.
6. `US-BERKSHIRE-PROMOTION-001`: advisory-to-ticket promotion gate.
7. `US-FOREX-PAPER-ADAPTER-001`: Forex paper/replay adapter planning.
8. `US-BERKSHIRE-OPS-UI-001`: operator UI upgrades for jobs, providers,
   ledger, and readiness.

## Verification Standard Per Story

Every story must provide:

- design doc before code;
- schema export check when schemas change;
- rulebook compile check when rules/playbooks change;
- targeted unit tests;
- `pytest -x`;
- frontend tests/build when UI changes;
- Docker build/up and `/health` when runtime changes;
- browser smoke for `/berkshire` when UI changes;
- Harness trace with evidence.

## Implementation Recommendation

Start with Phase 1. It creates the seam needed for all later work: durable
jobs, typed persistence, and async progress. Without that, LLM workers and live
evidence would be bolted onto the current JSON endpoint and become painful to
test or recover after failures.
