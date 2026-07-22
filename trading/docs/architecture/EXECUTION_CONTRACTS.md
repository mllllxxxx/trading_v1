# Execution Contracts

Execution policy is authored in canonical product docs, config profiles, hard
rulebook records, and schemas. Runtime code may enforce these contracts, but it
must not become the only source of policy.

## Decision Boundary

The LLM may produce a `TradeDecisionTicket`. It may not:

- call broker APIs;
- choose final executable quantity;
- bypass verifier or compiler;
- override hard rules;
- switch paper/testnet mode to live mode.

## Required Order Path

New executable orders must follow this sequence:

```text
MarketDossier
  -> RetrievedRuleContext
  -> TradeDecisionTicket
  -> CriticReview
  -> VerifierResult(passed=true)
  -> CompiledOrder
  -> execution adapter
```

Broker execution is allowed only after both verifier and compiler succeed.
The active executable target is OKX demo/paper/testnet. Live execution remains
blocked until `trading/docs/product/LIVE_READINESS.md` and reviewed evidence
explicitly permit promotion.

An approved demo-only scoring canary may choose between the canonical V1 score
and a review-ready V2 score before this required order path starts. It may not
bypass dossier validation, LLM review for gray-zone candidates, critic,
verifier, compiler, broker guards, or portfolio limits. V2 reject is a veto and
must not create an order. Canary routing is limited to deterministic
V1/V2-zone disagreements, the canonical allocation rate, reduced risk, and one
concurrent canary position globally.

## Compiler Responsibilities

The risk/order compiler must:

- derive side from `TradeDecisionTicket.action`;
- require numeric entry, stop-loss, and take-profit levels before execution;
- preserve enough decimal precision for sub-dollar instruments so compiler
  serialization cannot collapse distinct entry, stop-loss, or take-profit
  levels into the same price;
- calculate risk amount from equity and stop distance;
- calculate executable quantity itself;
- clamp risk and notional to hard-rule limits;
- reject orders below the hard-rule reward-to-risk minimum;
- fail closed if compiled hard rules are missing or malformed.

## Execution Adapter Responsibilities

Adapters receive `CompiledOrder` only. They must keep broker-specific behavior
outside scheduler and outside LLM prompts. Paper/testnet guards remain active
for the current system direction. A live adapter must remain inert until a
separate live-readiness approval exists.

The adapter interface lives under `trading/execution/`. Paper and replay
adapters may simulate acceptance, but live broker adapters must remain inert
until explicitly implemented and approved.

## OKX Demo Adapter

The OKX executable target for this phase is demo/testnet only. The adapter must:

- accept only `CompiledOrder`;
- require demo flags such as `OKX_TESTNET=true` and `OKX_SANDBOX=true`;
- refuse missing credentials or live-like environment settings;
- convert canonical symbols to the broker-specific OKX swap proposal inside the
  adapter boundary;
- use the existing futures bracket validator before submitting;
- submit swap entries through OKX `/api/v5/trade/order` with attached TP/SL
  legs via `attachAlgoOrds`, not as a standalone `/api/v5/trade/order-algo`
  trigger order;
- return a structured `OrderResult` with broker ids when available;
- treat accepted entry orders as pending until OKX reports matching active
  futures exposure; broker acceptance is not the same thing as entry fill;
- expire an unfilled pending entry after `AUTO_PENDING_ENTRY_TTL_S` (default
  `3600` seconds), cancel it on OKX demo when it is still open, and remove its
  pending journal row without recording a closed trade or PnL outcome;
- preserve a pending row when broker order status or cancellation is uncertain,
  rather than pretending the order was canceled;
- when the entry order is confirmed filled but a clean exchange snapshot shows
  no active exposure, remove it from active positions as an unresolved outcome,
  journal the broker fill evidence, and exclude it from performance metrics
  until exit evidence can be reconstructed; do not invent an exit or PnL;
- resolve exchange instrument metadata for the exact swap symbol before
  submitting futures orders; OKX quantity is contracts, and `contract_size` plus
  `min_qty` plus `qty_step` are broker facts, not scanner or prompt policy;
- quantize contract quantity down to the broker `lotSz`/quantity step; do not
  coerce contracts to integers because OKX demo instruments such as BTC and ETH
  allow fractional contract quantities;
- in demo/testnet mode, build the ranked universe from OKX ticker responses
  carrying `x-simulated-trading: 1`; live-only instruments must not reach LLM
  promotion or execution merely because they exist in the public live catalog;
- request the complete swap ticker catalog with `instType=SWAP` and filter
  `*-USDT-SWAP` locally; do not send `uly=USDT`, because `uly` is an underlying
  identifier and that invalid query can collapse universe loading to fallback;
- resolve from CCXT markets first, then use the OKX public instruments endpoint
  for the exact `instId` when the demo/sandbox CCXT catalog omits that swap;
- set leverage through the signed OKX `/api/v5/account/set-leverage` endpoint
  using the exact native swap `instId`; execution must not require CCXT to map
  a dynamic symbol after exact broker metadata has already been resolved;
- accept public fallback metadata only when OKX returns code `0`, the requested
  `instId`, positive `ctVal`, and positive `minSz` or `lotSz`;
- fail closed for dynamic symbols when contract metadata cannot be resolved
  instead of silently assuming `contract_size=1`;
- never let the LLM or scanner provide raw broker payloads.

## Runtime Evidence

Every future execution path must journal enough lifecycle data to replay the
decision: dossier, retrieved rules, ticket, critic result, verifier result,
compiled order, and execution result.

Before any adapter submits an approved open-position order, the runtime must
journal `trade_open_rationale`. That event explains why the trade was opened and
captures the market context used at decision time: source signal reasons,
ticket thesis, rule/playbook citations, regime, confluence, data quality,
spread/funding state, price levels, and compiled risk.

Demo execution results must also be tied back to the source `SignalCandidate`
when one exists so review and optimizer reports can measure performance by
signal source, playbook, regime, and symbol.

## Exchange Reconciliation

For demo/testnet futures, currently open broker exposure is exchange-truth-first.
The journal remains the replayable local ledger, but it must be reconciled from
OKX demo state when the two disagree.

Runtime reconciliation must:

- normalize canonical symbols, OKX native swap symbols, and CCXT swap symbols
  before comparing positions;
- treat active OKX demo positions as open exposure even if `positions.json` is
  empty or stale;
- reject a second active or pending local owner for the same OKX demo symbol,
  because exchange positions are not isolated by strategy team;
- repair missing local journal positions from active exchange positions with a
  clear `exchange_reconciled` marker;
- run on process/container startup and operator resume before any scheduler can
  open new demo orders;
- preserve journal positions on shutdown and never use shutdown as a flatten or
  clear signal;
- block new entries when startup/resume reconciliation cannot read OKX demo
  state, while leaving local journal positions intact;
- block new same-symbol demo execution when either journal or exchange exposure
  already exists;
- avoid closing local futures positions unless clean exchange snapshots confirm
  no matching active exposure beyond the first startup or retry cycle;
- expose sync health to dashboards so operators can see journal/exchange drift.

## Account State For Dashboards

For demo/testnet dashboards, current account equity is also exchange-truth-first.
Runtime dashboards should prefer a read-only OKX demo/testnet account snapshot
for current capital, available balance, margin use, and open unrealized PnL.
The local journal remains the realized/replay ledger and compatibility fallback.

Dashboard account state must:

- read only from demo/testnet account endpoints or sandbox-capable exchange
  clients;
- avoid blocking the dashboard request path on every frontend poll; repeated
  dashboard reads may use a short-lived read-only exchange snapshot cache while
  refreshing exchange state in the background;
- keep live trading guards unchanged;
- return a structured fallback from journal stats when account reads fail;
- keep journal `stats` available for history, replay, and older consumers;
- surface the source and sync timestamp so operators can distinguish exchange
  truth from journal fallback, including cache age/status when cached data is
  used.

## Paused Control Plane

The manual kill switch prevents new entry execution but must not terminate the
process that hosts read-only dashboards and Telegram. While paused, exchange
reconciliation and protective monitoring of existing demo/testnet positions
remain available. Resume must complete reconciliation before clearing the
manual guard. No observability callback may create, close, reduce, or cancel a
position.
