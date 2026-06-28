"""Backtest CLI — fetch data, run per-symbol and combined, print report.

Usage:
  cd trading
  .venv/Scripts/python -m backtest.run --days 30          # 30-day sanity
  .venv/Scripts/python -m backtest.run --days 180 --combined
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure trading/ is on sys.path so 'backtest' package resolves
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

import pandas as pd  # noqa: E402

from backtest import fetch_data  # noqa: E402
from backtest.engine import (  # noqa: E402
    SymbolResult, backtest_symbol, backtest_combined, CombinedResult,
)


# Default universe (matches the locked top-10 list)
DEFAULT_UNIVERSE = [
    "BTC-USDT-SWAP", "ETH-USDT-SWAP", "BNB-USDT-SWAP", "SOL-USDT-SWAP",
    "XRP-USDT-SWAP", "DOGE-USDT-SWAP", "ADA-USDT-SWAP", "AVAX-USDT-SWAP",
    "TRX-USDT-SWAP", "LINK-USDT-SWAP",
]


def fetch_all(symbols: list[str], days: int, bar: str = "1H",
              use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for all symbols. Use cache when possible."""
    data: dict[str, pd.DataFrame] = {}
    for s in symbols:
        try:
            if use_cache:
                data[s] = fetch_data.fetch_candles_cached(s, bar=bar, days=days)
            else:
                data[s] = fetch_data.fetch_candles(s, bar=bar, days=days)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] {s}: {exc}")
    return data


def print_symbol_report(result: SymbolResult) -> None:
    """One-line summary per symbol."""
    rs = result
    print(f"  {rs.symbol:18s}  trades={len(rs.trades):3d}  "
          f"PnL=${rs.final_equity - 500:+8.2f}  "
          f"WR={rs.win_rate*100:5.1f}%  "
          f"PF={rs.profit_factor:5.2f}  "
          f"Sharpe={rs.sharpe:5.2f}  "
          f"MaxDD={rs.max_drawdown_pct*100:5.1f}%  "
          f"Signals={rs.n_signals:4d} ({rs.n_filtered:4d} filtered)")


def print_combined_report(cr: CombinedResult) -> None:
    print()
    print("=" * 80)
    print("COMBINED BACKTEST REPORT")
    print("=" * 80)
    print(f"Starting capital: ${cr.starting_capital:.2f}")
    print(f"Final equity:     ${cr.final_equity:.2f}")
    print(f"Total PnL:        ${cr.total_pnl:+.2f}  ({cr.total_return_pct:+.2f}%)")
    print(f"Max drawdown:     ${cr.max_drawdown_usd:.2f}  ({cr.max_drawdown_pct*100:.1f}%)")
    print(f"Sharpe (per-trade): {cr.sharpe:.2f}")
    print(f"Sortino:          {cr.sortino:.2f}")
    print(f"Win rate:         {cr.win_rate*100:.1f}%")
    print(f"Profit factor:    {cr.profit_factor:.2f}")
    print(f"Total trades:     {cr.n_trades}")
    print(f"Total signals:    {cr.n_signals_total} ({cr.n_filtered_total} filtered)")
    print()
    print("Gates (per design doc):")
    print(f"  per-symbol Sharpe >= 0.8: ", end="")
    sym_sharpes = [(s, r.sharpe) for s, r in cr.per_symbol.items() if r.trades]
    passing = [s for s, sh in sym_sharpes if sh >= 0.8]
    print(f"{len(passing)}/{len(sym_sharpes)} pass")
    if sym_sharpes:
        for s, sh in sorted(sym_sharpes, key=lambda x: -x[1])[:3]:
            print(f"    top: {s:18s} Sharpe={sh:.2f}")
        for s, sh in sorted(sym_sharpes, key=lambda x: x[1])[:3]:
            if sh < 0.8:
                print(f"    bottom: {s:18s} Sharpe={sh:.2f}")
    print(f"  combined Sharpe >= 1.0:   {'PASS' if cr.sharpe >= 1.0 else 'FAIL'}")
    print(f"  max DD <= 8%:             {'PASS' if cr.max_drawdown_pct <= 0.08 else 'FAIL'}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Trade_V1 backtest CLI")
    parser.add_argument("--days", type=int, default=30,
                        help="Lookback period in days (default 30, gate wants 180)")
    parser.add_argument("--bar", default="1H", help="Candle bar (default 1H)")
    parser.add_argument("--capital", type=float, default=500.0)
    parser.add_argument("--risk-pct", type=float, default=0.01)
    parser.add_argument("--max-concurrent", type=int, default=3)
    parser.add_argument("--no-cache", action="store_true",
                        help="Force refresh from OKX API")
    parser.add_argument("--combined", action="store_true",
                        help="Run combined multi-symbol backtest")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE,
                        help="Symbols to backtest (default: top 10)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of text report")
    parser.add_argument("--sl-min-pct", type=float, default=1.5,
                        help="Min SL %% (default 1.5)")
    parser.add_argument("--sl-atr-mult", type=float, default=1.5,
                        help="SL = max(sl_min_pct, sl_atr_mult * ATR%%) (default 1.5)")
    parser.add_argument("--tp-rr", type=float, default=2.0,
                        help="TP = R:R * SL (default 2.0 = 1:2)")
    parser.add_argument("--max-atr-pct", type=float, default=10.0,
                        help="Skip entries when ATR%% > this (default 10%% = no skip)")
    parser.add_argument("--decision-every", type=int, default=6,
                        help="Decision every N bars (default 6 = 6h on 1H)")
    parser.add_argument("--max-bars", type=int, default=200,
                        help="Force-close after N bars (default 200)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("backtest")

    print(f"Fetching {args.days} days of {args.bar} data for {len(args.symbols)} symbols...")
    t0 = time.time()
    data = fetch_all(args.symbols, args.days, bar=args.bar, use_cache=not args.no_cache)
    print(f"  fetched {len(data)}/{len(args.symbols)} symbols in {time.time()-t0:.1f}s")
    if not data:
        print("No data fetched, aborting.")
        return 1

    print()
    print(f"Per-symbol backtest (capital=${args.capital}, risk={args.risk_pct*100:.1f}%/trade):")
    print("-" * 100)
    per_symbol: dict[str, SymbolResult] = {}
    for sym, df in data.items():
        result = backtest_symbol(
            df, sym,
            starting_capital=args.capital,
            risk_pct=args.risk_pct,
            sl_atr_mult=args.sl_atr_mult,
            sl_min_pct=args.sl_min_pct,
            tp_rr=args.tp_rr,
            decision_every_n_bars=args.decision_every,
            max_bars_in_trade=args.max_bars,
        )
        per_symbol[sym] = result
        if not args.json:
            print_symbol_report(result)

    if args.combined:
        cr = backtest_combined(
            data,
            starting_capital=args.capital,
            risk_pct=args.risk_pct,
            max_concurrent=args.max_concurrent,
            sl_atr_mult=args.sl_atr_mult,
            sl_min_pct=args.sl_min_pct,
            tp_rr=args.tp_rr,
            decision_every_n_bars=args.decision_every,
            max_bars_in_trade=args.max_bars,
        )
        if args.json:
            # Build a JSON-serializable summary
            summary = {
                "config": {
                    "days": args.days,
                    "bar": args.bar,
                    "capital": args.capital,
                    "risk_pct": args.risk_pct,
                    "max_concurrent": args.max_concurrent,
                    "symbols": list(data.keys()),
                },
                "combined": {
                    "starting_capital": cr.starting_capital,
                    "final_equity": cr.final_equity,
                    "total_pnl": cr.total_pnl,
                    "total_return_pct": cr.total_return_pct,
                    "max_drawdown_usd": cr.max_drawdown_usd,
                    "max_drawdown_pct": cr.max_drawdown_pct,
                    "sharpe": cr.sharpe,
                    "sortino": cr.sortino,
                    "win_rate": cr.win_rate,
                    "profit_factor": cr.profit_factor,
                    "n_trades": cr.n_trades,
                },
                "per_symbol": {
                    s: {
                        "trades": len(r.trades),
                        "pnl": r.final_equity - 500,
                        "win_rate": r.win_rate,
                        "profit_factor": r.profit_factor,
                        "sharpe": r.sharpe,
                        "sortino": r.sortino,
                        "max_dd_pct": r.max_drawdown_pct,
                        "n_signals": r.n_signals,
                        "n_filtered": r.n_filtered,
                        "avg_pnl": r.avg_pnl,
                        "avg_pnl_winner": r.avg_pnl_winner,
                        "avg_pnl_loser": r.avg_pnl_loser,
                    }
                    for s, r in cr.per_symbol.items()
                },
            }
            print(json.dumps(summary, indent=2, default=str))
        else:
            print_combined_report(cr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
