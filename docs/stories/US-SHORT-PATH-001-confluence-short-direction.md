# US-SHORT-PATH-001 Confluence Short Direction

## Status

implemented

## Lane

high-risk

## Product Contract

Trade_V1 must treat confluence as a signed directional signal. Strong negative
confluence is a short candidate, not an automatic skip. Weak absolute
confluence remains a fail-closed no-trade gate.

## Relevant Product Docs

- `docs/specs/trading_v1_llm_governed_refactor_spec.md`
- `trading/docs/architecture/DECISION_FLOW.md`
- `trading/docs/product/AUTONOMY_POLICY.md`
- `trading/confluence/README.md`
- `trading/README.md`

## Acceptance Criteria

- `+4` classifies as long candidate.
- `-4` classifies as short candidate.
- `+1`, `-1`, and `0` are weak/no candidate when threshold is `2`.
- `score=-3` is not skipped by the positive-only weak gate.
- The old `bearish_confluence` skip path is removed.
- Scheduler logs `candidate_direction=short` for a valid negative candidate.
- Prompt context receives `candidate_direction` and `candidate_side`.
- Direction/regime conflicts skip safely.
- Docs no longer describe scheduler gating as only `>= +2`.

## Design Notes

- Commands: none.
- Queries: none.
- API: scheduler helper `classify_confluence_direction`.
- Tables: unchanged.
- Domain rules: signed confluence interpretation only.
- UI surfaces: unchanged.

## Validation

| Layer | Expected proof |
| --- | --- |
| Unit | Scheduler direction tests |
| Integration | Full trading pytest suite |
| E2E | Not changed in this slice |
| Platform | Docker build/up and `/health` |
| Release | Final compliance audit later |

## Harness Delta

Story and design doc added before code.

## Evidence

- Targeted scheduler and market dossier tests passed 39 tests.
- `scripts/verify-trading-tests.ps1` passed 189 tests.
- `git diff --check` passed with only LF-to-CRLF working-copy warnings.
- `docker compose build` passed.
- `docker compose up -d` started `vibe-trading`; `http://127.0.0.1:8000/health`
  returned 200.
- Container smoke import returned `(True, 'short', 'sell')` for
  `classify_confluence_direction(-4, 2)` and `short` for the generated dossier.
