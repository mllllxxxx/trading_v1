"""Generate backtest report (text + JSON) without shell redirect issues."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest import fetch_data
from backtest.engine import backtest_combined

UNIVERSE_FULL = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "BNB-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP", "AVAX-USDT-SWAP",
    "TRX-USDT-SWAP", "LINK-USDT-SWAP",
]
UNIVERSE_TOP6 = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP",
    "BNB-USDT-SWAP", "XRP-USDT-SWAP", "TRX-USDT-SWAP",
]

DAYS = 180
PARAMS = dict(
    starting_capital=500.0,
    risk_pct=0.01,
    sl_atr_mult=2.0,
    sl_min_pct=3.0,
    tp_rr=3.0,
    decision_every_n_bars=6,
)


def run(name, symbols):
    print(f"\n[{name}] Fetching {len(symbols)} symbols × {DAYS}d...")
    t0 = time.time()
    # Use the public API directly per symbol (cache-aware)
    d = {}
    for s in symbols:
        try:
            d[s] = fetch_data.fetch_candles_cached(s, bar="1H", days=DAYS)
        except Exception as e:
            print(f"  skip {s}: {e}")
    print(f"  fetched {len(d)} symbols in {time.time()-t0:.1f}s")
    cr = backtest_combined(d, max_concurrent=3, **PARAMS)
    return cr


def summarize(name, cr):
    sym_sharpes = [(s, r.sharpe) for s, r in cr.per_symbol.items() if r.trades]
    n_pass = sum(1 for _, sh in sym_sharpes if sh >= 0.8)
    print(f"\n{'='*70}\n{name}\n{'='*70}")
    print(f"  Symbols:        {len(cr.per_symbol)}")
    print(f"  Total trades:   {cr.n_trades}")
    print(f"  PnL:            ${cr.total_pnl:+.2f}  ({cr.total_return_pct:+.2f}%)")
    print(f"  MaxDD:          {cr.max_drawdown_pct*100:.1f}%")
    print(f"  Sharpe:         {cr.sharpe:.2f}")
    print(f"  Sortino:        {cr.sortino:.2f}")
    print(f"  Win rate:       {cr.win_rate*100:.1f}%")
    print(f"  Profit factor:  {cr.profit_factor:.2f}")
    print(f"  per-symbol Sharpe >= 0.8: {n_pass}/{len(sym_sharpes)} pass")
    gates = {
        "per_symbol_sharpe_0.8": n_pass >= len(sym_sharpes) * 0.5,
        "combined_sharpe_1.0":   cr.sharpe >= 1.0,
        "max_dd_0.08":           cr.max_drawdown_pct <= 0.08,
    }
    print("  Gates:")
    for k, v in gates.items():
        print(f"    {'PASS' if v else 'FAIL'}  {k}")
    return {
        "name": name,
        "n_symbols": len(cr.per_symbol),
        "n_trades": cr.n_trades,
        "pnl_usd": cr.total_pnl,
        "pnl_pct": cr.total_return_pct,
        "max_dd_pct": cr.max_drawdown_pct,
        "sharpe": cr.sharpe,
        "sortino": cr.sortino,
        "win_rate": cr.win_rate,
        "profit_factor": cr.profit_factor,
        "per_symbol_sharpe_pass": n_pass,
        "per_symbol_sharpe_total": len(sym_sharpes),
        "gates": gates,
        "per_symbol": {
            s: {"trades": len(r.trades), "sharpe": r.sharpe,
                "pnl": r.final_equity - 500, "win_rate": r.win_rate,
                "max_dd": r.max_drawdown_pct}
            for s, r in cr.per_symbol.items()
        },
    }


if __name__ == "__main__":
    results = {}
    cr1 = run("FULL UNIVERSE (top 10)", UNIVERSE_FULL)
    results["top10"] = summarize("FULL UNIVERSE (top 10)", cr1)
    cr2 = run("FILTERED UNIVERSE (top 6 profitable)", UNIVERSE_TOP6)
    results["top6"] = summarize("FILTERED UNIVERSE (top 6 profitable)", cr2)

    out_path = Path("backtest/results_compare.json")
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults saved: {out_path}")
