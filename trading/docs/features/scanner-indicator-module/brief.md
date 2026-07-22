# Feature: Scanner indicator module mới
Priority: P1
Target branch: dev-autopilot/scanner-indicator-module

## Context
Hiện tại chưa có scanner module riêng tính đầy đủ indicators (Ichimoku, VSA, candlestick patterns, RSI divergence, BB squeeze...). System cần một module fetch OHLCV → compute indicators → output JSON format matching ARCHITECTURE_V2.md section I (Input JSON Structure).

The trading-rules skill defines S0-S7 soft rules requiring specific indicator data:
- S0 (MTF): Direction TF / Confirmation TF / Entry TF structure
- S1 (Trend): MA alignment (SMA, EMA, VWMA), golden/death cross
- S2 (S/R): Support/resistance levels, fib levels, swing points
- S3 (Volume): VSA analysis, volume ratio, spread analysis
- S4 (Candlestick): Single + multi bar pattern detection
- S5 (Ichimoku): Cloud, TK cross, Chikou span
- S6 (Oscillators): RSI + divergence, MACD, Bollinger Bands, Stochastic

## Yêu cầu
- Fetch OHLCV từ OKX API (hoặc data source có sẵn)
- Compute toàn bộ indicators cho các timeframe: 5m, 15m, 1H, 4H
- Output JSON format matching ARCHITECTURE_V2.md section I Input JSON Structure
- Có thể gọi riêng lẻ hoặc tích hợp vào scheduler
- Test coverage: compute indicators chính xác, edge cases

## Files chính
- `trading/auto/scanner.py` — New module: indicator computation
- `trading/auto/scheduler.py` — Tích hợp scanner output vào decision loop

## Done khi
- [ ] `pytest -x` pass — không break existing tests
- [ ] Scanner output JSON matching ARCHITECTURE_V2.md section I
- [ ] All indicators (Ichimoku, VSA, candlestick, RSI div, BB squeeze, Stochastic) implemented
- [ ] Backward compatible: scheduler vẫn chạy được với/không có scanner
