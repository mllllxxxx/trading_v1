# Feature Design Index

Role: implementation design and delivery history

Each feature directory may contain a `brief.md`, `design.md`, approval marker,
and status metadata. New feature work must create or update
`trading/docs/features/{feature-name}/design.md` before implementation.

These files are project-visible engineering artifacts. They are not canonical
trading policy and must not be indexed into runtime prompts or RAG. When a
feature changes trading behavior, update the relevant canonical product doc,
architecture contract, config, rulebook source, or schema first. The canonical
domain map is `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`.

The cockpit Project Feature Pipeline reads this directory for delivery status.
