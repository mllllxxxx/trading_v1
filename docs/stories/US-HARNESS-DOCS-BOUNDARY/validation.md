# Validation

Role: story validation

## Proof Strategy

Use static tests to prevent process docs from becoming trading runtime context,
then run the canonical trading unit suite and rulebook compiler check.

## Test Plan

| Layer | Cases |
| --- | --- |
| Unit | Boundary tests for AGENTS/README policy leakage, Harness banners, runtime denylist, and compiler source root |
| Integration | Rulebook compiler freshness check |
| E2E | Not applicable |
| Platform | Not applicable |
| Performance | Not applicable |
| Logs/Audit | Harness intake and decision records |

## Fixtures

No external fixtures required.

## Commands

```text
pytest -q trading\tests\test_source_of_truth_boundaries.py
python trading\rulebook\compile_rulebook.py --check
pytest -x
git diff --check
```

## Acceptance Evidence

- `pytest -q trading\tests\test_source_of_truth_boundaries.py`: 5 passed.
- `python trading\rulebook\compile_rulebook.py --check`: passed with 21 source records.
- `pytest -x`: 143 passed.
- `git diff --check`: passed, with only normal Windows CRLF warnings.
