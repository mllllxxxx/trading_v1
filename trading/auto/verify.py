"""Verify internal services and connectivity."""
import sys
sys.path.insert(0, '/app/auto')
import os
import json
import ccxt
import journal

journal.ensure_dirs()

# 1. Check services via journal
with journal.DECISIONS_LOG.open() as f:
    decisions = [json.loads(line) for line in f if line.strip()]
starts = [d for d in decisions if d.get("type") in ("start", "unified_start", "auto_start")]
vibes = [d for d in decisions if d.get("type") in ("vibe_starting", "vibe_ready")]
dashboards = [d for d in decisions if d.get("type") in ("dashboard_start", "dashboard_ready")]

print("=== Service startup events ===")
print(f"  Startup events: {len(starts)}")
print(f"  Vibe-Trading events: {len(vibes)} ({vibes[-1]['type'] if vibes else 'none'})")
print(f"  Dashboard events: {len(dashboards)} ({dashboards[-1]['type'] if dashboards else 'none'})")
unified = [d for d in decisions if d.get("type") == "unified_ready"]
if unified:
    last = unified[-1]
    print(f"  Last unified_ready: ports={last.get('vibe_port')}/{last.get('dashboard_port')}")
    print(f"    threads={last.get('all_threads')}")
print()

# 2. OKX connectivity
print("=== OKX connector ===")
key = os.environ.get("OKX_API_KEY", "")
secret = os.environ.get("OKX_API_SECRET", "")
pwd = os.environ.get("OKX_PASSPHRASE", "")
print(f"  API key: {'set' if key else 'missing'} ({len(key)} chars)")
print(f"  Secret: {'set' if secret else 'missing'}")
print(f"  Passphrase: {'set' if pwd else 'missing'}")
try:
    ex = ccxt.okx({
        "apiKey": key, "secret": secret, "password": pwd,
        "sandbox": True, "enableRateLimit": True,
        "options": {"defaultType": "spot"}
    })
    ticker = ex.fetch_ticker("BTC/USDT")
    print(f"  BTC/USDT: ${ticker['last']:,.2f}")
except Exception as e:
    print(f"  Error: {e}")
print()

# 3. DeepSeek
print("=== DeepSeek LLM ===")
print(f"  DEEPSEEK_API_KEY: {'set' if os.environ.get('DEEPSEEK_API_KEY') else 'missing'}")
print(f"  DEEPSEEK_BASE_URL: {os.environ.get('DEEPSEEK_BASE_URL', 'default')}")
print(f"  AUTO_LLM_MODEL: {os.environ.get('AUTO_LLM_MODEL', 'deepseek-chat (default)')}")
print()

# 4. Recent decisions
print("=== Last 5 decisions ===")
for d in decisions[-5:]:
    ts = d.get("ts", "?")[:19]
    dtype = d.get("type", "?")
    print(f"  [{ts}] {dtype}")
print()

# 5. Kill switch
print("=== Kill switch ===")
print(f"  Active: {journal.is_killed()}")
if journal.KILL_SWITCH.exists():
    print(f"  File: {journal.KILL_SWITCH}")
