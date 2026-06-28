# Design: Scanner Indicator Module

Priority: P1
Target branch: `dev-autopilot/scanner-indicator-module`

---

## 1. Summary

Tạo module `trading/auto/scanner.py` — fetch OHLCV từ OKX (CCXT) → compute đầy đủ indicators → output JSON format theo `ARCHITECTURE_V2.md §I`.

---

## 2. Files Affected

| File | Action | Reason |
|---|---|---|
| `trading/auto/scanner.py` | **NEW** | Scanner class |
| `trading/auto/scheduler.py` | MODIFY | Tích hợp scanner call |
| `trading/regime/indicators.py` | MODIFY | Add `compute_rsi()` + `compute_rsi_divergence()` + `compute_atr()` + `compute_vwma()` |
| `trading/tests/test_scanner.py` | **NEW** | Unit tests |

---

## 3. Architecture

```
scheduler.py
  └── run_once_symbol()
        ├── _run_scanner(symbol)          ← NEW, in-process call
        │     └── Scanner.fetch(symbol, timeframes)
        │           ├── OKX API (ccxt) → OHLCV dict per TF
        │           ├── indicators.compute_indicators(df) per TF
        │           ├── compute additional: RSI, VWMA, ATR, RSI divergence
        │           └── assemble → JSON matching §I format
        ├── _run_confluence(symbol)
        ├── _run_regime(symbol)
        └── LLM brain / bracket placement
```

### Data flow

```
ccxt.fetch_ohlcv()
  → pd.DataFrame (OHLCV)
    → indicators.compute_indicators(df)
        → S/R, VSA, Candlestick, Ichimoku, Oscillators, MA
    → scanner._compute_extra(df)
        → RSI(14), RSI divergence, VWMA(21), ATR(14)
    → scanner._assemble_output(symbol, tf, prices, ti, extra)
        → JSON dict matching §I format
```

---

## 4. Scanner Class Design

```python
class Scanner:
    """Fetch OHLCV → compute indicators → output §I JSON.

    Usage:
        sc = Scanner()
        result = sc.scan_single("BTC-USDT", "5m")
        mtf_result = sc.scan_mtf("BTC-USDT", ["1h", "15m", "5m"])
    """

    def __init__(self, ohlcv_limit: int = 300):
        self.ohlcv_limit = ohlcv_limit
        self._exchange: ccxt.okx | None = None

    def _get_exchange(self) -> ccxt.okx:
        """Lazy-init CCXT OKX client (loads config from .env)."""

    def fetch_ohlcv(self, symbol: str, timeframe: str,
                    limit: int | None = None) -> pd.DataFrame:
        """Fetch OHLCV from OKX, return DataFrame with columns:
        timestamp, Open, High, Low, Close, Volume."""

    # ── Public API ────────────────────────────────────────

    def scan_single(self, symbol: str, timeframe: str = "5m",
                    ohlcv_limit: int | None = None) -> dict:
        """Single-TF scan → full §I JSON."""
        # 1. fetch_ohlcv(symbol, timeframe)
        # 2. indicators.compute_indicators(df)
        # 3. compute extras: RSI, VWMA, ATR, RSI divergence
        # 4. _assemble_output(...) → §I JSON

    def scan_mtf(self, symbol: str,
                 timeframes: list[str] | None = None) -> dict:
        """Multi-TF scan → §1.2 JSON.
        Default TFs: ["1h", "15m", "5m"] (Direction/Confirmation/Entry)."""
        # scan_single() for each TF
        # _assemble_mtf_output(results)

    # ── Internal ──────────────────────────────────────────

    def _compute_prices(self, df: pd.DataFrame) -> dict:
        """Return {current, open, high, low, close, change_24h_pct}."""
        # current = df['Close'].iloc[-1]
        # Nếu có >= 2 bars, change_24h = (close - close_-N) / close_-N

    def _compute_vwma(self, df: pd.DataFrame, period: int = 21) -> float:
        """VWMA = Σ(Close * Volume) / Σ(Volume) over period."""

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Average True Range (already in confluence._atr, port to Scanner)."""

    def _compute_rsi(self, df: pd.DataFrame, period: int = 14) -> dict:
        """Return {value, zone, divergence}.
        zone: overbought/oversold/bullish/bearish/neutral
        divergence: hidden_bull / hidden_bear / regular_bull / regular_bear / none"""

    def _compute_rsi_divergence(self, df: pd.DataFrame,
                                period: int = 14) -> str:
        """Detect RSI divergence on last ~30 bars.
        Regular bullish: price lower low, RSI higher low
        Regular bearish: price higher high, RSI lower high
        Hidden bullish: price higher low, RSI lower low
        Hidden bearish: price lower high, RSI higher high"""

    def _compute_macd_divergence(self, df: pd.DataFrame) -> str:
        """Detect MACD histogram divergence."""

    def _assemble_output(self, symbol: str, timeframe: str,
                         df: pd.DataFrame, ti: dict,
                         extras: dict) -> dict:
        """Map indicators.py output → §I JSON format.

        Mapping:
          indicators.py              →  §I JSON
          ─────────────────────────────────────
          moving_averages.ma9       →  moving_averages.ema_9
          moving_averages.ma21      →  moving_averages.ema_21
          moving_averages.ma50      →  moving_averages.ema_50
          moving_averages.ma200     →  moving_averages.sma_200
          (extras.vwma)             →  moving_averages.vwma_21
          support_resistance         →  structure.support_levels / resistance_levels
          nearest                    →  structure.nearest_support / nearest_resistance
          vsa                        →  volume.{vsa_signal, volume_ratio, bar_type}
          candlestick                →  candlestick.{pattern, reliability}
          ichimoku                   →  ichimoku.{tenkan_sen ... signal}
          oscillators.macd           →  oscillators.macd
          oscillators.bollinger      →  oscillators.bollinger_bands
          oscillators.stochastic     →  oscillators.stochastic
          (extras.rsi)               →  oscillators.rsi_14
          (extras.rsi_divergence)    →  oscillators.rsi_divergence
          (extras.macd_divergence)   →  oscillators.macd_divergence
          (extras.atr)               →  atr_14
        """

    def _assemble_mtf_output(self, results: dict[str, dict]) -> dict:
        """3-TF → §1.2 JSON."""
        # results: {"1h": {...}, "15m": {...}, "5m": {...}}
        # overall_bias derived from direction TF
        # overall_signal derived from confirmation TF
        # entry_zone derived from entry TF (support/resistance band)
```

---

## 5. Output JSON Format

### 5.1 Single TF (matching §I exactly)

```json
{
  "symbol": "BTC-USDT",
  "timestamp": "2026-06-28T10:00:00+07:00",
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
    "macd": { "value": 120.0, "signal": 98.0, "histogram": 22.0,
              "histogram_direction": "rising" },
    "macd_divergence": "none",
    "bollinger_bands": { "upper": 71200.0, "middle": 68100.0, "lower": 65000.0,
      "bandwidth": 0.091, "bandwidth_signal": "squeeze" },
    "stochastic": { "k": 68.0, "d": 62.0, "zone": "neutral" }
  },
  "atr_14": 1200.0
}
```

### 5.2 Multi-TF (matching §1.2)

```json
{
  "symbol": "BTC-USDT",
  "timestamp": "2026-06-28T10:05:00+07:00",
  "timeframes": {
    "1h": { "timeframe": "1h", "bias": "up", "scan": { ... full §I ... } },
    "15m": { "timeframe": "15m", "bias": "up", "scan": { ... } },
    "5m": { "timeframe": "5m", "bias": "neutral", "scan": { ... } }
  },
  "direction_tf": { "timeframe": "1h", "overall_bias": "up" },
  "confirmation_tf": { "timeframe": "15m", "overall_signal": "confirmed" },
  "entry_tf": { "timeframe": "5m", "entry_zone": "68300..68500" }
}
```

---

## 6. New Indicators Needed in `trading/regime/indicators.py`

### 6.1 `compute_rsi(close: pd.Series, period: int = 14) -> float`

Currently RSI is only computed in `confluence.py` inline. Move to `indicators.py` for reuse.

### 6.2 `compute_rsi_divergence(df: pd.DataFrame, period: int = 14) -> str`

Algorithm:
1. Find swing highs/lows on price (last ~30 bars)
2. Find swing highs/lows on RSI
3. Compare:
   - **Regular bullish**: price ↓ lower low, RSI ↑ higher low → reversal up
   - **Regular bearish**: price ↑ higher high, RSI ↓ lower high → reversal down
   - **Hidden bullish**: price ↑ higher low, RSI ↓ lower low → trend continuation
   - **Hidden bearish**: price ↓ lower high, RSI ↑ higher high → trend continuation
4. Return `"regular_bull" | "regular_bear" | "hidden_bull" | "hidden_bear" | "none"`

### 6.3 `compute_macd_divergence(df: pd.DataFrame) -> str`

Compare MACD histogram or MACD line with price:
- Price higher high + MACD lower high → negative divergence (bearish)
- Price lower low + MACD higher low → positive divergence (bullish)

### 6.4 `compute_vwma(close: pd.Series, volume: pd.Series, period: int = 21) -> float`

VWMA = Σ(Close[i] × Volume[i]) / Σ(Volume[i]) over last `period` bars.

### 6.5 `compute_atr(df: pd.DataFrame, period: int = 14) -> float`

Port from `confluence._atr()` to `indicators.py`.

---

## 7. Integration with Scheduler

### 7.1 In-process call (recommended)

```python
# scheduler.py
def _run_scanner(symbol: str, timeframes: list[str] | None = None) -> dict | None:
    try:
        from trading.auto.scanner import Scanner
        sc = Scanner()
        if timeframes and len(timeframes) > 1:
            return sc.scan_mtf(symbol, timeframes)
        return sc.scan_single(symbol)
    except Exception as exc:
        journal.append_decision("scanner_error", {"error": str(exc)})
        return None
```

### 7.2 Integration point in `run_once_symbol`

```python
# After regime + confluence checks, before LLM brain call:
scanner_data = _run_scanner(current_symbol)
if scanner_data:
    # Pass scanner_data into prompts.build_user_prompt()
    # as additional context for LLM brain
    user_prompt = _prompts.build_user_prompt(
        ..., scanner=scanner_data,
    )
```

The scanner runs **before** the LLM brain call in each scheduler cycle. Its output feeds into the LLM user prompt as live indicator context.

### 7.3 Backward compatibility

- Scanner is **optional**: if `ccxt` or OKX config is missing, `_run_scanner()` returns `None` and scheduler continues without it.
- `build_user_prompt()` accepts `scanner=None` and skips scanner section in prompt.
- No existing tests break because nothing references `scanner` yet.

---

## 8. Test Plan

File: `trading/tests/test_scanner.py`

| Test | What it covers |
|---|---|
| `test_scan_single_output_format` | §I JSON keys presence |
| `test_scan_mtf_output_format` | §1.2 JSON structure |
| `test_fetch_ohlcv_columns` | DataFrame has OHLCV columns |
| `test_compute_rsi` | RSI values in [0,100] |
| `test_compute_rsi_divergence` | Each divergence type detectable |
| `test_compute_vwma` | VWMA calculation vs known values |
| `test_compute_atr` | ATR calculation |
| `test_assemble_output_field_types` | All fields are correct types |
| `test_missing_data_handling` | Empty/insufficient DF → graceful None |
| `test_backward_compat_scheduler` | scheduler runs without scanner installed |

Run: `pytest -x trading/tests/test_scanner.py`

---

## 9. Risk Assessment

| Risk | Mitigation |
|---|---|
| CCXT rate limit | Cache OHLCV per symbol/TF for 60s |
| OKX config missing | Scanner returns None → scheduler skips |
| RSI divergence false positives | Require min 2 consecutive bars confirmation |
| Large OHLCV payload | Limit to 300 bars per TF |
| Scheduler slow (multiple TF) | MTF scan only every hour, not every 5 min |

---

## 10. Dependencies

- `ccxt` (already in project via `okx_bracket.py`)
- `pandas`, `numpy` (already in project via `indicators.py`)
- No new pip packages required
