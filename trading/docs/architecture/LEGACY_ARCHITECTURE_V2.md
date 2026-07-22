# Legacy Architecture V2

Role: historical reference

Historical reference only. This file is not canonical trading policy, runtime
configuration, LLM trading context, or rulebook source of truth.

Canonical trading architecture lives in:

- `trading/docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/architecture/RUNTIME_CONTEXT_BOUNDARIES.md`
- `trading/docs/architecture/RAG_INDEXING_POLICY.md`

---
# Trade_V1 â€” Há»‡ Thá»‘ng Giao Dá»‹ch Hybrid Agentic Trading

## Tá»•ng Quan

Há»‡ thá»‘ng káº¿t há»£p **rules-based** (hard rules khÃ´ng thá»ƒ override) vÃ  **LLM reasoning** (soft rules linh hoáº¡t) Ä‘á»ƒ Ä‘Æ°a ra quyáº¿t Ä‘á»‹nh long/short/hold. Cháº¡y hoÃ n toÃ n local vá»›i LLM nhá» (DeepSeek-R1-1.5B, Qwen3-1.7B) káº¿t há»£p Vibe-Trading (HKUDS) lÃ m ná»n táº£ng data + backtesting.

---

## Kiáº¿n TrÃºc Tá»•ng Thá»ƒ

```
                      â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                      â”‚          CRON SCHEDULER              â”‚
                      â”‚         (má»—i 5 phÃºt / 12h)          â”‚
                      â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                        â”‚
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â–¼                   â–¼                   â–¼
          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
          â”‚  SCANNER        â”‚ â”‚  DEV AUTOPILOT  â”‚ â”‚  RESEARCH       â”‚
          â”‚  (5 phÃºt)       â”‚ â”‚  (12h)          â”‚ â”‚  AUTOPILOT      â”‚
          â”‚  Market data    â”‚ â”‚  Tá»± Ä‘á»™ng phÃ¡t   â”‚ â”‚  (Vibe-Trading) â”‚
          â”‚  â†’ Indicators   â”‚ â”‚  triá»ƒn feature  â”‚ â”‚  Hypothesisâ†’Testâ”‚
          â””â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                   â”‚
                   â–¼
          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
          â”‚              DECISION ENGINE                        â”‚
          â”‚                                                     â”‚
          â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”‚
          â”‚  â”‚ REGIME       â”‚  â”‚ CONFLUENCE   â”‚  â”‚ LLM BRAIN â”‚  â”‚
          â”‚  â”‚ (Hurst, ADX, â”‚  â”‚ (MTF scoring)â”‚  â”‚ (DeepSeek)â”‚  â”‚
          â”‚  â”‚ ATR, EMA50)  â”‚  â”‚              â”‚  â”‚           â”‚  â”‚
          â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â”‚
          â”‚                                                     â”‚
          â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”                 â”‚
          â”‚  â”‚ VALIDATOR    â”‚  â”‚ PROMPTS      â”‚                 â”‚
          â”‚  â”‚ (Hard rules) â”‚  â”‚ (System+User)â”‚                 â”‚
          â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                 â”‚
          â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                                    â”‚
                                    â–¼
          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
          â”‚              EXECUTION LAYER                        â”‚
          â”‚                                                     â”‚
          â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”‚
          â”‚  â”‚ BRACKET      â”‚  â”‚ MONITOR      â”‚  â”‚ EXCHANGE  â”‚  â”‚
          â”‚  â”‚ (OKX order)  â”‚  â”‚ (Position)   â”‚  â”‚ (CCXT)    â”‚  â”‚
          â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â”‚
          â”‚                                                     â”‚
          â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”                 â”‚
          â”‚  â”‚ JOURNAL      â”‚  â”‚ ALERTS       â”‚                 â”‚
          â”‚  â”‚ (Trade log)  â”‚  â”‚ (Telegram)   â”‚                 â”‚
          â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜                 â”‚
          â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

---

## I. DATA LAYER (Scanner)

### 1.1 Market Scanner (má»—i 5 phÃºt)

**Input:** Symbol list tá»« config
**Process:**
```
1. Fetch OHLCV tá»« OKX / Binance / data source
2. TÃ­nh toÃ¡n indicators:
   - MA: SMA_20/50/200, EMA_9/21/50, VWMA_21, Golden/Death Cross
   - Structure: Swing highs/lows, S/R levels, Fibonacci
   - Volume: VSA signal (buying_climax, selling_climax, stopping_volume, absorption), volume_ratio
   - Candlestick: Pattern detection (doji, hammer, engulfing, morning/evening star...)
   - Ichimoku: Tenkan/Kijun/Senkou/Chikou/Kumo, TK cross, price vs cloud
   - Oscillators: RSI (zone + divergence), MACD (histogram + divergence), Bollinger (%B, squeeze), Stochastic
3. Fetch news sentiment (optional: Arkham on-chain data)
4. Output: JSON
```

**Output JSON structure:**
```json
{
  "symbol": "BTC-USDT",
  "timestamp": "2026-06-21T10:00:00+07:00",
  "timeframe": "5m",
  "price": { "current": 68420.0, "change_24h_pct": 2.3 },
  "moving_averages": {
    "sma_20": 68000.0, "sma_50": 67500.0, "sma_200": 66000.0,
    "ema_9": 68100.0, "ema_21": 67800.0, "ema_50": 67200.0,
    "vwma_21": 68050.0, "golden_cross": false, "death_cross": false
  },
  "structure": {
    "support_levels": [67500, 66500, 65000],
    "resistance_levels": [68800, 69500, 70500],
    "nearest_support": 67500, "nearest_resistance": 68800
  },
  "volume": {
    "current": 32500.0, "sma_20": 25000.0, "ratio_vs_sma_20": 1.3,
    "vsa_signal": "normal", "bar_type": "up_bar"
  },
  "candlestick": {
    "current_bar": { "open": 68100, "high": 68600, "low": 67900, "close": 68420, "body": 320 },
    "pattern": "bull_engulfing", "pattern_reliability": "high"
  },
  "ichimoku": {
    "tenkan_sen": 68200.0, "kijun_sen": 67900.0,
    "senkou_a": 68000.0, "senkou_b": 67600.0, "chikou_span": 68100.0,
    "price_vs_cloud": "above", "cloud_type": "bullish",
    "tk_cross": "bullish", "chikou_vs_price": "above"
  },
  "oscillators": {
    "rsi_14": 62.5, "rsi_zone": "bullish", "rsi_divergence": "none",
    "macd": { "value": 120.0, "signal": 98.0, "histogram": 22.0, "histogram_direction": "rising" },
    "bollinger_bands": { "upper": 71200.0, "middle": 68100.0, "lower": 65000.0,
      "bandwidth": 0.091, "bandwidth_signal": "squeeze" },
    "stochastic": { "k": 68.0, "d": 62.0, "zone": "neutral" }
  },
  "atr_14": 1200.0
}
```

### 1.2 Multi-Timeframe Scanner (má»—i giá»)

TÆ°Æ¡ng tá»± nhÆ°ng fetch cho 3 TF:
```json
{
  "direction_tf": { "timeframe": "1h", "overall_bias": "up" },
  "confirmation_tf": { "timeframe": "15m", "overall_signal": "confirmed" },
  "entry_tf": { "timeframe": "5m", "entry_zone": "68300..68500" }
}
```

---

## II. DECISION ENGINE

### 2.1 Market Regime Detector (Ä‘Ã£ cÃ³)

**File:** `trading/regime/regime.py`

PhÃ¢n loáº¡i thá»‹ trÆ°á»ng thÃ nh 5 regime:
| Regime | Ã nghÄ©a | Chiáº¿n lÆ°á»£c |
|---|---|---|
| TRENDING_UP | Uptrend máº¡nh | Momentum, trend following |
| TRENDING_DOWN | Downtrend máº¡nh | Short momentum |
| RANGING | Sideways, mean-reverting | Range trade, fade extremes |
| HIGH_VOLATILITY | Biáº¿n Ä‘á»™ng cao | Reduce size, wide stops |
| MIXED | TÃ­n hiá»‡u mÃ¢u thuáº«n | NO TRADE |

**Indicators:** Hurst exponent, ADX, ATR ratio, EMA50 slope.

### 2.2 Multi-Timeframe Confluence (Ä‘Ã£ cÃ³, cáº§n má»Ÿ rá»™ng)

**File:** `trading/confluence/confluence.py`

Hiá»‡n táº¡i: EMA50/EMA200 alignment + EMA20 momentum cross 5 TF (15m, 1h, 4h, 1d, 1w).

**Lá»™ trÃ¬nh (Roadmap)**: Sáº½ má»Ÿ rá»™ng thÃ nh 8 category confluence (xem pháº§n IV) khi phÃ¡t triá»ƒn cÃ¡c module indicators nÃ¢ng cao.

### 2.3 LLM Brain (Ä‘Ã£ cÃ³)

**File:** `trading/auto/brain.py`

Gá»i LLM máº·c Ä‘á»‹nh `deepseek-chat` (hoáº·c thÃ´ng qua cáº¥u hÃ¬nh `AUTO_LLM_MODEL`) vá»›i:
- System prompt: role, hard rules, soft skills, output JSON schema
- User prompt: current market state + open positions + recent PnL

### 2.4 Prompts System (Ä‘Ã£ cÃ³, cáº§n cáº­p nháº­t)

**File:** `trading/auto/prompts.py`

Hiá»‡n táº¡i cÃ³ hard rules vÃ  soft skills. Cáº§n má»Ÿ rá»™ng (xem pháº§n IV).

### 2.5 Validator (Ä‘Ã£ cÃ³)

**File:** `trading/auto/validator.py`

Double-check hard rules sau khi LLM output. Reject náº¿u vi pháº¡m.

### 2.6 Post-Trade Review & LLM Feedback Loop (Má»›i)

**File liÃªn quan:** `trading/auto/journal.py`, `trading/auto/llm_override_tracker.py`, `trading/auto/prompts.py`

Nháº±m tá»‘i Æ°u hÃ³a hiá»‡u quáº£ giao dá»‹ch vÃ  rÃºt kinh nghiá»‡m tá»« cÃ¡c lá»‡nh thua lá»— hoáº·c cÃ¡c Ä‘á» xuáº¥t bá»‹ tá»« chá»‘i:
1. **Ghi nháº­n lá»—i (Logging Failures)**:
   - CÃ¡c lá»‡nh bá»‹ cáº¯t lá»— (loss trades) hoáº·c cÃ¡c quyáº¿t Ä‘á»‹nh cá»§a LLM bá»‹ bá»™ Validator cháº·n (override/reject) do vi pháº¡m quy táº¯c an toÃ n sáº½ Ä‘Æ°á»£c lÆ°u cáº¥u trÃºc vÃ o `llm_overrides.jsonl` hoáº·c nháº­t kÃ½ giao dá»‹ch (`closed_trades.jsonl`).
2. **Tá»± sá»­a lá»—i (Self-Correction)**:
   - Khi xÃ¢y dá»±ng User Prompt (`prompts.py`), há»‡ thá»‘ng sáº½ tá»± Ä‘á»™ng Ä‘á»c danh sÃ¡ch cÃ¡c lá»‡nh tháº¥t báº¡i gáº§n nháº¥t.
   - CÃ¡c lá»—i nÃ y Ä‘Æ°á»£c Ä‘Æ°a vÃ o pháº§n cáº£nh bÃ¡o ngá»¯ cáº£nh giÃºp LLM tá»± nháº­n diá»‡n sai láº§m trÆ°á»›c Ä‘Ã³ (nhÆ° FOMO, trade ngÆ°á»£c xu hÆ°á»›ng khung lá»›n, hoáº·c Ä‘á»‹nh size quÃ¡ lá»›n) Ä‘á»ƒ khÃ´ng láº·p láº¡i lá»—i cÅ©.

---

## III. EXECUTION LAYER

### 3.1 Bracket Orders (Ä‘Ã£ cÃ³)

**File:** `trading/brackets/okx_bracket.py`

OKX bracket order: entry + take profit + stop loss trong 1 lá»‡nh.

### 3.2 Position Monitor (Ä‘Ã£ cÃ³)

**File:** `trading/auto/monitor.py`

Poll OKX má»—i 30s, check order status, cancel opposite khi 1 side fill, log PnL.

### 3.3 Scheduler (Ä‘Ã£ cÃ³)

**File:** `trading/auto/scheduler.py`

Main loop chÃ­nh:
```
1. Check kill switch
2. Compute regime + confluence
3. Check safety guards (open count, daily loss, capital)
4. If conditions met â†’ LLM brain â†’ validator â†’ bracket order
5. Log to journal
```

### 3.4 Journal (Ä‘Ã£ cÃ³)

**File:** `trading/auto/journal.py`

Trade log: entry, exit, PnL, slippage, reasoning. DÃ¹ng cho kill switch H5.

### 3.5 Alerts (Ä‘Ã£ cÃ³)

**File:** `trading/auto/alerts.py`, `trading/auto/telegram.py`

Telegram alerts cho trade signals, errors, kill switch activation.

### 3.6 Dashboard (Ä‘Ã£ cÃ³)

**File:** `trading/auto/dashboard.py`

FastAPI dashboard cho monitoring.

---

## IV. TRADING RULES â€” Hybrid Rule Framework

ÄÃ¢y lÃ  core cá»§a há»‡ thá»‘ng. Hai-layer rules:

### Layer 1: HARD RULES & SCHEDULER GATES (KhÃ´ng thá»ƒ override)

Äá»ƒ Ä‘áº£m báº£o an toÃ n giao dá»‹ch tuyá»‡t Ä‘á»‘i, há»‡ thá»‘ng thá»±c thi hai táº§ng kiá»ƒm soÃ¡t lá»—i cá»©ng:

#### A. Bá»™ lá»c trÆ°á»›c (Scheduler Pre-Filter Gates - Enforced in `scheduler.py`)
CÃ¡c Ä‘iá»u kiá»‡n an toÃ n kiá»ƒm tra á»Ÿ Ä‘áº§u má»—i chu ká»³ giao dá»‹ch trÆ°á»›c khi gá»i LLM Brain:
* **Max Positions**: Sá»‘ lÆ°á»£ng vá»‹ tháº¿ má»Ÿ cÃ¹ng lÃºc $\ge$ 10 â”€â”€â–º NO TRADE (Skip).
* **Loss Streak**: Bá»‹ 3 lá»‡nh thua liÃªn tiáº¿p (H5) â”€â”€â–º KÃ­ch hoáº¡t Kill Switch dá»«ng há»‡ thá»‘ng.
* **Daily Loss Cap**: Lá»— rÃ²ng trong ngÃ y $\le$ -3% tá»•ng vá»‘n â”€â”€â–º NO TRADE (Skip).
* **Revenge Cooldown**: Äang trong thá»i gian nghá»‰ ngÆ¡i (Cooldown C2) sau má»™t lá»‡nh lá»— â”€â”€â–º NO TRADE (Skip).

#### B. Bá»™ lá»c sau (Validator Post-Decision Gates - Enforced in `validator.py` / `okx_bracket.py`)
Kiá»ƒm tra cáº¥u trÃºc vÃ  tÃ­nh há»£p lá»‡ cá»§a Ä‘á» xuáº¥t lá»‡nh do LLM Brain Ä‘Æ°a ra:
* **H1 (Volatility Cap)**: Cá»±c Ä‘áº¡i biáº¿n Ä‘á»™ng `ATR(14) * 3 > price * 5%` â”€â”€â–º NO TRADE.
* **H2 (News Blackout)**: Náº±m trong khoáº£ng $\pm30$ phÃºt cá»§a tin tá»©c vÄ© mÃ´ quan trá»ng â”€â”€â–º NO TRADE.
* **H3 (Position Size)**: Quy mÃ´ má»™t vá»‹ tháº¿ (Notional value) vÆ°á»£t quÃ¡ 20% tá»•ng vá»‘n â”€â”€â–º Clamp hoáº·c NO TRADE.
* **H4 (RSI Extreme)**: RSI khung ngÃ y $\ge$ 85 cáº¥m Long, RSI khung ngÃ y $\le$ 15 cáº¥m Short.
* **H5 (Leverage Cap)**: ÄÃ²n báº©y yÃªu cáº§u vÆ°á»£t quÃ¡ giá»›i háº¡n (BTC tá»‘i Ä‘a 10x, Altcoins tá»‘i Ä‘a 3x) â”€â”€â–º Clamp hoáº·c NO TRADE.
* **H6 (LLM Confidence)**: Äiá»ƒm tá»± tin cá»§a LLM Brain < 0.40 â”€â”€â–º NO TRADE.
* **H7 (Liquidation Buffer)**: Khoáº£ng cÃ¡ch tá»« giÃ¡ Entry Ä‘áº¿n giÃ¡ thanh lÃ½ (Liquidation Price) nhá» hÆ¡n Ä‘á»‡m an toÃ n (BTC tá»‘i thiá»ƒu 8%, Altcoins tá»‘i thiá»ƒu 25%) â”€â”€â–º NO TRADE.
* **H8 (Funding Blackout)**: VÃ o lá»‡nh trong khoáº£ng $\pm5$ phÃºt quanh thá»i Ä‘iá»ƒm tÃ­nh phÃ­ Funding cá»§a OKX â”€â”€â–º NO TRADE.

* **Quy táº¯c phÃ¢n bá»• vá»‘n Ä‘á»™ng (Dynamic Sizing - H9)**:
  * LLM Confidence $\ge$ 0.85: Cho phÃ©p rá»§i ro **3% - 5%** tá»•ng vá»‘n (tÃ­nh theo khoáº£ng cÃ¡ch Stop Loss).
  * LLM Confidence 0.60 - 0.84: Cho phÃ©p rá»§i ro **1% - 2%** tá»•ng vá»‘n.
  * LLM Confidence 0.40 - 0.59: Cho phÃ©p rá»§i ro **0.5%** tá»•ng vá»‘n.
  * LLM Confidence < 0.40: KhÃ´ng giao dá»‹ch (`no_trade`).

### Layer 2: SOFT RULES (LLM reasoning â€” override Ä‘Æ°á»£c, nhÆ°ng pháº£i giáº£i thÃ­ch)

**S0: Multi-Timeframe Framework & Holding Strategy**
```
Direction TF (1h/4h/D) â†’ bias (UP/DOWN/RANGE/CHOP)
Confirmation TF (15m/30m) â†’ xÃ¡c nháº­n bias
Entry TF (5m/1m) â†’ entry point

NguyÃªn táº¯c: KO trade ngÆ°á»£c Higher TF. 

Chiáº¿n lÆ°á»£c giá»¯ lá»‡nh (Holding Time Strategy):
- Swing Trading: Giá»¯ lá»‡nh kÃ©o dÃ i tá»« vÃ i ngÃ y Ä‘áº¿n 1 tuáº§n Ä‘á»ƒ báº¯t trá»n xu hÆ°á»›ng lá»›n, cháº¥p nháº­n phÃ­ Funding Fee trÃªn thá»‹ trÆ°á»ng Futures.
- Dynamic Exits: TÃ­ch há»£p Ä‘Ã¡nh giÃ¡ Ä‘á»™ng thÃ¡i thá»‹ trÆ°á»ng tá»« LLM Ä‘á»ƒ chá»§ Ä‘á»™ng Ä‘Ã³ng lá»‡nh linh hoáº¡t trÆ°á»›c thá»i háº¡n náº¿u bá»‘i cáº£nh thay Ä‘á»•i xáº¥u.
```

**S1: Moving Averages**
- MA alignment: bullish (9>21>50), bearish (9<21<50), mixed
- Golden/Death cross: MA50 Ã— MA200
- Price vs MA200: >15% overextended â†’ caution

**S2: Support/Resistance**
- Identify: swing highs/lows, round numbers, Fibonacci, order blocks
- Classify price position: at support, at resistance, between, breaking
- Validate breakout: close beyond + volume >1.5x + retest

**S3: Volume / VSA**
- Buying climas: wide spread + high vol + close mid/up â†’ prepare distribution
- Selling climax: wide spread + high vol + close low â†’ prepare accumulation
- Stopping volume: narrow spread + high vol â†’ trend exhaustion
- Volume ratio thresholds: <0.3 skip, 0.3-0.7 weak, 0.7-1.3 normal, 1.3-2.0 elevated, >2.0 climax

**S4: Candlestick Patterns**
- Tier 1 (high): Engulfing at S/R + volume
- Tier 2 (medium): Morning/Evening Star, Three Soldiers/Crows
- Tier 3 (low): Single bar (Doji, Hammer, Shooting Star)
- 2+ patterns + VSA + at S/R = high conviction

**S5: Ichimoku Cloud**
- Price vs Cloud: above (bull), below (bear), in cloud (wait)
- TK cross: bullish/bearish
- Chikou vs Price: above/below
- Decision matrix (9 combinations)

**S6: Oscillators**
- RSI: 6 zones (OB >80, bullish 60-80, neutral bull 50-60, neutral bear 40-50, bearish 20-40, OS <20)
- RSI divergence: regular (reversal) + hidden (continuation)
- MACD: line vs signal, histogram direction, zero line cross
- MACD divergence: positive (reversal up), negative (reversal down)
- Bollinger: %B, bandwidth squeeze/wide, price walking band
- Stochastic: overbought/oversold crossovers

**S7: Confluence (8 categories)**
| Sá»‘ category aligned | Min confidence | Position size cap |
|---|---|---|
| 1-2 | 0.50 | 5% |
| 3-4 | 0.65 | 10% |
| 5-6 | 0.75 | 15% |
| 7-8 | 0.85 | 20% |

Category list: S0 MTF (1.3x), S1 Trend (1.2x), S2 Structure (1.1x), S3 Volume (1.0x), S4 Candlestick (0.8x), S5 Ichimoku (1.1x), S6 Oscillators (0.9x), Sentiment (0.7x)

### Output JSON Format

```json
{
  "decision": "long|short|hold|no_trade",
  "confidence": 0.75,
  "reasoning": "Brief summary",
  "reasoning_detail": {
    "trend": "uptrend", "momentum": "bullish", "volume_conviction": "high",
    "structure": "near_resistance", "sentiment_bias": "bullish",
    "confluence_count": 6, "confluence_of": 8,
    "override_justifications": []
  },
  "indicator_analysis": {
    "multi_timeframe": "bullish_aligned_full",
    "ma_signal": "bullish_aligned", "sr_signal": "near_resistance",
    "vsa_signal": "normal", "candlestick_signal": "bull_engulfing",
    "ichimoku_signal": "bullish_aligned",
    "rsi_macd_consensus": "both_bullish", "bb_signal": "neutral_above_mid",
    "stochastic_signal": "neutral",
    "strongest_signal": "MTF + Ichimoku aligned",
    "weakest_signal": "S/R resistance â€” wait for breakout",
    "overall_verdict": "bullish_biased_with_caution"
  },
  "position_size_pct": 10,
  "stop_loss": 67500.0,
  "take_profit_levels": [68800.0, 69500.0],
  "hard_rules_checked": {
    "h1_volatility_ok": true, "h2_news_blackout_ok": true,
    "h3_position_limit_ok": true, "h4_rsi_extreme_ok": true,
    "h5_loss_streak_ok": true, "h6_confidence_ok": true, "h7_rr_ratio_ok": true
  },
  "invalidates_if": ["Price closes below EMA 50", "Volume drops below 0.5x SMA"]
}
```

---

## V. DEV AUTOPILOT â€” Self-Improving Agent Loop

### Concept

Há»‡ thá»‘ng tá»± Ä‘á»™ng phÃ¡t hiá»‡n gaps, design feature, implement vÃ  test â€” khÃ´ng cáº§n human code tá»«ng dÃ²ng.

### Pipeline

```
Step 1: SCAN (má»—i 12h)
  â”œâ”€â”€ Äá»c codebase structure
  â”œâ”€â”€ Äá»c GitHub issues cá»§a HKUDS/Vibe-Trading
  â”œâ”€â”€ Äá»c changelog + recent news
  â”œâ”€â”€ PhÃ¢n tÃ­ch: "Thiáº¿u tÃ­nh nÄƒng gÃ¬ so vá»›i competitor?"
  â”œâ”€â”€ Output: top 3 feature gaps â†’ pending.md
  â””â”€â”€ Gá»­i notification qua Telegram

Step 2: DESIGN
  â”œâ”€â”€ Agent tá»± Ä‘á»™ng phÃ¢n tÃ­ch vÃ  thiáº¿t káº¿:
  â”‚   â”œâ”€â”€ Files cáº§n thay Ä‘á»•i
  â”‚   â”œâ”€â”€ Data flow diagram
  â”‚   â”œâ”€â”€ Dependencies
  â”‚   â”œâ”€â”€ Risk assessment
  â”‚   â””â”€â”€ Test plan (Ä‘áº·c biá»‡t lÃ  Unit Test báº¯t buá»™c cho pháº§n code má»›i)
  â””â”€â”€ LÆ°u design doc. Trong cháº¿ Ä‘á»™ tá»± trá»‹ hoÃ n toÃ n, Agent tá»± phÃª duyá»‡t thiáº¿t káº¿ Ä‘á»ƒ Ä‘i tiáº¿p.

Step 3: IMPLEMENT
  â”œâ”€â”€ Branch: dev-autopilot/{feature-name}
  â”œâ”€â”€ Implement code
  â”œâ”€â”€ Viáº¿t unit tests (báº¯t buá»™c kÃ¨m theo cho cÃ¡c logic thay Ä‘á»•i)
  â”œâ”€â”€ Cháº¡y pytest
  â”œâ”€â”€ Náº¿u fail â†’ tá»± sá»­a â†’ cháº¡y láº¡i (max 3 láº§n)
  â””â”€â”€ Náº¿u pass â†’ commit + push

Step 4: REVIEW
  â”œâ”€â”€ Táº¡o PR tá»± Ä‘á»™ng
  â”œâ”€â”€ Cháº¡y full test suite (bao gá»“m Unit Test má»›i láº­p)
  â”œâ”€â”€ Náº¿u pass 100% â†’ tá»± Ä‘á»™ng merge PR vÃ  chuáº©n bá»‹ deploy
  â”œâ”€â”€ Náº¿u fail â†’ log error â†’ gá»­i notification qua Telegram
  â””â”€â”€ Update feature status: done.md
```

### Feature Priority (Æ°u tiÃªn implement)

1. **Scanner nÃ¢ng cáº¥p** â€” tÃ­nh Ä‘áº§y Ä‘á»§ indicators (Ichimoku, VSA, candlestick patterns, divergence)
2. **Multi-timeframe framework** â€” S0 integration vÃ o confluence scoring
3. **VSA + Candlestick signals** â€” thÃªm vÃ o system prompt + validator
4. **Arkham on-chain integration** â€” CEX netflow + smart money tracking
5. **Ichimoku decision matrix** â€” thÃªm vÃ o confluence category

### File Layout

```
trading/docs/features/
â”œâ”€â”€ features/
â”‚   â”œâ”€â”€ pending.md         # Danh sÃ¡ch feature cáº§n lÃ m
â”‚   â”œâ”€â”€ in_progress.md     # Feature Ä‘ang implement
â”‚   â”œâ”€â”€ done.md            # Feature Ä‘Ã£ ship
â”‚   â””â”€â”€ {feature}/
â”‚       â”œâ”€â”€ design.md      # Design doc
â”‚       â”œâ”€â”€ branch         # TÃªn branch
â”‚       â””â”€â”€ status         # designing | implementing | testing | done
â””â”€â”€ vibe-dev.skill         # Skill hÆ°á»›ng dáº«n agent dev
```

---

## VI. TÃCH Há»¢P VIBE-TRADING (HKUDS)

### Nhá»¯ng gÃ¬ dÃ¹ng tá»« Vibe-Trading

| ThÃ nh pháº§n | Má»¥c Ä‘Ã­ch | CÃ¡ch tÃ­ch há»£p |
|---|---|---|
| **18 data sources** | OHLCV + fallback chain | Import loader registry |
| **Alpha Zoo (456 factors)** | Feature engineering | Engine lÃ m signal input |
| **Research Autopilot** | Hypothesis â†’ backtest | Gá»i CLI `vibe-trading run` |
| **Backtest engine** | Validate strategy | Composite engine + PIT |
| **MCP tools (36 tools)** | External agent integration | MCP server |
| **10 broker connectors** | Execution | Reuse connector layer |
| **Shadow Account** | Self-diagnostics | PhÃ¢n tÃ­ch lá»‹ch sá»­ trade |

### TÃ­ch há»£p Arkham On-Chain

```json
"arkham_intel": {
  "cex_netflow_24h": { "btc": -15000, "eth": 22000 },
  "smart_money_bias": "bullish",
  "top_holders_change": "accumulating",
  "whale_movements": ["0x... deposited 5K ETH to Binance"]
}
```

ThÃªm Arkham signal vÃ o confluence scoring (category #9 â€” weight 0.8x).

---

## VII. TECH STACK

| Layer | CÃ´ng nghá»‡ | Note |
|---|---|---|
| **Runtime** | Python 3.11+ | Core logic |
| **LLM** | DeepSeek (OpenAI-compatible) | brain.py |
| **Exchange** | OKX (via CCXT) | okx_bracket.py |
| **Data** | Vibe-Trading loaders + custom scanner | 18 sources |
| **Backtest** | Vibe-Trading composite | PIT data |
| **Agent framework** | Hermes Agent | cron, skills, delegation |
| **Notification** | Telegram | alerts.py |
| **Dashboard** | FastAPI | dashboard.py |
| **Dev loop** | Hermes cron + delegate_task | Dev Autopilot |

---

## VIII. ROADMAP

### Phase 1 â€” Core Scanner Upgrade (Æ°u tiÃªn cao nháº¥t)
- [ ] ThÃªm Ä‘áº§y Ä‘á»§ indicators (Ichimoku, VSA, candlestick, divergence)
- [ ] Multi-timeframe scanner (1h, 15m, 5m)
- [ ] Update input JSON format

### Phase 2 â€” Trading Rules Integration
- [ ] Update system prompt vá»›i S0-S7 rules
- [ ] Má»Ÿ rá»™ng validator vá»›i H1-H7
- [ ] Update confluence scoring (8 categories)

### Phase 3 â€” Dev Autopilot
- [ ] Táº¡o vibe-dev skill cho Hermes
- [ ] Feature pipeline (pending â†’ design â†’ implement â†’ test)
- [ ] TÃ­ch há»£p GitHub for PR workflow

### Phase 4 â€” On-Chain + Advanced
- [ ] Arkham API integration
- [ ] Vibe-Trading Alpha Zoo lÃ m signal input
- [ ] Shadow Account diagnostics

---

## IX. FILE STRUCTURE (hiá»‡n táº¡i + cáº§n thÃªm)

```
Trade_V1/
â”œâ”€â”€ trading/docs/features/
â”‚   â””â”€â”€ features/                  # [NEW] Feature pipeline
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ ARCHITECTURE_V2.md         # [NEW] File nÃ y
â”‚   â””â”€â”€ ...
â”œâ”€â”€ trading/
â”‚   â”œâ”€â”€ auto/
â”‚   â”‚   â”œâ”€â”€ brain.py               # LLM brain (cÃ³)
â”‚   â”‚   â”œâ”€â”€ prompts.py             # System prompts (cÃ³, cáº§n update)
â”‚   â”‚   â”œâ”€â”€ validator.py           # Hard rules (cÃ³, cáº§n update)
â”‚   â”‚   â”œâ”€â”€ scheduler.py           # Main loop (cÃ³)
â”‚   â”‚   â”œâ”€â”€ monitor.py             # Position monitor (cÃ³)
â”‚   â”‚   â”œâ”€â”€ journal.py             # Trade log (cÃ³)
â”‚   â”‚   â”œâ”€â”€ alerts.py              # Alerts (cÃ³)
â”‚   â”‚   â”œâ”€â”€ telegram.py            # Telegram (cÃ³)
â”‚   â”‚   â”œâ”€â”€ dashboard.py           # Dashboard (cÃ³)
â”‚   â”‚   â”œâ”€â”€ skills.py              # Skills (cÃ³)
â”‚   â”‚   â””â”€â”€ scanner.py             # [ROADMAP] Scanner module (hiá»‡n tÃ­nh gá»™p trong indicators)
â”‚   â”œâ”€â”€ regime/
â”‚   â”‚   â”œâ”€â”€ regime.py              # Regime detector (cÃ³)
â”‚   â”‚   â””â”€â”€ indicators.py          # Indicators (cÃ³)
â”‚   â”œâ”€â”€ confluence/
â”‚   â”‚   â””â”€â”€ confluence.py          # MTF scoring (cÃ³, lá»™ trÃ¬nh má»Ÿ rá»™ng)
â”‚   â”œâ”€â”€ brackets/
â”‚   â”‚   â””â”€â”€ okx_bracket.py         # OKX orders (cÃ³)
â”‚   â””â”€â”€ api_server.py              # API (cÃ³)
â”œâ”€â”€ README.md
â””â”€â”€ AGENTS.md
```

---

## X. DEVELOPMENT RULES (cho agent code)

1. **Test before commit** â€” Cháº¡y `pytest -x` sau má»—i láº§n sá»­a code
2. **One feature = one branch** â€” Branch name: `dev-autopilot/{feature-name}`
3. **Design before code** â€” Design doc trong `trading/docs/features/{feature}/design.md`
4. **Max 3 retries** â€” Náº¿u test fail 3 láº§n â†’ stop + log + notify
5. **No scope creep** â€” KhÃ´ng sá»­a file ko liÃªn quan Ä‘áº¿n feature
6. **Backward compatible** â€” Ko break existing JSON format
7. **Document everything** â€” Má»—i function cÃ³ docstring, má»—i config cÃ³ comment


