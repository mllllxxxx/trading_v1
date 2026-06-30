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
