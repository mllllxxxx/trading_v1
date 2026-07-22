"""Show recent decisions for all 4 symbols."""
import sys
import json
sys.path.insert(0, '/app/auto')
import journal

journal.ensure_dirs()
with journal.DECISIONS_LOG.open() as f:
    decisions = [json.loads(line) for line in f if line.strip()]

# Count per symbol
by_symbol = {}
for d in decisions:
    sym = d.get("symbol", "n/a")
    by_symbol.setdefault(sym, []).append(d)

print("=== Decisions per symbol ===")
for sym, decs in by_symbol.items():
    last_skip = next((d for d in reversed(decs) if d.get("type") == "skip"), None)
    print(f"\n[{sym}]: {len(decs)} decisions")
    if last_skip:
        print(f"  last skip: {last_skip.get('reason')}")
        if last_skip.get("score") is not None:
            print(f"    score: {last_skip.get('score')}")

# Show latest 8
print()
print("=== Latest 8 decisions ===")
for d in decisions[-8:]:
    ts = d.get("ts", "?")[:19]
    dt = d.get("type", "?")
    sym = d.get("symbol", "")
    reason = d.get("reason", "")[:30]
    print(f"  [{ts}] {dt:20} {sym:10} {reason}")
