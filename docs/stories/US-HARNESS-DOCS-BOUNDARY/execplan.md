# Exec Plan

Role: story execution plan

## Goal

Demote repository-Harness docs and enforce source-of-truth boundaries for
Trade_V1 without changing trading runtime behavior.

## Scope

In scope:

- Update README and AGENTS routing.
- Move Harness process docs under `docs/harness/`.
- Convert root architecture docs to pointers or historical references.
- Add runtime context and RAG indexing policy docs.
- Add ADR and boundary tests.

Out of scope:

- Runtime refactors.
- Trading feature changes.
- Broker execution changes.
- Live trading enablement.

## Risk Classification

Risk flags:

- Source hierarchy.
- Validation requirements.
- Existing agent workflow behavior.

Hard gates:

- Do not weaken trading safety guards.
- Do not use Harness docs as runtime trading context.

## Work Phases

1. Discovery.
2. Design.
3. Documentation boundary updates.
4. Static boundary tests.
5. Verification.
6. Harness trace.

## Stop Conditions

Pause for human confirmation if:

- Canonical trading source paths need to move.
- Runtime behavior must change.
- Verification requirements need to be weakened.
