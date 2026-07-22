"""Verify all 4 symbols are being processed."""
import json
import sys
sys.path.insert(0, '/app/auto')
import journal
journal.ensure_dirs()
with journal.DECISIONS_LOG.open() as f:
    decisions = [json.loads(line) for line in f if line.strip()]

# Get recent decisions (last 3 min)
recent = [d for d in decisions if d.get("ts", "") > "2026-06-21T10:00"]
print(f"Total recent (last 3 min): {len(recent)}")
print()

# Count by symbol + type
by_sym = {}
for d in recent:
    s = d.get("symbol", "(global)")
    dt = d.get("type", "?")
    by_sym.setdefault(s, {})
    by_sym[s][dt] = by_sym[s].get(dt, 0) + 1

print("=== Per-symbol activity ===")
for s in sorted(by_sym.keys()):
    types_str = ", ".join(f"{k}:{v}" for k, v in by_sym[s].items())
    print(f"  [{s}]: {types_str}")
print()

# Show 1 cycle worth of decisions (last 20)
print("=== Last 20 decisions ===")
for d in decisions[-20:]:
    ts = d.get("ts", "?")[:19]
    dt = d.get("type", "?")
    sym = d.get("symbol", "")
    reason = d.get("reason", "")
    score = d.get("score", "")
    score_str = f" score={score}" if score != "" else ""
    print(f"  [{ts}] {dt:18} {sym:12} {reason}{score_str}")
