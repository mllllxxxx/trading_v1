# Trading Runtime Bottleneck Repair

Feature ID: trading-runtime-bottlenecks
Status: implementation

## Runtime Evidence

- Strategy scanners produced eligible candidates, but every LLM ticket failed
  before critic/verifier because compact prompts omitted exact nested shapes.
- The 15-minute scheduler ran four times per hour while the per-team LLM quota
  allowed only three calls per hour.
- Schema, budget, and adapter-infrastructure failures were misclassified as
  60-minute setup rejections.
- OKX demo CCXT markets omitted dynamic swaps that the public instruments API
  exposed with valid contract metadata.
- Package-mode scheduler execution could not import the shared journal budget
  gate even though service bootstrap mode could.

## Contract

- Render exact OPEN object shapes for `entry_plan` and `risk_plan`; terminal
  HOLD/REQUEST_MORE_DATA tickets use null.
- Demo quota is 160 calls/day, 16 calls/hour, four calls/team/hour, with the
  existing $0.20/day cost ceiling and fail-closed behavior.
- JSON/schema/provider/budget/adapter-infrastructure failures use a 15-minute
  cooldown. Valid HOLD and setup/verifier rejection use 60 minutes.
- Resolve exact swap metadata from CCXT first and OKX public instruments second;
  validate `instId`, `ctVal`, and `minSz`/`lotSz`, otherwise fail closed.
- The central budget gate supports both top-level service imports and package
  imports without duplicating journal state.
