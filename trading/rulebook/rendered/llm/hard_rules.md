DO NOT EDIT - generated from trading/rulebook/source by compile_rulebook.py

# Hard Rules

## HARD_DATA_001 - Missing or stale market data means hold

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

If required market data is missing, stale, or has invalid current price, the system must not open a new order.

LLM guidance:

When data quality is poor or unknown, return HOLD or REQUEST_MORE_DATA.

## HARD_EXECUTION_001 - No execution before verifier pass

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

Broker execution is allowed only after the verifier and risk/order compiler approve a decision.

LLM guidance:

You may propose intent only. You cannot request direct broker execution.

## HARD_LLM_001 - Non-HOLD LLM decisions must cite real rule IDs

- Type: `hard_rule`
- Status: `active`
- Markets: crypto, forex

Any non-HOLD decision must cite valid rulebook IDs and an applicable playbook ID.

LLM guidance:

If no retrieved playbook fits, return HOLD. Never invent rule IDs.

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

## HARD_RISK_001 - Maximum risk, position, and legacy leverage policy

- Type: `hard_rule`
- Status: `active`
- Markets: crypto

A single position must not exceed the configured max risk percentage or max notional percentage of capital. Legacy validator compatibility also keeps the generic max leverage value.

LLM guidance:

Do not propose trades that exceed the maximum notional cap. If the setup needs too much size, return HOLD or reduce risk.

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
