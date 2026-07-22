# Harness Docs Source Boundary

## Goal

Apply the harness-docs demotion addendum without changing trading runtime
behavior. The result should make it clear that Harness files are development
process guidance only, while trading policy remains under the existing
Trade_V1 source-of-truth hierarchy.

## Source-of-Truth Choice

The first governance slice already placed canonical trading product and
architecture docs under `trading/docs/`. This slice keeps that layout to avoid
path churn:

- Canonical specs: `docs/specs/`
- Canonical trading product docs: `trading/docs/product/`
- Canonical trading architecture docs: `trading/docs/architecture/`
- Canonical rulebook/config/schema roots: `trading/rulebook/source/`,
  `trading/config/`, and `trading/schemas/`
- Development-process docs: `docs/harness/`

## Scope

- Copy the supplied addendum into `docs/specs/`.
- Replace root README with a trading-oriented repo identity and process-doc
  links.
- Replace AGENTS with routing and safety instructions that do not define
  concrete trading policy values.
- Demote generic Harness docs under `docs/harness/` with a process-only banner.
- Convert root architecture docs into pointers or historical references.
- Add runtime context and RAG indexing boundary docs under
  `trading/docs/architecture/`.
- Add an ADR for the demotion decision.
- Add static tests for AGENTS policy leakage, Harness doc banners, runtime
  denylist, and rulebook source roots.

## Non-Goals

- No scheduler, prompt, validator, broker, order, or strategy behavior changes.
- No live trading enablement.
- No sandbox, paper, or testnet guard changes.
- No new trading features.

## Validation Plan

- Run the new source-of-truth boundary test directly.
- Run `pytest -x trading/tests`.
- Run `python trading/rulebook/compile_rulebook.py --check`.
- Report any pre-existing or environment-limited failures honestly.
