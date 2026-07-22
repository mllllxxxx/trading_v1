DO NOT EDIT - generated from trading/rulebook/source by compile_rulebook.py

# Rulebook

## CASE_BAD_CHASE_BREAKOUT_001 - Bad trade chasing extended breakout

- Type: `case_memory`
- Status: `active`
- Markets: crypto

A breakout trade entered late after price had already extended far from the breakout base.

LLM guidance:

Use this as a warning against late impulse entries.

## CASE_BAD_FUNDING_OVERHEATED_001 - Bad trade with overheated funding

- Type: `case_memory`
- Status: `active`
- Markets: crypto

A crowded long setup ignored elevated funding and produced poor entry quality.

LLM guidance:

Use this as a warning when funding state is elevated or extreme.

## CASE_GOOD_TREND_LONG_001 - Good trend long after pullback

- Type: `case_memory`
- Status: `active`
- Markets: crypto

A trend-following long where confluence, regime, and pullback entry aligned before risk checks passed.

LLM guidance:

Use this as a positive example for trend-aligned pullback entries.

## HARD_DATA_001 - Missing or stale market data means hold

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

If required market data is missing, stale, or has invalid current price, the system must not open a new order. For the 15m strategy trigger, freshness is measured from the latest confirmed candle close with a default maximum age of 1080 seconds.

LLM guidance:

When data quality is poor or unknown, return HOLD or REQUEST_MORE_DATA.

## HARD_EXECUTION_001 - No execution before verifier pass

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

Broker execution is allowed only after the verifier and risk/order compiler approve a decision.

LLM guidance:

You may propose intent only. You cannot request direct broker execution.

## HARD_LLM_001 - Non-HOLD LLM decisions must cite real rule IDs and fit team profiles

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

Any non-HOLD decision must cite valid rulebook IDs and an applicable playbook ID. Team-profile OPEN_LONG and OPEN_SHORT tickets must also prove profile compliance.

LLM guidance:

If no retrieved playbook fits, return HOLD. Never invent rule IDs. If a team profile is present, OPEN_LONG and OPEN_SHORT tickets must include profile_compliance_score, profile_compliance_summary, and profile_compliance_flags, and must use one of the team's preferred playbooks.

## HARD_LLM_002 - Invalid LLM JSON or schema failure means hold

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

Invalid LLM output must not reach execution after bounded repair attempts fail.

LLM guidance:

Return only valid JSON matching the required schema.

## HARD_MODE_001 - Paper and live-like modes fail closed

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

In autonomous paper or live-like modes, LLM, data, rule retrieval, verifier, compiler, or broker uncertainty must result in HOLD or halted execution.

LLM guidance:

Uncertainty is not permission to trade. Return HOLD when required context is unavailable.

## HARD_RISK_001 - Maximum risk, margin, notional, and leverage policy

- Type: `hard_rule`
- Status: `active`
- Markets: crypto

A team risk percentage is a target capped by market structure and execution limits. A single position must not exceed the hard risk, margin, gross-notional, or leverage limits.

LLM guidance:

Treat team risk as a target and never force it. The compiler may reduce actual risk to satisfy the 20% margin, 60% gross-notional, 3x leverage, contract-size, and 5% risk ceilings.

## HARD_RISK_002 - Stop loss and take profit required

- Type: `hard_rule`
- Status: `active`
- Markets: crypto

Any new non-HOLD trade must include both stop-loss and take-profit planning.

LLM guidance:

If a valid stop-loss or take-profit cannot be defined, return HOLD.

## HARD_RISK_003 - Minimum reward-to-risk requirement

- Type: `hard_rule`
- Status: `active`
- Markets: crypto

New trades must satisfy the minimum reward-to-risk threshold before execution.

LLM guidance:

Prefer HOLD over forcing an entry with insufficient reward-to-risk.

## PB_CRYPTO_BREAKOUT_PULLBACK_001 - Crypto breakout pullback

- Type: `playbook`
- Status: `active`
- Markets: crypto

Use after a confirmed breakout when price retests the breakout level with controlled volatility.

LLM guidance:

Prefer entry near retest; do not chase far above or below the breakout base.

## PB_CRYPTO_MEAN_REVERSION_001 - Crypto mean reversion

- Type: `playbook`
- Status: `active`
- Markets: crypto

Use only when regime is ranging and price is near a well-defined range boundary.

LLM guidance:

Mean reversion is invalid in strong trending regimes unless higher timeframe context supports range behavior.

## PB_CRYPTO_TREND_CONTINUATION_001 - Crypto trend continuation

- Type: `playbook`
- Status: `active`
- Markets: crypto

Use when higher timeframe regime and confluence point in the same trend direction.

LLM guidance:

Prefer pullback or retest entries aligned with trend. Avoid late impulse entries.

## PB_FX_POST_EVENT_CONTINUATION_001 - Forex post-event continuation

- Type: `playbook`
- Status: `active`
- Markets: forex

Future forex playbook for continuation after high-impact event volatility settles.

LLM guidance:

Use only after event spread and data quality policies exist and pass.

## PB_FX_TREND_CONTINUATION_001 - Forex trend continuation

- Type: `playbook`
- Status: `active`
- Markets: forex

Future forex playbook for aligned trend continuation after forex data and execution adapters exist.

LLM guidance:

Forex execution is not enabled by this playbook. It is source material for future adapter work.

## SOFT_CORRELATION_001 - Avoid stacking correlated exposure

- Type: `soft_policy`
- Status: `active`
- Markets: crypto, forex

Avoid accumulating several highly correlated positions in the same direction.

LLM guidance:

If correlation exposure is already high, reduce risk or return HOLD.

## SOFT_CRYPTO_001 - Avoid chasing extended crypto moves

- Type: `soft_policy`
- Status: `active`
- Markets: crypto

A valid trend does not justify chasing late entries after extended candles or extreme oscillator readings.

LLM guidance:

Prefer waiting for a retest or returning HOLD when price is stretched.

## SOFT_CRYPTO_002 - Reduce risk when funding is elevated

- Type: `soft_policy`
- Status: `active`
- Markets: crypto

Crypto breakouts are lower quality when funding is unusually elevated or crowded.

LLM guidance:

Treat elevated funding as a warning, not automatic permission to trade.

## SOFT_REGIME_001 - Trend-following preferred in trending regimes

- Type: `soft_policy`
- Status: `active`
- Markets: crypto, forex

In a strong trend, prefer continuation setups aligned with higher timeframe direction.

LLM guidance:

Use pullbacks or retests rather than impulse chasing.

## SOFT_REGIME_002 - Mean reversion only in ranging regimes

- Type: `soft_policy`
- Status: `active`
- Markets: crypto, forex

Mean-reversion setups are preferred only when regime and structure indicate a range.

LLM guidance:

Do not fade strong trends just because a short-term oscillator is extended.

## SOFT_STRATEGY_TEAM_001 - Strategy team skill profiles

- Type: `soft_policy`
- Status: `active`
- Markets: crypto

The strategy-team tournament uses distinct advisory skill profiles for Momentum, Mean Reversion, and Volatility Breakout while preserving the shared LLM, verifier, compiler, and demo execution path.

LLM guidance:

Use the strategy_skill_profiles metadata to interpret team-tagged SignalCandidate records. Skill profiles are advisory context only and never bypass hard rules, retrieved playbooks, verifier checks, or the risk compiler. For OPEN_LONG or OPEN_SHORT tickets from a team profile, return profile_compliance_score, profile_compliance_summary, and profile_compliance_flags; use HOLD when the selected setup cannot honestly meet the profile.

Profile compliance:

```json
{
  "applies_to": [
    "OPEN_LONG",
    "OPEN_SHORT"
  ],
  "failure_behavior": "verifier_reject",
  "min_profile_compliance_score": 0.6,
  "preferred_playbook_required": true,
  "required_ticket_fields": [
    "profile_compliance_score",
    "profile_compliance_summary",
    "profile_compliance_flags"
  ]
}
```

Strategy skill profiles:

```json
{
  "mean_reversion": {
    "avoid_conditions": [
      "strong trending regime",
      "disorderly range expansion",
      "missing range structure",
      "thin liquidity"
    ],
    "entry_style": "Fade a stretched RSI/Bollinger move only in a confirmed 1H range after 15m turns back toward value.",
    "llm_guidance": "Mean Reversion must not fade strong trends by default. It should return HOLD unless range behavior and invalidation are clear.",
    "preferred_playbook_ids": [
      "PB_CRYPTO_MEAN_REVERSION_001"
    ],
    "required_soft_policy_ids": [
      "SOFT_REGIME_002",
      "SOFT_CORRELATION_001",
      "SOFT_STRATEGY_TEAM_001"
    ],
    "risk_personality": "patient contrarian; low target risk unless range quality is clear."
  },
  "momentum": {
    "avoid_conditions": [
      "late impulse chase",
      "thin liquidity",
      "wide spread",
      "funding or crowding warning"
    ],
    "entry_style": "Wait for a confirmed 1H/15m pullback or EMA20 reclaim inside a 4H trend; do not chase beyond 0.5 ATR.",
    "llm_guidance": "Momentum may promote trend continuation only when liquidity, spread, and regime support the impulse. Prefer HOLD over chasing an extended move.",
    "preferred_playbook_ids": [
      "PB_CRYPTO_TREND_CONTINUATION_001"
    ],
    "required_soft_policy_ids": [
      "SOFT_CRYPTO_001",
      "SOFT_CRYPTO_002",
      "SOFT_REGIME_001",
      "SOFT_STRATEGY_TEAM_001"
    ],
    "risk_personality": "medium-high conviction trend follower; reduce confidence when entry is far from retest."
  },
  "volatility_breakout": {
    "avoid_conditions": [
      "range expansion missing",
      "failed breakout",
      "overextended breakout",
      "wide spread"
    ],
    "entry_style": "Trade range expansion only after directional pressure is visible, preferring retest or pullback over raw chase.",
    "llm_guidance": "Volatility Breakout may promote expansion setups, but must prefer pullback entries and reject failed or overextended breakouts.",
    "preferred_playbook_ids": [
      "PB_CRYPTO_BREAKOUT_PULLBACK_001"
    ],
    "required_soft_policy_ids": [
      "SOFT_CRYPTO_001",
      "SOFT_CRYPTO_002",
      "SOFT_CORRELATION_001",
      "SOFT_STRATEGY_TEAM_001"
    ],
    "risk_personality": "highest tournament risk target, but only for confirmed expansion with clear invalidation."
  }
}
```
