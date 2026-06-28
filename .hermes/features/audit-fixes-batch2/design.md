# Design: audit-fixes-batch2

**Feature ID:** audit-fixes-batch2
**Branch:** `dev-autopilot/audit-fixes-batch2`
**Story:** US-AUDIT-Q2-2026-B2
**Status:** implementing
**Ref:** Audit report (2026-06-21) — Medium + Low findings

---

## 1. Goal

Sửa 8 Medium + 5 Low findings từ audit batch 1. Tập trung:
- **Robustness**: error handling cụ thể, graceful shutdown
- **Data quality**: NaN/edge cases, ISO timestamps, round(0) bug
- **Resilience**: LLM retry, env re-read

## 2. Files ảnh hưởng

| File | Loại | Fix IDs |
|---|---|---|
| `trading/auto/monitor.py` | Edit | M1, M2 |
| `trading/auto/scheduler.py` | Edit | M3, M5, M6 |
| `trading/auto/brain.py` | Edit | L3, L6 |
| `trading/auto/journal.py` | Edit | L1, L2 |
| `trading/auto/telegram.py` | Edit | M7 |
| `trading/confluence/confluence.py` | Edit | M8 |
| `trading/regime/regime.py` | Edit | M4 |
| `trading/regime/indicators.py` | Edit | L4 |
| `trading/tests/test_monitor_robustness.py` | NEW | M1, M2 |
| `trading/tests/test_data_quality.py` | NEW | M8, L1, L4 |
| `trading/tests/test_resilience.py` | NEW | L6, M3, M7 |
| `trading/tests/test_freshness.py` | NEW | M5, M6 |

## 3. Fix catalog

| ID | File:line | Vấn đề | Fix |
|---|---|---|---|
| **M1** | monitor.py:225-247 | TP partially_filled → close prematurely | Phân biệt `closed` vs `partially_filled`. Chỉ close khi TP `closed` (full) |
| **M2** | monitor.py:280-282 | while True no health check | Thêm heartbeat log mỗi N cycle + catch unexpected exception |
| **M3** | scheduler.py:289-294 | bare except Exception | Phân biệt `ccxt.NetworkError`, `KeyError`, `ValueError`, để safety net cuối |
| **M4** | regime.py:103 + 345 | np.polyfit + compute_indicators no try/except | Wrap với `np.errstate(all='ignore')` + try/except returning default |
| **M5** | scheduler.py:404-410 | entry_to_use freshness | Reject nếu `abs(entry - current_price) / current_price > 0.05` |
| **M6** | scheduler.py:49-50 | env vars static | Wrap trong `_get_runtime_config()` đọc mỗi cycle |
| **M7** | telegram.py:317 | offset bug on missing update_id | Skip update nếu thiếu `update_id` |
| **M8** | confluence.py:104 | RSI NaN | Guard `math.isnan()` → trả 50.0 (neutral) |
| **L1** | journal.py:42 | Timestamp format | Dùng `datetime.now(timezone.utc).isoformat()` |
| **L2** | journal.py:325 | clear_kill_switch OSError | Wrap unlink() với try/except OSError |
| **L3** | brain.py:114 | max_tokens param | Thêm `max_tokens: int | None = None` qua call_brain |
| **L4** | indicators.py:751-752 | round(0.0) bug | `if x is not None else None` thay vì `if x else None` |
| **L6** | brain.py:120 | no LLM retry | Thêm retry decorator: 3 attempts, exponential backoff 1s/2s/4s |

## 4. Implementation Plan

### Batch 1: Data quality + timestamps (M8, L1, L4)
- M8: guard NaN RSI
- L1: ISO 8601 timestamp
- L4: round(0.0) bug

### Batch 2: Monitor robustness (M1, M2)
- M1: distinguish TP closed vs partially_filled
- M2: heartbeat + graceful exception catch

### Batch 3: Scheduler resilience (M3, M5, M6)
- M3: specific exceptions
- M5: entry freshness
- M6: runtime config reload

### Batch 4: Brain + telegram + regime (L3, L6, M7, M4)
- L3: max_tokens param
- L6: retry with exponential backoff
- M7: telegram offset guard
- M4: regime/indicators try/except

### Batch 5: Verify
- `pytest -x trading/tests/` 
- All 35 cũ + ~20 mới pass

## 5. Backward compatibility

- L1: timestamp format thay đổi từ `2026-06-21T09:59:00+0700` → `2026-06-21T09:59:00+07:00`. Both parseable by Python 3.11+. Downstream code dùng string compare vẫn OK (lex order preserved). api_server dùng `replace("Z", "+00:00")` vẫn work.
- M5: rejection mới — nếu LLM thường trả entry xa > 5%, reject. Có thể false positive trong high-vol periods. Acceptable trade-off.
- M6: env vars dynamic — không break gì, chỉ có thể change behavior khi operator restart container.
- L3: max_tokens qua param, default giữ 500. Backward compat.

## 6. Test Plan

| Test class | Cases | Validates |
|---|---|---|
| `TestMonitorTPPartialFill` | 3 | M1 |
| `TestMonitorHeartbeat` | 2 | M2 |
| `TestSpecificExceptions` | 3 | M3 |
| `TestRegimeErrorHandling` | 2 | M4 |
| `TestEntryFreshness` | 3 | M5 |
| `TestRuntimeConfigReload` | 2 | M6 |
| `TestTelegramOffsetGuard` | 2 | M7 |
| `TestRSINaNGuard` | 2 | M8 |
| `TestISOTimestamps` | 2 | L1 |
| `TestKillSwitchClearOSError` | 1 | L2 |
| `TestBrainMaxTokensParam` | 2 | L3 |
| `TestRoundZeroGuard` | 2 | L4 |
| `TestLLMRetry` | 3 | L6 |
| **Total new** | **~29** | |

Chạy: `pytest -x trading/tests/`

## 7. Risk

| Risk | Mitigation |
|---|---|
| L1 timestamp format break dashboard | Verify dashboard chỉ string-compare hoặc parse ISO. Test backward compat. |
| M5 false-positive reject high-vol | Threshold 5% là generous — high-vol BTC có thể move 3-4% trong 5 min |
| L6 retry có thể tăng latency | Exponential backoff 1+2+4 = max 7s overhead. Acceptable. |
| M3 refactor exception handling | Catch cụ thể + 1 safety net `except Exception` cuối cùng |

## 8. Out of scope

- 5 Info findings (cosmetic).
- L8/L9 (not real bugs).
- L5 (already handled by try/except inside _place_bracket_via_script).
- I1-I5 (mostly cosmetic).
- I4 obsolete (C3 fixed original confusing logic).