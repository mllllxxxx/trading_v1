# Documentation Map

Role: documentation index

This directory holds repository specs, decisions, stories, templates, and
development-process Harness docs. Canonical trading product and architecture
docs live under `trading/docs/`.

## Main Files

- `harness/HARNESS.md`: how humans and agents collaborate.
- `harness/FEATURE_INTAKE.md`: how prompts become tiny, normal, or high-risk work.
- `ARCHITECTURE.md`: pointer to canonical trading architecture and the demoted
  Harness architecture template.
- `harness/TEST_MATRIX.md`: legacy proof map; current proof status is queried
  with `scripts/bin/harness-cli query matrix`.
- `harness/HARNESS_BACKLOG.md`: legacy improvement list; current improvement
  records are stored with `scripts/bin/harness-cli backlog`.
- `harness/GLOSSARY.md`: Harness/process terms.

## Folders

- `specs/`: accepted Trade_V1 governance and refactor specifications.
- `harness/`: development-process docs only; not trading policy or runtime
  context.
- `product/`: compatibility pointer; canonical trading product docs are under
  `trading/docs/product/`.
- `stories/`: feature packets and backlog.
- `decisions/`: durable decisions and tradeoffs.
- `templates/`: reusable spec-intake, story, plan, decision, and validation
  formats.

## Current State

Trade_V1 has an active trading runtime under `trading/`. Root Harness docs are
process support only and must not be indexed as trading context.
