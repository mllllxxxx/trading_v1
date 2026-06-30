# Shared Decision Pipeline Schemas

## Goal

Create the shared schema contract for the LLM-governed decision pipeline before
refactoring the prompt, brain, verifier, risk compiler, or scheduler.

## Scope

- Add dataclass models and validation helpers for decision pipeline payloads.
- Add JSON schema export for LLM/prompt/verifier consumers.
- Validate `TradeDecisionTicket` core invariants.
- Add tests for valid and invalid tickets.

## Non-Goals

- Do not wire scheduler to the new schemas yet.
- Do not refactor `brain.py` output parsing yet.
- Do not add verifier/risk compiler implementation yet.
- Do not change broker execution behavior.

## Validation Plan

- `python trading/schemas/export_json_schemas.py --check`
- `python trading/rulebook/compile_rulebook.py --check`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-trading-tests.ps1`

