# Berkshire Top-50 Confidence Allocation

## Intent

Berkshire crypto scanning should cover the top 50 OKX USDT swap symbols and
feed the demo trading pipeline with a portfolio-aware selection policy:

- scan up to 50 symbols per cycle;
- allow up to 10 concurrent open positions in demo/paper mode;
- when more eligible signals exist than remaining slots, rank by signal
  confidence first, then scanner score, then liquidity;
- promote only the highest-ranked signals through LLM ticket generation,
  verifier, risk/order compiler, and demo execution.

This feature does not enable live trading and does not allow scanner output to
become an order. Berkshire remains a SignalCandidate source.

## Source Of Truth

- Signal confidence and ranking behavior live in
  `trading/docs/architecture/SIGNAL_CONTRACTS.md`.
- Concurrent exposure target lives in
  `trading/docs/product/RISK_MANDATE.md`.
- Runtime env values in Docker and `.env.template` select the active local
  demo profile but are not the canonical policy source.

## Runtime Behavior

1. The scanner derives a top-50 universe from explicit symbols when supplied,
   otherwise from the OKX USDT swap universe.
2. Every signal contains:
   - `confidence`: 0.0 to 1.0 final scanner confidence;
   - `confidence_components`: normalized evidence used to compute confidence;
   - `score`: legacy 0 to 100 score for UI compatibility.
3. Schedulers and API auto-promotion sort eligible signals by:
   - confidence descending;
   - score descending;
   - volume descending;
   - symbol ascending.
4. The portfolio guard checks current journal/exchange exposure before each
   promotion and stops once the configured max open position cap is reached.

## Safety Notes

- Top-50 scanning expands opportunity discovery, not execution authority.
- The LLM may still return HOLD or REQUEST_MORE_DATA.
- Verifier, risk/order compiler, exchange duplicate guard, testnet guards, and
  journal lifecycle remain mandatory.
- Unknown OKX swap symbols use conservative dynamic futures metadata so the
  bracket module can validate demo orders without hardcoding each top-50 coin.

## Verification

- Unit tests cover confidence ranking, max 10 promotion selection, dynamic
  universe metadata, and max-position guards.
- Full pytest and frontend build must pass.
- Docker local must be rebuilt and verified via `/api/berkshire/crypto/scan`
  or `/berkshire`.
