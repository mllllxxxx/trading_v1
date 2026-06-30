# US-SKILLS-001 Compiled Skills Loader Fail-Closed Behavior

## Status

implemented

## Lane

high-risk

## Product Contract

The existing validator and prompt compatibility layer must read skills from the
compiled rulebook artifact. It must not silently invent fallback trading policy
in paper/live-like modes when compiled skills are missing or malformed.

## Relevant Product Docs

- `docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/rulebook/README.md`

## Acceptance Criteria

- Default `load_skills()` reads `trading/rulebook/compiled/skills.json`.
- Missing compiled skills raise `SkillsLoadError` in paper/live-like modes.
- Malformed compiled skills raise `SkillsLoadError` in paper/live-like modes.
- Explicit test fallback works only for test/dev/research modes.
- `get_hard_skills()` and `get_soft_skills()` remain backward compatible.

## Design Notes

- Commands: none.
- Queries: none.
- API: `SkillsLoadError`, `load_compiled_rulebook`, `load_skills`.
- Tables: unchanged.
- Domain rules: no new trading rules; loader enforcement only.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | `pytest -x` |
| Integration | `python trading/rulebook/compile_rulebook.py --check` |
| E2E | Not changed in this slice |
| Platform | Docker build attempted if daemon is available |
| Release | Final source-of-truth compliance audit later |

## Harness Delta

Added a story record and feature design for the compiled skills loader slice.

## Evidence

- `python trading/rulebook/compile_rulebook.py --check` passed with 21 source
  records.
- `scripts/verify-trading-tests.ps1` passed 151 tests and is the durable story
  verification command.
- The first plain `pytest -x` attempt could not run because the current shell
  did not have `pytest` on PATH; `python -m pytest` used the Hermes venv without
  pytest installed.
- `docker compose build` was attempted. With default Docker config it was
  blocked by sandbox access to `C:\Users\minhl\.docker`; with workspace
  `DOCKER_CONFIG`, Docker daemon was unavailable (`docker_engine` pipe missing).
