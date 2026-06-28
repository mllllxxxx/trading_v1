# Trade_V1 — Hệ Thống Giao Dịch Hybrid Agentic Trading

## Tổng Quan

Hệ thống kết hợp **rules-based** (hard rules không thể override) và **LLM reasoning** (soft rules linh hoạt) để đưa ra quyết định long/short/hold. Chạy hoàn toàn local với LLM nhỏ (DeepSeek-R1-1.5B, Qwen3-1.7B) kết hợp Vibe-Trading (HKUDS) làm nền tảng data + backtesting.

---

## Kiến Trúc Tổng Thể

```
                      ┌──────────────────────────────────────┐
                      │          CRON SCHEDULER              │
                      │         (mỗi 5 phút / 12h)          │
                      └─────────────────┬────────────────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
          ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
          │  SCANNER        │ │  DEV AUTOPILOT  │ │  RESEARCH       │
          │  (5 phút)       │ │  (12h)          │ │  AUTOPILOT      │
          │  Market data    │ │  Tự động phát   │ │  (Vibe-Trading) │
          │  → Indicators   │ │  triển feature  │ │  Hypothesis→Test│
          └────────┬────────┘ └─────────────────┘ └─────────────────┘
                   │
                   ▼
          ┌─────────────────────────────────────────────────────┐
          │              DECISION ENGINE                        │
          │                                                     │
          │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
          │  │ REGIME       │  │ CONFLUENCE   │  │ LLM BRAIN │  │
          │  │ (Hurst, ADX, │  │ (MTF scoring)│  │ (DeepSeek)│  │
          │  │ ATR, EMA50)  │  │              │  │           │  │
          │  └──────────────┘  └──────────────┘  └───────────┘  │
          │                                                     │
          │  ┌──────────────┐  ┌──────────────┐                 │
          │  │ VALIDATOR    │  │ PROMPTS      │                 │
          │  │ (Hard rules) │  │ (System+User)│                 │
          │  └──────────────┘  └──────────────┘                 │
          └─────────────────────────┬───────────────────────────┘
                                    │
                                    ▼
          ┌─────────────────────────────────────────────────────┐
          │              EXECUTION LAYER                        │
          │                                                     │
          │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
          │  │ BRACKET      │  │ MONITOR      │  │ EXCHANGE  │  │
          │  │ (OKX order)  │  │ (Position)   │  │ (CCXT)    │  │
          │  └──────────────┘  └──────────────┘  └───────────┘  │
          │                                                     │
          │  ┌──────────────┐  ┌──────────────┐                 │
          │  │ JOURNAL      │  │ ALERTS       │                 │
          │  │ (Trade log)  │  │ (Telegram)   │                 │
          │  └──────────────┘  └──────────────┘                 │
          └─────────────────────────────────────────────────────┘
```

---

## I. DATA LAYER (Scanner)

### 1.1 Market Scanner (mỗi 5 phút)

**Input:** Symbol list từ config
**Process:**
```
1. Fetch OHLCV từ OKX / Binance / data source
2. Tính toán indicators:
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

### 1.2 Multi-Timeframe Scanner (mỗi giờ)

Tương tự nhưng fetch cho 3 TF:
```json
{
  "direction_tf": { "timeframe": "1h", "overall_bias": "up" },
  "confirmation_tf": { "timeframe": "15m", "overall_signal": "confirmed" },
  "entry_tf": { "timeframe": "5m", "entry_zone": "68300..68500" }
}
```

---

## II. DECISION ENGINE

### 2.1 Market Regime Detector (đã có)

**File:** `trading/regime/regime.py`

Phân loại thị trường thành 5 regime:
| Regime | Ý nghĩa | Chiến lược |
|---|---|---|
| TRENDING_UP | Uptrend mạnh | Momentum, trend following |
| TRENDING_DOWN | Downtrend mạnh | Short momentum |
| RANGING | Sideways, mean-reverting | Range trade, fade extremes |
| HIGH_VOLATILITY | Biến động cao | Reduce size, wide stops |
| MIXED | Tín hiệu mâu thuẫn | NO TRADE |

**Indicators:** Hurst exponent, ADX, ATR ratio, EMA50 slope.

### 2.2 Multi-Timeframe Confluence (đã có, cần mở rộng)

**File:** `trading/confluence/confluence.py`

Hiện tại: EMA50/EMA200 alignment + EMA20 momentum cross 5 TF (15m, 1h, 4h, 1d, 1w).

**Lộ trình (Roadmap)**: Sẽ mở rộng thành 8 category confluence (xem phần IV) khi phát triển các module indicators nâng cao.

### 2.3 LLM Brain (đã có)

**File:** `trading/auto/brain.py`

Gọi LLM mặc định `deepseek-chat` (hoặc thông qua cấu hình `AUTO_LLM_MODEL`) với:
- System prompt: role, hard rules, soft skills, output JSON schema
- User prompt: current market state + open positions + recent PnL

### 2.4 Prompts System (đã có, cần cập nhật)

**File:** `trading/auto/prompts.py`

Hiện tại có hard rules và soft skills. Cần mở rộng (xem phần IV).

### 2.5 Validator (đã có)

**File:** `trading/auto/validator.py`

Double-check hard rules sau khi LLM output. Reject nếu vi phạm.

### 2.6 Post-Trade Review & LLM Feedback Loop (Mới)

**File liên quan:** `trading/auto/journal.py`, `trading/auto/llm_override_tracker.py`, `trading/auto/prompts.py`

Nhằm tối ưu hóa hiệu quả giao dịch và rút kinh nghiệm từ các lệnh thua lỗ hoặc các đề xuất bị từ chối:
1. **Ghi nhận lỗi (Logging Failures)**:
   - Các lệnh bị cắt lỗ (loss trades) hoặc các quyết định của LLM bị bộ Validator chặn (override/reject) do vi phạm quy tắc an toàn sẽ được lưu cấu trúc vào `llm_overrides.jsonl` hoặc nhật ký giao dịch (`closed_trades.jsonl`).
2. **Tự sửa lỗi (Self-Correction)**:
   - Khi xây dựng User Prompt (`prompts.py`), hệ thống sẽ tự động đọc danh sách các lệnh thất bại gần nhất.
   - Các lỗi này được đưa vào phần cảnh báo ngữ cảnh giúp LLM tự nhận diện sai lầm trước đó (như FOMO, trade ngược xu hướng khung lớn, hoặc định size quá lớn) để không lặp lại lỗi cũ.

---

## III. EXECUTION LAYER

### 3.1 Bracket Orders (đã có)

**File:** `trading/brackets/okx_bracket.py`

OKX bracket order: entry + take profit + stop loss trong 1 lệnh.

### 3.2 Position Monitor (đã có)

**File:** `trading/auto/monitor.py`

Poll OKX mỗi 30s, check order status, cancel opposite khi 1 side fill, log PnL.

### 3.3 Scheduler (đã có)

**File:** `trading/auto/scheduler.py`

Main loop chính:
```
1. Check kill switch
2. Compute regime + confluence
3. Check safety guards (open count, daily loss, capital)
4. If conditions met → LLM brain → validator → bracket order
5. Log to journal
```

### 3.4 Journal (đã có)

**File:** `trading/auto/journal.py`

Trade log: entry, exit, PnL, slippage, reasoning. Dùng cho kill switch H5.

### 3.5 Alerts (đã có)

**File:** `trading/auto/alerts.py`, `trading/auto/telegram.py`

Telegram alerts cho trade signals, errors, kill switch activation.

### 3.6 Dashboard (đã có)

**File:** `trading/auto/dashboard.py`

FastAPI dashboard cho monitoring.

---

## IV. TRADING RULES — Hybrid Rule Framework

Đây là core của hệ thống. Hai-layer rules:

### Layer 1: HARD RULES & SCHEDULER GATES (Không thể override)

Để đảm bảo an toàn giao dịch tuyệt đối, hệ thống thực thi hai tầng kiểm soát lỗi cứng:

#### A. Bộ lọc trước (Scheduler Pre-Filter Gates - Enforced in `scheduler.py`)
Các điều kiện an toàn kiểm tra ở đầu mỗi chu kỳ giao dịch trước khi gọi LLM Brain:
* **Max Positions**: Số lượng vị thế mở cùng lúc $\ge$ 10 ──► NO TRADE (Skip).
* **Loss Streak**: Bị 3 lệnh thua liên tiếp (H5) ──► Kích hoạt Kill Switch dừng hệ thống.
* **Daily Loss Cap**: Lỗ ròng trong ngày $\le$ -3% tổng vốn ──► NO TRADE (Skip).
* **Revenge Cooldown**: Đang trong thời gian nghỉ ngơi (Cooldown C2) sau một lệnh lỗ ──► NO TRADE (Skip).

#### B. Bộ lọc sau (Validator Post-Decision Gates - Enforced in `validator.py` / `okx_bracket.py`)
Kiểm tra cấu trúc và tính hợp lệ của đề xuất lệnh do LLM Brain đưa ra:
* **H1 (Volatility Cap)**: Cực đại biến động `ATR(14) * 3 > price * 5%` ──► NO TRADE.
* **H2 (News Blackout)**: Nằm trong khoảng $\pm30$ phút của tin tức vĩ mô quan trọng ──► NO TRADE.
* **H3 (Position Size)**: Quy mô một vị thế (Notional value) vượt quá 20% tổng vốn ──► Clamp hoặc NO TRADE.
* **H4 (RSI Extreme)**: RSI khung ngày $\ge$ 85 cấm Long, RSI khung ngày $\le$ 15 cấm Short.
* **H5 (Leverage Cap)**: Đòn bẩy yêu cầu vượt quá giới hạn (BTC tối đa 10x, Altcoins tối đa 3x) ──► Clamp hoặc NO TRADE.
* **H6 (LLM Confidence)**: Điểm tự tin của LLM Brain < 0.40 ──► NO TRADE.
* **H7 (Liquidation Buffer)**: Khoảng cách từ giá Entry đến giá thanh lý (Liquidation Price) nhỏ hơn đệm an toàn (BTC tối thiểu 8%, Altcoins tối thiểu 25%) ──► NO TRADE.
* **H8 (Funding Blackout)**: Vào lệnh trong khoảng $\pm5$ phút quanh thời điểm tính phí Funding của OKX ──► NO TRADE.

* **Quy tắc phân bổ vốn động (Dynamic Sizing - H9)**:
  * LLM Confidence $\ge$ 0.85: Cho phép rủi ro **3% - 5%** tổng vốn (tính theo khoảng cách Stop Loss).
  * LLM Confidence 0.60 - 0.84: Cho phép rủi ro **1% - 2%** tổng vốn.
  * LLM Confidence 0.40 - 0.59: Cho phép rủi ro **0.5%** tổng vốn.
  * LLM Confidence < 0.40: Không giao dịch (`no_trade`).

### Layer 2: SOFT RULES (LLM reasoning — override được, nhưng phải giải thích)

**S0: Multi-Timeframe Framework & Holding Strategy**
```
Direction TF (1h/4h/D) → bias (UP/DOWN/RANGE/CHOP)
Confirmation TF (15m/30m) → xác nhận bias
Entry TF (5m/1m) → entry point

Nguyên tắc: KO trade ngược Higher TF. 

Chiến lược giữ lệnh (Holding Time Strategy):
- Swing Trading: Giữ lệnh kéo dài từ vài ngày đến 1 tuần để bắt trọn xu hướng lớn, chấp nhận phí Funding Fee trên thị trường Futures.
- Dynamic Exits: Tích hợp đánh giá động thái thị trường từ LLM để chủ động đóng lệnh linh hoạt trước thời hạn nếu bối cảnh thay đổi xấu.
```

**S1: Moving Averages**
- MA alignment: bullish (9>21>50), bearish (9<21<50), mixed
- Golden/Death cross: MA50 × MA200
- Price vs MA200: >15% overextended → caution

**S2: Support/Resistance**
- Identify: swing highs/lows, round numbers, Fibonacci, order blocks
- Classify price position: at support, at resistance, between, breaking
- Validate breakout: close beyond + volume >1.5x + retest

**S3: Volume / VSA**
- Buying climas: wide spread + high vol + close mid/up → prepare distribution
- Selling climax: wide spread + high vol + close low → prepare accumulation
- Stopping volume: narrow spread + high vol → trend exhaustion
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
| Số category aligned | Min confidence | Position size cap |
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
    "weakest_signal": "S/R resistance — wait for breakout",
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

## V. DEV AUTOPILOT — Self-Improving Agent Loop

### Concept

Hệ thống tự động phát hiện gaps, design feature, implement và test — không cần human code từng dòng.

### Pipeline

```
Step 1: SCAN (mỗi 12h)
  ├── Đọc codebase structure
  ├── Đọc GitHub issues của HKUDS/Vibe-Trading
  ├── Đọc changelog + recent news
  ├── Phân tích: "Thiếu tính năng gì so với competitor?"
  ├── Output: top 3 feature gaps → pending.md
  └── Gửi notification qua Telegram

Step 2: DESIGN
  ├── Agent tự động phân tích và thiết kế:
  │   ├── Files cần thay đổi
  │   ├── Data flow diagram
  │   ├── Dependencies
  │   ├── Risk assessment
  │   └── Test plan (đặc biệt là Unit Test bắt buộc cho phần code mới)
  └── Lưu design doc. Trong chế độ tự trị hoàn toàn, Agent tự phê duyệt thiết kế để đi tiếp.

Step 3: IMPLEMENT
  ├── Branch: dev-autopilot/{feature-name}
  ├── Implement code
  ├── Viết unit tests (bắt buộc kèm theo cho các logic thay đổi)
  ├── Chạy pytest
  ├── Nếu fail → tự sửa → chạy lại (max 3 lần)
  └── Nếu pass → commit + push

Step 4: REVIEW
  ├── Tạo PR tự động
  ├── Chạy full test suite (bao gồm Unit Test mới lập)
  ├── Nếu pass 100% → tự động merge PR và chuẩn bị deploy
  ├── Nếu fail → log error → gửi notification qua Telegram
  └── Update feature status: done.md
```

### Feature Priority (ưu tiên implement)

1. **Scanner nâng cấp** — tính đầy đủ indicators (Ichimoku, VSA, candlestick patterns, divergence)
2. **Multi-timeframe framework** — S0 integration vào confluence scoring
3. **VSA + Candlestick signals** — thêm vào system prompt + validator
4. **Arkham on-chain integration** — CEX netflow + smart money tracking
5. **Ichimoku decision matrix** — thêm vào confluence category

### File Layout

```
.hermes/
├── features/
│   ├── pending.md         # Danh sách feature cần làm
│   ├── in_progress.md     # Feature đang implement
│   ├── done.md            # Feature đã ship
│   └── {feature}/
│       ├── design.md      # Design doc
│       ├── branch         # Tên branch
│       └── status         # designing | implementing | testing | done
└── vibe-dev.skill         # Skill hướng dẫn agent dev
```

---

## VI. TÍCH HỢP VIBE-TRADING (HKUDS)

### Những gì dùng từ Vibe-Trading

| Thành phần | Mục đích | Cách tích hợp |
|---|---|---|
| **18 data sources** | OHLCV + fallback chain | Import loader registry |
| **Alpha Zoo (456 factors)** | Feature engineering | Engine làm signal input |
| **Research Autopilot** | Hypothesis → backtest | Gọi CLI `vibe-trading run` |
| **Backtest engine** | Validate strategy | Composite engine + PIT |
| **MCP tools (36 tools)** | External agent integration | MCP server |
| **10 broker connectors** | Execution | Reuse connector layer |
| **Shadow Account** | Self-diagnostics | Phân tích lịch sử trade |

### Tích hợp Arkham On-Chain

```json
"arkham_intel": {
  "cex_netflow_24h": { "btc": -15000, "eth": 22000 },
  "smart_money_bias": "bullish",
  "top_holders_change": "accumulating",
  "whale_movements": ["0x... deposited 5K ETH to Binance"]
}
```

Thêm Arkham signal vào confluence scoring (category #9 — weight 0.8x).

---

## VII. TECH STACK

| Layer | Công nghệ | Note |
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

### Phase 1 — Core Scanner Upgrade (ưu tiên cao nhất)
- [ ] Thêm đầy đủ indicators (Ichimoku, VSA, candlestick, divergence)
- [ ] Multi-timeframe scanner (1h, 15m, 5m)
- [ ] Update input JSON format

### Phase 2 — Trading Rules Integration
- [ ] Update system prompt với S0-S7 rules
- [ ] Mở rộng validator với H1-H7
- [ ] Update confluence scoring (8 categories)

### Phase 3 — Dev Autopilot
- [ ] Tạo vibe-dev skill cho Hermes
- [ ] Feature pipeline (pending → design → implement → test)
- [ ] Tích hợp GitHub for PR workflow

### Phase 4 — On-Chain + Advanced
- [ ] Arkham API integration
- [ ] Vibe-Trading Alpha Zoo làm signal input
- [ ] Shadow Account diagnostics

---

## IX. FILE STRUCTURE (hiện tại + cần thêm)

```
Trade_V1/
├── .hermes/
│   └── features/                  # [NEW] Feature pipeline
├── docs/
│   ├── ARCHITECTURE_V2.md         # [NEW] File này
│   └── ...
├── trading/
│   ├── auto/
│   │   ├── brain.py               # LLM brain (có)
│   │   ├── prompts.py             # System prompts (có, cần update)
│   │   ├── validator.py           # Hard rules (có, cần update)
│   │   ├── scheduler.py           # Main loop (có)
│   │   ├── monitor.py             # Position monitor (có)
│   │   ├── journal.py             # Trade log (có)
│   │   ├── alerts.py              # Alerts (có)
│   │   ├── telegram.py            # Telegram (có)
│   │   ├── dashboard.py           # Dashboard (có)
│   │   ├── skills.py              # Skills (có)
│   │   └── scanner.py             # [ROADMAP] Scanner module (hiện tính gộp trong indicators)
│   ├── regime/
│   │   ├── regime.py              # Regime detector (có)
│   │   └── indicators.py          # Indicators (có)
│   ├── confluence/
│   │   └── confluence.py          # MTF scoring (có, lộ trình mở rộng)
│   ├── brackets/
│   │   └── okx_bracket.py         # OKX orders (có)
│   └── api_server.py              # API (có)
├── README.md
└── AGENTS.md
```

---

## X. DEVELOPMENT RULES (cho agent code)

1. **Test before commit** — Chạy `pytest -x` sau mỗi lần sửa code
2. **One feature = one branch** — Branch name: `dev-autopilot/{feature-name}`
3. **Design before code** — Design doc trong `.hermes/features/{feature}/design.md`
4. **Max 3 retries** — Nếu test fail 3 lần → stop + log + notify
5. **No scope creep** — Không sửa file ko liên quan đến feature
6. **Backward compatible** — Ko break existing JSON format
7. **Document everything** — Mỗi function có docstring, mỗi config có comment
