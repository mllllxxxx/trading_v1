# US-RULEBOOK-001 Rulebook Source Seed And Compiler

## Status

implemented

## Lane

high-risk

## Product Contract

Canonical trading policy begins in `trading/rulebook/source`. Compiled and
rendered files are generated artifacts with a generated marker. Existing runtime
compatibility is preserved by generating `trading/auto/skills.json` with the
legacy `hard` and `soft` keys.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/rulebook/README.md`

## Acceptance Criteria

- Rulebook source records have stable IDs and required metadata.
- Compiler rejects duplicate IDs, invalid prefixes, missing required hard rule
  references, and missing hard-rule enforcement fields.
- Compiler generates compiled JSON and rendered Markdown artifacts with
  generated markers.
- `trading/auto/skills.json` is generated from rulebook source for backward
  compatibility.
- Runtime scheduler/validator/prompt behavior is otherwise unchanged.

## Design Notes

- Commands: `python trading/rulebook/compile_rulebook.py --check`
- Queries: none.
- API: unchanged.
- Tables: unchanged.
- Domain rules: source JSON records under `trading/rulebook/source`.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | `pytest -x trading/tests` |
| Integration | Compiler check command |
| E2E | Not changed in this slice |
| Platform | Docker not required because runtime behavior is unchanged |
| Release | Final source-of-truth compliance audit later |

## Harness Delta

Added story record and feature design for the rulebook compiler slice.

## Evidence

- `python trading/rulebook/compile_rulebook.py --check` passed with 21 source
  records.
- `pytest -x trading/tests` passed 138 tests.
- `trading/auto/skills.json` is generated from `trading/rulebook/source` and
  matches `trading/rulebook/compiled/skills.json`.
- `docker compose build` was attempted from `trading/`, but Docker Desktop was
  not running (`dockerDesktopLinuxEngine` pipe missing).
