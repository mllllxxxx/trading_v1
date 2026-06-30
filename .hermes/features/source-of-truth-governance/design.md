# Source-of-Truth Governance Foundation

## Goal

Establish the repository-owned governance foundation for the Trade_V1
LLM-governed refactor before changing runtime behavior.

## Scope

This slice covers workflow steps 0 through 2:

- Audit current source-of-truth drift.
- Copy the accepted governance and refactor specifications into the repo.
- Update identity docs so agents start from the trading application, not the
  generic harness.
- Add product and architecture docs that define the canonical source hierarchy.
- Add empty rulebook/config/schema directories for later compiler and runtime
  migration work.

## Non-Goals

- No scheduler, prompt, validator, broker, or order execution behavior changes.
- No live trading enablement.
- No rulebook compiler yet.
- No generated runtime artifact changes yet.

## Files Expected To Change

- `README.md`
- `AGENTS.md`
- `trading/README.md`
- `docs/specs/*`
- `docs/audits/*`
- `docs/stories/*`
- `trading/docs/product/*`
- `trading/docs/architecture/*`
- `trading/rulebook/*`
- skeleton keep files under `trading/config`, `trading/schemas`, and
  `trading/rulebook/source`.

## Validation Plan

- Confirm specs exist under `docs/specs`.
- Confirm `pytest -x` still passes or report the first existing failure.
- Confirm `git status --short` contains only intended governance/doc files.

