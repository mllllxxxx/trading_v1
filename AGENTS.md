# Agent Instructions

## Project: Trade_V1 — Hybrid Agentic Trading System

Read these docs in order:
1. `README.md`
2. `docs/ARCHITECTURE_V2.md` ← **Main architecture doc (start here)**
3. `docs/HARNESS.md`
4. `docs/FEATURE_INTAKE.md`
5. `docs/CONTEXT_RULES.md`
6. `docs/TOOL_REGISTRY.md`

## Key Files
- `trading/auto/brain.py` — LLM decision engine
- `trading/auto/prompts.py` — System/User prompts (cần update với trading rules)
- `trading/auto/validator.py` — Hard rules validator (cần mở rộng)
- `trading/auto/scheduler.py` — Main trading loop
- `trading/confluence/confluence.py` — MTF confluence scoring (cần mở rộng)
- `trading/regime/regime.py` — Market regime detector
- `trading/brackets/okx_bracket.py` — OKX bracket orders

## Project Vision
- **Target Market & Platform**: Cryptocurrency Futures (Swap contracts) trading via the **OKX** exchange.
- **Performance Target**: Consistent winrate of **55% - 65%**.
- **Watchlist**: Top 50 market cap coins (USDT-margined SWAP contracts).
- **Leverage Policy**: Medium leverage of **5x - 10x**.
- **Max Exposure**: Maximum of **10 concurrent open positions** at any time.
- **Dynamic Capital Management**: Capital risk per trade is dynamically scaled based on LLM confidence:
  - *High Confidence ($\ge$ 0.85)*: Risk **3% - 5%** of total capital (based on Stop Loss distance).
  - *Normal Confidence (0.60 - 0.84)*: Risk **1% - 2%** of total capital.
  - *Probe/Low Confidence (0.40 - 0.59)*: Risk **0.5%** of total capital.
- **Holding Strategy (Swing + Dynamic Exits)**: Primarily swing trading (retaining positions for a few days to 1 week) to capture major trends (accepting funding fees), integrated with dynamic exits managed by LLM market context evaluation.
- **Post-Trade Review & Self-Improvement**: Actively log all losing trades and validator rejections to `llm_overrides.jsonl` and/or `closed_trades.jsonl`. This failure telemetry is fed back into the LLM context to refine subsequent decision prompts.

## Development Rules
- **Design before code**: Create a design doc in `.hermes/features/{name}/design.md` before starting development.
- **Testing Mandate (Strict)**: Every new feature or logic change **MUST** be accompanied by comprehensive automated tests (Unit Tests) covering the changes.
- **Verification**: Run `pytest -x` after every change. All tests (new and existing) must pass 100%.
- **Autopilot Autonomy**: The Dev Autopilot is fully autonomous. Branches named `dev-autopilot/{feature-name}` may be merged automatically *only* if all automated tests pass 100%.
- **Max 3 retries**: If tests fail 3 times during development, stop immediately, log the failure, and notify the user.
- **Backward compatibility**: Never break existing JSON schemas, databases, or trade journal formats.
- **Docker Deployment**: Rebuild the Docker container (`docker compose build` and `docker compose up -d`) after every code change to deploy the changes to the running environment.

<!-- HARNESS:BEGIN -->
## Harness

This repo uses Harness. Before work, read:

- `README.md`
- `docs/HARNESS.md`
- `docs/FEATURE_INTAKE.md`
- `docs/ARCHITECTURE.md`
- `docs/CONTEXT_RULES.md`
- `docs/TOOL_REGISTRY.md`
- `scripts/bin/harness-cli query matrix` on macOS/Linux, or `.\scripts\bin\harness-cli.exe query matrix` on Windows

Use the Rust Harness CLI at `scripts/bin/harness-cli` on macOS/Linux or
`scripts/bin/harness-cli.exe` on Windows as the main operational tool. Before a
step that could use an external tool, run `scripts/bin/harness-cli query tools
--capability <name> --status present` to see what is equipped; an absent
capability is a clean skip.
<!-- HARNESS:END -->
