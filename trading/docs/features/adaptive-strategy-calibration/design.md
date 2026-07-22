# Adaptive Strategy Calibration

## Status

Approved for observe-only diagnostics. Strategy-specific runtime activation is
not authorized in this phase.

## Problem

The four strategy teams do not produce identically distributed raw scores.
Their conflict-free base ranges and feature increments differ, so a robust
global threshold may still route one strategy too aggressively and another too
conservatively. Global segment-stability gates prevent obvious harm but cannot
show each strategy's preferred strong/gray boundary.

## Evidence And Isolation

Diagnostics use only the same calibration-eligible `shadow` and `backtest`
records accepted by the global evaluator. Each strategy is evaluated in
isolation using its own chronological 70/30 split. Outcomes from another
strategy cannot satisfy its sample gate, confidence interval, validation, or
LLM review-health evidence.

Default canonical gates are:

- mode `observe_only`;
- at least `80` eligible outcomes for the strategy;
- at least `20` complete-sample outcomes in both proposed strong and gray
  zones;
- the evaluator's existing minimum `8` validation outcomes in both zones;
- the same confidence, profit-factor, drawdown/tail, and robustness rules as
  global threshold evaluation.

## Output Contract

`strategy_threshold_diagnostics` is keyed by stable `strategy_id`. Each compact
entry contains:

- eligible count and status;
- current effective global zones used as its baseline;
- insufficiency reasons;
- optional recommended strong/gray zones;
- changed flag, objective gain, validation delta, and compact robustness;
- compact LLM review-health status for that strategy.

The output excludes full candidate rankings and raw outcomes from
`/api/trader/status`.

## Safety Boundary

Diagnostics never write controller state, canonical config, risk limits, or
broker orders. The global controller must ignore strategy recommendations in
this phase. A future per-strategy activation contract requires explicit
governance, independent confirmations, per-strategy rollback, and immutable
multi-team snapshot semantics.

## Tests

- a sparse strategy cannot borrow another strategy's outcomes;
- each strategy keeps a separate chronological split and recommendation;
- strategy diagnostics do not recursively generate nested diagnostics;
- zone override changes each strategy's current baseline without mutating
  canonical config;
- API payload remains compact and broker/LLM-free.
