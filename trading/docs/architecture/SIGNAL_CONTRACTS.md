# Signal Contracts

Signal data is the bridge between market scanners and LLM-governed trading
decisions. A signal can suggest that a setup is worth considering, but it is
not an order and not a final decision.

## Canonical Contract

All signal sources should emit `SignalCandidate` records.

Required meaning:

- `signal_id`: stable id for this generated signal.
- `generated_at`: UTC timestamp.
- `source`: source engine, for example `berkshire_crypto_scanner`.
- `market`: `crypto` first; `forex` later after adapter contracts exist.
- `symbol`: normalized symbol.
- `timeframe`: scanner timeframe or horizon.
- `direction`: `long`, `short`, or `neutral`.
- `status`: `strong_candidate`, `candidate`, `watchlist`, or `blocked`.
- `confidence`: 0.0 to 1.0 signal confidence.
- `confidence_components`: normalized evidence used to compute confidence.
- `score`: 0 to 100 scanner score.
- `grade`: A, B, C, or D source quality grade.
- `action_hint`: `OPEN_LONG`, `OPEN_SHORT`, `HOLD`, or `REQUEST_MORE_DATA`.
- `promotion_gate`: whether the signal can be promoted to a draft ticket.
- `reasons`: human and LLM-readable evidence.
- `blockers`: reasons the signal cannot be promoted.
- `llm_context`: prompt-safe advisory context.
- `evidence`: provider and metric details.

Adaptive hybrid signals should also expose:

- `rule_score`: active deterministic setup score from `0` to `100`;
- `score_components`: normalized, inspectable setup evidence;
- `experimental_scores`: optional shadow-only score evidence keyed by experiment
  ID; it cannot alter active score, zone, confidence, route, or risk;
- `conflicts`: soft strategy disagreements that lower quality;
- `decision_zone`: `strong`, `gray`, or `reject`;
- `confidence_calibrated`: false until replay evidence proves calibration.

Optional team-tournament fields:

- `team_id`: stable strategy-team id, for example `berkshire` or `momentum`.
- `team_name`: operator-facing team name.
- `strategy_id`: stable method id.
- `strategy_name`: operator-facing method name.
- `team_capital_usd`: reporting/sizing capital for the team.
- `risk_min_pct_equity`, `risk_max_pct_equity`, `target_risk_pct_equity`:
  demo risk guidance for this team signal.

Compatibility aliases such as `signal` and `why` may remain while older UI code
uses them, but `status` and `reasons` are the canonical fields.

## Confidence And Ranking

Signal sources must compute confidence as a transparent scanner-confidence
value, not as execution permission. The canonical range is `0.0` to `1.0`.
For strategy-team crypto signals, confidence is derived from normalized,
confirmed OKX candle evidence:

- independent 4H trend and 1H regime strength;
- strategy-specific 1H setup quality and 15m entry confirmation;
- 24h liquidity depth;
- spread quality;
- ATR, RSI, Bollinger, Donchian, volume, and volatility state;
- evidence completeness and blocker penalties.

The scanner should include the evidence in `confidence_components` so the UI,
LLM prompt, journal, and optimizer can explain why one setup outranked another.

When a scan produces more eligible candidates than available portfolio slots,
the scheduler/API must select candidates by:

```text
confidence descending -> score descending -> liquidity descending -> symbol ascending
```

Ranking and promotion always use the active `score`/`rule_score`. An entry in
`experimental_scores`, including `continuous_conflict_v2`, is replay evidence
only and must declare `active_for_routing=false`.

This ranking decides only processing order. Under `adaptive_hybrid_v1`, strong
signals use the explicit deterministic lane, gray signals require LLM review,
and reject signals never call the LLM. Critic, verifier, risk/order compiler,
exchange exposure guard, and journal lifecycle remain mandatory for every
executed order.

## Promotion Rules

A signal may be promoted toward a `TradeDecisionTicket` only when:

- status is `strong_candidate` or `candidate`;
- direction is `long` or `short`;
- action hint matches the direction;
- blockers is empty;
- evidence source is present and not stale;
- the latest confirmed trigger-candle close is no older than 1,080 seconds by
  default (`STRATEGY_MAX_CONFIRMED_CANDLE_AGE_S` may tighten this runtime limit);
- confirmed 15m, 1H, and 4H feature evidence provides numeric regime,
  confluence, entry, stop, and target values;
- the configured decision lane, critic, verifier, and risk compiler all run;
- gray-zone candidates receive a valid LLM context review.

Watchlist and blocked signals may still be useful for context, but they must
not create execution tickets without fresh evidence and a separate decision.

## Demo Promotion Path

The canonical demo promotion path is:

```text
SignalCandidate
  -> MarketDossier
  -> RetrievedRuleContext
  -> deterministic RuleProposal
  -> strong / gray / reject route
  -> optional gray-zone LLM ContextReview
  -> deterministic TradeDecisionTicket
  -> critic
  -> verifier
  -> risk/order compiler
  -> demo/paper execution adapter
  -> journal lifecycle
```

The default implementation may use a broker-free paper adapter, but any OKX
demo adapter must preserve the same boundary: adapter receives only a verified
`CompiledOrder`.

Fail-closed behavior:

- invalid signal schema: no ticket, no execution;
- ineligible signal status: journal `fail_closed_skip`;
- missing numeric entry, stop, or target evidence: journal `fail_closed_skip`;
- gray-zone LLM failure or invalid review: journal `fail_closed_skip`;
- critic/verifier/compiler rejection: journal `fail_closed_skip`;
- adapter failure: journal `execution_result` with failure, no live fallback.

## Source Roles

Berkshire is one signal and research source. It may contribute quality,
inversion, and evidence-risk context, but it cannot place orders.

The strategy-team tournament adds Momentum, Mean Reversion, and Volatility
Breakout as additional signal sources using the same contract. Regime and
confluence must be computed independently from confirmed candles and must never
be inferred from a signal's chosen direction or score. Teams may differ in
setup logic, but not in execution authority.

Team-tagged signals may also carry strategy skill profile metadata, including
preferred playbooks, required soft policies, entry style, avoid conditions, LLM
guidance, and risk personality. These fields are advisory prompt/retrieval
context only; they do not override hard rules, the verifier, or the compiler.

Confluence, regime, alpha-zoo, funding, spread, news, and future forex scanners
should also converge on `SignalCandidate` instead of inventing source-specific
promotion rules.

## Journal Boundary

Signal candidates should be journaled before ticket promotion so later outcome
reviews can answer:

- which signal source found the setup;
- which signal was promoted or skipped;
- whether the LLM overrode the signal;
- whether verifier/risk compiler rejected it;
- whether the eventual demo trade won or lost.

Raw signal history is runtime evidence. It can inform reviews, but it does not
automatically become policy or case memory without curation.
