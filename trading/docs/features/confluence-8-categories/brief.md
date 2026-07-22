# Feature: Mở rộng confluence scoring lên 8 categories
Priority: P1
Target branch: dev-autopilot/confluence-8-categories

## Context
Hiện tại `trading/confluence/confluence.py` chỉ scoring dựa trên EMA alignment (trend + momentum) trên 5 TF, tương đương S1 duy nhất. Cần mở rộng thành 8 category confluence scoring theo `trading-rules` skill S7 và `ARCHITECTURE_V2.md` section IV.

Design ref: `ARCHITECTURE_V2.md` section IV (Soft Rules S0-S7 + Confluence S7) và skill `trading-rules`.

## Yêu cầu
- Mở rộng `compute_confluence()` thành 8 categories: S0 (MTF), S1 (Trend/MA), S2 (Structure/SR), S3 (Volume/VSA), S4 (Candlestick), S5 (Ichimoku), S6 (Oscillators), S7 (Sentiment)
- Áp dụng weighted contribution: S0=1.3x, S1=1.2x, S2=1.1x, S3=1.0x, S4=0.8x, S5=1.1x, S6=0.9x, Sentiment=0.7x
- Position sizing: 1-2 categories=5%, 3-4=10%, 5-6=15%, 7-8=20%
- Output JSON: thêm `confluence_breakdown` với từng category score
- Update `prompts.py` user prompt: dùng confluence_breakdown thay vì đếm TF alignment thủ công
- Bảo toàn backward compatibility: `total_score`, `weighted_score`, `action` vẫn giữ nguyên

## Files chính
- `trading/confluence/confluence.py` — Mở rộng scoring engine
- `trading/auto/prompts.py` — Update user prompt với confluence breakdown
- `trading/auto/brain.py` — Review parsing (nếu cần update REQUIRED_KEYS)

## Done khi
- [ ] Code changes implemented
- [ ] `pytest -x` pass — không break existing tests
- [ ] Backward compatible: old fields still present in output
- [ ] `compute_confluence()` returns new fields: `confluence_breakdown`, `aligned_categories_count`
