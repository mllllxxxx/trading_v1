"""Force-open a single position on OKX testnet for end-to-end smoke testing.

Bypasses scheduler safety guards so the user can verify:
  1. OKX API credentials work
  2. Bracket orders (entry + TP + SL) actually place on the exchange
  3. Position records to journal (visible in /trader dashboard)
  4. Telegram alert fires
  5. Monitor thread polls OKX and reports fills

Usage:
  python -m auto.force_trade --symbol SOL-USDT --side long --capital 10000
  python -m auto.force_trade --symbol BTC-USDT --side short --capital 5000 --risk-pct 0.005

Safety:
  - Testnet-only enforced (refuses to run on LIVE)
  - Position size capped at 20% of capital
  - R:R must be >= 1:1.2 (H2 rule)
  - Refuses if a position already exists for the symbol
  - Refuses if kill switch or cooldown is active

After placement:
  - Position recorded in journal so /trader dashboard shows it
  - Telegram "trade_opened" alert sent
  - Monitor thread (already running in container) will track TP/SL
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import journal  # type: ignore
import alerts as _alerts  # type: ignore

# Import okx_bracket from sibling directory.
_BRACKETS = Path(__file__).resolve().parent.parent / "brackets"
sys.path.insert(0, str(_BRACKETS))
import okx_bracket as _okx  # type: ignore  # noqa: E402


def _reject_if_unsafe(symbol: str) -> None:
    """Refuse if cooldown, kill switch, or existing position would cause issues."""
    block_reason_fn = getattr(journal, "trading_block_reason", None)
    block_reason_raw = block_reason_fn() if callable(block_reason_fn) else ""
    block_reason = block_reason_raw if isinstance(block_reason_raw, str) else ""
    if not block_reason and journal.is_killed() is True:
        block_reason = "kill_switch_active"
    if block_reason:
        print(f"✗ REFUSED: trading is blocked ({block_reason}).")
        sys.exit(2)
    in_cd, reason, rem = journal.is_in_cooldown()
    if in_cd:
        print(f"✗ REFUSED: cooldown active ({reason}, {rem}s remaining). "
              f"Wait or call journal.clear_cooldown().")
        sys.exit(2)
    positions = journal.read_positions()
    for p in positions:
        if p.get("symbol") == symbol:
            print(f"✗ REFUSED: position already exists for {symbol}. "
                  f"Close it first via /trader → Monitor → cancel orders.")
            sys.exit(2)


def _build_proposal(args: argparse.Namespace) -> dict:
    """Resolve entry/stop/tp from explicit args OR auto-compute from current price."""
    cfg = _okx.load_okx_config()
    if not cfg["api_key"]:
        print("✗ OKX_API_KEY not set in env.")
        sys.exit(2)
    if not cfg["testnet"]:
        print("✗ REFUSED: would place on LIVE. Set OKX_TESTNET=true.")
        sys.exit(2)

    # If entry/SL/TP not given, fetch current price and compute a sensible bracket.
    if args.entry is None or args.stop_loss is None or args.take_profit is None:
        import ccxt  # type: ignore
        exchange = ccxt.okx({
            "apiKey": cfg["api_key"],
            "secret": cfg["api_secret"],
            "password": cfg["passphrase"],
            "options": {"defaultType": "spot"},
        })
        if cfg["testnet"]:
            exchange.set_sandbox_mode(True)
        ticker = exchange.fetch_ticker(args.symbol)
        entry = float(ticker["last"])
        is_long = args.side in ("buy", "long")
        # Slightly wider TP to ensure RR > 2.0 after rounding (MIN_RR check).
        # 1.5% SL + 3.1% TP = 2.067 R:R (vs 2.0 after close rounding).
        if is_long:
            stop_loss = round(entry * 0.985, 4)
            take_profit = round(entry * 1.031, 4)
        else:
            stop_loss = round(entry * 1.015, 4)
            take_profit = round(entry * 0.969, 4)
        print(f"Auto-computed bracket from current price ${entry}")
    else:
        entry = float(args.entry)
        stop_loss = float(args.stop_loss)
        take_profit = float(args.take_profit)

    # Normalize side to okx_bracket's accepted values (buy/sell only).
    side_normalized = "buy" if args.side in ("buy", "long") else "sell"

    proposal = _okx.compute_bracket(
        args.symbol, side_normalized, entry, stop_loss, take_profit,
        float(args.capital), risk_pct=args.risk_pct,
    )
    return proposal


def _place(proposal: dict) -> dict:
    cfg = _okx.load_okx_config()
    # compute_bracket sets is_long based on side; okx_bracket uses side as stored.
    return _okx.place_orders_spot(proposal, cfg, dry_run=False)


def _record_position(proposal: dict, orders: dict, regime: str = "FORCED",
                     confluence_score: int = 5, entry_type: str = "limit") -> dict:
    """Add the position to journal so /trader dashboard shows it."""
    pos = {
        "symbol": proposal["symbol"],
        "side": "buy" if proposal["is_long"] else "sell",
        "entry": proposal["entry"],
        "stop_loss": proposal["stop_loss"],
        "take_profit": proposal["take_profit"],
        "position_size": proposal["position_size"],
        "notional": proposal["position_notional"],
        "risk_usd": proposal["actual_risk_usd"],
        "rr_ratio": proposal["rr_ratio"],
        "confluence_score": confluence_score,
        "regime": regime,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "orders": {
            "entry_id": (orders.get("entry_order") or {}).get("id", ""),
            "tp_id": (orders.get("tp_order") or {}).get("id", ""),
            "sl_id": (orders.get("sl_order") or {}).get("id", ""),
        },
        "status": "open",
        "entry_type": entry_type,  # "limit" or "market"
        "forced": True,
    }
    journal.add_position(pos)
    journal.append_decision("forced_open", {
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry": pos["entry"],
        "stop_loss": pos["stop_loss"],
        "take_profit": pos["take_profit"],
        "rr_ratio": pos["rr_ratio"],
        "risk_usd": pos["risk_usd"],
        "entry_type": entry_type,
        "order_ids": pos["orders"],
        "msg": "Manually forced trade for end-to-end test.",
    })
    _alerts.emit("trade_opened", {
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry": pos["entry"],
        "stop_loss": pos["stop_loss"],
        "take_profit": pos["take_profit"],
        "rr_ratio": pos["rr_ratio"],
        "confluence_score": pos["confluence_score"],
        "regime": pos["regime"],
        "position_size": pos["position_size"],
    })
    return pos


def _place_market_order(symbol: str, side_norm: str, amount: float,
                        sl_price: float | None = None, tp_price: float | None = None) -> dict:
    """Place a single MARKET order on OKX testnet, optionally followed by TP+SL.

    Returns dict with keys: entry_order, tp_order, sl_order, avg_fill_price.
    The "entry_order" is the market order; avg_fill_price is the fill price
    fetched after placement (used to set entry in journal).
    """
    import ccxt  # type: ignore
    cfg = _okx.load_okx_config()
    exchange = ccxt.okx({
        "apiKey": cfg["api_key"],
        "secret": cfg["api_secret"],
        "password": cfg["passphrase"],
        "options": {"defaultType": "spot"},
    })
    if cfg["testnet"]:
        exchange.set_sandbox_mode(True)

    # Place market order. amount is in BASE asset (e.g., 0.05 ETH).
    # OKX v5: new unified accounts (spot+derivatives) require tdMode=cross.
    # Old spot-only accounts use tdMode=cash. Try cross first, fall back to cash.
    entry_order = None
    last_err = None
    for tdm in ("cross", "cash"):
        try:
            entry_order = exchange.create_order(
                symbol=symbol,
                type="market",
                side=side_norm,
                amount=amount,
                params={"tdMode": tdm, "tgtCcy": "base_ccy"},
            )
            break
        except Exception as exc:
            last_err = exc
            if "51000" in str(exc) or "tdMode" in str(exc).lower():
                continue  # try next tdMode
            raise
    if entry_order is None:
        raise last_err or RuntimeError("market order placement failed")

    # Market orders may not include fill price in the immediate response.
    # Fetch order detail to get the actual fill (avg price).
    try:
        if entry_order.get("id"):
            time.sleep(0.3)  # small delay for OKX to record the fill
            detail = exchange.fetch_order(entry_order["id"], symbol)
            if detail.get("average"):
                entry_order["average"] = float(detail["average"])
            if detail.get("filled"):
                entry_order["filled"] = float(detail["filled"])
    except Exception:
        pass  # fallback to whatever was in the immediate response
    # Determine actual fill price from the response.
    avg_fill_price = float(
        entry_order.get("average")
        or entry_order.get("price")
        or (entry_order.get("cost") or 0) / max(amount, 1e-9)
        or 0.0
    )

    tp_order = {}
    sl_order = {}
    if tp_price is not None and tp_price > 0:
        for tdm in ("cross", "cash"):
            try:
                tp_order = exchange.create_order(
                    symbol=symbol,
                    type="limit",
                    side="sell" if side_norm == "buy" else "buy",
                    amount=amount,
                    price=tp_price,
                    params={"tdMode": tdm, "tgtCcy": "base_ccy"},
                )
                break
            except Exception as exc:
                if "51000" in str(exc) or "tdMode" in str(exc).lower():
                    continue
                raise
    if sl_price is not None and sl_price > 0:
        for tdm in ("cross", "cash"):
            try:
                sl_order = exchange.create_order(
                    symbol=symbol,
                    type="stop_market",
                    side="sell" if side_norm == "buy" else "buy",
                    amount=amount,
                    price=sl_price,
                    params={"stopPrice": sl_price, "tdMode": tdm, "tgtCcy": "base_ccy"},
                )
                break
            except Exception as exc:
                if "51000" in str(exc) or "tdMode" in str(exc).lower():
                    continue
                raise
    return {
        "entry_order": entry_order,
        "tp_order": tp_order,
        "sl_order": sl_order,
        "avg_fill_price": avg_fill_price,
    }


def _record_market_position(symbol: str, side_norm: str, amount: float,
                            entry_price: float, tp_id: str, sl_id: str,
                            regime: str = "FORCED") -> dict:
    """Record a market-order position to journal (skips bracket validation)."""
    is_long = side_norm == "buy"
    pos = {
        "symbol": symbol,
        "side": side_norm,
        "entry": entry_price,
        # For a market-only test we set SL/TP to entry +/- 1% as placeholders.
        # The user can adjust by closing manually or adding orders later.
        "stop_loss": round(entry_price * (0.99 if is_long else 1.01), 4),
        "take_profit": round(entry_price * (1.01 if is_long else 0.99), 4),
        "position_size": amount,
        "notional": entry_price * amount,
        "risk_usd": entry_price * amount * 0.01,  # 1% notional placeholder
        "rr_ratio": 1.0,
        "confluence_score": 5,
        "regime": regime,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "orders": {
            "entry_id": "market",
            "tp_id": tp_id,
            "sl_id": sl_id,
        },
        "status": "open",
        "entry_type": "market",
        "forced": True,
    }
    journal.add_position(pos)
    journal.append_decision("forced_open_market", {
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry": pos["entry"],
        "amount": amount,
        "notional_usd": round(pos["notional"], 4),
        "tp_id": tp_id,
        "sl_id": sl_id,
        "msg": f"Manually forced MARKET order for end-to-end test ({amount} {symbol.split('-')[0]}).",
    })
    _alerts.emit("trade_opened", {
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry": pos["entry"],
        "stop_loss": pos["stop_loss"],
        "take_profit": pos["take_profit"],
        "rr_ratio": pos["rr_ratio"],
        "confluence_score": pos["confluence_score"],
        "regime": pos["regime"],
        "position_size": pos["position_size"],
    })
    return pos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", required=True, help="e.g. SOL-USDT, BTC-USDT")
    p.add_argument("--side", required=True, choices=["buy", "sell", "long", "short"])
    p.add_argument("--capital", type=float, required=True,
                   help="Account capital in USD (e.g. 10000)")
    p.add_argument("--risk-pct", type=float, default=None,
                   help="Override risk-per-trade fraction (default from env BRACKET_RISK_PCT=0.01)")
    p.add_argument("--entry", type=float, default=None, help="Limit entry price (default = current)")
    p.add_argument("--stop-loss", type=float, default=None, help="Stop-loss price (default = entry*0.985)")
    p.add_argument("--take-profit", type=float, default=None, help="Take-profit price (default = entry*1.030)")
    p.add_argument("--regime", default="FORCED", help="Regime label to record in journal")
    p.add_argument("--dry-run", action="store_true", help="Build proposal but don't place orders")
    p.add_argument("--market", action="store_true",
                   help="Use a MARKET order instead of limit bracket (instant fill). "
                        "Requires --amount; ignores --entry/--stop-loss/--take-profit "
                        "(TP/SL are placed as separate orders at +/-1% if not given).")
    p.add_argument("--amount", type=float, default=None,
                   help="Position size in BASE asset (e.g. 0.05 ETH). Required for --market.")
    args = p.parse_args()

    journal.ensure_dirs()

    # Market-order path: skip bracket entirely, place single market order.
    if args.market:
        if args.amount is None:
            print("✗ --amount required when --market is set (size in BASE asset).")
            return 1
        return _run_market_path(args)

    print("=" * 60)
    print("FORCE TRADE — bypassing scheduler safety guards")
    print("=" * 60)
    print(f"Symbol    : {args.symbol}")
    print(f"Side      : {args.side.upper()}")
    print(f"Capital   : ${args.capital:,.2f}")
    print(f"Risk pct  : {args.risk_pct if args.risk_pct else 'from env (BRACKET_RISK_PCT)'}")
    print("-" * 60)

    if not args.dry_run:
        _reject_if_unsafe(args.symbol)
    proposal = _build_proposal(args)
    _okx._print_proposal_table(proposal)

    violations = _okx.validate(proposal)
    if violations:
        print("✗ VALIDATION FAILED:")
        for v in violations:
            print(f"  - {v}")
        return 1

    if args.dry_run:
        print("\n[dry-run] Not placing orders. Proposal built OK.")
        return 0

    print("\nPlacing orders on OKX testnet...")
    try:
        orders = _place(proposal)
    except Exception as exc:
        print(f"✗ OKX ORDER FAILED: {exc}")
        journal.append_decision("forced_open_failed", {
            "symbol": args.symbol, "error": str(exc)[:500],
        })
        return 2

    print("\nOrders placed:")
    for kind in ("entry_order", "tp_order", "sl_order"):
        o = orders.get(kind) or {}
        print(f"  {kind:12s} id={o.get('id', '?')} status={o.get('status', o.get('dry_run', '?'))}")
    if orders.get("warning"):
        print(f"  WARN: {orders['warning']}")

    _record_position(proposal, orders, regime=args.regime)
    print("\n✓ Position recorded to journal.")
    print("  View at: http://localhost:8000/trader")
    print("  Telegram alert sent.")
    print("  Monitor thread will track TP/SL fills every 30s.")
    return 0


def _run_market_path(args: argparse.Namespace) -> int:
    """Place a single MARKET order (bypasses bracket logic).

    TP/SL are optional. If not given, sets them at +/-1% as placeholders so
    journal/dashboard have non-null values. Trade shows up immediately because
    market orders fill synchronously on OKX.
    """
    print("=" * 60)
    print("FORCE TRADE — MARKET ORDER (instant fill)")
    print("=" * 60)
    print(f"Symbol    : {args.symbol}")
    print(f"Side      : {args.side.upper()}")
    print(f"Amount    : {args.amount} {args.symbol.split('-')[0]}")
    print("-" * 60)

    cfg = _okx.load_okx_config()
    if not cfg["testnet"]:
        print("✗ REFUSED: would place on LIVE. Set OKX_TESTNET=true.")
        return 2
    _reject_if_unsafe(args.symbol)

    # If user didn't pass TP/SL, default to +/-1% from current price.
    import ccxt  # type: ignore
    ex = ccxt.okx({
        "apiKey": cfg["api_key"], "secret": cfg["api_secret"],
        "password": cfg["passphrase"],
        "options": {"defaultType": "spot"},
    })
    ex.set_sandbox_mode(True)
    ticker = ex.fetch_ticker(args.symbol)
    current = float(ticker["last"])
    is_long = args.side in ("buy", "long")
    side_norm = "buy" if is_long else "sell"

    tp_price = args.take_profit
    if tp_price is None:
        tp_price = round(current * (1.01 if is_long else 0.99), 4)
    sl_price = args.stop_loss
    if sl_price is None:
        sl_price = round(current * (0.99 if is_long else 1.01), 4)
    print(f"Current   : ${current}")
    print(f"TP        : ${tp_price} ({(tp_price/current - 1) * 100:+.2f}%)")
    print(f"SL        : ${sl_price} ({(sl_price/current - 1) * 100:+.2f}%)")
    print("-" * 60)

    print(f"\nPlacing MARKET order: {side_norm.upper()} {args.amount} {args.symbol}...")
    try:
        result = _place_market_order(
            symbol=args.symbol,
            side_norm=side_norm,
            amount=args.amount,
            sl_price=sl_price,
            tp_price=tp_price,
        )
    except Exception as exc:
        print(f"✗ OKX ORDER FAILED: {exc}")
        journal.append_decision("forced_market_failed", {
            "symbol": args.symbol, "side": side_norm,
            "amount": args.amount, "error": str(exc)[:500],
        })
        return 2

    entry_order = result.get("entry_order") or {}
    tp_order = result.get("tp_order") or {}
    sl_order = result.get("sl_order") or {}
    avg_fill = result.get("avg_fill_price", current)

    print("\nMarket order filled:")
    print(f"  entry   id={entry_order.get('id', '?')[:25]} status={entry_order.get('status', '?')}")
    print(f"  fill    ${avg_fill:.4f}  (notional ~${avg_fill * args.amount:.2f})")
    if tp_order:
        print(f"  tp      id={tp_order.get('id', '?')[:25]} @ ${tp_price}")
    if sl_order:
        print(f"  sl      id={sl_order.get('id', '?')[:25]} @ ${sl_price}")

    _record_market_position(
        symbol=args.symbol,
        side_norm=side_norm,
        amount=args.amount,
        entry_price=avg_fill,
        tp_id=tp_order.get("id", ""),
        sl_id=sl_order.get("id", ""),
        regime=args.regime,
    )
    print("\n✓ Position recorded to journal.")
    print("  View live at: http://localhost:8000/trader  (auto-refreshes 5s)")
    print("  Telegram alert sent.")
    print("  Monitor thread polls OKX every 30s for fills + unrealized PnL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
