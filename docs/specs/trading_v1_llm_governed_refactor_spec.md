# Trading V1 — Adaptive Hybrid Rulebook Refactor Spec

## Adaptive hybrid addendum

The approved demo/testnet target profile is `adaptive_hybrid_v1`:

```text
market dossier + retrieved rulebook
  -> deterministic continuous RuleProposal
  -> reject zone: no order and no LLM call
  -> strong zone: explicit deterministic proposal lane
  -> gray zone: required LLM ContextReview (APPROVE/VETO/WAIT, risk 0/0.5/1)
  -> deterministic ticket construction
  -> critic -> verifier -> risk/order compiler -> demo adapter
```

This addendum narrows the LLM role. The LLM does not generate symbol, side,
entry, stop, target, leverage, quantity, or order timestamps. Strategy
conditions are continuous score evidence unless a condition is an actual hard
safety/data/execution rule. The strong lane is not fallback. A gray-zone LLM
failure or budget denial still means HOLD/skip. Live trading stays blocked.

**Mục đích của file này:** đưa trực tiếp cho một coding agent / AI model để sửa repo `mllllxxxx/trading_v1` theo hướng: **rulebook là source of truth, LLM là trader-reasoner đọc rulebook + market context để tạo trade intent, verifier/risk compiler là cổng an toàn cuối cùng trước khi đặt lệnh**.

**Repo mục tiêu:** `https://github.com/mllllxxxx/trading_v1`

**Phạm vi app hiện tại:** app trading thật nằm trong thư mục `trading/`; root repo hiện vẫn mang identity của `repository-harness` nên cần chỉnh lại docs để agent không đọc sai ngữ cảnh.

---

## 0. Nguyên tắc bắt buộc cho coding agent

Trước khi sửa code, đọc các file sau:

```text
README.md
AGENTS.md
trading/README.md
trading/.env.template
trading/docker-compose.yml
trading/Dockerfile
trading/auto/scheduler.py
trading/auto/brain.py
trading/auto/prompts.py
trading/auto/validator.py
trading/auto/skills.py
trading/auto/skills.json
trading/auto/journal.py
trading/confluence/README.md
trading/confluence/confluence.py
trading/regime/regime.py
trading/brackets/okx_bracket.py
trading/brackets/okx_futures_bracket.py
trading/backtest/FINDINGS.md
trading/berkshire_routes.py
```

Không được làm các việc sau:

```text
- Không bật live trading.
- Không xóa OKX_TESTNET / OKX_SANDBOX guard.
- Không commit secret, API key, passphrase, private key, token.
- Không để LLM gọi broker trực tiếp.
- Không để LLM tự quyết quantity thật.
- Không fallback sang rules-only khi mode yêu cầu LLM decision.
- Không bỏ journal/audit trail.
- Không sửa hàng loạt format cả repo nếu không cần thiết.
```

Nếu cần chạy lệnh thử, dùng paper/testnet/dry-run. Live mode phải fail closed.

---

## 1. Mục tiêu kiến trúc cuối cùng

Hiện tại hệ thống gần với mô hình:

```text
confluence/regime pre-filter
        ↓
LLM refinement nếu signal đủ mạnh
        ↓
validator
        ↓
OKX bracket order
```

Mục tiêu cần chuyển thành:

```text
Market data + portfolio state + journal
        ↓
Market Dossier Builder
        ↓
Rulebook Retriever
        ↓
LLM Trader Reasoner
        ↓
LLM Risk Critic
        ↓
Trade Decision Ticket
        ↓
Rule Verifier
        ↓
Risk Compiler / Order Compiler
        ↓
Execution Adapter / Bracket Router
        ↓
Journal + Replay Dataset
```

Diễn giải chính xác:

```text
Rulebook định nghĩa sự thật.
Market dossier mô tả trạng thái thị trường hiện tại.
LLM đọc rulebook + dossier để suy luận và tạo trade intent.
Verifier kiểm tra mọi hard truth bằng code.
Risk compiler mới tính size/order thật.
Execution layer chỉ nhận order đã compile.
Journal ghi lại toàn bộ decision lifecycle.
```

LLM được quyền quyết định:

```text
HOLD
OPEN_LONG
OPEN_SHORT
CLOSE_POSITION
REDUCE_POSITION
REQUEST_MORE_DATA
```

LLM không được quyền:

```text
- Gửi order trực tiếp.
- Override hard rule.
- Tự đặt quantity thật.
- Tự tăng leverage.
- Tự sửa rulebook trong runtime.
- Tự chuyển từ paper sang live.
```

---

## 2. Invariants cần giữ trong toàn bộ refactor

Các invariant này phải có test hoặc ít nhất có code path rõ ràng:

```text
1. LLM timeout => HOLD / skip.
2. LLM invalid JSON sau repair => HOLD / skip.
3. Rule retrieval lỗi => HOLD / skip.
4. Data stale hoặc thiếu close/current_price => HOLD / skip.
5. Verifier lỗi => HOLD / skip.
6. Không có non-HOLD ticket nào thiếu stop/risk plan.
7. Không có order nào thiếu stop-loss.
8. Không có order nào vượt max risk.
9. Không có order nào vượt max position cap.
10. Không có live order nếu OKX_TESTNET/OKX_SANDBOX không đúng.
11. Không có path nào gọi broker trước verifier.
12. Mọi final decision đều được log vào journal.
13. LLM phải cite rule_id/playbook_id có tồn tại trong rulebook.
14. Trong gray zone, `REQUIRE_LLM_DECISION=true` tuyệt đối không fallback sang rules-only execution.
15. Strong rules lane chỉ được phép khi canonical policy chọn `adaptive_hybrid_v1`; đây là explicit lane, không phải fallback.
16. Reject zone không được tiêu hao LLM quota.
17. LLM context review không được tạo hoặc sửa identity, side, price levels, leverage, quantity, hoặc order timestamp.
18. Mọi executable lane vẫn phải qua critic, verifier, compiler và demo/testnet guard.
```

---

## 3. Work package 1 — Sửa project identity ở root repo

### Mục tiêu

Root repo phải cho coding agent biết đây là trading system, không phải repository-harness generic project.

### File cần sửa

```text
README.md
AGENTS.md
trading/README.md
docs/ARCHITECTURE.md hoặc tạo docs/TRADING_PROJECT_OVERVIEW.md
```

### Việc cần làm

Sửa root `README.md` để mở đầu bằng nội dung tương tự:

```md
# trading_v1

This repository contains an AI-assisted paper trading system.
The main application lives in `trading/`.

Read first:
- `trading/README.md`
- `trading/auto/scheduler.py`
- `trading/auto/brain.py`
- `trading/auto/validator.py`
- `trading/confluence/README.md`
- `trading/regime/README.md`

The repository-harness files are supporting agent workflow docs only.
They are not the product itself.
```

Trong `AGENTS.md`, thêm phần local project note:

```md
## Local project note

This repo is not a blank harness repo. The real product is under `trading/`.
Do not start implementation from root harness docs only. Always inspect `trading/README.md` and `trading/auto/` first.
```

Tạo hoặc cập nhật `docs/TRADING_PROJECT_OVERVIEW.md`:

```text
- Current architecture
- Target LLM-governed architecture
- Safety model
- How paper/testnet is enforced
- Decision lifecycle
```

### Acceptance criteria

```text
- Root README không còn nói “no application implementation”.
- Người/AI đọc root repo hiểu ngay app chính nằm trong `trading/`.
- `trading/README.md` vẫn giữ phần quickstart hiện tại nhưng bổ sung target architecture mới.
```

---

## 4. Work package 2 — Fix short/bearish path trong scheduler

### Vấn đề

Confluence docs nói score từ `-5` đến `+5`, trong đó `-2..-3` là moderate sell và `-4..-5` là strong sell. Nhưng scheduler hiện đang dùng điều kiện kiểu:

```python
if score < cfg.min_confluence:
    skip
```

Với `min_confluence=2`, mọi score âm đều bị skip trước khi short được xử lý. Sau đó còn có nhánh skip bearish. Hệ quả: hệ thống gần như long-only dù docs và LLM schema có short.

### File cần sửa

```text
trading/auto/scheduler.py
trading/confluence/README.md
trading/README.md
trading/auto/test_phase_b.py hoặc thêm test mới
trading/auto/test_short_path.py
```

### Hướng sửa

Trong `scheduler.py`, thay logic lọc confluence thành:

```python
if abs(score) < cfg.min_confluence:
    journal.append_decision("skip", {
        "reason": "weak_confluence",
        "score": score,
        "min_required_abs": cfg.min_confluence,
        "symbol": current_symbol,
    })
    return

candidate_direction = "long" if score > 0 else "short"
candidate_side = "buy" if candidate_direction == "long" else "sell"
```

Xóa hoặc thay thế logic kiểu:

```python
if score <= -cfg.min_confluence:
    skip bearish_confluence
```

Regime check nên xử lý direction-aware:

```python
if candidate_direction == "long" and regime_name == "TRENDING_DOWN":
    # hoặc skip, hoặc đưa vào LLM với conflict flag. MVP nên skip để an toàn.
    skip regime_direction_conflict

if candidate_direction == "short" and regime_name == "TRENDING_UP":
    # hoặc skip, hoặc đưa vào LLM với conflict flag. MVP nên skip để an toàn.
    skip regime_direction_conflict
```

Nếu muốn LLM có quyền linh hoạt hơn, có thể cho phép conflict đi vào LLM nhưng bắt buộc giảm confidence/risk. Tuy nhiên giai đoạn đầu nên fail-safe.

Truyền direction vào market context / prompt:

```python
market_ctx["candidate_direction"] = candidate_direction
market_ctx["candidate_side"] = candidate_side
market_ctx["confluence_score"] = score
```

### Test cần thêm

Tạo test với mocked confluence score:

```text
score = +3 => candidate_direction == long
score = -3 => candidate_direction == short
score = +1, min=2 => skip weak_confluence
score = -1, min=2 => skip weak_confluence
```

Nếu chưa dễ unit-test `run_once_symbol`, tách helper:

```python
def classify_confluence_direction(score: int, min_abs: int) -> tuple[bool, str | None, str | None]:
    ...
```

Test helper trước.

### Acceptance criteria

```text
- Score -3 không còn bị skip vì `score < min_confluence`.
- Hệ thống có log rõ candidate_direction=short.
- LLM prompt nhận được candidate_direction.
- Confluence README và trading README không còn ghi chỉ “>= +2 mới trade”; đổi thành “abs(score) >= threshold, score positive = long, score negative = short”.
```

---

## 5. Work package 3 — Chuyển `auto/skills.json` thành rulebook source of truth

### Mục tiêu

`auto/skills.json` hiện chỉ là một file skills đơn giản. Cần chuyển thành rulebook có cấu trúc gồm hard laws, soft policies, playbooks và cases. LLM đọc bản rendered Markdown. Verifier đọc bản machine-readable YAML/JSON. `skills.json` chỉ còn là compiled compatibility artifact.

### File/thư mục cần tạo

```text
trading/rulebook/
  README.md
  __init__.py
  source/
    hard/
      HARD_RISK_001.yaml
      HARD_DATA_001.yaml
      HARD_SPREAD_001.yaml
      HARD_EVENT_001.yaml
      HARD_EXECUTION_001.yaml
      HARD_LLM_001.yaml
    soft/
      SOFT_CRYPTO_001.yaml
      SOFT_FX_001.yaml
      SOFT_REGIME_001.yaml
      SOFT_FUNDING_001.yaml
      SOFT_CORRELATION_001.yaml
    playbooks/
      PB_CRYPTO_TREND_CONTINUATION_001.yaml
      PB_CRYPTO_BREAKOUT_PULLBACK_001.yaml
      PB_CRYPTO_MEAN_REVERSION_001.yaml
      PB_FX_TREND_CONTINUATION_001.yaml
      PB_FX_POST_EVENT_CONTINUATION_001.yaml
    cases/
      CASE_GOOD_TREND_LONG_001.yaml
      CASE_BAD_CHASE_BREAKOUT_001.yaml
      CASE_BAD_FUNDING_OVERHEATED_001.yaml
  rendered/
    hard/
    soft/
    playbooks/
    cases/
  compiled/
    skills.json
    rule_index.json
  compile_rulebook.py
  schema.py
```

### File cần sửa

```text
trading/auto/skills.py
trading/auto/skills.json
trading/auto/prompts.py
trading/auto/validator.py
trading/auto/scheduler.py
trading/README.md
trading/Dockerfile
```

### Schema cho hard rule

Ví dụ `trading/rulebook/source/hard/HARD_RISK_001.yaml`:

```yaml
id: HARD_RISK_001
type: hard_constraint
name: Max risk per trade
scope: all_markets
severity: reject_order
description: "No trade may risk more than the configured maximum risk per trade."
params:
  max_risk_pct_equity: 0.01
llm_guidance: |
  This rule is absolute. If your desired setup requires more risk, return HOLD or reduce risk.
  Do not override this rule because of high confidence.
examples:
  valid:
    - "Risking 0.4% equity on BTCUSDT with defined stop."
  invalid:
    - "Risking 1.5% equity when max is 1.0%."
```

Ví dụ `HARD_LLM_001.yaml`:

```yaml
id: HARD_LLM_001
type: hard_constraint
name: LLM must cite rulebook
scope: all_markets
severity: reject_order
description: "Any non-HOLD decision must cite at least one playbook_id and at least two hard/soft rule IDs that exist in the rulebook."
params:
  require_playbook_for_non_hold: true
  min_rule_citations_for_non_hold: 2
llm_guidance: |
  If no playbook fits the current context, return HOLD.
```

### Schema cho soft policy

Ví dụ `SOFT_FUNDING_001.yaml`:

```yaml
id: SOFT_FUNDING_001
type: soft_policy
market: crypto
name: Avoid overheated funding
weight: 0.7
description: "Long crypto breakouts are lower quality when funding is already overheated."
llm_guidance: |
  If funding is elevated, prefer HOLD, reduced risk, or wait for retest.
  This is not an absolute ban unless a hard funding rule is triggered.
```

### Schema cho playbook

Ví dụ `PB_CRYPTO_TREND_CONTINUATION_001.yaml`:

```yaml
id: PB_CRYPTO_TREND_CONTINUATION_001
type: playbook
market: crypto
name: Crypto trend continuation
timeframes: ["15m", "1h", "4h", "1d"]
regimes: ["TRENDING_UP", "TRENDING_DOWN"]
directions: ["long", "short"]
tags: ["trend", "continuation", "confluence", "pullback"]
required_hard_rules:
  - HARD_RISK_001
  - HARD_DATA_001
  - HARD_SPREAD_001
  - HARD_LLM_001
preferred_soft_rules:
  - SOFT_REGIME_001
  - SOFT_FUNDING_001
  - SOFT_CORRELATION_001
setup_conditions: |
  Use when multi-timeframe confluence and regime point in the same direction.
  Prefer entries on pullback/retest instead of chasing extended candles.
invalidation: |
  Setup is invalid if price closes back through the structure base, volatility becomes abnormal,
  spread becomes abnormal, or funding/risk conditions deteriorate.
entry_guidance: |
  Prefer limit near retest/EMA area. Market entry allowed only when entry drift is within policy.
risk_guidance: |
  Use defined stop below/above structure or ATR-derived stop. Never exceed hard risk limits.
avoid_when: |
  Avoid when higher timeframes conflict, data quality is low, or correlation exposure is already high.
```

### Compiler behavior

`compile_rulebook.py` phải:

```text
1. Load YAML files from source.
2. Validate required fields.
3. Check ID uniqueness.
4. Check playbook required_hard_rules exist.
5. Render Markdown files for LLM.
6. Produce `compiled/rule_index.json`.
7. Produce `compiled/skills.json` for backward compatibility.
```

Không cần vector database ở bước này. Metadata filter deterministic là đủ.

### Acceptance criteria

```text
- `python trading/rulebook/compile_rulebook.py` chạy được.
- `compiled/rule_index.json` có tất cả hard/soft/playbook/case IDs.
- `auto/skills.py` load từ `rulebook/compiled/skills.json` hoặc fallback rõ ràng.
- `auto/skills.json` không còn là source chính; nếu còn giữ thì ghi rõ “generated/compatibility”.
- LLM prompt không còn nhét skills thô; prompt nhận rule snippets/playbook snippets có ID rõ ràng.
```

---

## 6. Work package 4 — Tạo Market Dossier Builder

### Mục tiêu

LLM không nên tự tính chỉ báo từ raw candles. Nó phải nhận market dossier đã chuẩn hóa từ confluence, regime, portfolio, journal, execution state và data quality.

### File cần tạo

```text
trading/auto/market_dossier.py
trading/auto/test_market_dossier.py
```

### File cần sửa

```text
trading/auto/scheduler.py
trading/auto/prompts.py
trading/auto/validator.py
trading/auto/journal.py
```

### Dossier schema đề xuất

```python
MarketDossier = {
    "schema_version": "market_dossier.v1",
    "symbol": "BTC-USDT",
    "market": "crypto",
    "trade_mode": "spot|futures|forex_paper|forex_live",
    "timestamp_utc": "...",
    "current_price": 0.0,
    "candidate_direction": "long|short|none",
    "candidate_side": "buy|sell|none",
    "confluence": {
        "total_score": 0,
        "threshold_abs": 3,
        "timeframes": {},
    },
    "regime": {
        "name": "TRENDING_UP|TRENDING_DOWN|RANGING|HIGH_VOLATILITY|MIXED|CHOPPY",
        "indicators": {},
    },
    "risk_state": {
        "capital": 0.0,
        "daily_pnl": 0.0,
        "daily_loss_cap_pct": 0.03,
        "open_positions_count": 0,
        "max_open_positions": 3,
        "same_direction_positions": 0,
        "drawdown_pct": 0.0,
        "risk_multiplier": 1.0,
    },
    "execution_state": {
        "testnet": True,
        "spread_state": "normal|wide|unknown",
        "entry_freshness_max_pct": 0.05,
    },
    "data_quality": {
        "grade": "A|B|C",
        "stale": False,
        "missing_fields": [],
        "warnings": [],
    },
    "recent_journal": {
        "recent_closed_trades": [],
        "cooldown_active": False,
        "loss_streak": 0,
    }
}
```

### Data quality rules

Fail closed nếu:

```text
- current_price missing hoặc <= 0.
- confluence total_score missing.
- regime missing.
- journal corrupt.
- data timestamp quá cũ nếu timestamp có sẵn.
```

Nếu data không đủ để trade nhưng vẫn đủ để ghi log, set:

```json
{"data_quality": {"grade": "C", "stale": true}}
```

LLM nhận grade C thì phải HOLD/REQUEST_MORE_DATA.

### Acceptance criteria

```text
- `build_market_dossier(...)` trả JSON serializable.
- Không có LLM prompt nào phải tự suy luận từ raw `regime`/`confluence` lộn xộn.
- Scheduler log dossier hash hoặc snapshot id.
- Test cover missing score, missing close, corrupt journal, negative price.
```

---

## 7. Work package 5 — Rule Retriever deterministic

### Mục tiêu

Khi có dossier, hệ thống lấy đúng hard rules + soft policies + playbooks/cases liên quan. Không nhét toàn bộ rulebook vào prompt.

### File cần tạo

```text
trading/auto/rule_retriever.py
trading/auto/test_rule_retriever.py
```

### Behavior

Input:

```python
retrieve_rules(dossier: dict) -> dict
```

Output:

```python
{
  "mandatory_hard_rules": [
    {"id": "HARD_RISK_001", "markdown": "..."},
    {"id": "HARD_DATA_001", "markdown": "..."}
  ],
  "candidate_playbooks": [
    {"id": "PB_CRYPTO_TREND_CONTINUATION_001", "markdown": "...", "score": 0.92}
  ],
  "soft_policies": [
    {"id": "SOFT_FUNDING_001", "markdown": "..."}
  ],
  "case_memory": [
    {"id": "CASE_BAD_CHASE_BREAKOUT_001", "markdown": "..."}
  ],
  "all_rule_ids": ["..."]
}
```

Deterministic retrieval logic:

```text
1. Always include hard rules: risk, data, spread/execution, LLM citation, live/testnet.
2. Filter playbooks by market, regime, direction, timeframe if metadata exists.
3. Include soft policies by market and tags.
4. Include 1-3 cases matching market + direction + regime.
5. If no playbook matches, return empty playbooks; LLM must HOLD.
```

### Acceptance criteria

```text
- Crypto trend dossier retrieves crypto trend playbook, not forex post-event playbook.
- Short trend retrieves a playbook that supports `short` direction.
- Missing rulebook index => fail closed, no trade.
- All returned IDs exist in `compiled/rule_index.json`.
```

---

## 8. Work package 6 — Trade Decision Ticket schema

### Mục tiêu

Thay output LLM đơn giản hiện tại bằng ticket có cấu trúc, cite rulebook và tách trade intent khỏi order thật.

### File cần tạo

```text
trading/auto/decision_schema.py
trading/auto/test_decision_schema.py
```

### File cần sửa

```text
trading/auto/brain.py
trading/auto/prompts.py
trading/auto/validator.py
trading/auto/scheduler.py
trading/auto/dashboard.py nếu hiển thị LLM decision
```

### Schema v1

```python
VALID_ACTIONS = {
    "HOLD",
    "OPEN_LONG",
    "OPEN_SHORT",
    "CLOSE_POSITION",
    "REDUCE_POSITION",
    "REQUEST_MORE_DATA",
}

TRADE_DECISION_TICKET_REQUIRED = {
    "schema_version",
    "decision_id",
    "timestamp_utc",
    "action",
    "symbol",
    "market",
    "data_quality",
    "confidence",
    "rule_citations",
    "thesis",
    "reasoning_summary",
}
```

Non-HOLD actions require:

```text
- playbook_id
- entry_plan
- risk_plan
- invalidation_conditions
- at least 2 rule citations
```

Ticket JSON mẫu:

```json
{
  "schema_version": "trade_decision.v1",
  "decision_id": "2026-06-28T10:15:00Z_BTC-USDT_001",
  "timestamp_utc": "2026-06-28T10:15:00Z",
  "action": "OPEN_LONG",
  "symbol": "BTC-USDT",
  "market": "crypto",
  "candidate_direction_from_rules": "long",
  "playbook_id": "PB_CRYPTO_TREND_CONTINUATION_001",
  "rule_citations": [
    "HARD_RISK_001",
    "HARD_DATA_001",
    "HARD_LLM_001",
    "SOFT_REGIME_001"
  ],
  "data_quality": "A",
  "market_regime": "TRENDING_UP",
  "thesis": "Multi-timeframe confluence and regime are aligned. The setup matches trend continuation.",
  "entry_plan": {
    "entry_type": "limit_or_current",
    "entry_reference": "near current price if drift <= policy",
    "chase_market": false
  },
  "risk_plan": {
    "risk_pct_equity": 0.005,
    "stop_logic": "below recent swing or ATR-derived level",
    "take_profit_logic": "minimum 1.2R, prefer 2R where structure allows"
  },
  "invalidation_conditions": [
    "Regime flips to CHOPPY/MIXED",
    "Price closes through structure base",
    "Spread or execution data becomes abnormal"
  ],
  "confidence": 0.64,
  "reasoning_summary": "Valid but not exceptional setup; use reduced risk if volatility rises."
}
```

### Validation behavior

`decision_schema.py` phải có function:

```python
def validate_trade_decision_ticket(ticket: dict, *, known_rule_ids: set[str]) -> tuple[bool, list[str]]:
    ...
```

Check:

```text
- action enum hợp lệ.
- confidence trong [0,1].
- data_quality trong A/B/C.
- rule_citations là list và tất cả rule_id tồn tại.
- non-HOLD phải có playbook_id tồn tại.
- non-HOLD phải có risk_plan.risk_pct_equity > 0.
- non-HOLD phải có invalidation_conditions.
- action OPEN_LONG/OPEN_SHORT phải khớp side hợp lệ.
```

### Backward compatibility

Trong giai đoạn chuyển tiếp, `brain.py` có thể map legacy actions:

```text
long => OPEN_LONG
short => OPEN_SHORT
hold/no_trade => HOLD
```

Nhưng prompt mới phải yêu cầu schema mới.

### Acceptance criteria

```text
- LLM output thiếu rule_citations bị reject.
- LLM output cite rule không tồn tại bị reject.
- LLM output OPEN_LONG không có risk_plan bị reject.
- HOLD ticket không cần playbook_id nhưng vẫn phải có reasoning_summary.
```

---

## 9. Work package 7 — Prompt refactor: LLM là trader-reasoner đọc rulebook

### Mục tiêu

Prompt hiện tại phải chuyển từ “paper trading assistant + skills” sang “constrained trader reasoner + rulebook source of truth”.

### File cần sửa

```text
trading/auto/prompts.py
trading/auto/brain.py
trading/auto/test_llm_full.py
trading/auto/test_hold.py
```

### System prompt mới

Nội dung hệ thống nên tương tự:

```text
You are a constrained trading decision agent.

You may reason about market context, select a playbook, and produce a trade decision ticket.
The provided Rulebook is the source of truth.

You may only choose one action:
HOLD, OPEN_LONG, OPEN_SHORT, CLOSE_POSITION, REDUCE_POSITION, REQUEST_MORE_DATA.

You must cite rule IDs and playbook IDs that support your decision.
If no playbook fits, return HOLD.
If a hard rule is violated, return HOLD.
If data_quality is C, return HOLD or REQUEST_MORE_DATA.
You are not allowed to invent rules.
You are not allowed to override hard constraints.
You are not allowed to change account-level risk limits.
You are not allowed to place orders.

Return only valid JSON matching the TradeDecisionTicket schema.
Do not include chain-of-thought. Use `reasoning_summary` only.
```

### User prompt structure

User prompt nên gồm:

```text
1. TradeDecisionTicket JSON schema.
2. Market dossier JSON.
3. Retrieved hard rules.
4. Retrieved playbooks.
5. Retrieved soft policies.
6. Case memory.
7. Current portfolio/open positions.
8. Recent journal summary.
9. Instruction: output only JSON.
```

Không nhét raw logs quá dài. Cắt context hợp lý.

### Repair prompt

Nếu JSON invalid, gọi một repair prompt duy nhất:

```text
Your previous output was invalid JSON or did not match the schema.
Return only corrected JSON. Do not change the trading decision unless required to satisfy schema/hard rules.
Validation errors:
...
```

Nếu repair vẫn lỗi => HOLD/skip.

### Acceptance criteria

```text
- Prompt luôn chứa rule IDs cụ thể.
- Prompt không còn yêu cầu “mention at least one soft skill” dạng văn bản mơ hồ; thay bằng rule_citations.
- LLM output có schema_version trade_decision.v1.
- Output parser không cần bóc prose nếu response_format hoạt động, nhưng vẫn có fallback parser.
```

---

## 10. Work package 8 — Provider-agnostic LLM client + local model support

### Mục tiêu

Hiện `brain.py` hard-wire DeepSeek key/base URL. Cần hỗ trợ DeepSeek và local OpenAI-compatible providers như Ollama/LM Studio/vLLM.

### File cần sửa

```text
trading/auto/brain.py
trading/.env.template
trading/docker-compose.yml
trading/Dockerfile
trading/README.md
```

### Env vars mới

Thêm vào `.env.template`:

```env
# -------- LLM provider --------------------------------------------------
# Supported: deepseek, ollama, lmstudio, openai_compatible
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_TIMEOUT_S=60
LLM_MAX_TOKENS=2000
LLM_TEMPERATURE=0.1
LLM_REQUIRE_JSON=true
LLM_SEND_RESPONSE_FORMAT=true
LLM_REASONING_EFFORT=

# Backward compatibility with old DeepSeek config
AUTO_LLM_MODEL=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

Thêm autonomy guards:

```env
AUTONOMY_MODE=paper
REQUIRE_LLM_DECISION=true
FAIL_CLOSED_ON_LLM_ERROR=true
FAIL_CLOSED_ON_DATA_ERROR=true
ENABLE_RULES_ONLY_FALLBACK=false
AUTO_ALLOW_SHORTS=true
```

### `brain.py` behavior

Refactor `_get_client()`:

```python
def _resolve_llm_config() -> dict:
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()

    if provider == "deepseek":
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        model = os.getenv("LLM_MODEL") or os.getenv("AUTO_LLM_MODEL") or "deepseek-chat"
    elif provider in ("ollama", "lmstudio", "openai_compatible"):
        base_url = os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
        api_key = os.getenv("LLM_API_KEY", "ollama")
        model = os.getenv("LLM_MODEL", "qwen2.5:3b")
    else:
        raise BrainError(f"Unsupported LLM_PROVIDER={provider}")

    if not api_key:
        raise BrainError("LLM API key missing")

    return {...}
```

Không gửi `reasoning_effort` cho Ollama/local nếu provider không hỗ trợ:

```python
if provider == "deepseek" and reasoning_effort in ("low", "medium", "high"):
    api_kwargs["reasoning_effort"] = reasoning_effort
```

`response_format` nên configurable:

```python
if os.getenv("LLM_SEND_RESPONSE_FORMAT", "true").lower() == "true":
    api_kwargs["response_format"] = {"type": "json_object"}
```

### Docker compose

Trong `docker-compose.yml`, nếu chạy Ollama trên host, thêm:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Và env:

```yaml
- LLM_PROVIDER=${LLM_PROVIDER:-ollama}
- LLM_MODEL=${LLM_MODEL:-qwen2.5:3b}
- LLM_BASE_URL=${LLM_BASE_URL:-http://host.docker.internal:11434/v1}
- LLM_API_KEY=${LLM_API_KEY:-ollama}
```

### Acceptance criteria

```text
- DeepSeek path vẫn chạy khi LLM_PROVIDER=deepseek.
- Ollama path không đòi DEEPSEEK_API_KEY.
- Nếu Ollama không reachable => BrainError => scheduler HOLD/skip, không rules-only execution khi REQUIRE_LLM_DECISION=true.
- README có hướng dẫn chạy: `ollama pull qwen2.5:3b`.
```

---

## 11. Work package 9 — Risk Critic agent

### Mục tiêu

Không dùng một LLM output là final. Thêm critic để tìm lỗi trước verifier.

### File cần tạo

```text
trading/auto/critic.py
trading/auto/test_critic.py
```

### File cần sửa

```text
trading/auto/scheduler.py
trading/auto/prompts.py
trading/auto/journal.py
```

### Critic behavior

Input:

```python
review_ticket(dossier: dict, retrieved_rules: dict, draft_ticket: dict) -> dict
```

Output:

```json
{
  "schema_version": "trade_critique.v1",
  "verdict": "PASS|REVISE|VETO",
  "issues": [
    {
      "severity": "info|warning|hard_violation",
      "rule_id": "HARD_RISK_001",
      "message": "Risk is too high for current drawdown."
    }
  ],
  "recommended_action": "KEEP|REDUCE_RISK|HOLD|REQUEST_MORE_DATA",
  "summary": "..."
}
```

MVP có thể có critic đơn giản:

```text
- Rule-based checks trước.
- Optional LLM critic sau.
```

Nếu critic verdict `VETO` => không cần gọi LLM revise ở MVP; chuyển HOLD/skip và log. Ở phase sau mới cho trader revise.

### Acceptance criteria

```text
- Draft ticket vi phạm hard rule bị critic flag.
- Critic output được journal log.
- Critic không được gọi broker.
- Critic không tự tạo order.
```

---

## 12. Work package 10 — Rule Verifier thay cho validator mơ hồ

### Mục tiêu

Validator hiện kiểm tra RR, size, SL/TP, reasoning quality. Cần nâng thành rule verifier kiểm tra rulebook citations + hard constraints + market/execution constraints. Có thể giữ `validator.py` nhưng đổi role hoặc tạo `rule_verifier.py`.

### File cần tạo/sửa

```text
trading/auto/rule_verifier.py
trading/auto/validator.py
trading/auto/test_rule_verifier.py
trading/auto/scheduler.py
```

### Behavior

```python
def verify_trade_ticket(ticket: dict, dossier: dict, retrieved_rules: dict) -> dict:
    return {
        "passed": bool,
        "violations": [
            {"rule_id": "HARD_RISK_001", "severity": "reject_order", "message": "..."}
        ],
        "warnings": [],
        "repair_allowed": bool,
    }
```

Verifier checks:

```text
1. Schema valid.
2. rule_citations exist.
3. playbook_id exists for non-HOLD.
4. playbook market matches dossier.market.
5. playbook direction includes candidate direction/action.
6. data_quality != C for non-HOLD.
7. current_price positive.
8. risk_pct_equity <= configured max.
9. entry drift <= policy.
10. stop/take-profit can be derived.
11. RR >= minimum.
12. max open positions not exceeded.
13. same-direction/correlation cap not exceeded.
14. event/news blackout if active.
15. spread/execution not abnormal.
16. LLM confidence above minimum if non-HOLD.
17. autonomy mode allows execution path.
```

Không còn dùng rule kiểu “reasoning text phải mention ≥1 soft skill”. Thay bằng:

```text
- rule_citations must include existing IDs.
- playbook_id must be valid.
```

### Fail-closed

Nếu verifier gặp exception:

```python
return {
    "passed": False,
    "violations": [{"rule_id": "SYSTEM_VERIFIER", "message": str(exc)}],
    "repair_allowed": False,
}
```

### Acceptance criteria

```text
- Ticket OPEN_LONG không cite playbook bị reject.
- Ticket cite rule giả bị reject.
- Ticket data_quality C bị reject.
- Ticket vượt max risk bị reject.
- Verifier error không bao giờ cho pass.
```

---

## 13. Work package 11 — Risk compiler / Order compiler

### Mục tiêu

LLM tạo intent. Code mới tính order thật. Không dùng trực tiếp quantity do LLM đưa ra.

### File cần tạo

```text
trading/auto/risk_compiler.py
trading/auto/order_compiler.py
trading/auto/test_risk_compiler.py
```

### File cần sửa

```text
trading/auto/scheduler.py
trading/brackets/okx_bracket.py nếu cần interface clean hơn
trading/brackets/okx_futures_bracket.py nếu cần futures support
```

### Risk compiler input

```python
compile_risk_plan(ticket: dict, dossier: dict, cfg: RuntimeConfig) -> dict
```

### Output

```json
{
  "symbol": "BTC-USDT",
  "side": "buy",
  "entry": 61250.0,
  "stop_loss": 60100.0,
  "take_profit": 63550.0,
  "risk_pct_equity": 0.005,
  "risk_amount_usd": 50.0,
  "position_size_units": 0.0434,
  "position_notional_usd": 2658.0,
  "rr_ratio": 2.0,
  "source": "risk_compiler.v1"
}
```

### Rules

```text
- LLM may propose risk_pct_equity but compiler clamps to hard max.
- If clamp would materially change thesis, skip or reduce risk with log.
- Stop-loss must be numeric before order.
- Take-profit must satisfy min RR.
- For market entry, use current_price.
- For limit entry, reject if drift exceeds ENTRY_FRESHNESS_MAX_PCT.
- For futures, enforce leverage and liquidation buffer.
```

### Acceptance criteria

```text
- LLM cannot set raw quantity.
- No compiled order without stop_loss.
- No compiled order with RR below hard minimum.
- Compiled order can be passed to existing bracket module.
```

---

## 14. Work package 12 — Scheduler pipeline refactor

### Mục tiêu

`scheduler.py` hiện làm quá nhiều việc. Giai đoạn đầu không nhất thiết rewrite toàn bộ, nhưng phải chuyển decision lifecycle sang pipeline mới.

### File cần sửa

```text
trading/auto/scheduler.py
trading/auto/auto.py nếu có thread startup assumptions
trading/auto/journal.py
```

### Pipeline mong muốn trong `run_once_symbol`

```python
def run_once_symbol(current_symbol: str) -> None:
    cfg = _runtime()

    # 1. Safety prechecks
    if journal.is_killed(): return log_skip(...)
    positions = read_positions_fail_closed()
    if max_positions_hit(...): return log_skip(...)
    if daily_loss_hit(...): return log_skip(...)
    if cooldown_active(...): return log_skip(...)

    # 2. Data
    conf = _run_confluence(spot_symbol)
    reg = _run_regime(spot_symbol)
    candidate = classify_confluence_direction(score, cfg.min_confluence)

    # 3. Dossier
    dossier = build_market_dossier(...)
    if dossier.data_quality.grade == "C": return log_skip(...)

    # 4. Rule retrieval
    rules = retrieve_rules(dossier)
    if no_playbook_for_non_hold_candidate: still call LLM or HOLD based on policy

    # 5. LLM trader
    draft_ticket = brain.call_trader(dossier, rules)

    # 6. Critic
    critique = critic.review_ticket(dossier, rules, draft_ticket)
    if critique.verdict == "VETO": log and return

    # 7. Verifier
    verification = verify_trade_ticket(draft_ticket, dossier, rules)
    if not verification.passed: log and return

    # 8. Compile order
    compiled_order = compile_order(draft_ticket, dossier, cfg)

    # 9. Final bracket validation/execution
    result = _place_bracket_via_script(...compiled_order...)

    # 10. Journal full lifecycle
    journal.append_decision("decision_lifecycle", {...})
```

### Rules-only fallback policy

Current scheduler has cost cap fallback to rules-only. Replace with explicit policy:

```python
require_llm = os.getenv("REQUIRE_LLM_DECISION", "true").lower() == "true"
enable_rules_only = os.getenv("ENABLE_RULES_ONLY_FALLBACK", "false").lower() == "true"

if llm_unavailable:
    if require_llm:
        skip reason="llm_required_unavailable"
    elif enable_rules_only:
        execute legacy rules-only path
    else:
        skip reason="llm_unavailable_rules_only_disabled"
```

Cost cap:

```text
- If cap hit and REQUIRE_LLM_DECISION=true => skip.
- If cap hit and ENABLE_RULES_ONLY_FALLBACK=true => legacy fallback allowed only in research/paper mode.
- Never rules-only fallback in live mode.
```

### Acceptance criteria

```text
- Scheduler still runs in Docker.
- No call to bracket execution happens before verifier pass.
- Cost cap no longer silently switches to rules-only when LLM is required.
- All skips include clear reason in journal.
```

---

## 15. Work package 13 — Journal/audit trail upgrade

### Mục tiêu

Journal phải lưu đủ để replay lại quyết định.

### File cần sửa

```text
trading/auto/journal.py
trading/auto/dashboard.py
trading/auto/test_phase_c.py hoặc test mới
```

### Log event mới

Thêm event type:

```text
market_dossier
rule_retrieval
llm_draft_ticket
critic_review
final_ticket
rule_verification
risk_compilation
execution_result
fail_closed_skip
```

Mỗi lifecycle nên có `decision_id` xuyên suốt:

```json
{
  "event": "llm_draft_ticket",
  "decision_id": "2026-06-28T10:15:00Z_BTC-USDT_001",
  "symbol": "BTC-USDT",
  "ticket": {...},
  "dossier_hash": "sha256:...",
  "rule_ids": ["HARD_RISK_001", "PB_CRYPTO_TREND_CONTINUATION_001"]
}
```

Snapshot folder:

```text
/data/journal/snapshots/
  2026-06-28/
    decision_id.market_dossier.json
    decision_id.rules_context.json
    decision_id.ticket.json
```

### Acceptance criteria

```text
- Với bất kỳ trade/reject nào, có thể tìm được dossier + rules + ticket + verifier result.
- Journal corrupt vẫn fail closed như hiện tại.
- Dashboard không crash nếu event type mới xuất hiện.
```

---

## 16. Work package 14 — Replay engine cho LLM decisions

### Mục tiêu

Backtest truyền thống chưa đủ. Cần replay decision lifecycle từ historical snapshots.

### File/thư mục cần tạo

```text
trading/replay/
  __init__.py
  run_replay.py
  snapshot.py
  metrics.py
  README.md
```

### Replay flow

```text
historical bars/snapshots
→ confluence/regime
→ market dossier
→ rule retrieval
→ LLM decision hoặc mocked LLM
→ critic
→ verifier
→ simulated order
→ outcome metrics
```

### Metrics cần output

```text
JSON validity rate
Rule citation validity rate
Hallucinated rule rate
HOLD rate
Rejected ticket rate
Verifier rejection reasons
Win rate
Profit factor
Max drawdown
Average R
Performance by playbook
Performance by regime
Decision stability
```

### MVP replay modes

```text
1. mock mode: no real LLM; feed fixed tickets to test verifier/risk compiler.
2. llm mode: call local/deepseek LLM on historical snapshots.
```

### Acceptance criteria

```text
- Có thể chạy replay không cần broker key.
- Replay không đặt order thật.
- Replay report lưu JSON/Markdown.
- Có test cho metrics.
```

---

## 17. Work package 15 — Backtest/live parity

### Mục tiêu

Backtest hiện tại không được lệch quá xa live loop. Cần ghi rõ khác biệt và tiến tới mirror live components.

### File cần sửa

```text
trading/backtest/engine.py
trading/backtest/run.py
trading/backtest/report.py
trading/backtest/FINDINGS.md
```

### Việc cần làm

```text
- Dùng cùng confluence/regime logic với scheduler, hoặc import helper chung.
- Dùng cùng rulebook/playbook IDs.
- Simulate bracket order với fee/slippage cơ bản.
- Lưu performance theo playbook_id.
- Report rõ cái gì chưa simulate được: funding, order book, gaps, live spread.
```

### Acceptance criteria

```text
- Backtest report có playbook_id/regime breakdown.
- Backtest không dùng proxy strategy khác hẳn live mà không ghi warning.
- Nếu chưa full parity, FINDINGS.md phải nói rõ gap.
```

---

## 18. Work package 16 — Berkshire research thành context/critic, không phải executor

### Mục tiêu

`berkshire_routes.py` hiện là research route. Giữ nó như research/context source, không để tự đặt lệnh.

### File cần sửa/tạo

```text
trading/berkshire_routes.py
trading/auto/research_context.py
trading/auto/prompts.py
trading/auto/scheduler.py
```

### Behavior

Tạo internal function:

```python
def build_berkshire_research_context(symbol: str, market: str, dossier: dict) -> dict:
    return {
        "schema_version": "research_context.v1",
        "symbol": symbol,
        "macro_summary": "...",
        "risk_flags": [],
        "contrarian_points": [],
        "information_quality": "A|B|C",
        "research_only": True,
    }
```

Inject vào prompt như context phụ:

```text
Research context is advisory only. It cannot override hard rules.
```

### Acceptance criteria

```text
- Berkshire output chỉ ảnh hưởng thesis/risk flags.
- Không có execution path từ Berkshire route.
- Nếu Berkshire context lỗi, system vẫn có thể HOLD hoặc trade tùy policy; trong paper mode nên log warning, trong live mode nên fail closed nếu research required.
```

---

## 19. Work package 17 — Forex readiness bằng adapter interface

### Mục tiêu

Không nhét forex trực tiếp vào OKX-centric scheduler. Tạo interface trước.

### File/thư mục cần tạo

```text
trading/execution/
  __init__.py
  base.py
  okx_adapter.py
  paper_adapter.py
  oanda_adapter.py
  mt5_adapter.py
```

### Interface

```python
class ExecutionAdapter:
    def get_account(self) -> dict: ...
    def get_positions(self) -> list[dict]: ...
    def get_quote(self, symbol: str) -> dict: ...
    def place_bracket_order(self, order: dict) -> dict: ...
    def close_position(self, position_id: str) -> dict: ...
```

### MVP

```text
- Implement OKX adapter by wrapping existing bracket modules.
- Implement PaperAdapter for replay/paper tests.
- Add OandaAdapter/MT5Adapter stubs only, with NotImplementedError.
- Do not enable forex live until adapter + data + tests exist.
```

### Acceptance criteria

```text
- Scheduler/risk compiler talks to ExecutionAdapter, not OKX functions directly.
- OKX behavior remains unchanged in paper/testnet.
- Forex stubs cannot place live orders accidentally.
```

---

## 20. Test matrix bắt buộc

### Unit tests

```text
trading/auto/test_short_path.py
trading/auto/test_market_dossier.py
trading/auto/test_rule_retriever.py
trading/auto/test_decision_schema.py
trading/auto/test_rule_verifier.py
trading/auto/test_risk_compiler.py
trading/auto/test_brain_provider.py
trading/replay/test_metrics.py
```

### Integration smoke tests

```bash
# compile rulebook
python trading/rulebook/compile_rulebook.py

# run unit tests
pytest trading/auto -q
pytest trading/replay -q

# dry-run confluence/regime
python trading/confluence/confluence.py --symbol BTC-USDT --json
python trading/regime/regime.py --symbol BTC-USDT --json

# docker build
cd trading
docker compose build

# docker up paper/testnet only
cd trading
docker compose up -d
curl http://localhost:8000/health
```

### Manual test scenarios

```text
1. LLM unavailable with REQUIRE_LLM_DECISION=true => skip, no order.
2. LLM invalid JSON => repair once, then skip if still invalid.
3. LLM cites fake rule => verifier reject.
4. LLM OPEN_LONG with no risk_plan => reject.
5. Confluence score -3 => candidate_direction short.
6. Data current_price <= 0 => skip.
7. Daily loss cap hit => skip.
8. Kill switch file exists => skip.
9. OKX_TESTNET=false => refuse execution.
10. Cost cap hit + REQUIRE_LLM_DECISION=true => skip, no rules-only fallback.
```

---

## 21. Definition of Done cho toàn bộ refactor

Hoàn thành khi đạt tất cả:

```text
- Root docs trỏ đúng vào `trading/`.
- Short/bearish path hoạt động theo abs(score).
- Rulebook tồn tại dưới `trading/rulebook/source` và compile được.
- LLM prompt dùng retrieved rulebook snippets, không dùng skills thô.
- LLM output là TradeDecisionTicket schema v1.
- Ticket non-HOLD phải cite rule_id và playbook_id có thật.
- Rule verifier reject hard violations bằng code.
- Risk compiler tính size/order, không lấy quantity từ LLM.
- Scheduler không gọi execution trước verifier.
- Local LLM provider chạy được qua OpenAI-compatible endpoint.
- DeepSeek backward compatibility vẫn còn.
- REQUIRE_LLM_DECISION=true chặn rules-only fallback.
- Journal lưu decision lifecycle đầy đủ.
- Replay skeleton chạy được không cần broker.
- Docker build không lỗi.
- Tests mới pass.
```

---

## 22. Thứ tự implement khuyến nghị cho coding agent

Không làm tất cả trong một lần. Chia thành PR nhỏ:

```text
PR 1: Docs identity + short path bug.
PR 2: Rulebook folder + compiler + compiled skills compatibility.
PR 3: Market dossier + deterministic rule retriever.
PR 4: TradeDecisionTicket schema + prompt refactor.
PR 5: Provider-agnostic brain.py + Ollama config.
PR 6: Rule verifier + risk compiler.
PR 7: Scheduler pipeline integration.
PR 8: Journal lifecycle events + dashboard compatibility.
PR 9: Replay skeleton + metrics.
PR 10: Berkshire context integration.
PR 11: Execution adapter interface + OKX adapter wrapper.
```

Mỗi PR phải có:

```text
- Files changed list.
- Behavior changed summary.
- Tests run.
- Known limitations.
- Safety impact.
```

---

## 23. Prompt copy/paste cho AI coding agent

Dùng prompt này cho coding agent:

```text
You are modifying the repository `mllllxxxx/trading_v1`.
Read `trading_v1_llm_governed_refactor_spec.md` first.

Goal: migrate the current hybrid rules + LLM trading system into an LLM-governed, rulebook-grounded trading system.

Do not enable live trading. Do not remove testnet guards. Do not commit secrets. Do not let LLM call broker directly.

Implement the work in small PR-sized changes. Start with PR 1 only:
1. Fix root repo identity docs so the main app is clearly under `trading/`.
2. Fix the short/bearish confluence path in `trading/auto/scheduler.py` by using `abs(score) < min_confluence` and adding candidate_direction.
3. Update docs/tests for positive long and negative short confluence.
4. Run relevant tests.

After PR 1, stop and report:
- files changed
- exact behavior change
- tests run
- safety impact
- next recommended PR
```

Prompt cho PR 2:

```text
Continue from PR 1.
Implement PR 2 from `trading_v1_llm_governed_refactor_spec.md`:
- Create `trading/rulebook/` structure.
- Add hard rules, soft policies, playbooks, and cases.
- Add `compile_rulebook.py` and `schema.py`.
- Produce `compiled/rule_index.json` and compatibility `compiled/skills.json`.
- Update `auto/skills.py` to load compiled rulebook artifacts.
- Keep backward compatibility with existing `auto/skills.json` if needed.
- Add tests for ID uniqueness and missing referenced rules.

Do not change scheduler execution behavior in this PR except loading skills if needed.
```

Prompt cho PR 3:

```text
Continue from PR 2.
Implement PR 3:
- Add `trading/auto/market_dossier.py`.
- Add `trading/auto/rule_retriever.py`.
- Build dossier from current confluence/regime/journal/portfolio state.
- Retrieve relevant hard rules, playbooks, soft policies, and cases deterministically from compiled rulebook index.
- Add tests.
- Do not route orders through this new pipeline yet; just integrate enough to log dossier/retrieval in scheduler if safe.
```

Prompt cho PR 4:

```text
Continue from PR 3.
Implement PR 4:
- Add `trading/auto/decision_schema.py` with TradeDecisionTicket v1 validation.
- Refactor prompts so LLM is a constrained trading decision agent reading market dossier + retrieved rulebook.
- Update `brain.py` to validate TradeDecisionTicket.
- Add repair-once behavior for invalid JSON/schema.
- Add tests for valid HOLD, valid OPEN_LONG, fake rule citation, missing risk plan.
- Do not change live/testnet guards.
```

Prompt cho PR 5:

```text
Continue from PR 4.
Implement PR 5:
- Refactor `trading/auto/brain.py` to support DeepSeek and local OpenAI-compatible providers.
- Add env vars: LLM_PROVIDER, LLM_MODEL, LLM_BASE_URL, LLM_API_KEY.
- Keep backward compatibility with DEEPSEEK_API_KEY and AUTO_LLM_MODEL.
- Update `.env.template`, `docker-compose.yml`, and README for Ollama qwen2.5:3b.
- Add tests for config resolution.
- If local provider is unavailable and REQUIRE_LLM_DECISION=true, scheduler must skip/fail closed.
```

Prompt cho PR 6:

```text
Continue from PR 5.
Implement PR 6:
- Add `rule_verifier.py`, `risk_compiler.py`, and optionally `order_compiler.py`.
- Verifier must reject fake rule IDs, missing playbook, data_quality C, risk above max, missing stop/risk plan, and bad action enum.
- Risk compiler must compute order size from capital, stop distance, and risk_pct; LLM cannot supply raw quantity.
- Add tests.
```

Prompt cho PR 7:

```text
Continue from PR 6.
Implement PR 7:
- Refactor scheduler decision lifecycle to use market dossier, rule retriever, LLM ticket, critic if available, verifier, risk compiler, and bracket execution.
- Ensure no execution path happens before verifier pass.
- Implement REQUIRE_LLM_DECISION and ENABLE_RULES_ONLY_FALLBACK policies.
- Cost cap + REQUIRE_LLM_DECISION=true must skip, not execute rules-only.
- Add integration-style tests with mocked confluence/regime/LLM.
```

---

## 24. Ghi chú thiết kế quan trọng

Không biến hệ thống thành pure rule-based. Rulebook là source of truth, nhưng LLM vẫn có quyền suy luận trade intent.

Không biến hệ thống thành pure LLM. LLM có thể quyết định `OPEN_LONG` hoặc `OPEN_SHORT`, nhưng verifier/risk compiler mới quyết định liệu intent đó có được compile thành order hợp lệ hay không.

Thiết kế cuối cùng cần đạt:

```text
Rules define the allowed universe.
LLM reasons inside that universe.
Verifier enforces the non-negotiable boundaries.
Risk compiler turns intent into safe order parameters.
Execution adapter places only verified compiled orders.
Journal makes every decision replayable.
```

---

## 25. Các lỗi cần tránh khi implement

```text
- Chỉ thêm prompt mà không thêm schema/verifier.
- Cho LLM cite rule IDs nhưng không kiểm tra IDs tồn tại.
- Cho LLM đặt position_size_units trực tiếp.
- Vẫn giữ fallback rules-only trong mode yêu cầu LLM.
- Sửa short path nhưng quên docs/tests.
- Thêm rulebook nhưng không compile/render cho LLM.
- Dùng vector retrieval quá sớm; deterministic metadata retrieval đủ cho MVP.
- Thêm forex trước khi execution adapter sạch.
- Tích hợp Berkshire như executor; chỉ dùng làm research context/critic.
- Reformat toàn bộ minified/compact files trong cùng PR logic lớn, gây diff khó review.
```

---

## 26. Minimal viable end-state

Sau các PR đầu tiên, trạng thái tối thiểu chấp nhận được:

```text
- Repo docs đúng.
- Long/short path đúng.
- Rulebook compile được.
- Dossier + rule retrieval chạy được.
- LLM xuất TradeDecisionTicket có rule citations.
- Verifier reject ticket sai.
- Risk compiler tạo order từ ticket hợp lệ.
- Scheduler fail closed khi LLM/rule/data lỗi.
- Journal ghi lifecycle.
- Docker build chạy.
```

Chưa cần xong ngay:

```text
- Full forex execution.
- Full vector RAG.
- Fine-tune local model.
- Full live trading.
- Complex multi-agent committee.
```

Ưu tiên hiện tại là biến kiến trúc từ:

```text
rules pre-filter + LLM confirmation
```

thành:

```text
rulebook-grounded LLM decision + verifier + risk compiler
```
