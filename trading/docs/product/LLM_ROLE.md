# LLM Role

The LLM is a trade-reasoning component. It may propose intent inside the
rulebook-defined universe, but it is not an executor and not the final risk
authority.

## Allowed LLM Outputs

The target LLM output is a `TradeDecisionTicket` with one action:

- `HOLD`
- `OPEN_LONG`
- `OPEN_SHORT`
- `CLOSE_POSITION`
- `REDUCE_POSITION`
- `REQUEST_MORE_DATA`

## Required For Non-HOLD Tickets

- Existing `playbook_id`.
- Existing rule citations.
- Thesis.
- Entry plan.
- Risk plan.
- Invalidation conditions.
- Confidence.
- Data quality.

## Not Allowed

- Calling broker/execution tools.
- Choosing final order quantity.
- Overriding hard rules.
- Bypassing verifier or risk/order compiler.
- Changing autonomy mode or live trading state.

