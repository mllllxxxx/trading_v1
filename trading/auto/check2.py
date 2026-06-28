import json
import sys
sys.path.insert(0, '/app/auto')
import journal

journal.ensure_dirs()
with journal.DECISIONS_LOG.open() as f:
    all_decisions = [json.loads(l) for l in f if l.strip()]

# Show recent decisions with symbols
recent = [d for d in all_decisions if d.get("ts", "") > "2026-06-21T09:59"]
print(f"Total recent: {len(recent)}")
print()

# Count by symbol
by_sym = {}
for d in recent:
    s = d.get("symbol", "(no symbol)")
    by_sym.setdefault(s, 0)
    by_sym[s] += 1
print("Decisions per symbol (last 2 min):")
for s, n in by_sym.items():
    print(f"  {s}: {n}")
print()

# Show last 12
print("Last 12 decisions:")
for d in recent[-12:]:
    ts = d.get("ts", "?")[:19]
    dt = d.get("type", "?")
    sym = d.get("symbol", "")
    reason = d.get("reason", "")
    if not reason and dt == "llm":
        reason = f"action={d.get('action')}"
    print(f"  [{ts}] {dt:20} sym={sym:12} {reason[:50]}")
