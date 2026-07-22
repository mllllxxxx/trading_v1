# Feature: audit-fixes-2026-q2

**Feature ID:** audit-fixes-2026-q2
**Branch:** `dev-autopilot/audit-fixes-2026-q2`
**Story:** US-AUDIT-Q2-2026
**Status:** implementing
**Ref:** Audit report (2026-06-21), `docs/ARCHITECTURE_V2.md` §III (Hard rules H1-H6)

---

## 1. Goal

Sửa 4 Critical + 7 High bugs phát hiện trong audit ngày 2026-06-21. Toàn bộ thay đổi phải:

- **Backward compatible** — không phá vỡ JSON format đang có (positions.json, decisions.jsonl, stats.json, regime/confluence output).
- **Test được** — mỗi fix có 1-2 unit test reproducible.
- **Tối thiểu** — không refactor ngoài vùng bug (tránh scope creep).

## 2. Files ảnh hưởng

| File | Loại | Fix IDs |
|---|---|---|
| `trading/auto/scheduler.py` | Major edit | C1, C2, C3, C4, H2, H3, H5, H6 |
| `trading/auto/journal.py` | Major edit | H1, H4 |
| `trading/api_server.py` | Minor edit | H7 |
| `trading/tests/test_scheduler_safety.py` | NEW | C1, C2, C3, C4, H2, H3, H5, H6 |
| `trading/tests/test_journal_thread_safety.py` | NEW | H1, H4 |
| `trading/tests/test_api_server_status.py` | NEW | H7 |
| `trading/pytest.ini` | NEW | Test discovery |
| `trading/tests/conftest.py` | NEW | sys.path + tmp dir fixture |

## 3. Fix catalog

| ID | File:line | Vấn đề | Fix |
|---|---|---|---|
| **C1** | scheduler.py:384 | `mod` undefined trong Phase 1 fallback → NameError | Import `_okx_bracket` ở top-level, dùng trực tiếp |
| **C2** | scheduler.py:181,198,222 | `KeyError` khi JSON thiếu key | Dùng `.get()` + default + log skip |
| **C3** | scheduler.py:289-310 | Lỗi chứa "deepseek" tự fallback rules-only | Phân biệt rõ "API key missing" vs "API error" |
| **C4** | scheduler.py:332 | `(CAPITAL * pct) / current_price` không guard current_price=0 | Thêm guard `if current_price <= 0: return` |
| **H1** | journal.py:53-86 | Race condition read-modify-write positions/stats | Thêm `threading.Lock` cho 3 writers |
| **H2** | scheduler.py | Multi-symbol loop ghi decisions.jsonl race | Serialize symbol loop qua `_scheduler_lock` |
| **H3** | scheduler.py:155 | Correlation check chỉ check 1 hướng | Tính direction từ confluence score |
| **H4** | journal.py:53-58 | `read_positions` trả `[]` khi corrupt → double exposure | Backup file + re-raise |
| **H5** | scheduler.py:80-84 | SL/TP cố định 1.5%/3% không adapt ATR | Dùng `max(1.5%, ATR%)` làm stop distance |
| **H6** | scheduler.py:331 | LLM position_size_pct không clamp | `min(max(pct, 0), 20)` |
| **H7** | api_server.py:1875 | `stats["total_trades"]` KeyError | Dùng `.get()` nhất quán |

## 4. Implementation Plan

### Batch 1: Foundation (test framework + journal lock)
- Tạo `trading/pytest.ini`, `trading/tests/conftest.py` (tmp dir, isolated DATA_DIR)
- Viết conftest fixture `tmp_journal` (monkeypatch DATA_DIR sang tmp)
- Apply H1: `threading.Lock` cho `add_position`, `remove_position`, `write_stats`, `update_stats_on_close`
- Apply H4: `read_positions` fail-loud + backup corrupt
- Test: `test_journal_thread_safety.py` (4 cases)

### Batch 2: Scheduler safety
- Apply C1: top-level `import brackets.okx_bracket as _okx_bracket`
- Apply C2: 3 guards `.get()` cho conf/regime/close
- Apply C3: refactor fallback logic thành explicit `_classify_llm_error()`
- Apply C4: guard `current_price <= 0`
- Apply H6: clamp position_size_pct
- Test: `test_scheduler_safety.py` (8 cases)

### Batch 3: scheduler concurrency + trading logic
- Apply H2: serialize SYMBOLS loop qua single-thread hoặc lock
- Apply H3: correlation check cả 2 hướng
- Apply H5: ATR-based SL/TP
- Test: thêm cases vào `test_scheduler_safety.py`

### Batch 4: api_server
- Apply H7: `.get("total_trades", 0)` thay `["total_trades"]`
- Test: `test_api_server_status.py`

### Batch 5: verify
- `pytest -x trading/tests/`
- Regression: `python -c "from auto import scheduler"` không crash
- Test net-new: build decision trong journal có đủ field cũ

## 5. Backward compatibility contract

- `positions.json`: schema giữ nguyên (list of dicts với symbol/side/entry/...).
- `decisions.jsonl`: mỗi entry có `ts` + `type` + payload — không xóa type cũ.
- `stats.json`: keys hiện tại (total_trades/wins/losses/...) giữ nguyên.
- `confluence.py` / `regime.py` output JSON: không thay đổi.

Mọi fix đều **additive** (thêm field mới optional) hoặc **defensive** (thêm guard không đổi output khi input hợp lệ).

## 6. Test Plan

| Test class | Cases | Validates |
|---|---|---|
| `TestJournalThreadSafety` | 4 | H1, H4 |
| `TestSchedulerKeyError` | 3 | C2 |
| `TestSchedulerLLMFallback` | 4 | C3 |
| `TestSchedulerDivisionByZero` | 2 | C4 |
| `TestSchedulerModFallback` | 2 | C1 |
| `TestSchedulerSizeClamp` | 2 | H6 |
| `TestSchedulerATR_SL_TP` | 2 | H5 |
| `TestSchedulerCorrelation` | 2 | H3 |
| `TestApiServerStatus` | 2 | H7 |
| **Total** | **23** | All 11 fixes |

Chạy: `pytest -x trading/tests/`

## 7. Risk

| Risk | Mitigation |
|---|---|
| Lock contention gây deadlock | Chỉ lock file I/O; critical section ngắn (<10 LOC) |
| ATR-based SL thay đổi behavior production | Backward compat: nếu ATR thiếu → fallback 1.5%/3% cũ |
| `read_positions` raise thay vì trả [] | Caller (scheduler) đã có try/except `journal.is_killed` → thêm catch `JournalCorruptError` → halt cycle |
| C3 thay đổi trade-flow (silent → abort) | Mục đích là dừng trade khi LLM fail → đây là behavior MONG MUỐN; flag qua journal decision log |

## 8. Out of scope (giữ nguyên)

- 9 Medium / 9 Low / 5 Info findings (sẽ có batch tiếp theo).
- Refactor scheduler thành async.
- Add SQLite (H1 chỉ lock file I/O; chuyển SQLite là story khác).
- Backtest với data audit-fixes.
- Live trading enable.