# Futures Layer — Design Document

> **Project**: Trade_V1
> **Status**: Tuần 1 / Day 0 (design)
> **Author**: Auto-generated from plan v3
> **Date**: 2026-06-23

## 0. Background

Trade_V1 hiện chạy trên **OKX spot** (`AUTO_SYMBOLS=BTC-USDT,...`, `okx_bracket.py:11`
note: "OKX spot does not have native OCO"). User yêu cầu chuyển sang **OKX USDT-margined
futures** với 10 symbols (top 10 theo market cap, locked 6 tháng).

Mục tiêu Tuần 1: thêm futures layer **parallel** với spot (không phá spot mode), cho
phép scheduler chạy `TRADE_MODE=futures` độc lập.

## 1. Architecture

### 1.1 Mode fork

```
                  ┌──────────────────┐
                  │   scheduler.py   │
                  │  (entry point)   │
                  └─────────┬────────┘
                            │ read TRADE_MODE env
              ┌─────────────┴─────────────┐
              ▼                           ▼
   ┌────────────────────┐      ┌────────────────────┐
   │   SPOT MODE        │      │   FUTURES MODE     │
   │   (existing)       │      │   (NEW)            │
   │                    │      │                    │
   │ • okx_bracket.py   │      │ • okx_futures_     │
   │ • spot symbols     │      │   bracket.py       │
   │   BTC-USDT         │      │ • SWAP symbols     │
   │                    │      │   BTC-USDT-SWAP    │
   │ • no leverage      │      │ • per-symbol lev   │
   │ • no liquidation   │      │ • liq buffer check │
   │                    │      │ • funding blackout  │
   └────────────────────┘      └────────────────────┘
              │                           │
              └─────────────┬─────────────┘
                            ▼
                  ┌──────────────────┐
                  │   validator.py   │
                  │   (shared)       │
                  └──────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │  journal.py      │
                  │  monitor.py      │
                  │  (shared)       │
                  └──────────────────┘
```

**Single source of truth**: `TRADE_MODE` env var (`spot` | `futures`). Default = `spot`
để giữ backward compat.

### 1.2 Module map (Tuần 1)

| Module | Status | Mục đích |
|---|---|---|
| `brackets/okx_futures_bracket.py` | NEW | Compute + place futures bracket |
| `auto/universe.py` | NEW | Top-N symbol loader, daily refresh |
| `auto/llm_override_tracker.py` | NEW | Track override decisions, compute winrate |
| `auto/validator.py` | EXTEND | Thêm H5/H7/H8 |
| `auto/scheduler.py` | EXTEND | Fork spot/futures mode |
| `tests/test_futures_bracket.py` | NEW | Unit tests bracket |
| `tests/test_validator_futures.py` | NEW | Unit tests validator |
| `tests/test_universe.py` | NEW | Unit tests universe |
| `tests/test_llm_override_tracker.py` | NEW | Unit tests tracker |

## 2. Data Model

### 2.1 SymbolConfig

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class SymbolConfig:
    base: str               # "BTC"
    swap_symbol: str        # "BTC-USDT-SWAP" (OKX futures format)
    spot_symbol: str        # "BTC-USDT" (cho confluence + data)
    leverage: int           # 10 (BTC), 2-3 (alts)
    max_notional_pct: float # 0.30 = 30% capital
    min_confluence: int     # 4 (BTC), 3 (alts)
    liq_buffer_pct: float   # 0.30 = entry cách liq >= 30%
    min_rr: float           # 1.5 (futures: account for funding cost)
    contract_size: float    # 0.01 (BTC), 1 (altcoin) - from OKX
    min_qty: float          # min order qty
```

### 2.2 UniverseSnapshot

```python
@dataclass(frozen=True)
class UniverseSnapshot:
    fetched_at: datetime    # UTC
    symbols: list[SymbolConfig]
    source: str             # "okx_api" | "fallback_hardcoded"
    raw_tickers: list[dict] # cho debug
```

### 2.3 LLMOverrideLog (append-only)

```python
@dataclass
class LLMOverrideLog:
    ts: datetime
    symbol: str
    llm_action: str         # "long" | "short" | "no_trade"
    rules_action: str       # action mà rules recommend
    llm_overrode: bool      # true = LLM action != rules action
    reasoning: str          # LLM's reasoning
    # filled after close:
    closed_at: datetime | None
    pnl_usd: float | None
    win: bool | None
```

## 3. OKX API Mapping

### 3.1 Endpoints cần dùng

| Mục đích | Method | Path | Auth |
|---|---|---|---|
| Fetch universe | GET | `/api/v5/market/tickers?instType=SWAP&uly=USDT` | no |
| Place algo order (TP/SL) | POST | `/api/v5/trade/order-algo` | yes |
| Set leverage | POST | `/api/v5/account/set-leverage` | yes |
| Funding rate | GET | `/api/v5/public/funding-rate?instId=...` | no |
| Funding rate history | GET | `/api/v5/public/funding-rate-history?instId=...` | no |
| Open interest | GET | `/api/v5/public/open-interest?instType=SWAP&instId=...` | no |
| Position info | GET | `/api/v5/account/positions?instType=SWAP&instId=...` | yes |
| Algo order history | GET | `/api/v5/trade/orders-algo-pending?instType=SWAP&instId=...` | yes |
| Cancel algo order | POST | `/api/v5/trade/cancel-algo-order` | yes |

### 3.2 Algo order format (TP/SL futures)

OKX futures supports algo orders với `slTriggerPx` + `tpTriggerPx` cùng lúc (native OCO).
Request shape:

```json
{
  "instId": "BTC-USDT-SWAP",
  "tdMode": "isolated",
  "side": "buy" | "sell",
  "posSide": "long" | "short" | "net",
  "ordType": "conditional",
  "sz": "0.01",
  "tgtCcy": "base_ccy",
  "tpTriggerPx": "70000",
  "tpOrdPx": "-1",          // market
  "tpOrdKind": "condition",
  "slTriggerPx": "64000",
  "slOrdPx": "-1",
  "slTriggerPxType": "mark"
}
```

### 3.3 Error codes cần handle

| Code | Meaning | Action |
|---|---|---|
| 51000 | Parameter error | log + halt cycle |
| 51131 | Algo order not allowed | skip symbol, alert |
| 51400 | Insufficient margin | scale down or skip |
| 51008 | Position > leverage limit | reduce position |
| 51003 | Instrument not found | refresh universe, skip |
| 51022 | Risk limit breach | reduce leverage, alert |

## 4. Risk Layer

### 4.1 Existing hard rules (keep + verify)

| ID | Rule | Source |
|---|---|---|
| H1 | Volatility cap: ATR(14) * 3 > price * 5% | validator.py:7 |
| H2 | News blackout ±30 min | validator.py:81 |
| H3 | Position ≤ 20% capital (per-trade notional) | okx_bracket.py:47 |
| H4 | RSI extreme: ≥85 no long, ≤15 no short | validator.py:110 |
| H6 | Confidence < 0.40 → no_trade | validator.py:124 |

### 4.2 NEW hard rules (Tuần 1)

| ID | Rule | Implementation |
|---|---|---|
| **H5** | Per-symbol leverage cap (BTC=10, alts=2-3) | `validator.check_leverage(symbol, lev)` |
| **H7** | Liquidation buffer: `|entry - liq| / entry ≥ SYMBOL_CFG.liq_buffer_pct` (default 30%) | `okx_futures_bracket.compute_liquidation_price()` + check |
| **H8** | Funding blackout: refuse new position 5 min before/after funding time | `validator.check_funding_blackout(symbol, now)` |

### 4.3 Liquidation math (isolated, linear USDT-margined)

```
LONG:
  liq_price = entry * (1 - 1/leverage + maintenance_margin_rate)
  
SHORT:
  liq_price = entry * (1 + 1/leverage - maintenance_margin_rate)

maintenance_margin_rate (MMR): OKX returns per instrument
  ~0.5% cho BTC, ~1% cho alts (fetch từ /api/v5/account/risk-state?)

Buffer check:
  distance_pct = |entry - liq_price| / entry
  if distance_pct < SYMBOL_CFG.liq_buffer_pct:
    REJECT (H7 violation)
```

### 4.4 Funding rate

- Funding time: mỗi 8h (00:00, 08:00, 16:00 UTC)
- `funding_rate` positive = longs pay shorts
- `next_funding_time` returned by `/funding-rate` endpoint
- Blackout window: `[next_funding_time - 5min, next_funding_time + 5min]`
- Outside blackout: cho phép, log rate để tracking

## 5. Hybrid LLM Override

### 5.1 Design

Thay vì static `AUTO_OVERRIDE_ALLOWED=true`, dùng **rolling winrate** của LLM overrides.

### 5.2 Algorithm

```python
def should_allow_llm_override(symbol: str) -> bool:
    """Dynamic override gate based on LLM historical performance."""
    config = LLM_OVERRIDE_CONFIG  # see below
    recent = tracker.get_recent_overrides(
        symbol=symbol, 
        n=config.lookback,
        only_used=True  # chỉ tính trades mà LLM đã override
    )
    if len(recent) < config.min_samples:
        return False  # cold start: nghe rules
    winrate = sum(o.win for o in recent) / len(recent)
    return winrate >= config.winrate_threshold
```

### 5.3 Config (env)

```
LLM_OVERRIDE_MIN_SAMPLES=20       # need 20+ closed overrides before allowing
LLM_OVERRIDE_WINRATE_THRESHOLD=0.60  # 60% winrate
LLM_OVERRIDE_LOOKBACK=30          # rolling window of 30 trades
LLM_OVERRIDE_ENABLED=true         # master switch
```

### 5.4 Per-trade logging

Trong `journal.append_decision` (existing), thêm fields:
- `llm_action`, `rules_action`, `llm_overrode`
- Sau khi close: thêm row vào `closed_trades.jsonl` với `override_used` flag

## 6. Universe Loader

### 6.1 Logic

```python
def load_universe() -> UniverseSnapshot:
    """Fetch top 10 USDT-margined SWAP by 24h volume."""
    try:
        tickers = okx_get("/api/v5/market/tickers?instType=SWAP&uly=USDT")
        candidates = [
            t for t in tickers["data"]
            if t["instId"].endswith("-USDT-SWAP")  # USDT-margined only
            and not is_stablecoin(t["instId"])
        ]
        candidates.sort(key=lambda t: float(t["volCcy24h"]), reverse=True)
        top_10 = candidates[:10]
        return UniverseSnapshot(
            fetched_at=datetime.utcnow(),
            symbols=[map_to_config(t) for t in top_10],
            source="okx_api",
            raw_tickers=top_10,
        )
    except Exception as e:
        logger.warning("universe fetch failed: %s, using fallback", e)
        return HARDCODED_FALLBACK
```

### 6.2 Hardcoded fallback (2026-06-23)

```python
HARDCODED_FALLBACK = UniverseSnapshot(
    symbols=[
        SymbolConfig("BTC", "BTC-USDT-SWAP", "BTC-USDT", 10, 0.30, 4, 0.30, 1.5, 0.01, 0.01),
        SymbolConfig("ETH", "ETH-USDT-SWAP", "ETH-USDT", 3, 0.30, 3, 0.30, 1.5, 0.01, 0.01),
        SymbolConfig("BNB", "BNB-USDT-SWAP", "BNB-USDT", 3, 0.30, 3, 0.30, 1.5, 0.01, 0.01),
        SymbolConfig("SOL", "SOL-USDT-SWAP", "SOL-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("XRP", "XRP-USDT-SWAP", "XRP-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("DOGE", "DOGE-USDT-SWAP", "DOGE-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("ADA", "ADA-USDT-SWAP", "ADA-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("AVAX", "AVAX-USDT-SWAP", "AVAX-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("TRX", "TRX-USDT-SWAP", "TRX-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
        SymbolConfig("LINK", "LINK-USDT-SWAP", "LINK-USDT", 3, 0.30, 3, 0.30, 1.5, 1, 1),
    ],
    source="fallback_hardcoded",
    ...
)
```

### 6.3 Refresh strategy

- Daily refresh: cron at 00:00 UTC, save to `/data/universe.json`
- On startup: load from cache, attempt fresh fetch
- If fetch fails: keep using cache, log warning
- Manual override: `UNIVERSE_OVERRIDE=BTC-USDT-SWAP,ETH-USDT-SWAP,...` env (comma-separated)

## 7. Test Plan

### 7.1 Unit tests

| Module | Test cases |
|---|---|
| `compute_bracket_futures` | long/short happy path, R:R < min reject, leverage cap, scale-down on max notional |
| `compute_liquidation_price` | long/short formula correctness, buffer check reject |
| `check_leverage` (H5) | per-symbol table, reject if exceeds |
| `check_funding_blackout` (H8) | inside window reject, outside allow |
| `load_universe` | API success, API fail → fallback, stablecoin filter, top-10 sort |
| `should_allow_llm_override` | cold start false, < min_samples false, winrate >= threshold true, < threshold false |
| `tracker.append` + `get_recent_overrides` | append order, filter by symbol, lookback window |

### 7.2 Integration tests (mock OKX)

- Full pipeline: universe load → scheduler cycle → bracket compute → validator pass/fail
- Hybrid mode: log 20 losers → override auto-disabled → log 20 winners → override re-enabled

### 7.3 E2E (paper)

- OKX demo account, 1 symbol (BTC-USDT-SWAP), 3 cycles
- Verify: orders placed, position monitored, TP/SL triggers, journal entries
- Manual check: Telegram alert on each event

## 8. Migration Checklist

### 8.1 Pre-deploy (Tuần 1 end)

- [ ] `pytest -x` all pass
- [ ] `okx_futures_bracket.py --dry-run` for 10 symbols → all return valid proposal
- [ ] `validator.py` H5/H7/H8 tests pass
- [ ] `universe.py` loads OK on OKX demo
- [ ] LLM override tracker: simulate 30 trades, verify gate logic
- [ ] Existing spot mode regression: `TRADE_MODE=spot python -m auto.scheduler --once`

### 8.2 Deploy (Tuần 3)

- [ ] Local Windows: `TRADE_MODE=futures OKX_TESTNET=true python -m auto.auto`, run 24h
- [ ] VPS Oracle: deploy Docker image, run 24h on demo
- [ ] Verify healthcheck, Telegram alerts, journal persistence

### 8.3 Rollback

If critical issue:
- [ ] `docker compose down`
- [ ] `git checkout main` (revert all new files)
- [ ] Restart with `TRADE_MODE=spot` (revert to known-good)

## 9. Open Questions / Risks

| Item | Risk | Mitigation |
|---|---|---|
| OKX algo order OCO | If OKX thay đổi API → bracket fail | Pin API version, add retry |
| Liquidation formula chính xác | Maintenance margin rate OKX biến động | Fetch từ `/risk-state` mỗi cycle |
| LLM override cold start | Chưa có data → luôn false | Manual `LLM_OVERRIDE_ENABLED=false` trong 30 ngày đầu |
| BTC min notional 0.01 BTC = $1000 | All-in với $500 capital | Per-symbol max_notional cap, alert if breached |
| 10x leverage BTC 1 swing 5% = -$50 | DD gate trigger frequently | Track per-symbol DD, không pool chung |

## 10. Out of Scope (Phase 2, sau 30 ngày live)

- Alpha Zoo 456 factors integration
- 8-category confluence
- ML ensemble
- Multi-symbol correlation filter
- Auto re-tune per-symbol leverage based on live data
- HA / failover setup
- Object Storage backup automation

## 11. File-by-file Estimates

| File | LoC est | Time est |
|---|---|---|
| `okx_futures_bracket.py` | ~350 | Day 1 |
| `universe.py` | ~150 | Day 4 |
| `llm_override_tracker.py` | ~120 | Day 5 |
| `validator.py` (extend) | ~80 | Day 3 |
| `scheduler.py` (fork) | ~50 | Day 4 |
| Tests (4 files) | ~300 | Day 5 |
| **Total** | **~1050 LoC** | **5 days** |
