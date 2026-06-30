# Risk Mandate

Risk policy must be authored in canonical product docs, config profiles, and
rulebook hard rules. Prompt text, scheduler code, validator code, and `.env`
files must not be the only place risk limits live.

## Current Target Mandate

- Crypto futures via OKX paper/testnet first.
- Maximum concurrent exposure target: 10 open positions.
- Medium leverage target: 5x to 10x only where explicitly allowed.
- Every non-HOLD open-position decision requires a stop-loss and risk plan.
- Risk per trade is based on account equity and stop distance, not raw LLM
  quantity.
- Position sizing must be computed by the risk/order compiler.

## Future Canonical Inputs

- `trading/config/risk_profiles.yaml`
- `trading/rulebook/source/hard/HARD_RISK_*.yaml`
- `trading/schemas/order_intent.schema.json`
- `trading/schemas/trade_decision_ticket.schema.json`

