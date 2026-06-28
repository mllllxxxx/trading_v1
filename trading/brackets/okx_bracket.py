#!/usr/bin/env python3
"""Bracket order placement for OKX with R:R validation.

Validates trade against risk rules (R:R >= 1:2, position <= 20% capital,
risk <= 1% capital) before placing 3 separate orders on OKX spot:
  1. Entry (limit)
  2. Take profit (limit)
  3. Stop loss (trigger / stop_market)

NOTE: OKX spot does not have native OCO. After entry fills, the user
must monitor and cancel the opposite order when TP or SL triggers.
This script does NOT do that monitoring - it just places the 3 orders.

Usage:
  python okx_bracket.py --symbol BTC-USDT --side buy --entry 65000 \\
    --stop-loss 64000 --take-profit 68000 --capital 10000 --dry-run

Exit codes:
  0 - success (orders placed or dry-run validated)
  1 - input error
  2 - risk rules violated (rejected)
  3 - order placement failed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------

ENV_PATH = Path.home() / ".vibe-trading" / ".env"
load_dotenv(ENV_PATH)

# Risk rules - beginner defaults, can be overridden in .env
MIN_RR = float(os.getenv("BRACKET_MIN_RR", "2.0"))
RISK_PCT = float(os.getenv("BRACKET_RISK_PCT", "0.01"))         # 1%
MAX_POSITION_PCT = float(os.getenv("BRACKET_MAX_POSITION_PCT", "0.20"))  # 20%
DAILY_LOSS_CAP = float(os.getenv("BRACKET_DAILY_LOSS_CAP", "0.03"))     # 3%
MAX_LEVERAGE = int(os.getenv("BRACKET_MAX_LEVERAGE", "3"))


def load_okx_config() -> dict[str, Any]:
    return {
        "api_key": os.getenv("OKX_API_KEY", "").strip(),
        "api_secret": os.getenv("OKX_API_SECRET", "").strip(),
        "passphrase": os.getenv("OKX_PASSPHRASE", "").strip(),
        "testnet": os.getenv("OKX_TESTNET", "true").lower() in ("true", "1", "yes"),
    }


# ---------------------------------------------------------------------------
# Pure functions (no I/O) - easy to test
# ---------------------------------------------------------------------------

def parse_symbol(symbol: str) -> tuple[str, str]:
    """BTC-USDT -> ('BTC', 'USDT')."""
    if "-" not in symbol:
        raise ValueError(f"Invalid symbol '{symbol}'. Expected e.g. BTC-USDT")
    base, quote = symbol.split("-", 1)
    return base.strip().upper(), quote.strip().upper()


def compute_bracket(
    symbol: str,
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    capital: float,
    risk_pct: float | None = None,
) -> dict[str, Any]:
    """Compute all metrics. No I/O. Raises ValueError on bad input.

    risk_pct: per-trade risk as fraction of capital (e.g., 0.01 = 1%).
              When None (default), uses module-level RISK_PCT (from env).
              Callers can pass a smaller value to shrink size during drawdowns.
    """
    base, quote = parse_symbol(symbol)
    side_lower = side.lower()
    if side_lower not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, got '{side}'")
    is_long = side_lower == "buy"

    e = Decimal(str(entry))
    sl = Decimal(str(stop_loss))
    tp = Decimal(str(take_profit))
    cap = Decimal(str(capital))

    # Allow per-call override of risk; fall back to env-derived default.
    effective_risk_pct = float(risk_pct) if risk_pct is not None else RISK_PCT
    if effective_risk_pct < 0:
        raise ValueError(f"risk_pct must be >= 0, got {effective_risk_pct}")
    if effective_risk_pct > RISK_PCT + 1e-9:
        raise ValueError(
            f"risk_pct {effective_risk_pct:.4f} exceeds default {RISK_PCT:.4f}. "
            "Override must shrink, not enlarge, risk."
        )

    if e <= 0 or sl <= 0 or tp <= 0 or cap <= 0:
        raise ValueError("entry, stop_loss, take_profit, capital must all be > 0")

    if is_long:
        if sl >= e:
            raise ValueError("LONG: stop_loss must be BELOW entry")
        if tp <= e:
            raise ValueError("LONG: take_profit must be ABOVE entry")
        stop_distance = e - sl
        reward = tp - e
    else:
        if sl <= e:
            raise ValueError("SHORT: stop_loss must be ABOVE entry")
        if tp >= e:
            raise ValueError("SHORT: take_profit must be BELOW entry")
        stop_distance = sl - e
        reward = e - tp

    rr_ratio = float(reward / stop_distance)

    # Position size by risk
    risk_amount = cap * Decimal(str(effective_risk_pct))
    pos_by_risk = risk_amount / stop_distance

    # Cap by max position notional
    pos_notional = pos_by_risk * e
    max_notional = cap * Decimal(str(MAX_POSITION_PCT))

    scaled = False
    if pos_notional > max_notional:
        pos_size = max_notional / e
        actual_risk_usd = pos_size * stop_distance
        actual_risk_pct = float(actual_risk_usd / cap) * 100
        scaled = True
    else:
        pos_size = pos_by_risk
        actual_risk_usd = risk_amount
        actual_risk_pct = effective_risk_pct * 100

    # Round down to 8 decimals (typical for crypto). This is conservative
    # because we never want to overshoot position notional / risk.
    pos_size = float(pos_size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN))

    return {
        "symbol": f"{base}-{quote}",
        "base": base,
        "quote": quote,
        "side": side_lower,
        "is_long": is_long,
        "entry": float(e),
        "stop_loss": float(sl),
        "take_profit": float(tp),
        "stop_distance": float(stop_distance),
        "reward": float(reward),
        "rr_ratio": rr_ratio,
        "rr_ratio_str": f"1:{rr_ratio:.2f}",
        "stop_pct": float(stop_distance / e * 100),
        "tp_pct": float(reward / e * 100),
        "position_size": pos_size,
        "position_notional": pos_size * float(e),
        "position_pct": pos_size * float(e) / float(cap) * 100,
        "actual_risk_usd": float(actual_risk_usd),
        "actual_risk_pct": actual_risk_pct,
        "scaled": scaled,
    }


def validate(proposal: dict[str, Any]) -> list[str]:
    """Return list of violation messages. Empty list = all pass."""
    violations: list[str] = []
    if proposal["rr_ratio"] < MIN_RR:
        violations.append(
            f"R:R = {proposal['rr_ratio_str']} < 1:{MIN_RR:.1f} (minimum)"
        )
    if proposal["position_pct"] > MAX_POSITION_PCT * 100 + 1e-6:
        violations.append(
            f"Position = {proposal['position_pct']:.1f}% > "
            f"{MAX_POSITION_PCT * 100:.0f}% (max notional)"
        )
    if proposal["actual_risk_pct"] > RISK_PCT * 100 + 1e-6:
        violations.append(
            f"Risk = {proposal['actual_risk_pct']:.2f}% > "
            f"{RISK_PCT * 100:.1f}% (max risk per trade)"
        )
    return violations


# ---------------------------------------------------------------------------
# OKX interaction
# ---------------------------------------------------------------------------

def _make_exchange(cfg: dict[str, Any]):
    """Build ccxt OKX client. Imported lazily so unit tests don't need ccxt."""
    import ccxt  # type: ignore

    exchange = ccxt.okx({
        "apiKey": cfg["api_key"],
        "secret": cfg["api_secret"],
        "password": cfg["passphrase"],
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if cfg["testnet"]:
        exchange.set_sandbox_mode(True)
    return exchange


def place_orders_spot(
    proposal: dict[str, Any],
    cfg: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place 3 separate spot orders: entry (limit), TP (limit), SL (trigger).

    Returns dict with entry_order / tp_order / sl_order keys.
    """
    entry_side = "buy" if proposal["is_long"] else "sell"
    exit_side = "sell" if proposal["is_long"] else "buy"

    if dry_run:
        return {
            "entry_order": {
                "dry_run": True,
                "type": "limit",
                "side": entry_side,
                "symbol": proposal["symbol"],
                "amount": proposal["position_size"],
                "price": proposal["entry"],
            },
            "tp_order": {
                "dry_run": True,
                "type": "limit",
                "side": exit_side,
                "symbol": proposal["symbol"],
                "amount": proposal["position_size"],
                "price": proposal["take_profit"],
            },
            "sl_order": {
                "dry_run": True,
                "type": "stop_market",
                "side": exit_side,
                "symbol": proposal["symbol"],
                "amount": proposal["position_size"],
                "trigger_price": proposal["stop_loss"],
            },
            "warning": (
                "OKX spot has no native OCO. After entry fills, you must "
                "manually cancel the OPPOSITE order (TP if SL hits, SL if TP hits)."
            ),
        }

    exchange = _make_exchange(cfg)

    # OKX v5: new unified accounts (spot+derivatives) accept tdMode=cross.
    # Old spot-only accounts use tdMode=cash. Try cross first, fall back to cash.
    def _place_with_fallback(**kwargs):
        for tdm in ("cross", "cash"):
            params = dict(kwargs.get("params") or {})
            params["tdMode"] = tdm
            params["tgtCcy"] = "base_ccy"
            try:
                return exchange.create_order(**{**kwargs, "params": params})
            except Exception as exc:
                if "51000" in str(exc) or "tdMode" in str(exc).lower():
                    continue
                raise
        raise RuntimeError("order placement failed: tdMode cross/cash both rejected")

    entry_order = _place_with_fallback(
        symbol=proposal["symbol"],
        type="limit",
        side=entry_side,
        amount=proposal["position_size"],
        price=proposal["entry"],
    )

    tp_order = _place_with_fallback(
        symbol=proposal["symbol"],
        type="limit",
        side=exit_side,
        amount=proposal["position_size"],
        price=proposal["take_profit"],
    )

    sl_order = _place_with_fallback(
        symbol=proposal["symbol"],
        type="stop_market",
        side=exit_side,
        amount=proposal["position_size"],
        price=proposal["stop_loss"],
        params={"stopPrice": proposal["stop_loss"]},
    )

    return {
        "entry_order": entry_order,
        "tp_order": tp_order,
        "sl_order": sl_order,
        "warning": (
            "OKX spot has no native OCO. After entry fills, you must "
            "manually cancel the OPPOSITE order (TP if SL hits, SL if TP hits)."
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_proposal_table(p: dict[str, Any]) -> None:
    side_label = "LONG" if p["is_long"] else "SHORT"
    print("=" * 60)
    print("BRACKET ORDER PROPOSAL")
    print("=" * 60)
    print(f"Symbol        : {p['symbol']}")
    print(f"Side          : {side_label}")
    print(f"Entry         : {p['entry']}")
    print(f"Stop Loss     : {p['stop_loss']}  (-{p['stop_pct']:.2f}%)")
    print(f"Take Profit   : {p['take_profit']}  (+{p['tp_pct']:.2f}%)")
    print("-" * 60)
    rr_ok = "OK" if p["rr_ratio"] >= MIN_RR else "FAIL"
    print(f"R:R Ratio     : {p['rr_ratio_str']}  [{rr_ok}]")
    print(f"Position Size : {p['position_size']} {p['base']}")
    print(f"Notional      : ${p['position_notional']:,.2f} "
          f"({p['position_pct']:.1f}% vốn)")
    print(f"Risk          : ${p['actual_risk_usd']:,.2f} "
          f"({p['actual_risk_pct']:.3f}% vốn)")
    if p["scaled"]:
        print("[!] Position was scaled DOWN to fit max notional cap")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate + place OKX bracket order (spot)"
    )
    parser.add_argument("--symbol", required=True, help="e.g. BTC-USDT")
    parser.add_argument("--side", required=True, choices=["buy", "sell", "long", "short"])
    parser.add_argument("--entry", type=float, required=True)
    parser.add_argument("--stop-loss", type=float, required=True)
    parser.add_argument("--take-profit", type=float, required=True)
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate + show what would be placed, no API call")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip the interactive confirmation prompt")
    args = parser.parse_args()

    side_norm = "buy" if args.side in ("buy", "long") else "sell"

    try:
        proposal = compute_bracket(
            args.symbol, side_norm, args.entry,
            args.stop_loss, args.take_profit, args.capital,
        )
    except ValueError as exc:
        print(json.dumps({"status": "error", "stage": "compute", "error": str(exc)},
                         indent=2))
        return 1

    violations = validate(proposal)
    if violations:
        print("=" * 60)
        print("BRACKET ORDER REJECTED")
        print("=" * 60)
        for v in violations:
            print(f"  X {v}")
        print("=" * 60)
        print("Fix the issues above and retry.")
        return 2

    _print_proposal_table(proposal)

    if args.dry_run:
        print("\n[DRY RUN] No orders will be placed.")
        cfg = load_okx_config()
        print(f"\nTestnet mode: {cfg['testnet']}")
        print(f"API key set:  {bool(cfg['api_key'])}")
        print("\nOrders that WOULD be placed:")
        shown = place_orders_spot(proposal, cfg, dry_run=True)
        print(json.dumps(shown, indent=2))
        return 0

    cfg = load_okx_config()
    if not cfg["api_key"]:
        print("ERROR: OKX_API_KEY not set in .env")
        return 1
    if cfg["testnet"]:
        print("\n>>> Using OKX TESTNET (paper trading) <<<")
    else:
        print("\n!!! LIVE TRADING - REAL MONEY !!!")
        print("Are you sure? Type LIVE in next 5 seconds...")
        try:
            resp = input("> ").strip()
        except EOFError:
            resp = ""
        if resp != "LIVE":
            print("Aborted.")
            return 1

    if not args.yes:
        print("\nĐặt 3 lệnh? (yes/no): ", end="")
        try:
            resp = input().strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("yes", "y"):
            print("Cancelled.")
            return 0

    try:
        orders = place_orders_spot(proposal, cfg, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        print(f"\nX Error placing orders: {exc}")
        print("Tip: re-check API key/secret/passphrase and OKX_TESTNET=true")
        return 3

    print("\n[V] Orders placed:")
    print(json.dumps(orders, indent=2, default=str))
    print("\n" + orders.get("warning", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
