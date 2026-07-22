"""Position monitor: poll OKX open orders, auto-cancel opposite when one fills.

For each open position with order_ids:
  - Check entry order status (open / partially_filled / closed / canceled)
  - If entry partially filled: track filled amount, expected vs actual price (slippage)
  - If entry fully filled: monitor TP and SL
  - If TP filled: cancel SL, log PnL with realized price
  - If SL filled: cancel TP, log PnL with realized price
  - Track all order status changes in journal
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # type: ignore
import alerts as _alerts  # type: ignore
import exchange_reconciler  # type: ignore

MONITOR_INTERVAL = int(os.getenv("AUTO_MONITOR_INTERVAL_S", "30"))
HEARTBEAT_EVERY = int(os.getenv("AUTO_MONITOR_HEARTBEAT", "20"))
# C2: Cool-down after a losing trade to discourage revenge trading.
# 0 = disabled. Default 30 minutes.
COOLDOWN_MINUTES = float(os.getenv("AUTO_COOLDOWN_MINUTES", "30"))


def _get_exchange():
    import ccxt  # type: ignore
    trade_mode = os.getenv("TRADE_MODE", "spot").strip().lower()
    cfg = {
        "apiKey": os.getenv("OKX_API_KEY", "").strip(),
        "secret": os.getenv("OKX_API_SECRET", "").strip(),
        "password": os.getenv("OKX_PASSPHRASE", "").strip(),
        "enableRateLimit": True,
        "options": {"defaultType": "swap" if trade_mode == "futures" else "spot"},
    }
    if os.getenv("OKX_TESTNET", "true").lower() in ("true", "1", "yes"):
        cfg["sandbox"] = True
    return ccxt.okx(cfg)


def _native_to_ccxt_symbol(symbol: str) -> str:
    """Map OKX native symbol (e.g. 'BTC-USDT-SWAP' or 'BTC-USDT') to CCXT symbol."""
    trade_mode = os.getenv("TRADE_MODE", "spot").strip().lower()
    if trade_mode == "futures" or symbol.upper().endswith("-SWAP") or ":" in symbol:
        return exchange_reconciler.ccxt_swap_symbol(symbol)
    parts = symbol.split("-")
    if len(parts) == 3 and parts[2] == "SWAP":
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return symbol


def _determine_exit_reason(pos: dict[str, Any], exit_price: float) -> str:
    tp = pos.get("take_profit", 0.0)
    sl = pos.get("stop_loss", 0.0)
    if tp <= 0 or sl <= 0:
        return "exchange_sync_exit"
    
    dist_to_tp = abs(exit_price - tp) / tp
    dist_to_sl = abs(exit_price - sl) / sl
    
    if dist_to_tp < 0.01:  # within 1% of TP
        return "take_profit"
    if dist_to_sl < 0.01:  # within 1% of SL
        return "stop_loss"
    return "exchange_sync_exit"



def _fetch_order_status(exchange, symbol: str, order_id: str) -> dict[str, Any] | None:
    if not order_id:
        return None
    try:
        return exchange.fetch_order(order_id, symbol)
    except Exception as exc:  # noqa: BLE001
        # OKX testnet often auto-cancels orders after some time. Treat 51603
        # ("Order does not exist") and 51000 ("Parameter ordId error") as
        # benign stale-order signals, not real errors. Log once at debug level.
        msg = str(exc)
        if "51603" in msg or "51000" in msg or "Order does not exist" in msg:
            journal.append_decision("stale_order", {
                "where": "fetch_order",
                "order_id": order_id,
                "msg": "Order auto-cancelled or expired on OKX testnet",
            })
        else:
            journal.append_decision("error", {
                "where": "fetch_order", "order_id": order_id, "error": msg,
            })
        return None


def _cancel_order(exchange, symbol: str, order_id: str) -> bool:
    if not order_id:
        return False
    try:
        exchange.cancel_order(order_id, symbol)
        return True
    except Exception as exc:  # noqa: BLE001
        journal.append_decision("error", {"where": "cancel_order", "order_id": order_id,
                                            "error": str(exc)})
        return False


def _extract_fill_info(order: dict[str, Any]) -> dict[str, Any]:
    """Extract filled amount, average price, and status from ccxt order dict.

    ccxt normalizes these fields:
      - status: 'open' | 'closed' | 'canceled' | 'expired' | 'rejected'
      - filled: amount filled so far
      - average: average fill price
      - price: order price (requested)
      - cost: filled * average
    """
    return {
        "status": order.get("status", ""),
        "filled": float(order.get("filled", 0) or 0),
        "average": float(order.get("average", 0) or 0) if order.get("average") else 0.0,
        "requested_price": float(order.get("price", 0) or 0) if order.get("price") else 0.0,
        "cost": float(order.get("cost", 0) or 0) if order.get("cost") else 0.0,
    }


def _compute_slippage(expected: float, actual: float, side: str) -> dict[str, Any]:
    """Slippage = difference between expected and actual fill price.

    For long: positive slippage = paid more than expected (bad)
    For short: positive slippage = received less than expected (bad)
    """
    if expected <= 0 or actual <= 0:
        return {"slippage_usd": 0.0, "slippage_pct": 0.0, "direction": "none"}
    if side == "buy":
        diff = actual - expected  # paid more = positive (bad for buyer)
    else:
        diff = expected - actual  # received less = positive (bad for seller)
    return {
        "slippage_usd_per_unit": round(diff, 4),
        "slippage_pct": round(diff / expected * 100, 4),
        "direction": "negative" if diff > 0 else ("positive" if diff < 0 else "none"),
    }


def _close_position(symbol: str, exit_price: float, exit_reason: str,
                    position_id: str | None = None,
                     extra: dict[str, Any] | None = None) -> None:
    """Remove position, compute PnL, append to closed log, update stats."""
    pos = journal.remove_position(symbol, position_id=position_id)
    if not pos:
        return
    side = str(pos["side"]).lower()
    if side not in {"buy", "long", "sell", "short"}:
        journal.add_position(pos)
        journal.append_decision(
            "close_rejected",
            {"symbol": symbol, "reason": f"unknown_position_side:{side}"},
        )
        return
    entry = float(pos["entry"])
    size = float(pos["position_size"])
    is_long = side in {"buy", "long"}
    gross_pnl = (exit_price - entry) * size if is_long else (entry - exit_price) * size
    fees_usd = _estimated_demo_fees(entry, exit_price, size)
    pnl = gross_pnl - fees_usd
    market_context = pos.get("market_context") if isinstance(pos.get("market_context"), dict) else {}
    trade = {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "exit_price": exit_price,
        "position_size": size,
        "gross_pnl_usd": round(gross_pnl, 2),
        "fees_usd": round(fees_usd, 6),
        "pnl_usd": round(pnl, 2),
        "rr_ratio": pos.get("rr_ratio", 0),
        "confluence_score": pos.get("confluence_score", 0),
        "regime": pos.get("regime") or market_context.get("regime", ""),
        "exit_reason": exit_reason,
        "opened_at": pos.get("opened_at", ""),
        "closed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    risk_usd = _positive_optional_float(pos.get("risk_usd"))
    if risk_usd is not None:
        trade["r_multiple"] = round(pnl / risk_usd, 6)
    # Phase 2: execution analytics
    if extra:
        trade["execution"] = extra
        if "slippage_pct" in extra:
            trade["slippage_pct"] = extra["slippage_pct"]
    # Phase 4: skill usage tracking and demo-learning rationale inherited from
    # the decision path. Closed-trade review needs the opening context.
    for key in (
        "llm_reasoning",
        "skills_applied",
        "position_id",
        "team_id",
        "team_name",
        "strategy_id",
        "strategy_name",
        "team_capital_usd",
        "target_risk_pct_equity",
        "preferred_playbook_ids",
        "required_soft_policy_ids",
        "entry_style",
        "avoid_conditions",
        "llm_guidance",
        "risk_personality",
        "notional",
        "risk_usd",
        "requested_risk_pct_equity",
        "actual_risk_pct_equity",
        "risk_cap_reason",
        "margin_used_usd",
        "gross_notional_usd",
        "leverage",
        "broker_contracts",
        "profile_compliance_score",
        "profile_compliance_summary",
        "profile_compliance_flags",
        "source_signal_id",
        "decision_id",
        "open_reason",
        "market_context",
        "decision_context",
        "decision_policy",
        "decision_lane",
        "rule_score",
        "score_components",
        "rule_conflicts",
        "llm_context_review",
        "routing_experiment",
    ):
        if key in pos:
            trade[key] = pos[key]
    journal.append_closed_trade(trade)
    # C2: Trigger cool-down BEFORE writing stats (set_cooldown acquires the
    # journal lock and writes cooldown fields; doing it first ensures
    # write_stats below doesn't overwrite them).
    if pnl < 0 and COOLDOWN_MINUTES > 0:
        try:
            journal.set_cooldown(
                minutes=COOLDOWN_MINUTES,
                reason=f"loss_{symbol}_{exit_reason}",
            )
        except Exception as exc:  # noqa: BLE001
            journal.append_decision("cooldown_set_failed", {"error": str(exc)})
    stats = journal.read_stats()
    stats = journal.update_stats_on_close(trade, stats)
    stats["open_count"] = len(journal.read_positions())
    journal.write_stats(stats)
    # Telegram alert on close (separate events for TP vs SL for nicer formatting)
    base_payload = {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "exit_price": exit_price,
        "pnl_usd": round(pnl, 2),
        "rr_ratio": pos.get("rr_ratio", 0),
        "position_size": size,
        "regime": pos.get("regime", ""),
        "team_id": trade.get("team_id"),
        "team_name": trade.get("team_name"),
        "decision_id": trade.get("decision_id"),
        "gross_pnl_usd": trade.get("gross_pnl_usd"),
        "fees_usd": trade.get("fees_usd"),
    }
    if exit_reason in ("take_profit", "tp_filled", "tp_hit"):
        _alerts.emit("tp_hit", base_payload)
    elif exit_reason in ("stop_loss", "sl_filled", "sl_hit"):
        _alerts.emit("sl_hit", base_payload)
    _alerts.emit("trade_closed", {**base_payload, "exit_reason": exit_reason})


def _estimated_demo_fees(entry: float, exit_price: float, size: float) -> float:
    """Estimate both filled legs when broker fee detail is unavailable."""
    try:
        fee_rate = max(0.0, float(os.getenv("AUTO_DEMO_FEE_RATE", "0.0005")))
    except ValueError:
        fee_rate = 0.0005
    return (abs(entry) + abs(exit_price)) * abs(size) * fee_rate


def _positive_optional_float(value: Any) -> float | None:
    """Return a finite positive number for fee-aware R attribution."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _handle_entry(exchange, pos: dict[str, Any], entry_info: dict[str, Any]) -> bool:
    """Process entry order. Returns True if we should continue to monitor TP/SL."""
    symbol = pos["symbol"]
    status = entry_info["status"]
    expected_entry = pos["entry"]

    if status == "open":
        return False  # Wait
    if status in ("canceled", "expired", "rejected"):
        journal.append_decision("cleanup", {"symbol": symbol,
                                            "reason": f"entry_{status}"})
        _cancel_order(exchange, symbol, pos["orders"].get("tp_id", ""))
        _cancel_order(exchange, symbol, pos["orders"].get("sl_id", ""))
        exchange_reconciler.resolve_pending_entry(
            journal,
            pos,
            reason=f"entry_{status}",
            broker_evidence=entry_info,
        )
        return False

    if status == "closed":
        slip = _compute_slippage(expected_entry, entry_info["average"], pos["side"])
        journal.append_decision("execution", {
            "symbol": symbol, "order": "entry",
            "filled": entry_info["filled"],
            "expected_price": expected_entry,
            "actual_price": entry_info["average"],
            "slippage_pct": slip["slippage_pct"],
            "slippage_usd": round(slip["slippage_pct"] / 100 * pos["position_size"] * expected_entry, 2),
        })
        return True

    if status == "partially_filled":
        # Partial fill: log and continue to monitor
        slip = _compute_slippage(expected_entry, entry_info["average"], pos["side"])
        journal.append_decision("execution", {
            "symbol": symbol, "order": "entry", "status": "partial",
            "filled": entry_info["filled"], "expected": pos["position_size"],
            "avg_price": entry_info["average"],
            "slippage_pct": slip["slippage_pct"],
        })
        # For partial fills, we still monitor TP/SL. TP/SL will fill proportionally
        # on OKX if we use reduce-only. For spot, we accept the partial and proceed.
        return True

    return False


def _check_position(exchange, pos: dict[str, Any]) -> None:
    symbol = pos["symbol"]
    orders = pos.get("orders", {})
    entry_id = orders.get("entry_id", "")
    tp_id = orders.get("tp_id", "")
    sl_id = orders.get("sl_id", "")

    # For legacy positions or market entries, treat "market" or empty entry_id as already filled.
    if entry_id == "market" or not entry_id:
        if not pos.get("entry_filled"):
            journal.update_position(
                symbol,
                {"entry_filled": True},
                position_id=pos.get("position_id") or pos.get("decision_id"),
            )
            pos["entry_filled"] = True

    trade_mode = os.getenv("TRADE_MODE", "spot").strip().lower()
    is_futures = (trade_mode == "futures") or symbol.endswith("-SWAP")

    if is_futures:
        entry_filled = pos.get("entry_filled", False)
        if not entry_filled:
            try:
                raw_active_positions = exchange.fetch_positions()
                ccxt_symbol = _native_to_ccxt_symbol(symbol)
                has_active = False
                for p in raw_active_positions:
                    size = float(p.get("contracts", 0) or p.get("size", 0) or 0)
                    if p.get("symbol") == ccxt_symbol and size != 0:
                        has_active = True
                        break
                
                if has_active:
                    journal.update_position(
                        symbol,
                        {"entry_filled": True},
                        position_id=pos.get("position_id") or pos.get("decision_id"),
                    )
                    pos["entry_filled"] = True
                    journal.append_decision("execution", {
                        "symbol": symbol, "order": "entry",
                        "msg": "Futures position detected active on exchange."
                    })
                    _alerts.emit("trade_entry_filled", {
                        "symbol": symbol,
                        "side": pos.get("side"),
                        "entry": pos.get("entry"),
                        "team_id": pos.get("team_id"),
                        "team_name": pos.get("team_name"),
                        "decision_id": pos.get("decision_id"),
                    })
            except Exception as exc:
                journal.append_decision("error", {
                    "where": "futures_check_entry",
                    "symbol": symbol,
                    "error": str(exc)
                })
        return

    # Spot mode logic
    entry_filled = pos.get("entry_filled", False)
    if not entry_filled:
        entry = _fetch_order_status(exchange, symbol, entry_id)
        if not entry:
            return
        entry_info = _extract_fill_info(entry)

        if not _handle_entry(exchange, pos, entry_info):
            return  # Entry not done (open, canceled, etc.)
        
        journal.update_position(
            symbol,
            {"entry_filled": True},
            position_id=pos.get("position_id") or pos.get("decision_id"),
        )
        pos["entry_filled"] = True
        _alerts.emit("trade_entry_filled", {
            "symbol": symbol,
            "side": pos.get("side"),
            "entry": entry_info.get("average") or pos.get("entry"),
            "team_id": pos.get("team_id"),
            "team_name": pos.get("team_name"),
            "decision_id": pos.get("decision_id"),
        })

    # Entry filled (or partial) - now monitor TP and SL
    tp = _fetch_order_status(exchange, symbol, tp_id)
    sl = _fetch_order_status(exchange, symbol, sl_id)
    tp_info = _extract_fill_info(tp) if tp else None
    sl_info = _extract_fill_info(sl) if sl else None

    # M1: Distinguish "fully filled" (closed) vs "partially filled".
    tp_full = tp_info and tp_info["status"] == "closed"
    sl_full = sl_info and sl_info["status"] == "closed"
    tp_partial = tp_info and tp_info["status"] == "partially_filled"
    sl_partial = sl_info and sl_info["status"] == "partially_filled"

    if tp_full and not sl_full:
        _cancel_order(exchange, symbol, sl_id)
        exit_price = tp_info["average"] if tp_info["average"] > 0 else pos["take_profit"]
        slip = _compute_slippage(pos["take_profit"], exit_price, pos["side"])
        _close_position(
            symbol,
            exit_price=exit_price,
            exit_reason="take_profit",
            position_id=pos.get("position_id") or pos.get("decision_id"),
            extra={"exit_status": tp_info["status"],
                   "slippage_pct": slip["slippage_pct"]},
        )
    elif sl_full and not tp_full:
        _cancel_order(exchange, symbol, tp_id)
        exit_price = sl_info["average"] if sl_info["average"] > 0 else pos["stop_loss"]
        slip = _compute_slippage(pos["stop_loss"], exit_price, pos["side"])
        _close_position(
            symbol,
            exit_price=exit_price,
            exit_reason="stop_loss",
            position_id=pos.get("position_id") or pos.get("decision_id"),
            extra={"exit_status": sl_info["status"],
                   "slippage_pct": slip["slippage_pct"]},
        )
    elif tp_full and sl_full:
        journal.append_decision("warning", {"symbol": symbol,
                                              "msg": "both TP and SL filled - rare race"})
        _close_position(
            symbol,
            exit_price=pos["stop_loss"],
            exit_reason="both_filled",
            position_id=pos.get("position_id") or pos.get("decision_id"),
        )
    elif tp_partial or sl_partial:
        # Log partial fill; don't close until full. Spot TP/SL are NOT
        # reduce-only OCO so the opposite side still works; just wait for
        # full fill of one side.
        journal.append_decision("partial_exit", {
            "symbol": symbol,
            "tp_partial": tp_partial,
            "tp_filled_pct": (tp_info["filled"] / pos["position_size"] * 100) if tp_partial else 0,
            "sl_partial": sl_partial,
            "sl_filled_pct": (sl_info["filled"] / pos["position_size"] * 100) if sl_partial else 0,
        })


def run_once() -> None:
    # H5: Auto kill switch on 3+ consecutive losses
    if journal.check_loss_streak_kill():
        journal.append_decision("h5_activated", {
            "msg": "Trading halted. Manual review required."
        })
        _alerts.emit("kill_switch", {"reason": "loss_streak"})
    trade_mode = os.getenv("TRADE_MODE", "spot").strip().lower()
    positions = journal.read_positions()
    if trade_mode != "futures" and not positions:
        return
    try:
        exchange = _get_exchange()
    except Exception as exc:  # noqa: BLE001
        journal.append_decision("error", {"where": "exchange_init", "error": str(exc)})
        return

    # Reconciliation logic to handle out-of-sync positions
    if trade_mode == "futures":
        try:
            snapshot = exchange_reconciler.fetch_okx_demo_snapshot(
                exchange=exchange,
                include_pending_algo=False,
                journal_module=journal,
            )
            if snapshot.get("errors"):
                journal.append_decision("error", {
                    "where": "futures_sync_reconciliation",
                    "error": "; ".join(str(item) for item in snapshot.get("errors", [])),
                    "msg": "Exchange snapshot failed; preserving local journal positions.",
                })
                return
            sync_status = exchange_reconciler.reconcile_journal_with_exchange(
                snapshot=snapshot,
                journal_module=journal,
                import_missing=True,
                update_existing=True,
            )
            if sync_status.get("status") != "in_sync":
                journal.append_decision("exchange_sync_status", sync_status)
            pending_status = exchange_reconciler.reconcile_pending_entries(
                exchange=exchange,
                snapshot=snapshot,
                journal_module=journal,
            )
            if pending_status.get("errors"):
                journal.append_decision("pending_entry_reconciliation_status", pending_status)
            if getattr(journal, "startup_sync_guard_active", lambda: False)():
                journal.clear_startup_sync_guard()
            positions = journal.read_positions()
            if not positions:
                return
            
            for pos in list(positions):
                symbol = pos["symbol"]
                ccxt_symbol = _native_to_ccxt_symbol(symbol)
                # Only reconcile if entry has already been filled
                active, _, _ = exchange_reconciler.has_active_exchange_exposure(
                    symbol,
                    snapshot=snapshot,
                )
                if pos.get("entry_filled") and not active:
                    if not _confirm_exchange_missing_before_close(pos, snapshot):
                        continue
                    journal.append_decision("sync_reconciliation_exit", {
                        "symbol": symbol,
                        "ccxt_symbol": ccxt_symbol,
                        "msg": "Futures position not active on exchange, closing locally."
                    })
                    exit_price = pos["entry"]
                    try:
                        ticker = exchange.fetch_ticker(ccxt_symbol)
                        if ticker and "close" in ticker:
                            exit_price = ticker["close"]
                        elif ticker and "last" in ticker:
                            exit_price = ticker["last"]
                    except Exception:
                        pass
                    
                    reason = _determine_exit_reason(pos, exit_price)
                    _close_position(
                        symbol,
                        exit_price=exit_price,
                        exit_reason=reason,
                        position_id=pos.get("position_id") or pos.get("decision_id"),
                    )
                    
                    # Cancel any orphaned orders
                    orders = pos.get("orders", {})
                    for oid_key in ("entry_id", "tp_id", "sl_id"):
                        oid = orders.get(oid_key, "")
                        if oid:
                            _cancel_order(exchange, symbol, oid)
                            
                    positions = [
                        p for p in positions
                        if not _same_position_record(p, symbol, pos.get("position_id") or pos.get("decision_id"))
                    ]
        except Exception as exc:
            journal.append_decision("error", {
                "where": "futures_sync_reconciliation",
                "error": str(exc)
            })
    else:
        # Spot reconciliation: close position if both TP and SL orders are inactive (canceled/expired/none)
        for pos in list(positions):
            symbol = pos["symbol"]
            if pos.get("entry_filled"):
                orders = pos.get("orders", {})
                tp_id = orders.get("tp_id", "")
                sl_id = orders.get("sl_id", "")
                
                tp_status = None
                sl_status = None
                
                if tp_id:
                    tp_order = _fetch_order_status(exchange, symbol, tp_id)
                    if tp_order:
                        tp_status = tp_order.get("status")
                if sl_id:
                    sl_order = _fetch_order_status(exchange, symbol, sl_id)
                    if sl_order:
                        sl_status = sl_order.get("status")
                
                tp_inactive = tp_status in ("canceled", "expired", "rejected", None)
                sl_inactive = sl_status in ("canceled", "expired", "rejected", None)
                
                if tp_inactive and sl_inactive:
                    journal.append_decision("sync_reconciliation_exit", {
                        "symbol": symbol,
                        "tp_status": tp_status,
                        "sl_status": sl_status,
                        "msg": "Both TP and SL orders are inactive/pruned on exchange, closing spot position locally."
                    })
                    exit_price = pos["entry"]
                    try:
                        ccxt_symbol = _native_to_ccxt_symbol(symbol)
                        ticker = exchange.fetch_ticker(ccxt_symbol)
                        if ticker and "close" in ticker:
                            exit_price = ticker["close"]
                    except Exception:
                        pass
                    _close_position(
                        symbol,
                        exit_price=exit_price,
                        exit_reason="orders_inactive_or_pruned",
                        position_id=pos.get("position_id") or pos.get("decision_id"),
                    )
                    positions = [
                        p for p in positions
                        if not _same_position_record(p, symbol, pos.get("position_id") or pos.get("decision_id"))
                    ]

    for pos in positions:
        try:
            _check_position(exchange, pos)
        except Exception as exc:  # noqa: BLE001
            journal.append_decision("error", {"where": "check_position",
                                                "symbol": pos.get("symbol"),
                                                "error": str(exc)})


def _confirm_exchange_missing_before_close(pos: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    """Require a second clean missing-on-exchange observation before close."""
    symbol = str(pos.get("symbol") or "")
    fetched_at = str(snapshot.get("fetched_at") or "")
    previous = str(pos.get("exchange_missing_confirmed_at") or "")
    if previous:
        return True
    journal.update_position(
        symbol,
        {
            "exchange_missing_confirmed_at": fetched_at,
            "sync_status": "exchange_missing_pending",
        },
        position_id=pos.get("position_id") or pos.get("decision_id"),
    )
    journal.append_decision("exchange_missing_pending_close", {
        "symbol": symbol,
        "fetched_at": fetched_at,
        "msg": "Futures position missing from exchange snapshot; waiting for one more clean snapshot before closing locally.",
    })
    return False


def _same_position_record(pos: dict[str, Any], symbol: str, position_id: str | None) -> bool:
    """Return whether a loop-local position is the one just closed."""
    if pos.get("symbol") != symbol:
        return False
    if not position_id:
        return True
    return str(pos.get("position_id") or pos.get("decision_id") or "") == str(position_id)


def _one_cycle(cycle_ref: list[int], heartbeat_every: int) -> None:
    """M2: Run a single cycle + handle heartbeat + catch fatal exceptions.

    Extracted from main_loop so tests can drive single cycles.
    `cycle_ref` is a single-element list used as a mutable counter so the
    heartbeat state survives across calls without globals.
    """
    try:
        run_once()
        cycle_ref[0] += 1
        if cycle_ref[0] >= heartbeat_every:
            journal.append_decision("monitor_heartbeat", {
                "cycle": cycle_ref[0],
                "interval_s": MONITOR_INTERVAL,
                "open_positions": len(journal.read_positions()),
            })
            cycle_ref[0] = 0
    except Exception as exc:  # noqa: BLE001
        try:
            journal.append_decision("monitor_fatal", {
                "error": str(exc),
                "traceback": __import__("traceback").format_exc()[:500],
            })
        except Exception:  # noqa: BLE001
            pass
        time.sleep(MONITOR_INTERVAL)  # back off after fatal


def main_loop_cycle() -> None:
    """Public alias for _one_cycle with module-level state.

    Convenience for tests; production code uses main_loop().
    """
    if not hasattr(main_loop_cycle, "_cycle_ref"):
        main_loop_cycle._cycle_ref = [0]
    _one_cycle(main_loop_cycle._cycle_ref, HEARTBEAT_EVERY)


def main_loop() -> None:
    """M2: Heartbeat every N cycles + catch unexpected exceptions so the
    monitor thread never silently dies. Without this, a single fatal error
    (e.g., disk full, network permanently down) would leave positions open
    on OKX without any monitoring. Heartbeat lets ops confirm liveness.
    """
    journal.ensure_dirs()
    journal.append_decision("monitor_start", {"interval_s": MONITOR_INTERVAL})
    cycle_ref = [0]
    while True:
        _one_cycle(cycle_ref, HEARTBEAT_EVERY)
        time.sleep(MONITOR_INTERVAL)


if __name__ == "__main__":
    main_loop()
