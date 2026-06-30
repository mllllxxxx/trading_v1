# ADR-0002 Harness Docs Demotion

Role: architecture decision record

Date: 2026-06-28

## Status

Accepted

## Context

Trade_V1 contains a real trading application under `trading/` and also retains
generic repository-harness documents. Those Harness docs are useful for coding
workflow, but they can be mistaken for trading policy, runtime configuration, or
LLM context if they remain beside canonical trading docs without a boundary.

The first governance slice already selected `trading/docs/` as the canonical
product and architecture root for this repository.

## Decision

Harness and process documents are demoted to `docs/harness/` and must carry a
process-only banner. Root architecture files become compatibility pointers, and
legacy architecture content is retained only as historical reference.

Canonical trading policy and runtime contracts remain under:

- `docs/specs/`
- `trading/docs/product/`
- `trading/docs/architecture/`
- `trading/rulebook/source/`
- `trading/config/`
- `trading/schemas/`

Runtime modules and future RAG/prompt retrievers must use allowlist-first
behavior and must not index README, AGENTS, or Harness docs as trading context.

## Alternatives Considered

1. Delete Harness docs entirely.
2. Move canonical trading docs from `trading/docs/` into root `docs/`.
3. Keep current paths and add warnings only.

## Consequences

Positive:

- Future agents have a clear boundary between trading truth and process docs.
- The existing governance layout remains stable.
- Runtime context rules can be tested with static checks.

Tradeoffs:

- Some Harness references need path updates.
- Historical root architecture docs now require one extra click.

## Follow-Up

- Future retrievers and prompt builders must implement the allowlist in
  `trading/docs/architecture/RAG_INDEXING_POLICY.md`.
- Any new document must declare its role at the top.
