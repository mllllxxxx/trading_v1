# US-BERKSHIRE-FOUNDATIONS-001 Berkshire Platform Foundations

## Status

planned

## Lane

high-risk

## Product Contract

Trade_V1 must extend `/berkshire` into a durable advisory platform for crypto
and future Forex without allowing AI Berkshire research to bypass source of
truth, verifier, risk compiler, journal, or execution adapter safety gates.

The first implementation focus is not live Forex trading. The first focus is
the missing foundation: research jobs, evidence bundles, LLM worker contracts,
Forex rule/schema compatibility, shared exposure ledger, and a safe promotion
gate into the existing decision pipeline.

## Relevant Product Docs

- `.hermes/features/berkshire-platform-foundations/design.md`
- `.hermes/features/ai-berkshire-trading-desk/design.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`
- `trading/docs/architecture/EXECUTION_CONTRACTS.md`
- `trading/docs/architecture/JOURNAL_CONTRACTS.md`
- `trading/docs/product/TRADING_SYSTEM_INTENT.md`
- `trading/docs/product/RISK_MANDATE.md`
- `trading/docs/product/AUTONOMY_POLICY.md`
- `trading/docs/product/LLM_ROLE.md`

## Acceptance Criteria

- Berkshire research uses a durable job lifecycle instead of only synchronous
  deterministic run creation.
- Research runs can store source-aware evidence bundles and explicit stale or
  missing evidence flags.
- Multi-agent LLM workers return strict structured outputs and fail closed on
  malformed or incomplete outputs.
- Forex lane has canonical rulebook, schema, dossier, and journal contracts
  before any execution adapter work.
- Shared exposure ledger is used by both crypto and future Forex paths.
- Berkshire advisory output can only be promoted into a draft
  `TradeDecisionTicket`; it cannot call execution directly.
- `/berkshire` UI displays provider health, job progress, run history, audit
  failures, exposure pressure, and Forex readiness gates.
- Tests prove Forex remains execution-blocked until explicit live-readiness work
  is separately approved.

## Proposed Slice Order

1. `US-BERKSHIRE-JOBS-001`: durable research jobs and typed store.
2. `US-BERKSHIRE-EVIDENCE-001`: provider registry and evidence bundle.
3. `US-BERKSHIRE-LLM-001`: multi-agent LLM workers and report audit.
4. `US-FOREX-CONTRACTS-001`: Forex rulebook, schemas, dossier, and journal
   compatibility.
5. `US-RISK-LEDGER-001`: shared exposure ledger across markets.
6. `US-BERKSHIRE-PROMOTION-001`: advisory-to-ticket promotion gate.
7. `US-FOREX-PAPER-ADAPTER-001`: Forex paper/replay adapter planning.
8. `US-BERKSHIRE-OPS-UI-001`: operator UI upgrades.

## Validation Expectations

Each implementation slice must run the relevant subset of:

- `python trading/schemas/export_json_schemas.py --check`
- `python trading/rulebook/compile_rulebook.py --check`
- targeted unit tests
- `pytest -x`
- frontend tests and build when UI changes
- Docker build/up and `/health` when runtime changes
- browser smoke for `/berkshire` when UI changes

## Notes

Start with durable research jobs. That creates the operational spine for real
LLM workers, live evidence providers, retries, progress states, audit events,
and replayable failures.
