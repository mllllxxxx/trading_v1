# Feature Pipeline — Done

> Lịch sử feature đã hoàn thành.

---

## [P1] audit-fixes-2026-q2 (2026-06-21)
- **Story:** US-AUDIT-Q2-2026
- **Branch:** `dev-autopilot/audit-fixes-2026-q2`
- **Fixed:** 4 Critical + 7 High từ audit ngày 2026-06-21
- **Files changed:**
  - `trading/auto/scheduler.py` — C1, C2, C3, C4, H2, H3, H5, H6
  - `trading/auto/journal.py` — H1, H4
  - `trading/api_server.py` — H7
- **Tests added:** 35 cases (`trading/tests/`)
  - `test_journal_thread_safety.py` (8): RLock + corrupt-JSON halt
  - `test_scheduler_safety.py` (21): LLM classify, KeyError guards, div-by-zero, clamp, ATR SL/TP, correlation, journal halt
  - `test_api_server_status.py` (6): winrate KeyError regression
- **Verification:** `harness-cli story verify US-AUDIT-Q2-2026` → pass (35/35)
- **Backward compat:** positions.json, stats.json, decisions.jsonl schemas unchanged

---

## [P2] audit-fixes-batch2 (2026-06-21)
- **Story:** US-AUDIT-Q2-2026-B2
- **Branch:** `dev-autopilot/audit-fixes-batch2`
- **Fixed:** 8 Medium + 5 Low từ audit
- **Files changed:**
  - `trading/auto/monitor.py` — M1 (TP partial), M2 (heartbeat + fatal catch)
  - `trading/auto/scheduler.py` — M3 (specific except), M5 (entry freshness), M6 (runtime config reload)
  - `trading/auto/brain.py` — L3 (max_tokens param), L6 (retry + exponential backoff)
  - `trading/auto/journal.py` — L1 (ISO 8601 timestamp), L2 (clear_kill_switch OSError)
  - `trading/auto/telegram.py` — M7 (skip malformed updates)
  - `trading/confluence/confluence.py` — M8 (RSI NaN guard)
  - `trading/regime/regime.py` — M4 (indicator try/except)
  - `trading/regime/indicators.py` — L4 (round(0.0) bug)
- **Tests added:** 30 cases (`trading/tests/`)
  - `test_data_quality.py` (8): ISO timestamps, RSI NaN, round(0), kill switch OSError
  - `test_monitor_robustness.py` (6): TP partial-fill, heartbeat, fatal catch
  - `test_resilience.py` (16): runtime reload, freshness, specific except, max_tokens, retry, regime fallback, telegram offset
- **Verification:** `harness-cli story verify US-AUDIT-Q2-2026-B2` → pass (65/65)
- **Backward compat:** timestamp format cải thiện (cũ vẫn parse được); env re-read opt-in

---

## [P1] confluence-8-categories (2026-06-26)
- **Story:** confluence-8-categories
- **Branch:** `dev-autopilot/confluence-8-categories`
- **Fixed:** Mở rộng confluence scoring từ 5-TF lên 8-category weighted system
- **Files changed:**
  - `trading/confluence/confluence.py` — Mở rộng scoring engine thành 8 categories (S0-S7)
  - `trading/auto/prompts.py` — Update user prompt với confluence breakdown và 8-category sizing
  - `trading/auto/scheduler.py` — Update position sizing logic từ suggested size
- **Tests added:** 20 cases (`trading/confluence/test_confluence_8cat.py`)
- **Verification:** `pytest -x confluence/test_confluence_8cat.py` and `pytest -x` (129/129)
- **Backward compat:** Tất cả keys của Phase B được bảo toàn đầy đủ.
