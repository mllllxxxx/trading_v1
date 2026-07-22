# AI Berkshire Trading Desk Design

## Decision

Implement a standalone React route named `/berkshire` that presents AI Berkshire as a research and risk desk inside the existing terminal app. The page is a foundation for two market lanes:

- Crypto Futures: current Trade_V1 execution domain, connected conceptually to OKX, confluence, validator, scheduler, and journal telemetry.
- Forex: future execution domain, shown as a planned lane with explicit readiness gaps for broker adapter, symbol universe, session calendar, spread controls, and journal schema extensions.

The feature must now move beyond frontend-only scaffolding. It gets a local backend research workflow that can create and persist AI Berkshire-style research runs. This is still not an execution engine: Forex remains research-only until a broker adapter, spread/session guards, and shared exposure ledger exist.

## Source Mapping

AI Berkshire upstream content maps into Trade_V1 as follows:

| AI Berkshire concept | Trade_V1 screen responsibility |
| --- | --- |
| investment-team | Show analyst pods for business quality, financial/macro, market structure, and risk review |
| investment-research | Show research queue and thesis workbench |
| investment-checklist | Show pre-trade checklist and gate criteria |
| quality-screen | Show quality moat / liquidity / risk filters |
| news-pulse | Show catalyst radar and stale-context checks |
| thesis-tracker | Show thesis state, invalidation level, review cadence |
| portfolio-review | Show portfolio heat and allocation pressure |
| financial_rigor / report_audit tools | Show audit controls and evidence quality states |

## UX Structure

The screen uses the existing Trading Command Center design language:

- top operator header with market lane switch and screen status
- summary tiles for research coverage, market lanes, active theses, and risk gates
- left column: Crypto and Forex lane matrix
- center column: Berkshire research pipeline and analyst pods
- right column: current thesis workbench, risk guardrails, and audit log
- bottom band: build roadmap for parallel Crypto/Forex operation

The design must be dense, scannable, and responsive. Cards are used only for repeated operational items and panels. No hero, no decorative gradients, no fake execution controls.

## Operational Backend Contract

The screen consumes:

- `GET /api/berkshire/state`: return lanes, pipelines, analyst pods, roadmap, latest research runs, active run, and audit events.
- `POST /api/berkshire/research`: create a research run for a lane/symbol/skill, generate four analyst perspectives, checklist verdict, Decimal-based price/risk sanity checks when price fields are provided, persist it, and return updated state.

State is stored under `$VIBE_TRADING_HOME/berkshire/state.json` and must survive container restart.

```json
{
  "lanes": [
    {
      "key": "crypto",
      "label": "Crypto Futures",
      "status": "live",
      "symbols": 50,
      "execution": "okx",
      "risk_policy": "1-5% dynamic risk, 5x-10x leverage"
    },
    {
      "key": "forex",
      "label": "Forex",
      "status": "foundation",
      "symbols": 0,
      "execution": "planned",
      "risk_policy": "pending broker adapter"
    }
  ],
  "research_items": [],
  "theses": [],
  "audit_events": []
}
```

The first operational implementation is deterministic and local. It mirrors the upstream AI Berkshire process shape, but it does not claim to run external web research or true LLM subagents yet.

## Safety

- UI labels must distinguish `live`, `shadow`, `planned`, and `blocked`.
- Forex is never presented as trade-enabled in this slice.
- AI Berkshire recommendations are research context only and cannot override validators.
- Future integration must keep a shared risk ledger so Crypto and Forex cannot exceed global exposure limits.
- POST actions require the same local/auth gate as sensitive control-plane APIs.
- Generated research verdicts must say `research_only` and must not produce order payloads.

## Verification

- Add a page test that renders the desk, verifies Crypto and Forex lanes, verifies tab switching, and confirms Forex is marked as foundation/planned.
- Add backend tests for state bootstrap and persisted research creation.
- Run frontend unit tests and build.
- Run `pytest -x` for backend regression.
- Rebuild and restart Docker Compose after code changes.
