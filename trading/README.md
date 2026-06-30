# Trade_V1 Trading Runtime

The trading application lives in this `trading/` directory. Root-level Harness
docs are workflow support, not the runtime itself.

For future refactor work, read these first:

- `../docs/specs/trading_v1_source_of_truth_governance_plan.md`
- `../docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `docs/architecture/SOURCE_OF_TRUTH_MAP.md`
- `docs/architecture/DECISION_FLOW.md`
- `docs/product/TRADING_SYSTEM_INTENT.md`
- `docs/product/AUTONOMY_POLICY.md`
- `docs/product/RISK_MANDATE.md`
- `docs/product/LLM_ROLE.md`

Current README sections below describe the existing runtime. If they conflict
with the governance plan, the governance plan wins.

# Vibe-Trading workspace

Personal AI trading assistant. Paper-trades on **OKX** (crypto) using **DeepSeek**
as the LLM brain. Built on [Vibe-Trading](https://github.com/HKUDS/Vibe-Trading).

## Layout

```
trading/
  .venv/                  Python virtual environment (local dev)
  .env.template           Template for ~/.vibe-trading/.env (no secrets)
  run.ps1                 Wrapper: loads .env, runs vibe-trading
  brackets/               F1: Bracket order + R:R validator
  confluence/             F2: Multi-timeframe confluence (15m-1w)
  regime/                 F3: Market regime detection
  frontend/               React UI source (built dist served by API)
  Dockerfile              Multi-stage Docker build
  docker-compose.yml      Container orchestration
  .dockerignore
  README.md               This file
```

Real config lives in `C:\Users\minhl\.vibe-trading\.env` (user home, NOT in
this folder). Edit it directly to add your real API keys.

## Quick start

Every command goes through `run.ps1` so your `.env` is loaded automatically.

```powershell
# from project root
.\trading\run.ps1 --version
.\trading\run.ps1 provider doctor
.\trading\run.ps1 connector list
.\trading\run.ps1 alpha list
```

## What you need to fill in

Open `C:\Users\minhl\.vibe-trading\.env` and replace the `PASTE_*` placeholders:

| Key | Where to get it |
|---|---|
| `DEEPSEEK_API_KEY` | https://platform.deepseek.com (~$5-10 for 2-3 months of paper trading) |
| `OKX_API_KEY` | https://www.okx.com/vi/demo-trading -> Profile -> API -> Create |
| `OKX_API_SECRET` | Same place |
| `OKX_PASSPHRASE` | Set at API key creation |
| `ALPHA_VANTAGE_API_KEY` | (optional) https://www.alphavantage.co/support/#api-key |

### OKX setup (paper / testnet)

1. Log in to https://www.okx.com (or create an account)
2. Switch to **Demo Trading** mode (top-right toggle, or use the demo URL)
3. Profile -> API -> Create API key
4. Permissions: enable **Read** + **Trade**, **disable Withdraw**
5. Set a passphrase (you'll need to remember it)
6. Copy the key, secret, and passphrase into `~/.vibe-trading/.env`

Then select the paper profile and check it:

```powershell
.\trading\run.ps1 connector use okx-paper-trade
.\trading\run.ps1 connector check
```

## Recommended workflow (first 2-3 months)

Paper trade only. Don't touch live money until you've seen stable Sharpe > 1
across at least 2 months.

### Day 1 - verify setup
```powershell
.\trading\run.ps1 provider doctor        # confirm DeepSeek is active
.\trading\run.ps1 connector check        # confirm OKX testnet reachable
.\trading\run.ps1 alpha list             # confirm 452 alphas available
```

### Week 1 - find a candidate alpha
```powershell
# browse a single alpha
.\trading\run.ps1 alpha show academic_carhart_mom

# bench a small universe (uses yfinance, no broker needed)
.\trading\run.ps1 alpha bench --zoo academic --universe equity_us --period 2018-2025

# head-to-head comparison
.\trading\run.ps1 alpha compare academic_carhart_mom academic_hml
```

### Week 2+ - paper trade
Open the Web UI and start a chat session:

```powershell
.\trading\run.ps1 serve                  # opens http://localhost:8000
```

In the Web UI, try prompts like:

```
Analyze BTC-USDT on the 4h timeframe.
- Run academic momentum + reversal alphas
- Show Sharpe / max drawdown for the last 2 years
- What is the current signal?
- Recommend position size given my 30% per-position mandate
- DO NOT place any orders automatically
```

### Month 2-3 - validate, then decide
- Track P&L in a spreadsheet
- Look for Sharpe > 1 with max drawdown < 20%
- Look for consistency across multiple timeframes
- Only then consider live trading with very small size

## Safety rules

| Rule | Why |
|---|---|
| Always start with `okx-paper-trade`, never `okx-live-*` | Paper money first |
| Never enable `Withdraw` permission on API keys | Defense-in-depth |
| Use a **mandate** in prompts (max position %, max leverage, daily loss cap) | Hard guard before orders |
| `DO NOT place orders automatically` in early prompts | Force human review |
| Read the decision log weekly | Learn what the agent is doing |

## Available commands

| Command | What it does |
|---|---|
| `vibe-trading provider doctor` | Show LLM config (redacted) |
| `vibe-trading connector list` | List broker profiles |
| `vibe-trading connector use <id>` | Select default profile |
| `vibe-trading connector check` | Test selected profile |
| `vibe-trading connector account` | Read account summary |
| `vibe-trading connector positions` | Read open positions |
| `vibe-trading alpha list` | List 452 alphas |
| `vibe-trading alpha show <id>` | Show alpha source + paper reference |
| `vibe-trading alpha bench` | Benchmark alphas on a universe |
| `vibe-trading alpha compare <id1> <id2> ...` | Head-to-head ranking |
| `vibe-trading serve` | Start Web UI on localhost:8000 |
| `vibe-trading run -p "..."` | One-shot prompt |
| `vibe-trading chat` | Interactive REPL |

## Troubleshooting

**`provider doctor` shows `provider: openai` instead of `deepseek`**
- The `.env` was not loaded. Make sure you use `.\trading\run.ps1` and not the raw exe.

**`provider doctor` shows `DEEPSEEK_API_KEY: unset` or `PASTE_*`**
- Edit `C:\Users\minhl\.vibe-trading\.env` and replace the placeholder with your real key.

**`connector check` fails with `api_key missing`**
- Run `vibe-trading connector configure okx-paper-trade` and enter the key/secret/passphrase when prompted.
- OR put them in `~/.vibe-trading/.env` under `OKX_API_KEY` etc.

**Model name `deepseek-v4-pro` not recognized by DeepSeek**
- DeepSeek sometimes renames models. Check https://platform.deepseek.com/api-docs/ for current names and update `LANGCHAIN_MODEL_NAME` in `.env`.

**Pip install is slow**
- Normal on first run. Subsequent installs use the cache at `~\AppData\Local\pip\cache`.

## What's NOT here

- nautilus_trader (production engine) - not needed for paper trading
- AI-Trader (social layer) - single user, no value
- TradingAgents (LLM research framework) - no real alpha, no execution
- Custom glue code - Vibe-Trading covers the full stack out of the box for retail

Add these only if a specific bottleneck appears after months of paper trading.

## Custom features (3 trading techniques, all winrate-focused)

Tôi đã bổ sung 3 tính năng lấy cảm hứng từ nautilus_trader + TradingAgents, mỗi
cái tác động trực tiếp lên **winrate** thay vì chỉ tổ chức/journal.

### F1: Bracket Order + R:R Validator (`brackets/`)

Mỗi lệnh bắt buộc có R:R >= 1:2, position <= 20% vốn, risk <= 1% vốn. Tự động
đặt entry + TP + SL trên OKX.

- Prompt template: `brackets/bracket.md` (đọc khi chat với Vibe-Trading)
- Script: `brackets/okx_bracket.py`
- Test: `brackets/test-bracket.ps1 -Scenario good|bad_rr|bad_size|short_good`
- Đặt lệnh: `brackets/run-bracket.ps1 -Symbol BTC-USDT -Side buy -Entry ...`

Xem chi tiết trong `brackets/README.md`.

### F2: Multi-TF Confluence (`confluence/`)

Chỉ vào lệnh khi **5 khung thời gian (15m, 1h, 4h, 1d, 1w) đồng thuận**.
Trader retail thường nhìn 1 chart → confluence lọc ra ~70% lệnh xấu.

- Script: `confluence/confluence.py`
- Test: `confluence/test-confluence.ps1 -Symbol BTC-USDT`
- Score: -5 đến +5. Gate dùng `abs(score) >= AUTO_MIN_CONFLUENCE`;
  score dương là long candidate, score âm là short candidate.

Xem chi tiết trong `confluence/README.md`.

### F3: Market Regime Detection (`regime/`)

Phát hiện regime hiện tại (TRENDING_UP/DOWN, RANGING, HIGH_VOL, MIXED) bằng
Hurst exponent + ADX + ATR ratio, rồi recommend alphas phù hợp. Edge của
alpha chỉ work trong đúng regime của nó.

- Script: `regime/regime.py`
- Test: `regime/test-regime.ps1 -Symbol BTC-USDT`
- Output: regime + list alphas nên bench

Xem chi tiết trong `regime/README.md`.

### Workflow tổng hợp (paper trade)

```
1. REGIME check:    .\trading\regime\run-regime.ps1 -Symbol BTC-USDT
                    → biết regime + list alphas phù hợp

2. CONFLUENCE:      .\trading\confluence\run-confluence.ps1 -Symbol BTC-USDT
                    → score MTF, cần abs(score) >= threshold; dương long, âm short

3. BRACKET:         .\trading\brackets\run-bracket.ps1 -Symbol BTC-USDT ... 
                    → R:R >= 1:2, position <= 20%, risk <= 1%

4. THEO DÕI:       .\trading\run.ps1 connector positions
                    .\trading\run.ps1 connector orders
                    → nếu TP hit: cancel SL, ngược lại
```

Mỗi feature có thể dùng độc lập, nhưng dùng cả 3 sẽ tăng winrate đáng kể
vì: regime cho biết dùng alpha nào, confluence cho biết vào lúc nào,
bracket đảm bảo R:R đúng.

## Docker (single container - recommended)

Build + run toàn bộ stack trong **1 container** duy nhất:

```powershell
# Build image (lần đầu ~3-5 phút)
docker compose build

# Start in background
docker compose up -d

# Verify both ports
curl http://localhost:8000/health    # Vibe-Trading UI
curl http://localhost:8001/          # Auto-trader dashboard

# View logs (all services)
docker compose logs -f

# Stop
docker compose down
```

**Single container chạy 4 services via threads:**
- `vibe_trading` (port 8000) - Vibe-Trading UI + chat với LLM
- `scheduler` (no port) - check confluence/regime mỗi 5 phút
- `monitor` (no port) - poll OKX mỗi 30s
- `dashboard` (port 8001) - live PnL, decisions, technical indicators

**Ports exposed:** 8000 (Vibe-Trading UI), 8001 (Auto-trader dashboard)

**Env file**: docker compose tự động đọc `~/.vibe-trading/.env` (user home).

**Data persistence**: volume `vibe-trading-data` mount vào `/data` - sessions, decision log, OKX config, journal tự động lưu.

**Chạy custom scripts trong container:**
```powershell
docker compose exec vt python /app/confluence/confluence.py --symbol BTC-USDT
docker compose exec vt python /app/regime/regime.py --symbol BTC-USDT
docker compose exec vt python /app/brackets/okx_bracket.py --symbol BTC-USDT --dry-run
```

**Khi nào rebuild:** sau khi sửa code trong `trading/`, chạy `docker compose build && docker compose up -d`

## Auto-trader (100% paper automation)

Container `auto` chạy 100% tự động:
- **Scheduler** (mỗi 5 phút): check confluence + regime, đặt bracket nếu đủ điều kiện
- **Monitor** (mỗi 30 giây): poll OKX, auto-cancel lệnh ngược khi TP/SL hit
- **Dashboard** (port 8001): live PnL, winrate, open positions, decision log
- **Journal** (volume `vibe-trading-data/journal/`): append-only decision + trade log

**Dashboard**: http://localhost:8001

**Auto-trade điều kiện** (TẤT CẢ phải pass):
1. Kill switch KHÔNG active (`/data/STOP` không tồn tại)
2. Số open positions < 3
3. Chưa có open position cho symbol
4. Daily loss chưa chạm -3% vốn
5. `abs(confluence score) >= AUTO_MIN_CONFLUENCE`; score dương → long, score âm → short
6. Regime ∈ {TRENDING_UP, TRENDING_DOWN}
7. R:R >= 1:2 (auto-validated)
8. Risk per trade <= 1% vốn
9. Position size <= 20% vốn
10. OKX testnet only (refuse nếu OKX_TESTNET≠true)

**Config** (env vars trong `docker-compose.yml`):
```
AUTO_SYMBOL=BTC-USDT
AUTO_INTERVAL_S=300          # 5 min
AUTO_MONITOR_INTERVAL_S=30   # 30s
AUTO_MIN_CONFLUENCE=2
AUTO_MAX_POSITIONS=3
AUTO_DAILY_LOSS_CAP_PCT=0.03
AUTO_CAPITAL=10000
```

**Kill switch** (dừng tự động ngay lập tức):
```powershell
docker compose exec auto touch /data/STOP
# Resume
docker compose exec auto rm /data/STOP
```

**Hoặc qua API**:
```powershell
# Halt
curl http://localhost:8001/api/kill
# Resume
curl http://localhost:8001/api/resume
```

**Xem journal thủ công**:
```powershell
docker compose exec auto tail -f /data/journal/decisions.jsonl
docker compose exec auto cat /data/journal/positions.json
docker compose exec auto cat /data/journal/closed_trades.jsonl
```

**Demo data** (đã inject sẵn): 5 closed trades, PnL +$59, 60% winrate.
Mở http://localhost:8001 để xem UI.

**Sau khi rotate keys**: container tự pick up qua env_file, chỉ cần `docker compose restart auto`.

## Hybrid Rules + LLM (Phase 2-4)

Từ Phase 2, scheduler tích hợp **LLM brain** (deepseek-v4-flash) vào workflow:
1. Pre-filter (rules-only): confluence + regime check
2. **STRONG signal** (`abs(confluence) >= threshold` + direction-aware regime OK) → gọi LLM
3. LLM đọc: stats + open positions + recent PnL + **skills** (từ `auto/skills.json`)
4. LLM output JSON: action (long/short/hold), entry, SL, TP, size, reasoning
5. Validator kiểm tra hard rules (R:R >= 1.2, position <= 20%, SL/TP set)
6. Conflict handling: LLM có thể override rules (vd: rules nói "long" nhưng LLM thấy RSI overbought → "hold")
7. Reasoning quality check: text > 50 chars + mention ≥1 soft skill
8. Execute bracket order, log everything

**Skills** (user-editable trong `auto/skills.json`):
- Hard: R:R minimum, max position %, max leverage, SL/TP required
- Soft: avoid_overbought_long, avoid_oversold_short, high_vol_caution, major_news_avoid, btc_dominance_rule, trend_persistence

**Cost**: ~$1-2/tháng (chỉ gọi LLM khi STRONG signal = ~28 calls/day × deepseek-v4-flash)

**Files mới**:
- `auto/skills.json` — 5 hard + 6 soft skills
- `auto/skills.py` — load + validate
- `auto/validator.py` — hard rule check + reasoning quality
- `auto/prompts.py` — system + user prompt templates
- `auto/brain.py` — LLM call (OpenAI-compatible) + JSON parse

**Xem LLM decisions trên dashboard**: section "LLM brain — recent decisions" hiển thị action + reasoning mỗi lần LLM được gọi.
