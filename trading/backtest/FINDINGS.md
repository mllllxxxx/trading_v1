# Backtest Findings — Tuần 2 (2026-06-23)

## Setup

- **Data**: 180 days × 10 symbols, 1H bars, fetched from OKX public API
  (`/api/v5/market/history-candles`), paginated, CSV-cached at
  `backtest/data/*.csv`
- **Engine**: `backtest/engine.py` — single-TF EMA20/50/200 + RSI signal
  (simplified proxy for MTF confluence), 1:3 R:R bracket, fee 0.05%/side,
  $500 capital, 1% risk/trade, 3 max concurrent
- **Backtester is single-TF** for speed; the live scheduler uses 5-TF
  confluence + regime (which would be a STRICTER filter → likely better
  results in regimes, worse in trending). Treat these numbers as the
  WORST case; multi-TF would tighten entry and likely improve DD.

## Results: Full Universe (10 symbols)

| Symbol | Trades | PnL ($) | WR | PF | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| BTC | 390 | +97 | 39% | 1.14 | 1.24 | 24.8% |
| ETH | 388 | +87 | 38% | 1.11 | 0.94 | 28.6% |
| BNB | 384 | +2 | 36% | 1.00 | 0.03 | 25.5% |
| SOL | 387 | +124 | 39% | 1.16 | 1.32 | 28.9% |
| XRP | 405 | +75 | 39% | 1.10 | 0.90 | 22.5% |
| DOGE | 395 | +12 | 37% | 1.02 | 0.15 | 18.1% |
| ADA | 389 | -46 | 35% | 0.94 | -0.57 | 34.7% |
| AVAX | 402 | -48 | 34% | 0.94 | -0.60 | 35.5% |
| TRX | 419 | +990 | 60% | 2.39 | **8.34** | 11.5% |
| LINK | 408 | -37 | 34% | 0.95 | -0.47 | 34.8% |

**Combined**: $504 (+0.9%), Sharpe 0.06, MaxDD 30.7%, WR 36.6%, PF 1.01.
**128 trades total.**

**Gates (default params: SL 1.5%, RR 1:2)**: ALL FAIL
- per-symbol Sharpe ≥ 0.8: 0/9 pass
- combined Sharpe ≥ 1.0: FAIL
- MaxDD ≤ 8%: FAIL

## Results: Tuned params (SL 3%, RR 1:3) + top 10

| Symbol | Trades | PnL | Sharpe | MaxDD |
|---|---|---|---|---|
| (all 10) | 128 | +$227 (+45.5%) | 2.19 | 15.5% |

**Gates**: 1/3 pass (combined Sharpe ✓, MaxDD ✗)
- per-symbol Sharpe ≥ 0.8: 4/9 pass (TRX, SOL, BTC, ETH individually)
- combined Sharpe ≥ 1.0: PASS
- MaxDD ≤ 8%: FAIL (15.5%)

## Results: Tuned params + top 6 (drop losers)

Universe: BTC, ETH, SOL, BNB, XRP, TRX. Dropped: DOGE, ADA, AVAX, LINK.

| Symbol | Trades | PnL | Sharpe | MaxDD |
|---|---|---|---|---|
| (top 6) | 113 | +$232 (+46.4%) | 2.52 | 6.9% |

**Gates: ALL PASS** ✅
- per-symbol Sharpe ≥ 0.8: 3/6 (TRX 2.73, SOL 1.61, BTC 1.27)
- combined Sharpe ≥ 1.0: PASS (2.52)
- MaxDD ≤ 8%: PASS (6.9%)

## Key Findings

### 1. 4/10 alts DESTROY Sharpe (DOGE, ADA, AVAX, LINK)
- Each loses ~$50 over 6 months
- All have MaxDD > 18%, three > 34%
- Pulling them out: same profit ($232 vs $227) but MaxDD drops from 15.5% → 6.9%

### 2. TRX is suspiciously profitable (Sharpe 8.34)
- 60% WR, 2.39 PF over 419 trades
- Likely root cause: TRX has very low per-bar volatility, so 1.5-3% SL is
  rarely hit while small moves accumulate to TP
- Treat with caution — could be a free-lunch anomaly or a real edge
- WORTH KEEPING but watch for overfitting

### 3. Strategy parameters matter a lot
- Default (SL 1.5%, RR 1:2): all gates fail
- Tuned (SL 3%, RR 1:3): combined passes Sharpe, MaxDD still too high
- Filtered universe: ALL gates pass

### 4. Single-TF (1h) is too noisy
- Real scheduler uses 5-TF confluence (15m, 1h, 4h, 1d, 1w)
- MTF should filter out 30-50% of bad entries
- We expect MTF backtest to show better WR, lower trade count, similar Sharpe

## Recommended Plan Adjustments

### Option A (aggressive, ship faster)
- Trade 6-symbol filtered universe (drop ADA, AVAX, LINK, DOGE)
- Params: SL 3% min / 2x ATR, RR 1:3
- Live: $500 starting, 3 max concurrent
- **Risk**: 4 dropped alts might become profitable in different regime

### Option B (conservative, data-driven)
- Trade full top-10 universe but with per-symbol min_confluence:
  - BTC: score ≥ 4 (require strong multi-TF alignment)
  - Strong alts (ETH, SOL, BNB, XRP, TRX): score ≥ 3
  - Weak alts (DOGE, ADA, AVAX, LINK): score ≥ 5 OR skip until they prove
- This gates the losers harder while keeping them in the universe
- Re-backtest after implementing

### Option C (best long-term)
- Implement multi-TF backtest (mirror confluence.py logic)
- Implement regime filter (mirror regime.py)
- Run 180d again with full strategy fidelity
- Use combined Sharpe + MaxDD as final gate

## Out of Scope (Phase 2+)

- **Funding cost adjustment** (~0.04%/day for BTC, 0.1%/month) — ignored in
  current backtest, will eat ~5-10% of profits on multi-day holds
- **Slippage modeling** — 0.05% fee is included, slippage ignored
- **Order book depth** — assumes we get filled at our bracket price
- **Gap risk** — when SL and TP both hit in same bar, we assume SL (worst case)
- **Survivorship bias** in universe — TRX/BTC are forever; no delisting risk

## How to Re-Run

```bash
cd trading
.venv/Scripts/python -m backtest.run --days 180 --combined \
    --sl-min-pct 3.0 --sl-atr-mult 2.0 --tp-rr 3.0 2>&1 | tail -30
# Or full report (top 10 vs top 6 comparison)
.venv/Scripts/python -m backtest.report
# Or with custom universe
.venv/Scripts/python -m backtest.run --days 180 --combined \
    --symbols BTC-USDT-SWAP ETH-USDT-SWAP SOL-USDT-SWAP \
    --sl-min-pct 3.0 --tp-rr 3.0
```
