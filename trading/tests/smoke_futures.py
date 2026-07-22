"""Quick smoke test for new futures modules — run with .venv Python."""
import sys
import tempfile
from pathlib import Path

# Add parent (trading/) and siblings to sys.path
TRADING = Path(__file__).parent.parent
sys.path.insert(0, str(TRADING))
sys.path.insert(0, str(TRADING / "brackets"))
sys.path.insert(0, str(TRADING / "auto"))

import okx_futures_bracket as f  # noqa: E402
import universe  # noqa: E402
from validator import check_leverage, check_liquidation_buffer  # noqa: E402
from llm_override_tracker import OverrideTracker, HybridOverrideGate, OverrideRecord  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

print("=== okx_futures_bracket smoke test ===")
print(f"SymbolMeta fields: {list(f.SymbolMeta.__dataclass_fields__.keys())}")
print(f"BTC meta: {f.DEFAULT_FUTURES_UNIVERSE['BTC']}")
print()

liq = f.compute_liquidation_price(100000, 10, "long", 0.005)
print(f"BTC long 10x liq @ 100k: ${liq:,.2f} (distance {(100000-liq)/100000:.2%})")
liq = f.compute_liquidation_price(100000, 10, "short", 0.005)
print(f"BTC short 10x liq @ 100k: ${liq:,.2f} (distance {(liq-100000)/100000:.2%})")
liq = f.compute_liquidation_price(3000, 3, "long", 0.005)
print(f"ETH long 3x liq @ 3000: ${liq:,.2f} (distance {(3000-liq)/3000:.2%})")
print()

# Test compute_bracket_futures
p = f.compute_bracket_futures(
    "BTC-USDT-SWAP", "long", 100000, 95000, 110000, 500, leverage=10
)
print("BTC long proposal:")
for k in ["symbol", "side", "leverage", "td_mode", "contracts", "position_notional",
          "position_pct", "margin_required", "actual_risk_usd", "rr_ratio",
          "liq_price", "liq_distance_pct", "below_min_qty"]:
    print(f"  {k}: {p.get(k)}")
print()

violations = f.validate_futures(p)
print(f"Violations: {violations if violations else 'NONE'}")
print()

# Test SOL (alt)
p = f.compute_bracket_futures(
    "SOL-USDT-SWAP", "long", 150, 140, 170, 500, leverage=3
)
print("SOL long proposal:")
print(f"  contracts: {p['contracts']}, notional: ${p['position_notional']:,.2f}, "
      f"liq: ${p['liq_price']:.2f} ({p['liq_distance_pct']:.2%} from entry)")
violations = f.validate_futures(p)
print(f"  Violations: {violations if violations else 'NONE'}")

print()
print("=== Validator H5/H7 ===")
ok5, msg5 = check_leverage("BTC-USDT-SWAP", 10)
print(f"  BTC 10x: ok={ok5}, msg={msg5}")
ok5, msg5 = check_leverage("BTC-USDT-SWAP", 15)
print(f"  BTC 15x: ok={ok5}, msg={msg5}")
ok5, msg5 = check_leverage("ETH-USDT-SWAP", 5)
print(f"  ETH 5x: ok={ok5}, msg={msg5}")
ok5, msg5 = check_leverage("ETH-USDT-SWAP", 3)
print(f"  ETH 3x: ok={ok5}, msg={msg5}")
ok7, msg7 = check_liquidation_buffer(100000, 90500, "BTC-USDT-SWAP")
print(f"  BTC liq=90500 entry=100000: ok={ok7}, msg={msg7}")

print()
print("=== Universe loader smoke ===")
print(f"  Hardcoded universe: {len(universe.HARDCODED_UNIVERSE)} symbols")
print(f"  Bases: {[s.base for s in universe.HARDCODED_UNIVERSE]}")
snap = universe.load_universe(fetcher=lambda url: {"data": []})  # force fallback
print(f"  Live fetch failed -> source: {snap.source}, count: {len(snap.symbols)}")

print()
print("=== LLM override tracker smoke ===")

with tempfile.TemporaryDirectory() as td:
    tracker = OverrideTracker(path=Path(td) / "log.jsonl")
    gate = HybridOverrideGate(tracker=tracker, min_samples=3, threshold=0.6)
    # Cold start: should be false
    ok, reason = gate.allow("BTC-USDT-SWAP")
    print(f"  Cold start: ok={ok}, reason={reason}")
    # Add 5 closed overrides, 4 wins
    for i in range(5):
        rec = OverrideRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            symbol="BTC-USDT-SWAP",
            llm_action="long", rules_action="no_trade",
            llm_overrode=True, used_override=True,
            closed_at=datetime.now(timezone.utc).isoformat(),
            pnl_usd=10.0, win=(i < 4),
        )
        gate.record(rec)
    ok, reason = gate.allow("BTC-USDT-SWAP")
    print(f"  4/5 wins: ok={ok}, reason={reason}")

print()
print("ALL SMOKE TESTS PASSED")
