# Overview

Role: story packet

## Current Behavior

Root Harness documents and generic architecture templates sit beside Trade_V1
trading specs. Future agents can mistake process docs for trading policy or LLM
runtime context.

## Target Behavior

Root docs identify Trade_V1 as the trading system, Harness docs are demoted to
process-only guidance, and runtime/RAG boundary docs deny README, AGENTS, and
Harness docs as trading context.

## Affected Users

- Coding agents working in Trade_V1.
- Maintainers reviewing source-of-truth governance changes.

## Affected Product Docs

- `docs/specs/trading_v1_harness_docs_source_of_truth_addendum.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`

## Non-Goals

- No trading runtime behavior changes.
- No scheduler, prompt, validator, broker, or strategy refactor.
- No live trading enablement.
