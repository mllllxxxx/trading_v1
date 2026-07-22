# Short Confluence Path

## Goal

Fix the scheduler pre-filter so signed confluence works in both directions:

- `abs(score) < min_confluence` means weak/no candidate;
- positive score is a long candidate;
- negative score is a short candidate;
- score `0` is no candidate.

## Scope

- Add a scheduler helper for confluence direction classification.
- Replace the legacy positive-only gate in `run_once_symbol`.
- Remove the `bearish_confluence` skip path that made the scheduler effectively
  long-only.
- Log `candidate_direction` and `candidate_side` before regime checks.
- Add candidate direction fields to LLM prompt context.
- Update confluence/trading README text that still says `>= +2` only.
- Add scheduler tests for long, short, weak, and regime conflict paths.

## Non-Goals

- Do not integrate the full MarketDossier pipeline into scheduler yet.
- Do not change broker execution guards.
- Do not change position sizing, validator, risk compiler, or live readiness.
- Do not enable live trading.

## Safety

The change only opens the previously blocked short-candidate path when confluence
is strong enough and regime agrees with the candidate direction. Direction/regime
conflicts still fail closed with a skip.

## Validation Plan

- Targeted scheduler tests.
- Full `scripts/verify-trading-tests.ps1`.
- Docker build/up and `/health`.
