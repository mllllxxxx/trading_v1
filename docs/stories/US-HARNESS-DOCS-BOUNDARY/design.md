# Design

Role: story design

## Domain Model

This is a documentation-boundary story. The relevant roles are:

- Canonical trading source: specs, trading product docs, architecture docs,
  rulebook source, config, and schemas.
- Generated artifact: compiled and rendered rulebook output.
- Development-process doc: Harness workflow docs under `docs/harness/`.
- Historical reference: legacy architecture material retained for context only.

## Application Flow

Runtime behavior is unchanged. Future retrievers and prompt builders must use
allowlist-first context sources defined in the RAG indexing policy.

## Interface Contract

No API, CLI, database, broker, or UI contract changes.

## Data Model

No schema or migration changes.

## UI / Platform Impact

No platform impact. Root `pytest.ini` routes default `pytest` execution to the
canonical `trading/tests` suite.

## Observability

Harness intake, decision, and trace records capture the source-boundary change.

## Alternatives Considered

1. Move canonical trading docs to root `docs/`: rejected to avoid churn because
   governance already selected `trading/docs/`.
2. Keep Harness docs in root with warnings only: rejected because path separation
   is clearer and easier to test.
