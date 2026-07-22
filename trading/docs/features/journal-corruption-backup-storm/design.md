# Journal Corruption Backup Storm Recovery

Role: implementation design; canonical journal behavior is defined in
`trading/docs/architecture/JOURNAL_CONTRACTS.md`.

## Problem

The runtime `positions.json` can be corrupted when overlapping writers replace
the same file non-atomically. The trader status endpoint then fails closed, but
every frontend poll copies the identical corrupt file to a new timestamped
backup. This creates thousands of redundant files, slows status requests, and
makes the frontend appear frozen while the API still returns HTTP 200.

## Contract

- Mutable journal JSON is written to a unique sibling temporary file and then
  atomically replaces the target.
- Identical corrupt `positions.json` bytes create at most one content-addressed
  backup, including across repeated polls and process restarts.
- Corruption continues to fail closed; it is never converted to an empty
  positions list.
- The web shell preserves the last good trader snapshot and shows the current
  status error instead of silently rendering empty data.
- Repair keeps the valid decoded positions prefix only after an explicit
  runtime inspection and preserves the original corrupt bytes in a manual
  backup.

## Verification

- Journal tests cover atomic replacement and backup deduplication.
- Frontend tests/build cover status-error rendering and shared polling.
- Docker rebuild and live smoke require a parseable status payload, healthy
  container, and responsive `/trader` page.

## Safety

No live mode, risk limit, signal route, verifier, compiler, or exchange guard
changes. Corrupt position state remains a hard no-new-entry condition.
