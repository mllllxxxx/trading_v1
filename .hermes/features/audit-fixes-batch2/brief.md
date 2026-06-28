# Brief: audit-fixes-batch2

**Feature ID:** audit-fixes-batch2
**Priority:** P2
**Target branch:** `dev-autopilot/audit-fixes-batch2`
**Story:** US-AUDIT-Q2-2026-B2

## Context

Tiếp theo batch 1 (US-AUDIT-Q2-2026) đã fix 4 Critical + 7 High. Batch 2 xử lý **8 Medium + 5 Low** findings còn lại từ audit 2026-06-21. Tập trung vào robustness (error handling cụ thể, graceful shutdown), data quality (NaN/edge cases, ISO timestamps), và external API resilience (LLM retry).

## Yêu cầu (theo audit IDs)

### Medium (8)
- **M1**: monitor.py — TP partially_filled → close prematurely → PnL sai
- **M2**: monitor.py — `while True` no health-check / graceful shutdown
- **M3**: scheduler.py — bare `except Exception` rộng → nuốt bug thật
- **M4**: regime.py — `np.polyfit` + `compute_indicators` không try/except
- **M5**: scheduler.py — `entry_to_use` từ LLM không kiểm tra freshness vs current_price
- **M6**: scheduler.py — env vars đọc 1 lần lúc import (DAILY_LOSS_CAP_PCT, CAPITAL)
- **M7**: telegram.py — offset bug khi update thiếu `update_id`
- **M8**: confluence.py — RSI có thể NaN khi `gain = loss = 0`

### Low (5)
- **L1**: journal.py — `_now()` không phải ISO 8601 chuẩn (timezone offset thiếu `:`)
- **L2**: journal.py — `clear_kill_switch` không catch OSError
- **L3**: brain.py — `max_tokens` hardcode, không qua parameter
- **L4**: indicators.py — `round(x,2) if x else None` bug khi `x = 0.0` → trả `None`
- **L6**: brain.py — không retry khi LLM fail (network blip = skip 5min cycle)

## Files chính

- `trading/auto/monitor.py` (M1, M2)
- `trading/auto/scheduler.py` (M3, M5, M6)
- `trading/auto/brain.py` (L3, L6)
- `trading/auto/journal.py` (L1, L2)
- `trading/auto/telegram.py` (M7)
- `trading/confluence/confluence.py` (M8)
- `trading/regime/regime.py` (M4)
- `trading/regime/indicators.py` (L4)
- `trading/tests/test_*.py` — bổ sung ~20 cases mới

## Done khi

- [ ] 13 fix applied
- [ ] `pytest -x trading/tests/` pass (35 cũ + ~20 mới)
- [ ] Backward compat: timestamp format cũ vẫn parse được bởi code hiện tại (nếu L1 thay đổi format)
- [ ] Regression: import sạch, no module-level error
- [ ] Trace recorded