# Design: AI Berkshire Advisory Layer

**Feature ID:** ai-berkshire-advisory-layer
**Status:** designing
**Lane:** high-risk
**External source:** https://github.com/xbtlin/ai-berkshire
**Reviewed external HEAD:** `d8d274b975e196dca6d61723c2b39280b8012c01`

---

## 1. Executive Summary

`xbtlin/ai-berkshire` is not an app server or trading executor. It is a Claude
Code skill/report/tool framework for value-investing research. Its strongest
assets are:

- multi-agent research patterns,
- explicit verdict discipline,
- anti-bias and inversion checks,
- thesis tracking,
- portfolio review,
- news/catalyst attribution,
- exact financial calculation and report audit utilities.

Trade_V1 is a crypto futures auto-trader. Its live path is:

```text
scheduler
  -> confluence.py
  -> regime.py
  -> prompts.py
  -> brain.py
  -> validator.py
  -> okx bracket layer
  -> journal
```

The correct integration is therefore an **advisory research layer** that feeds
structured context into the existing LLM prompt and risk journal. It must never
place orders directly and must never override validator hard rules.

Design principle: AI Berkshire can say "this setup deserves more caution" or
"this move is probably news/catalyst-driven"; it cannot say "place a trade".

---

## 2. Source Audit

### 2.1 AI Berkshire shape

Observed repository layout:

```text
skills/
  investment-team.md
  investment-research.md
  investment-checklist.md
  quality-screen.md
  news-pulse.md
  portfolio-review.md
  thesis-tracker.md
  financial-data.md
  ...
tools/
  financial_rigor.py
  report_audit.py
  momentum_backtest_v2.py
  stock_screener.py
  ...
reports/
data/
assets/
CLAUDE.md
README_EN.md
LICENSE
```

There is no `package.json`, no Python package manifest, and no reusable API
surface. The reusable units are markdown skill protocols plus some standalone
Python tools.

### 2.2 License

AI Berkshire is MIT licensed. If any prompt text or tool code is vendored into
Trade_V1, include attribution and preserve the MIT notice in a local third-party
notice file.

### 2.3 Relevant concepts to reuse

| AI Berkshire concept | Trade_V1 adaptation |
| --- | --- |
| `investment-team` four-role research | Crypto research team: token/protocol model, market/on-chain valuation, competitor/liquidity structure, risk/governance/regulatory |
| `investment-checklist` | Pre-trade quality checklist for top-50 coins and major narratives |
| `quality-screen` | Universe quality filter: avoid low-liquidity, weak-tokenomics, unlock-heavy, governance-risk assets |
| `news-pulse` | Catalyst attribution for abnormal price/funding/open-interest moves |
| `portfolio-review` | Exposure review: symbol, sector, correlation, long/short imbalance, max concurrent positions |
| `thesis-tracker` | Per-symbol trade thesis and invalidation checklist |
| `financial-data` + `financial_rigor.py` | Exact arithmetic and cross-source validation discipline for market, funding, OI, unlock, and supply metrics |
| `report_audit.py` | Audit generated research reports before using them in prompts or dashboards |

### 2.4 Concepts not suitable for direct reuse

- Stock valuation heuristics like PE, PB, ROE are not directly applicable to
  crypto futures.
- Long-only value investing conclusions must not become futures entry signals.
- AI Berkshire reports are mostly markdown and human-readable; Trade_V1 needs
  typed JSON contracts before prompt/runtime use.

---

## 3. Current Trade_V1 Integration Points

### Existing runtime facts

- `trading/auto/scheduler.py` is the main loop and owns pre-LLM safety gates:
  kill switch, cooldown, max positions, daily loss cap, confluence, regime.
- `trading/confluence/confluence.py` returns 5-timeframe legacy scores plus
  8-category confluence enrichment.
- `trading/regime/regime.py` classifies market regime and returns technical
  indicator context.
- `trading/auto/prompts.py` builds the LLM system/user prompt.
- `trading/auto/brain.py` calls DeepSeek-compatible chat completion and validates
  required JSON keys.
- `trading/auto/validator.py` enforces hard rules after LLM output.
- `trading/auto/journal.py` writes decisions, positions, closed trades, stats,
  and LLM cost.
- `trading/auto/llm_override_tracker.py` already has a pattern for outcome-based
  trust gates and append-only learning logs.

### Integration target

Add a new module family:

```text
trading/research/
  __init__.py
  berkshire/
    __init__.py
    models.py
    advisor.py
    cache.py
    prompt_context.py
    source_validation.py
    templates/
      README.md
      checklist.md
      news_pulse.md
      thesis_tracker.md
      portfolio_review.md
```

Optional tests:

```text
trading/tests/
  test_berkshire_models.py
  test_berkshire_advisor.py
  test_berkshire_prompt_context.py
  test_berkshire_scheduler_integration.py
```

---

## 4. Feature Contract

### 4.1 Input contract

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ResearchHorizon = Literal["intraday", "swing", "weekly"]

@dataclass(frozen=True)
class BerkshireResearchRequest:
    """Input snapshot for the AI Berkshire advisory layer."""

    symbol: str
    horizon: ResearchHorizon
    generated_for_ts: str
    current_price: float
    regime: dict[str, Any]
    confluence: dict[str, Any]
    open_positions: list[dict[str, Any]]
    recent_trades: list[dict[str, Any]]
    market_context: dict[str, Any] = field(default_factory=dict)
```

### 4.2 Output contract

```python
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["constructive", "caution", "avoid", "unknown"]
Bias = Literal["long", "short", "neutral"]

@dataclass(frozen=True)
class BerkshireAdvisoryReport:
    """Typed advisory output safe to feed into prompts and journals."""

    symbol: str
    generated_at: str
    source_version: str
    horizon: str
    information_richness: Literal["A", "B", "C"]
    verdict: Verdict
    bias: Bias
    confidence: float
    quality_score: float
    catalyst_score: float
    thesis_health_score: float
    risk_flags: list[str]
    invalidates_if: list[str]
    suggested_size_multiplier: float
    prompt_summary: str
    sources: list[dict[str, str]]
```

### 4.3 Safety semantics

`suggested_size_multiplier` must be clamped to `[0.0, 1.0]`.

- It may reduce exposure.
- It may ask for no new trade by returning `0.0`.
- It may leave normal sizing unchanged with `1.0`.
- It must never enlarge a position beyond confluence/scheduler/validator caps.

If the advisor fails, times out, lacks data, or produces invalid JSON, the system
falls back to neutral:

```json
{
  "verdict": "unknown",
  "bias": "neutral",
  "confidence": 0.0,
  "suggested_size_multiplier": 1.0,
  "risk_flags": ["berkshire_advisor_unavailable"]
}
```

This prevents external research failures from blocking the existing bot unless
we explicitly enable a stricter mode later.

---

## 5. Runtime Modes

Use one env var:

```text
BERKSHIRE_ADVISOR_MODE=off|shadow|prompt|gate
```

Recommended defaults:

- `off` in production until tested.
- `shadow` in development and paper trading: generate reports and journal them,
  but do not alter prompts or sizing.
- `prompt`: include `prompt_summary` in `prompts.build_user_prompt()`.
- `gate`: apply `suggested_size_multiplier` after validator passes, before
  bracket placement. This mode requires explicit tests and paper evidence.

Mode behavior:

| Mode | Research job | Prompt context | Size effect | Can block trade |
| --- | --- | --- | --- | --- |
| `off` | no | no | no | no |
| `shadow` | yes | no | no | no |
| `prompt` | yes | yes | no | no |
| `gate` | yes | yes | reduce only | yes, only by multiplier `0.0` |

---

## 6. Data Flow

```text
Trade_V1 market cycle
  -> scheduler loads symbol
  -> confluence + regime
  -> berkshire advisor reads cached research or runs lightweight refresh
  -> journal records advisory event
  -> prompt mode: prompt_summary is appended to LLM user prompt
  -> LLM returns action JSON
  -> validator hard rules run unchanged
  -> gate mode: position size is multiplied by advisory multiplier
  -> bracket order path runs unchanged
```

Cache location:

```text
VIBE_TRADING_HOME/research/berkshire/
  advisory_latest/{symbol}.json
  advisory_events.jsonl
  thesis/{symbol}.json
```

Cache TTL:

- `news_pulse`: 30-60 minutes.
- `checklist` and `thesis`: 12-24 hours.
- `portfolio_review`: every scheduler run can use current open positions, but
  long-form commentary should be cached.

---

## 7. Berkshire-to-Crypto Adapters

### 7.1 Checklist adapter

Replace stock gates with crypto futures-safe checks:

| Original value lens | Crypto futures adapter |
| --- | --- |
| circle of competence | is the asset narrative and main driver understood |
| good business | protocol/network quality or exchange/liquidity quality |
| moat | network effects, developer ecosystem, liquidity depth, brand trust |
| management | foundation/governance, insider unlocks, major holder behavior |
| margin of safety | technical distance to invalidation, liquidation buffer, funding risk |
| discipline | FOMO/revenge/chasing check |

Output:

```json
{
  "checklist_pass": true,
  "score": 0.72,
  "red_flags": ["large_unlock_within_14d"],
  "summary": "Quality acceptable but unlock risk requires smaller size."
}
```

### 7.2 News pulse adapter

Trigger when any condition is true:

- 24h price move exceeds configured threshold.
- Funding rate spikes.
- Open interest jumps.
- Confluence flips sharply.
- LLM would enter after a large one-direction move.

Output:

```json
{
  "nature": "value_event|sentiment|technical|unknown|mixed",
  "primary_cause": "...",
  "confidence": 0.0,
  "trade_implication": "avoid_chase|normal|watch_for_reversal",
  "sources": []
}
```

### 7.3 Thesis tracker adapter

Maintain per-symbol thesis:

```json
{
  "symbol": "BTC-USDT-SWAP",
  "active_thesis": "Higher timeframe trend intact; pullbacks are buyable while 1d EMA structure holds.",
  "core_assumptions": [
    "1d and 1w trend do not conflict",
    "funding remains below stress threshold",
    "no exchange or regulatory shock"
  ],
  "red_lines": [
    "1d closes below EMA50 with volume expansion",
    "funding spike plus OI unwind",
    "validator rejection for stale entry or R:R"
  ],
  "health_score": 8
}
```

### 7.4 Portfolio review adapter

Use open positions and current candidate trade to flag:

- too many same-direction trades,
- hidden sector correlation,
- long/short imbalance,
- high beta cluster,
- drawdown regime mismatch.

This duplicates some existing scheduler protection but adds a research-language
explanation and can reduce `suggested_size_multiplier`.

---

## 8. Prompt Integration

Add an optional section to `trading/auto/prompts.py`:

```text
## Berkshire advisory context
- Verdict: caution
- Bias: neutral
- Confidence: 0.62
- Information richness: B
- Key risk flags: large unlock, recent move unexplained
- Invalidates if: funding spikes above X, 1d close below EMA50
- Sizing hint: reduce size, never increase beyond hard caps
```

Rules for prompt text:

- Keep under roughly 250 words.
- No chain-of-thought from the advisory model.
- Include facts, flags, and final advisory verdict only.
- Tell LLM explicitly that validator hard rules still dominate.

---

## 9. Scheduler Integration

Minimal implementation in `run_once_symbol()`:

1. After confluence/regime are available, build `BerkshireResearchRequest`.
2. Call advisor only if `BERKSHIRE_ADVISOR_MODE != off`.
3. Journal `berkshire_advisory` result.
4. In `prompt`/`gate`, pass report to `build_user_prompt()`.
5. In `gate`, after validator accepts LLM proposal:
   - clamp multiplier,
   - recompute `position_size_units`,
   - append `berkshire_size_adjustment` to journal.

No direct import from external clone at runtime. Vendored templates and local
typed adapters only.

---

## 10. Data Validation Rules

Borrow AI Berkshire's "no LLM mental math" discipline:

- Any arithmetic used for position or risk must remain in existing bracket and
  validator code.
- Advisory calculations must use `Decimal` when money/size precision matters.
- Key external data points need source metadata.
- If two sources disagree beyond tolerance, mark risk flag instead of guessing.
- Missing data means `information_richness = "C"` and conservative output.

For crypto-specific future sources, prefer:

- exchange market data,
- OKX funding/open interest,
- token unlock calendars,
- official project announcements,
- reputable market/news feeds.

Secrets remain in `.env` / operator config, never in repo docs.

---

## 11. Implementation Plan

### Phase 1: Design and local contracts

- Create `trading/research/berkshire/models.py`.
- Create pure helpers for:
  - clamp multiplier,
  - normalize verdict,
  - render prompt summary,
  - fallback neutral report.
- Add unit tests for schema and safety semantics.

### Phase 2: Shadow advisor

- Add `advisor.py` that derives conservative advisory from existing local data:
  regime, confluence, journal, open positions.
- Do not use network in the first slice.
- Write advisory events to `VIBE_TRADING_HOME/research/berkshire/advisory_events.jsonl`.
- Add scheduler shadow-mode call.

### Phase 3: Prompt integration

- Extend `build_user_prompt()` to accept optional `berkshire_advisory`.
- Include compact context when mode is `prompt` or `gate`.
- Unit test prompt with and without advisory.

### Phase 4: Gate mode in paper only

- Apply multiplier after validator pass.
- Add tests proving multiplier can only reduce size.
- Add journal evidence.
- Keep `BERKSHIRE_ADVISOR_MODE=shadow` as default until paper metrics justify escalation.

### Phase 5: External data and AI Berkshire templates

- Vendor selected prompt templates under `trading/research/berkshire/templates/`.
- Add MIT attribution notice.
- Add optional external data collectors behind explicit env flags.
- Add report audit if generated markdown reports become part of the workflow.

---

## 12. Tests

### Unit

- `test_neutral_fallback_on_invalid_report`
- `test_multiplier_clamped_to_zero_one`
- `test_multiplier_never_increases_size`
- `test_prompt_context_omitted_when_off_or_shadow`
- `test_prompt_context_included_when_prompt_mode`
- `test_information_richness_c_sets_conservative_flags`
- `test_news_pulse_unknown_does_not_create_directional_bias`
- `test_portfolio_review_flags_same_direction_cluster`

### Integration

- Scheduler with advisor disabled behaves exactly like current path.
- Scheduler with shadow mode journals advisory and does not alter prompt/size.
- Scheduler with prompt mode includes context but validator still rejects invalid
  LLM proposals.
- Scheduler with gate mode reduces position size only after validator pass.

### Regression

- Existing `pytest -x` must pass.
- Existing confluence tests must still pass.
- Existing scheduler safety tests must still pass.

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Value-investing framework conflicts with short-term futures | Bad trade reasoning | Treat as advisory only; no direct order placement |
| LLM narrative bias increases confidence | Oversizing | Multiplier can only reduce size; validator hard caps unchanged |
| External research stale | Wrong context | TTL cache; timestamps in prompt; stale data falls back to unknown |
| Markdown skill output too unstructured | Parser failures | Convert to typed JSON contracts before runtime use |
| Prompt grows too large | Higher LLM cost and weaker JSON reliability | Compact summary under 250 words |
| Licensing attribution missed | Compliance risk | Add MIT notice if code/templates are vendored |
| Network/provider failures | Runtime instability | Fail neutral and journal warning |

---

## 14. Acceptance Criteria

- `trading/docs/features/ai-berkshire-advisory-layer/design.md` exists.
- Feature has a typed JSON contract before any code implementation.
- Design explicitly states AI Berkshire cannot place orders or override hard rules.
- Integration points are mapped to current Trade_V1 files.
- Runtime modes are defined with safe defaults.
- Test plan covers disabled, shadow, prompt, and gate behavior.
- Future implementation can proceed in small phases without changing live defaults.

---

## 15. Open Decisions

1. Should the first implementation be `shadow` only, or should `prompt` mode be
   available behind env flag in the same story?
2. Which external data provider should power catalyst/news pulse for crypto:
   OKX-only public data, paid news API, or curated manual feeds?
3. Should generated research reports be shown in the dashboard, or only stored
   as JSON events initially?

Recommended first answer: implement `shadow` first. After tests and a week of
paper evidence, enable `prompt`; only later consider `gate`.
