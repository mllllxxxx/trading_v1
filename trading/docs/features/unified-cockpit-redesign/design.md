# Feature Design: Unified Trading Cockpit Redesign

## 1. Goal & Context
The user wants to unify all daily operational aspects of the `Trade_V1` system into a single screen (a Cockpit dashboard) instead of having separate pages that hide critical context (such as hiding active positions when chatting with the Agent, or hiding the Chat when looking at positions). 

The new UI/UX must be:
- **Beautiful & Sleek**: High-end dark-tech aesthetic (Bloomberg/TradingView style) with glassmorphism, precise neon indicators, and clean spacing.
- **Logical & Scientific**: Organize data panels systematically (System Metrics & Regime on the left, active execution and controls in the center, and Co-Pilot reasoning + chat on the right).
- **Easy to Use**: Unified control surfaces, no unnecessary tab hopping, clear visual cues for SL/TP distances and liquidation buffers.

---

## 2. Layout Architecture
We will introduce a 3-pane layout on the root (`/`) page, combining live trader telemetry with the AI Agent Chat:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              TOP BAR (Ticker scroll, Cap, PnL, Kill Switch)            │
├──────────────────────┬───────────────────────────────────────────────────┬─────────────┤
│  LEFT PANEL (260px)  │           CENTER WORKSPACE (Flex-1)               │ RIGHT PANEL │
│                      │                                                   │   (360px)   │
│  - Account Stats     │  ┌──────────────────────────────────────────────┐ │             │
│    (PnL, Cap, WR)    │  │ 1. Active Positions Deck                     │ │ - AI Agent  │
│  - Watchlist Prices  │  │    (Leverage, SL/TP progress, PnL)           │ │   Chat      │
│  - Market Regime     │  └──────────────────────────────────────────────┘ │   Console   │
│    (Hurst, ADX)      │  ┌──────────────────────────────────────────────┐ │   (Welcome, │
│  - MTF Confluence    │  │ 2. Tabbed Workspace                          │ │    bubbles, │
│    Score             │  │    [Journal] [Indicators] [Corr] [Settings]  │ │    input,   │
│                      │  │    - Closed Trades Table                     │ │    proposls)│
│                      │  │    - Multi-Timeframe Indicators Grid         │ │ - Brain     │
│                      │  │    - Correlation Matrix builder              │ │   Log       │
│                      │  │    - LLM & Strategy Settings                 │ │             │
│                      │  └──────────────────────────────────────────────┘ │             │
└──────────────────────┴───────────────────────────────────────────────────┴─────────────┘
```

---

## 3. Component Walkthrough

### 3.1 Extracting Reusable Chat (`AgentChat.tsx`)
Currently, `Agent.tsx` is a huge page (1600+ lines) containing both state management (SSE, session fetching, file uploading, goal operations) and visual rendering.
We will create a clean, reusable component `AgentChat` (or reuse it dynamically) that allows rendering the chat workspace anywhere (including inside the Right Panel).

### 3.2 Unified Cockpit Page (`Home.tsx`)
Instead of displaying a simple feature-link page, the root route `/` will now render the unified **Cockpit** which:
1. Polls exchange status (positions, closed trades, stats) every 5s.
2. Embeds the interactive Agent chat and sessions list directly in the right panel.
3. Automatically sets `isTraderRoute` to true for the root `/` route in `TerminalLayout` so the full layout remains visible and responsive.

### 3.3 Enhanced Positions Display
Improve `PositionCard.tsx` with:
- Clearer visual indicator of Stop Loss & Take Profit distance.
- Margin usage and liquidation risk level alerts (H7 validator warning).
- Dynamic color indicators matching the trade side (green for Long, red for Short).

---

## 4. Visual Enhancements (Tailwind + CSS)
- **Glassmorphism**: Add subtle backdrops (`backdrop-blur-md`) and borders to panels to make them look premium.
- **Status Accents**: Calibrated neon shades for status indicators (no flat primary red/green).
- **Tabular Font Formatting**: Enforce `tabular-nums` for all prices, sizes, and timestamps to prevent layout shifts during real-time updates.

---

## 5. Verification Plan
- **Unit Tests**: Add tests for the new cockpit rendering and ensure existing tests pass.
- **Verification**: Run `npm run test:run` and verify 100% success.
