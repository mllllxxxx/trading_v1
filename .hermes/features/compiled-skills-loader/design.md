# Compiled Skills Loader Fail-Closed Behavior

## Goal

Make `trading/auto/skills.py` consume generated compiled rulebook skills instead
of treating `trading/auto/skills.json` as an editable source of truth.

## Scope

- Default loader path becomes `trading/rulebook/compiled/skills.json`.
- `trading/auto/skills.json` remains a generated compatibility artifact only.
- Missing, malformed, or non-generated skills raise `SkillsLoadError`.
- Paper/live/review modes always fail closed.
- Test fixture fallback exists only when explicitly requested in test/dev mode.
- Existing validator API remains compatible: `get_hard_skills()` and
  `get_soft_skills()`.

## Non-Goals

- No scheduler pipeline refactor.
- No prompt builder refactor.
- No verifier/risk compiler wiring.
- No broker/live guard changes.

## Validation Plan

- `python trading/rulebook/compile_rulebook.py --check`
- `pytest -x`

