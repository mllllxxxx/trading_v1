# Multi-Timeframe Confluence

Kỹ thuật kinh điển của prop trader: **một tín hiệu trade chỉ valid khi đa số các
khung thời gian đồng thuận**. Trader retail thường chỉ nhìn 1 chart rồi vào
lệnh → thường xuyên trade ngược xu hướng lớn.

Confluence script này phân tích **5 khung thời gian** (15m, 1h, 4h, 1d, 1w)
và đưa ra điểm tổng hợp từ -5 đến +5.

## Score interpretation

| Total score | Action | Ý nghĩa |
|---|---|---|
| +4 đến +5 | **STRONG BUY** | 4-5/5 TFs bullish — high conviction long |
| +2 đến +3 | **MODERATE BUY** | 3-4/5 TFs bullish — nên giảm size |
| -1 đến +1 | **NO TRADE** | Mixed hoặc neutral — ngồi ngoài |
| -2 đến -3 | **MODERATE SELL** | 3-4/5 TFs bearish |
| -4 đến -5 | **STRONG SELL** | 4-5/5 TFs bearish — high conviction short |

## Cách mỗi timeframe được chấm

Mỗi TF được chấm **+1, 0, hoặc -1** dựa trên:

- **Trend**: EMA50 > EMA200 → UP, ngược lại DOWN
- **Momentum**: close > EMA20 → UP, ngược lại DOWN

Nếu cả 2 cùng chiều → +1 (long) hoặc -1 (short). Nếu conflict → 0.

## Cách dùng

### Từ CLI
```powershell
.\trading\confluence\run-confluence.ps1 -Symbol BTC-USDT
.\trading\confluence\run-confluence.ps1 -Symbol ETH-USDT -Json
```

### Từ Vibe-Trading chat
```
Đọc file confluence.md và tính confluence cho BTC-USDT.
Nếu STRONG BUY -> đề xuất entry + SL/TP theo bracket order.
```

### Test mode
```powershell
.\trading\confluence\test-confluence.ps1 -Symbol BTC-USDT
```

## Lưu ý

- **Data source**: yfinance (free, không cần API key)
- **Time yfinance** ước tính: 5-15 giây cho 5 timeframes
- Symbol OKX (BTC-USDT) tự động convert sang yfinance (BTC-USD)
- Nên chạy confluence TRƯỚC khi vào bracket order, không chạy song song
- Kết hợp với F1 (bracket order): chỉ vào lệnh khi confluence = MODERATE hoặc STRONG

## Ví dụ output

```
============================================================
MTF CONFLUENCE  -  BTC-USDT
============================================================
TF     Trend  Mom   RSI    Close        Score
------------------------------------------------------------
15m    UP     UP    58.3   65234.50     +1
1h     UP     UP    55.1   65234.50     +1
4h     UP     UP    52.8   65234.50     +1
1d     UP     DOWN  48.2   65234.50      0
1w     UP     UP    -      65234.50     +1
------------------------------------------------------------
Total Score: +4  (range -5..+5)
============================================================
[++] STRONG BUY
   4/5 TFs bullish - high conviction long setup
============================================================
```
