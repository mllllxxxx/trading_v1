# Runtime Context Boundaries

Role: runtime contract

Runtime trading modules must not read generic Harness or development-process
docs as policy or prompt context.

## Allowed Runtime Policy/Context Sources

- `trading/rulebook/source/`
- `trading/rulebook/compiled/`
- `trading/rulebook/rendered/`
- `trading/schemas/`
- `trading/config/`
- `trading/docs/product/`
- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/SIGNAL_CONTRACTS.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`

## Disallowed Runtime Policy/Context Sources

- `docs/harness/`
- `AGENTS.md`
- `README.md`
- generic templates
- repository-harness scripts
- old or legacy architecture docs unless explicitly whitelisted
- `.hermes/`
- `trading/docs/features/`
- `docs/prompts/`
- `docs/development/`

## Enforcement Rule

If a runtime module needs a policy value, it must load the canonical source or a
compiled artifact. It must not scrape README, AGENTS, or Harness docs.
