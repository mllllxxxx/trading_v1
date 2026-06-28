# Market Regime Detection

**Mục đích**: Phát hiện "tính cách" hiện tại của thị trường rồi chỉ chọn alpha
phù hợp. Edge thật của trading đến từ việc **dùng đúng alpha cho đúng regime** —
không phải lúc nào cũng dùng 1 alpha.

## Regimes

| Regime | Ý nghĩa | Alphas phù hợp |
|---|---|---|
| **TRENDING_UP** | Uptrend bền vững | Momentum (carhart_mom, alpha101_001) |
| **TRENDING_DOWN** | Downtrend bền vững | Inverse momentum (short only) |
| **RANGING** | Sideways, mean-reverting | Reversal (alpha101 reversal) |
| **HIGH_VOLATILITY** | Biến động cao | Defensive (academic_cma) |
| **MIXED** | Tín hiệu conflict | Value (academic_hml) hoặc nghỉ |

## Indicators

| Indicator | Ý nghĩa | Threshold |
|---|---|---|
| **Hurst exponent** | Trending (>0.5) hay mean-revert (<0.5) | 0.5 là random walk |
| **ADX** | Trend strength | >25 = có trend, >50 = trend rất mạnh |
| **ATR ratio** | Volatility regime | >1.5 = elevated, <0.7 = low |
| **EMA50 slope (5d)** | Trend direction | >0 = up, <0 = down |

## Phân loại regime

Ưu tiên: `HIGH_VOLATILITY > TRENDING > RANGING > MIXED`

```python
if atr_ratio > 1.5:     regime = HIGH_VOLATILITY
elif hurst > 0.55 and adx > 25:
    regime = TRENDING_UP if ema_slope > 0 else TRENDING_DOWN
elif hurst < 0.45:      regime = RANGING
else:                   regime = MIXED
```

## Cách dùng

```powershell
# Default 2 năm daily data
.\trading\regime\run-regime.ps1 -Symbol BTC-USDT

# Khác period
.\trading\regime\run-regime.ps1 -Symbol ETH-USDT -Period 1y

# JSON output cho script khác dùng
.\trading\regime\run-regime.ps1 -Symbol BTC-USDT -Json
```

## Workflow kết hợp với F1 + F2

```
1. Regime check:  .\trading\regime\run-regime.ps1 -Symbol BTC-USDT
   → Trả về regime + list alphas phù hợp

2. Bench alphas được recommend:
   vibe-trading alpha bench --alpha academic_carhart_mom ...

3. Confluence check:  .\trading\confluence\run-confluence.ps1 -Symbol BTC-USDT
   → Xác nhận entry timing

4. Nếu confluence >= MODERATE:
   → .\trading\brackets\run-bracket.ps1 (đặt bracket order)
```

## Ví dụ output

```
============================================================
MARKET REGIME  -  BTC-USDT
Period: 2y    Close: $64014.30
============================================================
Indicators:
  Hurst exponent  : 0.510  (random walk)
  ADX             : 18.3  (weak/no trend)
  ATR ratio       : 1.05  (normal)
  EMA50 slope(5d) : -0.85%
------------------------------------------------------------
REGIME: MIXED
  Conflicting signals - sit out or use defensive alphas
------------------------------------------------------------
Recommended alphas:
  - academic_hml
```

## Giới hạn

- Data source: yfinance daily (OKX có thể lệch nhẹ do rate/feed)
- Hurst tính theo R/S method, DFA sẽ chính xác hơn nhưng chậm hơn
- Regime thay đổi theo thời gian — chạy hàng tuần hoặc trước mỗi trade
- Không nên dùng 1 mình, hãy kết hợp với confluence + bracket order
