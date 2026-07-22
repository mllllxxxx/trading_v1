DO NOT EDIT - generated from trading/rulebook/source by compile_rulebook.py

# Soft Policies

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
