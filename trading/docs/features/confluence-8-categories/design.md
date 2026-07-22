# Design: Mở rộng confluence scoring lên 8 categories

**Feature ID:** confluence-8-categories
**Branch:** `dev-autopilot/confluence-8-categories`
**Status:** designing
**Ref:** `docs/ARCHITECTURE_V2.md` §IV (Soft Rules S0-S7 + Confluence table), `trading/docs/features/confluence-8-categories/brief.md`

---

## 1. Goal

Hiện tại `compute_confluence()` chỉ score theo 1 trục duy nhất (EMA alignment trên 5 TF ≈ S1 trend/momentum) — đó là một phiên bản "đếm TFs thẳng hàng" chứ chưa phải confluence thực sự theo trading-rules skill.

Feature này biến nó thành **8-category confluence scoring**:
- Mỗi category trả lời 1 câu hỏi độc lập: "signal này long, short, hay neutral?"
- Weighted contribution theo ARCHITECTURE_V2.md §IV (S0=1.3x … Sentiment=0.7x).
- Output `confluence_breakdown` + `aligned_categories_count` để LLM dùng thẳng (không phải tự đếm).
- **Backward compatible:** `total_score`, `weighted_score`, `action`, `direction_bias`, `bullish_tfs`, `bearish_tfs`, `timeframes` đều giữ nguyên kiểu & ý nghĩa.

> **Triết lý:** `total_score` (flat -5..+5) vẫn là gate chính trong scheduler (đã wire từ Phase B). Phần 8-category là enrichment bổ sung, KHÔNG thay thế gate cũ — đây là điểm mấu chốt để tránh regression.

---

## 2. Files cần sửa

| File | Loại thay đổi | Mục đích |
|---|---|---|
| `trading/confluence/confluence.py` | **Major refactor** | Thêm 8-category scoring, giữ backward-compat layer |
| `trading/auto/prompts.py` | **Edit** (user prompt) | Render `confluence_breakdown` thay vì tự đếm TF; thêm position-sizing table 8-cat |
| `trading/auto/scheduler.py` | **Edit nhỏ** | Đọc `aligned_categories_count` nếu có, dùng cho log/validator (không bắt buộc) |
| `trading/auto/test_phase_b.py` | **Edit** | Assert thêm fields mới (không break assert cũ) |
| `trading/confluence/test_confluence_8cat.py` | **NEW** | Unit tests cho 8-category logic (stub data, không gọi yfinance) |
| `docs/CONFLUENCE_V2.md` | **NEW** | Mô tả output schema + mapping skill S0-S7 |

**KHÔNG sửa** (out of scope, tránh scope creep):
- `trading/auto/brain.py` — `REQUIRED_KEYS` không liên quan tới confluence schema; LLM parse output riêng.
- `trading/auto/validator.py` — validator enforce hard rules, không thuộc confluence.
- `trading/regime/regime.py` — regime detector tách biệt.

---

## 3. Data Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│  CURRENT (Phase B):                                                    │
│  yfinance OHLCV → score_timeframe (EMA tr+mom) → 5 × {trend,mom}      │
│            → total_score (-5..+5) → action                             │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  NEW (Phase 8-cat):                                                    │
│  yfinance OHLCV                                                        │
│      ├── score_timeframe (giữ nguyên)  → timeframes[15m..1w]            │
│      │         → total_score / weighted_score / bullish_tfs / bearish  │
│      │         (BACKWARD-COMPATIBLE: vẫn là aggregation của score)     │
│      │                                                                 │
│      └── score_categories(df_4h hoặc df_1d tùy signal)                 │
│           ├── S0 MTF bias           (weight 1.3) ─┐                    │
│           ├── S1 Trend/MA enrich    (weight 1.2)  │                    │
│           ├── S2 Structure/SR       (weight 1.1)  │  mỗi cat          │
│           ├── S3 Volume/VSA         (weight 1.0)  │  score:           │
│           ├── S4 Candlestick        (weight 0.8)  │  +1 / -1 / 0      │
│           ├── S5 Ichimoku           (weight 1.1)  │                    │
│           ├── S6 Oscillators        (weight 0.9)  │                    │
│           └── S7 Sentiment          (weight 0.7) ─┘                    │
│                     ↓                                                  │
│            confluence_breakdown: 8 × {score, weight, signal, detail}   │
│            aligned_categories_count: số cat có |score|=1               │
│            suggested_position_size_pct: lookup theo count               │
│            category_weighted_score: Σ (score × weight)                  │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │  Output JSON (merged, backward compatible):              │
        │  • total_score, weighted_score, action (giữ nguyên)      │
        │  • bullish_tfs, bearish_tfs, aligned_tfs, direction_bias│
        │  • timeframes (giữ nguyên)                               │
        │  + confluence_breakdown (NEW)                            │
        │  + aligned_categories_count (NEW)                        │
        │  + category_weighted_score (NEW)                         │
        │  + suggested_position_size_pct (NEW)                     │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
              prompts.build_user_prompt() → render `confluence_breakdown`
                                   │
                                   ▼
                            LLM (DeepSeek)
```

**Điểm quan trọng:** Cả 2 layer (5-TF flat + 8-cat weighted) đều chạy trên cùng 1 OHLCV fetch. `score_categories()` dùng `df_1d` (đủ dài cho swing/structure/vsa) làm canonical timeframe để tính S2-S6. S0 dùng 3-TF aggregate (1d bias + 4h confirm + 1h entry). S7 sentiment optional — nếu chưa wire news API thì trả neutral (0).

---

## 4. Implementation Steps

### Step 1 — Constants & category registry (`confluence.py`)

```python
# Module-level constants
CATEGORY_WEIGHTS = {
    "S0_mtf":      1.3,
    "S1_trend":    1.2,
    "S2_struct":   1.1,
    "S3_volume":   1.0,
    "S4_candle":   0.8,
    "S5_ichimoku": 1.1,
    "S6_oscill":   0.9,
    "S7_sentiment":0.7,
}

# Position sizing lookup theo ARCHITECTURE_V2.md §IV
POSITION_SIZE_BY_ALIGNED = [
    (2, 5),    # 1-2 categories
    (4, 10),   # 3-4
    (6, 15),   # 5-6
    (8, 20),   # 7-8
]
def suggested_size_pct(aligned_count: int) -> int:
    for upper, pct in POSITION_SIZE_BY_ALIGNED:
        if aligned_count <= upper:
            return pct
    return 20
```

### Step 2 — Per-category scorers

Mỗi `score_X(df)` trả về `{"score": +1|0|-1, "signal": "...", "detail": {...}}`. Thiết kế stateless + pure → unit test được.

| Category | Input | Logic | Score |
|---|---|---|---|
| `S0_mtf` | `timeframes` dict (đã có) | Aggregate 3-tier bias (direction 1.3x, conf 1.0x, entry 0.8x) theo dấu tổng hợp | +1 nếu weighted >0, -1 nếu <0, 0 nếu tie |
| `S1_trend` | `df_1d` closes | EMA9/21/50 alignment: 9>21>50 bull, 9<21<50 bear, else neutral | +1/-1/0 |
| `S2_struct` | `df_1d` highs/lows | Nearest support/resistance: price at support (within 1.5×ATR) → +1, at resistance → -1, mid-range → 0 | +1/-1/0 |
| `S3_volume` | `df_1d` (close, volume) | VSA-lite: 5-bar vol ratio + spread. Climax→0 (uncertain), elevated + same direction → +1, divergent → -1 | +1/-1/0 |
| `S4_candle` | last 1-3 bars | Engulfing/morning-star/hammer (bullish pattern at support → +1, bearish at resistance → -1, single doji → 0) | +1/-1/0 |
| `S5_ichimoku` | `df_1d` (26 high/low, 52-period) | Price vs cloud + TK cross + Chikou (majority vote) | +1/-1/0 |
| `S6_oscill` | `df_1d` | RSI zone (40-60 neutral → 0, >60 → +1, <40 → -1) + MACD histogram direction consensus | +1/-1/0 |
| `S7_sentiment` | optional `news_signal` arg | Default 0 nếu không có news module. Khi wire: positive → +1, negative → -1, neutral → 0 | +1/-1/0 |

**Helper functions (reusable):**
```python
def _ema(series, span): ...
def _rsi(close, period=14): ...
def _atr(df, period=14): ...
def _macd(close): ...
def _ichimoku(df): ...
def _support_resistance(df, lookback=50): ...
def _candlestick_pattern(last_3_bars): ...
def _vsa_signal(df, lookback=20): ...
```

### Step 3 — `compute_confluence()` refactor

Cấu trúc mới (giữ nguyên public signature):

```python
def compute_confluence(symbol: str, news_signal: dict | None = None) -> dict[str, Any]:
    # --- Phase B block (giữ nguyên) ---
    timeframes = {}
    for label, interval, period in TIMEFRAMES:
        ...
        timeframes[label] = score_timeframe(df)
        time.sleep(0.3)
    total_score, weighted_score, bullish_tfs, bearish_tfs, aligned_tfs_list = \
        _aggregate_5tf(timeframes)

    # --- Phase 8-cat block (NEW) ---
    df_1d = _fetch_one(symbol, "1d", "2y")   # canonical for structure/vsa/candle
    breakdown = {
        "S0_mtf":       _score_s0_mtf(timeframes),
        "S1_trend":     _score_s1_trend(df_1d),
        "S2_struct":    _score_s2_structure(df_1d),
        "S3_volume":    _score_s3_volume(df_1d),
        "S4_candle":    _score_s4_candlestick(df_1d),
        "S5_ichimoku":  _score_s5_ichimoku(df_1d),
        "S6_oscill":    _score_s6_oscillators(df_1d),
        "S7_sentiment": _score_s7_sentiment(news_signal),
    }
    aligned_count = sum(1 for v in breakdown.values() if v["score"] != 0)
    cat_weighted = sum(v["score"] * v["weight"] for v in breakdown.values())

    action = determine_action(total_score)   # giữ nguyên Phase B logic

    return {
        # --- backward-compatible (Phase B) ---
        "symbol": symbol,
        "timestamp": ...,
        "timeframes": timeframes,
        "total_score": total_score,
        "weighted_score": round(weighted_score, 2),
        "bullish_tfs": bullish_tfs,
        "bearish_tfs": bearish_tfs,
        "aligned_tfs": aligned_tfs_list,
        "direction_bias": ...,
        "action": action,
        # --- new (Phase 8-cat) ---
        "confluence_breakdown": breakdown,
        "aligned_categories_count": aligned_count,
        "category_weighted_score": round(cat_weighted, 2),
        "suggested_position_size_pct": suggested_size_pct(aligned_count),
    }
```

**Backward-compat guarantee:**
- Tất cả key cũ (`total_score`, `weighted_score`, `action`, `bullish_tfs`, `bearish_tfs`, `aligned_tfs`, `direction_bias`, `timeframes`) đều xuất hiện với cùng type và ý nghĩa như Phase B.
- `total_score` vẫn = sum 5-TF score (gate cho scheduler).
- `weighted_score` vẫn = sum(score × tier_weight) của 5 TF — không bị ảnh hưởng bởi 8-cat.
- `confluence_breakdown` là key MỚI, optional downstream — scheduler không bắt buộc đọc.

### Step 4 — `prompts.py` user prompt update

**Trước** (đếm thủ công):
```
## Position sizing by confluence (ap dung)
- 1 TF aligned = 5% capital
- 2-3 TFs aligned = 10% capital
- 4 TFs aligned = 15% capital
- 5/5 TFs aligned = 20% capital (max)
- Hien tai: {bullish_count} TFs long-aligned, {bearish_count} TFs short-aligned
```

**Sau** (8-cat breakdown + recommended size):
```
## Confluence 8-category breakdown (NEW)
- S0 MTF (1.3x): {cd.S0_mtf.score:+d} - {cd.S0_mtf.signal}
- S1 Trend (1.2x): {cd.S1_trend.score:+d} - {cd.S1_trend.signal}
- S2 Structure (1.1x): {cd.S2_struct.score:+d} - {cd.S2_struct.signal}
- S3 Volume (1.0x): {cd.S3_volume.score:+d} - {cd.S3_volume.signal}
- S4 Candlestick (0.8x): {cd.S4_candle.score:+d} - {cd.S4_candle.signal}
- S5 Ichimoku (1.1x): {cd.S5_ichimoku.score:+d} - {cd.S5_ichimoku.signal}
- S6 Oscillators (0.9x): {cd.S6_oscill.score:+d} - {cd.S6_oscill.signal}
- S7 Sentiment (0.7x): {cd.S7_sentiment.score:+d} - {cd.S7_sentiment.signal}
- Aligned categories: {aligned_count}/8 → suggested size {suggested_pct}%
- Category-weighted score: {cat_weighted:+.2f}/7.8

## Position sizing table (theo ARCHITECTURE_V2.md)
- 1-2 cat aligned = 5% capital (probe)
- 3-4 cat aligned = 10% capital (normal)
- 5-6 cat aligned = 15% capital (high confidence)
- 7-8 cat aligned = 20% capital (max)
```

Đồng thời giữ block cũ về 5-TF (vì scheduler vẫn dùng `total_score` làm gate). LLM nhận cả 2 view: gate hiện tại (5-TF flat) + enrichment (8-cat).

### Step 5 — Scheduler touch-up (optional, low-risk)

Thêm 1 dòng log vào journal (không đổi flow):
```python
conf = _run_confluence(current_symbol)
journal.append_decision("confluence", {
    "total_score": conf.get("total_score"),
    "weighted_score": conf.get("weighted_score"),
    "aligned_categories": conf.get("aligned_categories_count"),  # NEW
    "cat_weighted": conf.get("category_weighted_score"),         # NEW
})
```

**KHÔNG đổi** logic gate (`score < MIN_CONFLUENCE`) — đó là decision bám theo Phase B đã ship.

### Step 6 — Render text update

`render_text()` thêm 1 section mới:
```
--- Confluence 8-category ---
S0 MTF       (1.3x):  +1 bullish
S1 Trend     (1.2x):  +1 bullish
...
Aligned: 5/8 → suggested 15% | category-weighted: +2.40/7.8
```

---

## 5. Output JSON Spec (final shape)

```json
{
  "symbol": "BTC-USDT",
  "timestamp": "2026-06-21T10:00:00+00:00",
  "timeframes": { "15m": {...}, "1h": {...}, "4h": {...}, "1d": {...}, "1w": {...} },
  "total_score": 3,
  "weighted_score": 3.6,
  "bullish_tfs": 3,
  "bearish_tfs": 0,
  "aligned_tfs": ["15m", "1h", "4h"],
  "direction_bias": "long",
  "action": { "action": "MODERATE BUY", "color": "YELLOW", ... },
  "confluence_breakdown": {
    "S0_mtf":       {"score":  1, "weight": 1.3, "signal": "bias_long_3tier",       "detail": {"direction": 3, "confirmation": 2, "entry": 1}},
    "S1_trend":     {"score":  1, "weight": 1.2, "signal": "ema_bullish_aligned",   "detail": {"ema9": 68100, "ema21": 67800, "ema50": 67200}},
    "S2_struct":    {"score":  1, "weight": 1.1, "signal": "near_support_bounce",   "detail": {"nearest_support": 67500, "distance_atr": 0.8}},
    "S3_volume":    {"score":  1, "weight": 1.0, "signal": "elevated_confirming",   "detail": {"vol_ratio": 1.4, "spread": "wide"}},
    "S4_candle":    {"score":  0, "weight": 0.8, "signal": "no_pattern",            "detail": {}},
    "S5_ichimoku":  {"score":  1, "weight": 1.1, "signal": "above_cloud_tk_bull",   "detail": {"price_vs_cloud": "above"}},
    "S6_oscill":    {"score":  1, "weight": 0.9, "signal": "rsi_bullish_macd_up",   "detail": {"rsi": 62, "macd_hist_dir": "rising"}},
    "S7_sentiment": {"score":  0, "weight": 0.7, "signal": "no_news_module",        "detail": {}}
  },
  "aligned_categories_count": 5,
  "category_weighted_score": 5.5,
  "suggested_position_size_pct": 15
}
```

---

## 6. Dependencies

### Internal (đã có sẵn)
- `pandas`, `numpy` — used by `score_timeframe` already
- `yfinance` — used by `fetch_timeframe` already

### Internal (cần thêm nhưng minimal)
- Không cần thêm package mới — Ichimoku/RSI/MACD/ATR/SR đều tính được bằng pandas/numpy.

### Future (out of scope cho feature này)
- News sentiment module → S7 hiện trả 0 với `signal: "no_news_module"`. Khi wire xong chỉ cần truyền `news_signal` arg vào `compute_confluence(symbol, news_signal=...)`.
- Arkham on-chain (per ARCHITECTURE_V2.md §VI category #9 weight 0.8x) — phase khác.

### Risk về dependency
- **Thời gian fetch:** Phase B đã có `time.sleep(0.3)` giữa các TF. Thêm 1 fetch `df_1d` (đã có trong TIMEFRAMES) → không tăng latency đáng kể vì có thể reuse `df_1d` từ loop TIMEFRAMES.
- **Test isolation:** yfinance cần internet. Unit test phải mock `fetch_timeframe` hoặc dùng DataFrame fixtures.

---

## 7. Risk & Mitigation

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | **`total_score` thay đổi ý nghĩa** → scheduler gate sai | HIGH (regression) | `total_score` vẫn dùng logic Phase B cũ (5-TF sum), 8-cat là enrichment riêng trong `category_weighted_score`. Test snapshot số liệu cũ trước/sau refactor. |
| R2 | **Score_categories sai logic** → LLM ra quyết định tệ | MEDIUM | Mỗi `score_X` pure function, unit test với DataFrame fixtures. Conservative: khi không chắc chắn → return 0 (neutral), KHÔNG bias theo hướng nào. |
| R3 | **Position sizing sai range** → vượt 20% cap | HIGH | `suggested_position_size_pct` clamp max=20. Validator H3 vẫn enforce ≤20% là lớp bảo vệ cuối. |
| R4 | **Backward compat break** — key cũ mất tích hoặc type đổi | MEDIUM | Test Phase B output schema (assert keys + types) trong `test_phase_b.py`. Snapshot test golden output. |
| R5 | **S7 sentiment = 0 mặc định** → LLM bias "không có sentiment là bearish/bullish" | LOW | Signal string `"no_news_module"` explicit, LLM được nhắc trong prompt "nếu signal=no_news_module thì ignore S7". |
| R6 | **Ichimoku/SR tính chậm trên 2y daily** | LOW | Daily 2y = ~730 bars, computation pandas vectorized < 100ms. Không đáng lo. |
| R7 | **S2 "near support" heuristic sai crypto** | MEDIUM | Dùng 1.5×ATR làm threshold (per trading-rules skill). Test với fixture "near support" và "mid range". |
| R8 | **Prompts token budget vượt** | LOW | 8-cat breakdown ~200 tokens. Hiện user prompt ~600 tokens. Tổng vẫn trong 2K context window của DeepSeek. |
| R9 | **Skill S0-S7 wording không khớp code** | LOW | Code mapping khớp 1:1 với ARCHITECTURE_V2.md §IV. Đặt comment `// skill S0-S7 from trading-rules` cạnh mỗi hàm. |
| R10 | **Migration của callers khác ngoài scheduler** | LOW | `grep "compute_confluence\|total_score\|weighted_score"` confirm chỉ scheduler + prompts + 2 test scripts dùng. Tất cả đều dùng `.get(key, default)` nên key mới không ảnh hưởng. |

---

## 8. Test Plan

### 8.1 Unit tests — `trading/confluence/test_confluence_8cat.py` (NEW)

| Test case | Input | Expected |
|---|---|---|
| `test_s1_trend_bullish` | df_1d với EMA9>21>50 | `score_s1_trend() == +1` |
| `test_s1_trend_bearish` | EMA9<21<50 | `== -1` |
| `test_s1_trend_mixed` | EMA9>21<50 | `== 0` |
| `test_s2_struct_at_support` | close within 1.5×ATR of swing low | `+1` |
| `test_s2_struct_at_resistance` | close within 1.5×ATR of swing high | `-1` |
| `test_s2_struct_midrange` | xa cả 2 | `0` |
| `test_s3_volume_elevated_bull` | vol_ratio=1.4, close>prev, wide spread | `+1` |
| `test_s3_volume_climax` | vol_ratio=2.5, narrow spread | `0` (climax = uncertain) |
| `test_s4_candle_engulfing_at_support` | 2 bars: engulfing + at support | `+1` |
| `test_s4_candle_no_pattern` | 1 bar doji at midrange | `0` |
| `test_s5_ichimoku_above_cloud_bull` | price above cloud, tk_bullish, chikou_above | `+1` |
| `test_s5_ichimoku_in_cloud` | price inside cloud | `0` |
| `test_s6_oscill_rsi_bull_macd_up` | rsi=65, macd_hist rising | `+1` |
| `test_s6_oscill_rsi_overbought` | rsi=85 | `+1` nhưng weighted yếu (chỉ 1 indicator) → vẫn `+1` theo score |
| `test_s7_sentiment_no_news` | news_signal=None | `score==0`, signal="no_news_module" |
| `test_s7_sentiment_positive` | news_signal={"bias":"bullish"} | `+1` |
| `test_s0_mtf_tie` | bullish=2, bearish=2 | `0` |
| `test_s0_mtf_long_bias` | bullish=3, bearish=0 | `+1` |
| `test_suggested_size_pct` | aligned=1 → 5, aligned=4 → 10, aligned=5 → 15, aligned=8 → 20 | Đúng bảng |
| `test_backward_compat_keys` | Call `compute_confluence(symbol)` mock yfinance | Dict có đủ keys: `symbol, timestamp, timeframes, total_score, weighted_score, bullish_tfs, bearish_tfs, aligned_tfs, direction_bias, action, confluence_breakdown, aligned_categories_count, category_weighted_score, suggested_position_size_pct` |
| `test_total_score_unchanged_logic` | Mock 5 TFs với scores [1,1,1,-1,0] | `total_score==2` (giống Phase B) |

### 8.2 Integration tests

- `test_phase_b.py` — extend assert list thêm keys mới; assert `total_score` vẫn đúng (snapshot).
- `test_phase_c.py` — assert `build_user_prompt` không crash khi `confluence_breakdown` có hoặc không.

### 8.3 Manual smoke test

```bash
# Mock mode (no LLM, no real fetch)
python -c "
import sys; sys.path.insert(0, 'trading/confluence')
from confluence import compute_confluence
import json
r = compute_confluence('BTC-USDT')
print(json.dumps({
  'total_score': r['total_score'],
  'weighted_score': r['weighted_score'],
  'aligned_categories_count': r['aligned_categories_count'],
  'category_weighted_score': r['category_weighted_score'],
  'suggested_position_size_pct': r['suggested_position_size_pct'],
  'breakdown_keys': list(r['confluence_breakdown'].keys()),
}, indent=2))
"
```
Verify: `breakdown_keys` = 8 items, all scores ∈ {-1, 0, +1}, `suggested_position_size_pct` ∈ {5,10,15,20}.

### 8.4 Regression check

- `pytest -x trading/` — must pass.
- `pytest -x` (root) — must pass (nếu có).
- Manual check scheduler dry-run: import & instantiate không lỗi.

---

## 9. Migration & Rollback

- **Migration:** Pure additive — không cần data migration. Consumers cũ dùng `.get()` → ignore keys mới → 0-downtime.
- **Rollback:** `git revert` 1 commit là đủ — backward compat đảm bảo không caller nào crash.
- **Feature flag (optional):** thêm env `CONFLUENCE_8CAT_ENABLED=1` (default 1 sau khi stable) để tắt 8-cat block nếu lỗi downstream.

---

## 10. Acceptance Checklist

- [ ] `compute_confluence()` returns đủ 14 keys (6 cũ + 8 mới: 5 hiển thị + 3 NEW thực sự + metadata).
- [ ] `confluence_breakdown` có đúng 8 categories với `score, weight, signal, detail`.
- [ ] `aligned_categories_count ∈ {0..8}`, `suggested_position_size_pct ∈ {5,10,15,20}`.
- [ ] `total_score` không đổi logic Phase B (snapshot test).
- [ ] `pytest -x` pass.
- [ ] `prompts.build_user_prompt` render được cả khi `confluence_breakdown` thiếu (graceful fallback).
- [ ] `render_text` in ra section 8-cat mới.
- [ ] Docs `docs/CONFLUENCE_V2.md` mô tả schema mới.

---

## 11. Out of Scope (ghi rõ để tránh creep)

- News sentiment module thực sự (chỉ placeholder).
- Arkham on-chain (category #9).
- LLM-side schema change (`brain.REQUIRED_KEYS` vẫn `{"action","symbol","reasoning","confidence"}`).
- Backtest lại với data 8-cat (làm ở Phase 3 sau khi có data).
- Thay đổi scheduler gate logic (`MIN_CONFLUENCE`).
- Live trading enable — feature này paper-trade only như cũ.
