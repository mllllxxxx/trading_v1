# Market Dossier And Rule Retriever

## Goal

Add the first runtime-safe context layer for the LLM-governed pipeline:

- build a normalized `MarketDossier` from confluence, regime, portfolio, and
  data-quality inputs;
- retrieve deterministic rulebook context from generated artifacts;
- keep scheduler and broker execution behavior unchanged in this slice.

## Scope

- Add `trading/auto/market_dossier.py`.
- Add `trading/auto/rule_retriever.py`.
- Extend rulebook compilation with `compiled/retriever_manifest.json`.
- Update `RetrievedRuleContext` schema to carry prompt-ready rule snippets.
- Add tests for fail-closed dossier building and deterministic retrieval.

## Non-Goals

- Do not route scheduler decisions through the new pipeline yet.
- Do not change order execution, broker guards, or live trading state.
- Do not refactor prompts, brain, verifier, or risk compiler in this slice.
- Do not add vector search; deterministic metadata filtering is enough.

## Design

`build_market_dossier(...)` accepts explicit inputs and returns a
JSON-serializable `MarketDossier`. Missing or invalid core data such as
current price, confluence score, or regime raises `MarketDossierBuildError` so
callers can fail closed. Stale data or optional state issues are represented as
`data_quality=C` with warnings in `portfolio_exposure`.

The rulebook compiler generates `retriever_manifest.json` from canonical source
records. The retriever reads only generated compiled artifacts and filters by:

- market;
- active status;
- candidate direction;
- regime;
- timeframe;
- related hard/soft rules;
- matching case playbook references.

## Validation Plan

- `python trading/rulebook/compile_rulebook.py --check`
- `python trading/schemas/export_json_schemas.py --check`
- targeted tests for `test_market_dossier.py` and `test_rule_retriever.py`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`
- Docker build/up and `/health` after code changes
