P1+P2 refactor summary (integrated into initial commit)

## P1 - Cleanup & contracts
- Created src/types/api.ts: canonical backend types (Stats, AccountState,
  ClosedTrade, TraderStatusPayload, Adaptive/Shadow status types).
- Removed duplicate type declarations from TerminalLayout.tsx, Cockpit.tsx,
  Trader.tsx.
- Replaced local request<T>() helpers in TerminalLayout, Trader, Cockpit,
  Correlation, TraderHistory with shared api client methods:
  api.getTraderStatus, api.getTraderTicker, api.getCorrelation,
  api.getTraderHistory(Stats), api.armKillSwitch, api.disarmKillSwitch.
- Extracted duplicated groupMessages() into src/lib/groupMessages.ts.
- Consolidated Skeleton components (common/Skeleton now re-exports
  terminal/primitives Skeleton).
- Removed :any from ECharts formatters (EquityChart, CandlestickChart,
  Compare) via new ChartFormatterParams type in lib/echarts.ts.
- Removed :any from TerminalLayout llm_decisions reduce/filter.
- Deleted dead code: Layout.tsx.deprecated, unused Home.tsx.
- Added ESLint flat config (eslint.config.mjs) + Prettier config
  (.prettierrc.json) + lint/format npm scripts.

## P2 - Design system
- Split src/index.css into:
  - src/styles/base.css        (HSL tokens + ttcc palette + resets)
  - src/styles/animations.css   (keyframes + reduced-motion)
  - src/styles/components.css   (utility classes: tt-skeleton, tt-live-dot...)
- Merged .tt-root and .ttcc-root CSS rules (both now share --tt-* vars).
- Removed unused term.* palette from tailwind.config.ts.
- Fixed BOM/irregular whitespace in WelcomeScreen.tsx.

## Verification
- tsc --noEmit: pass (0 errors)
- vitest run: 27 files, 231 tests pass
- eslint: 0 errors, 5 warnings (deferred to P3)
- vite build: success