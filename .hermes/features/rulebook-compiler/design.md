# Rulebook Source Seed And Compiler

## Goal

Create the first canonical rulebook source and deterministic compiler for
Trade_V1. This moves policy authorship toward `trading/rulebook/source` while
keeping runtime behavior stable for this slice.

## Scope

- Seed JSON source records for hard rules, soft policies, playbooks, and cases.
- Add a deterministic compiler that validates source IDs and references.
- Generate compiled JSON artifacts and rendered Markdown artifacts.
- Generate `trading/auto/skills.json` as a compatibility artifact for the
  existing `skills.py` loader.
- Add tests for compiler validation and generated artifact markers.

## Non-Goals

- Do not refactor `scheduler.py`, `validator.py`, `prompts.py`, or `skills.py`.
- Do not change fail-open/fail-closed runtime behavior yet.
- Do not add broker, execution, LLM, or live trading behavior.

## Validation Plan

- `python trading/rulebook/compile_rulebook.py --check`
- `pytest -x trading/tests`

