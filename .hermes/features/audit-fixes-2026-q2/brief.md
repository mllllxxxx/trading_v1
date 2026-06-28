# Brief: audit-fixes-2026-q2

**Feature ID:** audit-fixes-2026-q2
**Priority:** P1
**Target branch:** `dev-autopilot/audit-fixes-2026-q2`
**Story:** US-AUDIT-Q2-2026

## Context

Ngày 2026-06-21 đã audit 25 file Python trong `trading/`. Phát hiện **4 Critical + 7 High** bugs có khả năng gây mất tiền hoặc double-exposure. Toàn bộ bugs nằm trong `trading/auto/scheduler.py`, `trading/auto/journal.py`, `trading/api_server.py`. Đây là batch fix đầu tiên của audit.

## Yêu cầu (từ audit report)

1. **C1**: scheduler.py:384 — `mod` undefined trong Phase 1 fallback → NameError mỗi cycle khi LLM fail.
2. **C2**: scheduler.py:181,198,222 — `KeyError` không guard khi JSON từ confluence/regime thiếu key.
3. **C3**: scheduler.py:289-310 — Lỗi LLM chứa "deepseek" bất kỳ → silent fallback rules-only → mất oversight.
4. **C4**: scheduler.py:332 — `position_size_units = (CAPITAL * pct) / current_price` không guard current_price=0.
5. **H1**: journal.py — race condition file I/O trên positions/stats → mất position trên disk.
6. **H2**: scheduler.py — symbol loop ghi decisions.jsonl đan xen.
7. **H3**: scheduler.py:155 — correlation check chỉ check 1 hướng.
8. **H4**: journal.py:53 — `read_positions` trả `[]` khi corrupt → double exposure.
9. **H5**: scheduler.py:80 — SL/TP cố định 1.5%/3% không adapt ATR.
10. **H6**: scheduler.py:331 — LLM `position_size_pct` không clamp max 20%.
11. **H7**: api_server.py:1875 — `stats["total_trades"]` KeyError khi stats trống.

## Files chính

- `trading/auto/scheduler.py` (8 fixes: C1-C4, H2, H3, H5, H6)
- `trading/auto/journal.py` (2 fixes: H1, H4)
- `trading/api_server.py` (1 fix: H7)
- `trading/tests/` (NEW) — pytest framework + 23 test cases

## Done khi

- [ ] Tất cả 11 fix đã apply, code không phá JSON format cũ
- [ ] `pytest -x trading/tests/` pass (23 cases)
- [ ] Không regression: `python -c "from auto import scheduler, journal, monitor"` import OK
- [ ] `docs/ARCHITECTURE_V2.md` không cần update (fix là defensive, không đổi contract)
- [ ] Trace recorded via `harness-cli trace`