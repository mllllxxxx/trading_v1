# Berkshire Crypto Signal Scanner

## Goal

Implement the first crypto-first Berkshire scanner slice. `/berkshire` should
scan the crypto futures universe and surface research-only market signals that
can later be supplied to the LLM decision path as advisory context.

This slice does not place orders and does not promote signals to
`TradeDecisionTicket` yet.

## LLM Integration Contract

Berkshire is not a second executor. Berkshire becomes an advisory signal engine
that sits before the existing LLM-governed pipeline:

```text
Berkshire crypto scan
  -> BerkshireSignal
  -> advisory prompt context
  -> LLM TradeDecisionTicket
  -> critic
  -> verifier
  -> risk/order compiler
  -> execution adapter
```

The scanner may propose:

- signal state: `strong_candidate`, `candidate`, `watchlist`, or `blocked`;
- direction: `long`, `short`, or `neutral`;
- confidence/grade;
- entry, invalidation, and target reference zones;
- supporting reasons and blockers;
- an LLM context payload for a future ticket prompt.

The scanner may not:

- submit orders;
- choose executable quantity;
- bypass verifier or compiler;
- call broker APIs;
- mark Forex as execution-ready.

## Scope

- Add `trading/berkshire_scanner.py`.
- Add `POST /api/berkshire/crypto/scan`.
- Persist latest crypto scans in the Berkshire state store.
- Add signal data to `GET /api/berkshire/state`.
- Add `/berkshire` UI controls and signal board for crypto.
- Add backend and frontend tests for scanner behavior.

## Source Inputs

The first implementation uses public OKX swap ticker data when available and
falls back cleanly when data is unavailable. It scores:

- 24h momentum;
- quote volume/liquidity;
- bid/ask spread;
- 24h range/risk;
- data freshness and source quality.

This is intentionally a market-signal layer, not a full trade decision. Later
phases can enrich the signal with confluence, regime, funding, news, and true
multi-agent LLM research workers.

## API

`POST /api/berkshire/crypto/scan`

Request:

```json
{
  "symbols": ["BTC-USDT", "ETH-USDT"],
  "limit": 10
}
```

Response:

```json
{
  "status": "ok",
  "scan": {
    "id": "bscan_...",
    "market": "crypto",
    "mode": "signal_only",
    "signals": []
  },
  "state": {}
}
```

## Safety

- Signals are `signal_only`; they cannot create order payloads.
- Missing market data produces `blocked` signals or an empty scan with explicit
  provider error metadata.
- LLM context text must label Berkshire output as advisory evidence.
- Future promotion to tickets must go through a separate story and must use the
  existing critic/verifier/compiler path.

## Verification

- Backend unit tests for deterministic scan scoring and route persistence.
- Frontend test for scan button and signal board rendering.
- `pytest -x`.
- `npm run test:run`.
- `npm run build`.
- Docker build/up and `/health` if runtime code changes.
