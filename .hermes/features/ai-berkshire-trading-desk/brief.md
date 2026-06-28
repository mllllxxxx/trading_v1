# AI Berkshire Trading Desk Brief

## Request

Ben wants the `xbtlin/ai-berkshire` repository represented as a real product feature inside Trade_V1, not only as an internal advisory design. The feature must be a standalone screen with complete interface treatment and become the foundation for running future Forex trading workflows in parallel with the existing Crypto trading stack.

## Product Reading

This is an operator-facing trading cockpit surface. It should feel like a dense research and risk desk, not a marketing page. The first version is allowed to be UI-foundation only, but it must clearly show how Crypto and Forex lanes will coexist without implying that Forex execution is already wired.

## Scope

- Add a separate frontend route for the AI Berkshire desk.
- Add navigation access from the existing terminal mini-nav.
- Build a complete responsive screen using the existing terminal visual system.
- Model the feature around AI Berkshire research processes: investment team, research intake, quality screen, news pulse, thesis tracking, portfolio review, and audit controls.
- Expose Crypto and Forex as two parallel market lanes with clear readiness states.
- Add automated frontend tests for the new screen.

## Non-goals

- Do not wire live Forex broker execution in this slice.
- Do not modify OKX crypto order placement, validator rules, or scheduler behavior.
- Do not import AI Berkshire as a runtime dependency. The upstream repo is a skill/report framework, not a package or service.
- Do not break existing JSON journal formats or trade execution paths.
