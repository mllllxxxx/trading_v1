# Project Cleanup and Runtime Optimization

Feature ID: project-cleanup-runtime-optimization
Status: implementation

## Goal

Reduce repository noise and startup work without changing trading policy,
risk limits, decision routing, broker behavior, or demo-only safeguards.

## Baseline Evidence

- Backend: 500 tests passed from the repository root.
- Frontend: 231 tests passed.
- Production build passed, but the initial application chunk was about 810 kB.
- Ruff reported unused imports, unused local assignments, and pandas names that
  were available only through function-local imports.
- Repeated pytest runs left many cache and temporary directories at repository
  root and below `trading/`.

## Contract

- Remove only imports and assignments proven unused by static analysis.
- Preserve public function signatures and accepted keyword arguments.
- Keep pandas as a lazy runtime dependency while making type-only references
  explicit through `TYPE_CHECKING`.
- Lazy-load the chat console so Markdown and syntax-highlighting dependencies
  are not part of the synchronous application bootstrap.
- Ignore generated dependency, lint, pytest, and build caches.
- Do not modify canonical trading policy or generated rulebook artifacts.

## Acceptance Criteria

- Ruff has no F401, F811, F821, or F841 findings in maintained Python code.
- Backend and frontend test counts remain green.
- Frontend production build remains green and the initial bundle is smaller.
- Git status no longer reports newly generated pytest or pnpm cache paths.
