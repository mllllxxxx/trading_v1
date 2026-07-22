"""Exchange-to-journal reconciliation for OKX demo/testnet futures."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

try:
    import journal  # type: ignore
    import equity as _equity  # type: ignore
except ImportError:  # pragma: no cover - package import fallback
    from . import journal  # type: ignore
    from . import equity as _equity  # type: ignore


JournalModule = Any


def utc_now() -> str:
    """Return a compact UTC timestamp for reconciliation metadata."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_symbol(symbol: str | None) -> str:
    """Normalize spot/swap/CCXT symbols to the canonical journal symbol."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    raw = raw.replace("/", "-")
    if raw.endswith("-SWAP"):
        raw = raw[: -len("-SWAP")]
    parts = [part for part in raw.split("-") if part]
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return raw


def okx_swap_symbol(symbol: str | None) -> str:
    """Return OKX native swap symbol, e.g. BTC-USDT-SWAP."""
    canonical = canonical_symbol(symbol)
    if not canonical:
        return ""
    return f"{canonical}-SWAP"


def ccxt_swap_symbol(symbol: str | None) -> str:
    """Return CCXT swap symbol, e.g. BTC/USDT:USDT."""
    canonical = canonical_symbol(symbol)
    parts = canonical.split("-")
    if len(parts) != 2:
        return canonical
    base, quote = parts
    return f"{base}/{quote}:{quote}"


def same_symbol(left: str | None, right: str | None) -> bool:
    """Compare symbols after canonical normalization."""
    return bool(canonical_symbol(left)) and canonical_symbol(left) == canonical_symbol(right)


def fetch_okx_demo_snapshot(
    *,
    exchange: Any | None = None,
    include_pending_algo: bool = False,
    include_account: bool = False,
    journal_module: JournalModule = journal,
) -> dict[str, Any]:
    """Fetch active OKX demo/testnet futures positions and optional account state."""
    fetched_at = utc_now()
    errors: list[str] = []
    account_errors: list[str] = []
    positions: list[dict[str, Any]] = []
    pending_algo: list[dict[str, Any]] = []
    account_balance: Mapping[str, Any] | None = None
    exchange_obj: Any | None = None
    try:
        exchange_obj = exchange or _make_okx_exchange()
        raw_positions = exchange_obj.fetch_positions()
        pending_algo = _fetch_pending_algo_orders(raw_positions) if include_pending_algo else []
        for raw in raw_positions:
            normalized = normalize_exchange_position(raw, pending_algo=pending_algo, fetched_at=fetched_at)
            if normalized is not None:
                positions.append(normalized)
    except Exception as exc:  # noqa: BLE001
        error_text = compact_provider_error(exc)
        errors.append(error_text)
        _safe_append_decision(
            journal_module,
            "exchange_reconciliation_error",
            {"stage": "fetch_snapshot", "error": error_text, "fetched_at": fetched_at},
        )
    if include_account:
        if exchange_obj is None:
            account_errors.append("exchange_client_unavailable")
        else:
            try:
                raw_balance = exchange_obj.fetch_balance()
                if isinstance(raw_balance, Mapping):
                    account_balance = raw_balance
                else:
                    account_errors.append("account_balance_shape_invalid")
            except Exception as exc:  # noqa: BLE001
                error_text = compact_provider_error(exc)
                account_errors.append(error_text)
                _safe_append_decision(
                    journal_module,
                    "exchange_account_snapshot_error",
                    {"stage": "fetch_balance", "error": error_text, "fetched_at": fetched_at},
                )
    return {
        "fetched_at": fetched_at,
        "ok": not errors,
        "exchange": "okx",
        "mode": "demo",
        "positions": positions,
        "pending_algo": pending_algo,
        "account_balance": account_balance,
        "account_errors": account_errors,
        "errors": errors,
    }


def compact_provider_error(error: Exception | str, *, max_length: int = 500) -> str:
    """Keep actionable provider errors while omitting oversized HTML response bodies."""

    text = str(error).strip()
    lowered = text.lower()
    html_offsets = [
        offset
        for marker in ("<!doctype html", "<html")
        if (offset := lowered.find(marker)) >= 0
    ]
    if html_offsets:
        text = f"{text[:min(html_offsets)].strip()} [html response omitted]"
    text = " ".join(text.split())
    if len(text) > max_length:
        text = f"{text[: max(0, max_length - 15)].rstrip()} [truncated]"
    return text or type(error).__name__


def normalize_exchange_position(
    raw_position: Mapping[str, Any],
    *,
    pending_algo: list[Mapping[str, Any]] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any] | None:
    """Normalize a CCXT/OKX position into journal-friendly shape."""
    info = _mapping(raw_position.get("info"))
    symbol = canonical_symbol(
        str(raw_position.get("symbol") or "")
        or str(info.get("instId") or "")
    )
    contracts = abs(_float(raw_position.get("contracts") or raw_position.get("size") or info.get("pos")))
    if not symbol or contracts <= 0:
        return None

    side = _side(raw_position, info)
    entry = _float(raw_position.get("entryPrice") or info.get("avgPx"))
    mark = _float(raw_position.get("markPrice") or info.get("markPx") or raw_position.get("last"))
    contract_size = _resolved_contract_size(raw_position, info, symbol)
    position_size = contracts * contract_size
    notional = _float(raw_position.get("notional") or info.get("notionalUsd"))
    if notional <= 0 and mark > 0:
        notional = position_size * mark

    protection = _protection_summary(symbol, side, pending_algo or [])
    synced_at = fetched_at or utc_now()
    return {
        "symbol": symbol,
        "instId": okx_swap_symbol(symbol),
        "ccxt_symbol": ccxt_swap_symbol(symbol),
        "side": "sell" if side == "short" else "buy",
        "position_side": side,
        "entry": round(entry, 8),
        "stop_loss": protection.get("stop_loss", 0.0),
        "take_profit": protection.get("take_profit", 0.0),
        "position_size": round(position_size, 8),
        "contracts": contracts,
        "contract_size": contract_size,
        "notional": round(notional, 8),
        "risk_usd": 0.0,
        "rr_ratio": 0.0,
        "confluence_score": 0,
        "regime": "",
        "opened_at": _position_open_time(info, synced_at),
        "entry_filled": True,
        "mode": "okx_demo",
        "status": "exchange_open",
        "source": "exchange_reconciler",
        "sync_status": "exchange_reconciled",
        "broker_sync_at": synced_at,
        "mark_price": round(mark, 8),
        "unrealized_pnl": _float(raw_position.get("unrealizedPnl") or info.get("upl"), signed=True),
        "leverage": _float(raw_position.get("leverage") or info.get("lever")),
        "margin_mode": str(raw_position.get("marginMode") or info.get("mgnMode") or ""),
        "protective_orders": protection.get("protective_orders", []),
        "orders": {
            "source": "exchange_reconciler",
            "protective_order_count": len(protection.get("protective_orders", [])),
        },
        "market_context": {
            "data_source": "okx_demo_exchange_snapshot",
            "sync_status": "exchange_reconciled",
            "mark_price": round(mark, 8),
        },
        "decision_context": {
            "thesis": "Imported from active OKX demo exchange exposure because journal was missing the open position.",
            "reasoning_summary": "Exchange reconciliation repair; original decision context may be incomplete.",
        },
        "open_reason": "Imported from active OKX demo exchange exposure during journal reconciliation.",
    }


def reconcile_journal_with_exchange(
    *,
    snapshot: Mapping[str, Any] | None = None,
    exchange: Any | None = None,
    journal_module: JournalModule = journal,
    include_pending_algo: bool = False,
    import_missing: bool = True,
    update_existing: bool = True,
) -> dict[str, Any]:
    """Repair journal open positions from exchange active-position truth."""
    snap = dict(snapshot) if snapshot is not None else fetch_okx_demo_snapshot(
        exchange=exchange,
        include_pending_algo=include_pending_algo,
        journal_module=journal_module,
    )
    exchange_positions = list(snap.get("positions") or [])
    exchange_keys = {canonical_symbol(pos.get("symbol")) for pos in exchange_positions}

    try:
        journal_positions = list(journal_module.read_positions())
    except Exception as exc:  # noqa: BLE001
        return _sync_status(
            snapshot=snap,
            journal_positions=[],
            missing_in_journal=[],
            missing_on_exchange=[],
            errors=[f"journal_read_failed: {exc}"],
        )

    journal_keys = {canonical_symbol(pos.get("symbol")) for pos in journal_positions}
    active_journal_keys = {
        canonical_symbol(pos.get("symbol"))
        for pos in journal_positions
        if _requires_active_exchange_position(pos)
    }
    missing_in_journal = sorted(key for key in exchange_keys - journal_keys if key)
    missing_on_exchange = sorted(key for key in active_journal_keys - exchange_keys if key)

    if update_existing:
        for exchange_pos in exchange_positions:
            key = canonical_symbol(exchange_pos.get("symbol"))
            for journal_pos in journal_positions:
                if canonical_symbol(journal_pos.get("symbol")) == key:
                    _update_existing_position(journal_module, journal_pos, exchange_pos)

    if import_missing:
        for exchange_pos in exchange_positions:
            if canonical_symbol(exchange_pos.get("symbol")) in missing_in_journal:
                journal_module.add_position(dict(exchange_pos))
                _safe_append_decision(
                    journal_module,
                    "exchange_reconciled_position",
                    {
                        "symbol": exchange_pos.get("symbol"),
                        "instId": exchange_pos.get("instId"),
                        "ccxt_symbol": exchange_pos.get("ccxt_symbol"),
                        "contracts": exchange_pos.get("contracts"),
                        "side": exchange_pos.get("side"),
                        "broker_sync_at": exchange_pos.get("broker_sync_at"),
                    },
                )

    status = _sync_status(
        snapshot=snap,
        journal_positions=journal_positions,
        missing_in_journal=missing_in_journal,
        missing_on_exchange=missing_on_exchange,
        errors=list(snap.get("errors") or []),
    )
    if missing_on_exchange:
        _safe_append_decision(
            journal_module,
            "exchange_reconciliation_drift",
            {
                "missing_on_exchange": missing_on_exchange,
                "message": "journal has open positions not found in exchange snapshot",
                "fetched_at": snap.get("fetched_at"),
            },
        )
    return status


def reconcile_pending_entries(
    *,
    exchange: Any | None = None,
    snapshot: Mapping[str, Any] | None = None,
    journal_module: JournalModule = journal,
    now_utc: str | datetime | None = None,
    ttl_s: int | None = None,
) -> dict[str, Any]:
    """Resolve demo limit entries without inventing a closed trade or PnL."""
    try:
        positions = list(journal_module.read_positions())
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "pending": 0,
            "resolved": 0,
            "filled": 0,
            "unresolved": 0,
            "retained": 0,
            "errors": [f"journal_read_failed: {exc}"],
        }

    pending = [position for position in positions if _is_pending_entry(position)]
    result: dict[str, Any] = {
        "status": "ok",
        "pending": len(pending),
        "resolved": 0,
        "filled": 0,
        "unresolved": 0,
        "retained": 0,
        "errors": [],
    }
    if not pending:
        return result

    snap = dict(snapshot) if snapshot is not None else fetch_okx_demo_snapshot(
        exchange=exchange,
        include_pending_algo=False,
        journal_module=journal_module,
    )
    snapshot_errors = [str(item) for item in snap.get("errors") or [] if item]
    if snapshot_errors:
        result["status"] = "error"
        result["retained"] = len(pending)
        result["errors"] = [f"exchange_snapshot_failed: {item}" for item in snapshot_errors]
        return result

    active_symbols = {
        canonical_symbol(position.get("symbol"))
        for position in snap.get("positions") or []
        if canonical_symbol(position.get("symbol"))
    }
    exchange_obj = exchange
    if exchange_obj is None:
        try:
            exchange_obj = _make_okx_exchange()
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["retained"] = len(pending)
            result["errors"] = [f"exchange_client_failed: {exc}"]
            return result

    now = _parse_utc_datetime(now_utc) or datetime.now(timezone.utc)
    pending_ttl_s = max(1, ttl_s if ttl_s is not None else _env_int("AUTO_PENDING_ENTRY_TTL_S", 3600))
    demo_cancel_allowed = _env_bool("OKX_TESTNET", False) and _env_bool("OKX_SANDBOX", False)

    for position in pending:
        symbol = canonical_symbol(position.get("symbol"))
        position_id = str(position.get("position_id") or position.get("decision_id") or "") or None
        if symbol in active_symbols:
            journal_module.update_position(
                str(position.get("symbol")),
                {"entry_filled": True, "status": "open"},
                position_id=position_id,
            )
            result["filled"] += 1
            continue

        expires_at = _pending_entry_expiry(position, ttl_s=pending_ttl_s)
        if expires_at is None:
            result["retained"] += 1
            result["errors"].append(f"{symbol}: pending_entry_timestamp_missing")
            continue
        expired = now >= expires_at
        orders = position.get("orders") if isinstance(position.get("orders"), Mapping) else {}
        order_id = str(orders.get("entry_id") or "").strip()
        if not order_id:
            if expired and _remove_pending_entry(
                journal_module,
                position,
                reason="ttl_expired_missing_order_id",
                resolved_at=now,
            ):
                result["resolved"] += 1
            else:
                result["retained"] += 1
            continue

        ccxt_symbol = ccxt_swap_symbol(symbol)
        try:
            order = exchange_obj.fetch_order(order_id, ccxt_symbol)
        except Exception as exc:  # noqa: BLE001
            if expired and _is_order_not_found_error(exc):
                if _remove_pending_entry(
                    journal_module,
                    position,
                    reason="broker_order_absent",
                    resolved_at=now,
                ):
                    result["resolved"] += 1
                else:
                    result["retained"] += 1
                continue
            result["retained"] += 1
            result["errors"].append(f"{symbol}: fetch_order_failed: {exc}")
            continue

        order_status = str((order or {}).get("status") or "").strip().lower()
        if order_status in {"canceled", "cancelled", "expired", "rejected"}:
            if _remove_pending_entry(
                journal_module,
                position,
                reason=f"broker_order_{order_status}",
                resolved_at=now,
            ):
                result["resolved"] += 1
            else:
                result["retained"] += 1
            continue
        if order_status in {"closed", "filled"}:
            if not expired:
                result["retained"] += 1
                result["errors"].append(f"{symbol}: filled_order_awaiting_active_position")
                continue
            if _remove_pending_entry(
                journal_module,
                position,
                reason="filled_without_active_exposure",
                resolved_at=now,
                outcome_status="unresolved",
                broker_evidence=_pending_order_evidence(order),
            ):
                result["resolved"] += 1
                result["unresolved"] += 1
            else:
                result["retained"] += 1
            continue
        if not expired:
            result["retained"] += 1
            continue
        if not demo_cancel_allowed:
            result["retained"] += 1
            result["errors"].append(f"{symbol}: pending_cancel_blocked_outside_demo")
            continue
        try:
            exchange_obj.cancel_order(order_id, ccxt_symbol)
        except Exception as exc:  # noqa: BLE001
            result["retained"] += 1
            result["errors"].append(f"{symbol}: cancel_order_failed: {exc}")
            continue
        if _remove_pending_entry(
            journal_module,
            position,
            reason="ttl_expired_canceled",
            resolved_at=now,
        ):
            result["resolved"] += 1
        else:
            result["retained"] += 1

    if result["errors"]:
        result["status"] = "partial" if result["resolved"] or result["filled"] else "error"
    return result


def run_startup_reconciliation(
    *,
    trigger: str = "startup",
    exchange: Any | None = None,
    journal_module: JournalModule = journal,
    include_pending_algo: bool = True,
) -> dict[str, Any]:
    """Synchronize OKX demo futures exposure before new entries are allowed."""
    trade_mode = os.getenv("TRADE_MODE", "spot").strip().lower()
    if not _env_bool("STARTUP_EXCHANGE_RECONCILE", True):
        _clear_startup_guard(journal_module)
        payload = {
            "status": "skipped",
            "trigger": trigger,
            "reason": "startup_exchange_reconcile_disabled",
            "trade_mode": trade_mode,
        }
        _safe_append_decision(journal_module, "startup_reconciliation_skipped", payload)
        return payload
    if trade_mode != "futures":
        _clear_startup_guard(journal_module)
        payload = {
            "status": "skipped",
            "trigger": trigger,
            "reason": "trade_mode_not_futures",
            "trade_mode": trade_mode,
        }
        _safe_append_decision(journal_module, "startup_reconciliation_skipped", payload)
        return payload

    started_at = utc_now()
    _safe_append_decision(
        journal_module,
        "startup_reconciliation_start",
        {
            "trigger": trigger,
            "trade_mode": trade_mode,
            "started_at": started_at,
        },
    )
    snapshot = fetch_okx_demo_snapshot(
        exchange=exchange,
        include_pending_algo=include_pending_algo,
        journal_module=journal_module,
    )
    snapshot_errors = [str(item) for item in snapshot.get("errors") or [] if item]
    if snapshot_errors:
        payload = {
            "status": "error",
            "trigger": trigger,
            "reason": "exchange_snapshot_failed",
            "errors": snapshot_errors,
            "started_at": started_at,
            "fetched_at": snapshot.get("fetched_at"),
            "positions_preserved": True,
        }
        if _env_bool("STARTUP_RECONCILE_REQUIRED", True):
            _set_startup_guard(journal_module, "exchange_snapshot_failed", payload)
        _safe_append_decision(journal_module, "startup_reconciliation_error", payload)
        return payload

    sync_status = reconcile_journal_with_exchange(
        snapshot=snapshot,
        journal_module=journal_module,
        import_missing=True,
        update_existing=True,
    )
    sync_errors = [str(item) for item in sync_status.get("errors") or [] if item]
    if sync_errors:
        payload = {
            "status": "error",
            "trigger": trigger,
            "reason": "journal_reconciliation_failed",
            "errors": sync_errors,
            "sync_status": sync_status,
            "started_at": started_at,
            "fetched_at": snapshot.get("fetched_at"),
            "positions_preserved": True,
        }
        if _env_bool("STARTUP_RECONCILE_REQUIRED", True):
            _set_startup_guard(journal_module, "journal_reconciliation_failed", payload)
        _safe_append_decision(journal_module, "startup_reconciliation_error", payload)
        return payload

    pending_status = reconcile_pending_entries(
        exchange=exchange,
        snapshot=snapshot,
        journal_module=journal_module,
    )

    _clear_startup_guard(journal_module)
    payload = {
        "status": "ok",
        "trigger": trigger,
        "started_at": started_at,
        "fetched_at": snapshot.get("fetched_at"),
        "positions_on_exchange": len(snapshot.get("positions") or []),
        "sync_status": sync_status,
        "pending_entry_status": pending_status,
    }
    _safe_append_decision(journal_module, "startup_reconciliation_complete", payload)
    return payload


def has_active_exchange_exposure(
    symbol: str,
    *,
    snapshot: Mapping[str, Any] | None = None,
    exchange: Any | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any]]:
    """Return whether OKX currently has active exposure for `symbol`."""
    snap = dict(snapshot) if snapshot is not None else fetch_okx_demo_snapshot(exchange=exchange)
    target = canonical_symbol(symbol)
    for position in snap.get("positions") or []:
        if canonical_symbol(position.get("symbol")) == target:
            return True, dict(position), snap
    return False, None, snap


def build_account_state(
    *,
    snapshot: Mapping[str, Any] | None,
    journal_stats: Mapping[str, Any],
) -> dict[str, Any]:
    """Build dashboard account state from exchange balance or journal fallback."""
    snap = dict(snapshot or {})
    errors = [str(item) for item in snap.get("account_errors") or [] if item]
    raw_balance = snap.get("account_balance")
    if isinstance(raw_balance, Mapping):
        account = normalize_account_balance(
            raw_balance,
            fetched_at=str(snap.get("fetched_at") or utc_now()),
            mode=str(snap.get("mode") or "demo"),
            journal_stats=journal_stats,
            positions=list(snap.get("positions") or []),
            errors=errors,
        )
        if str(account.get("source") or "").startswith("okx_demo"):
            return account
        errors = list(account.get("errors") or errors)
    return journal_account_state(journal_stats, errors=errors)


def normalize_account_balance(
    raw_balance: Mapping[str, Any],
    *,
    fetched_at: str,
    mode: str,
    journal_stats: Mapping[str, Any],
    positions: list[Mapping[str, Any]] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a CCXT/OKX balance response into `/api/trader/status` shape."""
    errors = list(errors or [])
    starting_capital = _first_number(
        journal_stats.get("starting_capital"),
        os.getenv("AUTO_CAPITAL"),
        default=10_000.0,
    )
    journal_realized = _first_number(journal_stats.get("total_pnl_usd"), default=0.0)
    account_row = _okx_account_row(raw_balance)
    usdt_detail = _okx_currency_detail(raw_balance, "USDT")
    total = _mapping(raw_balance.get("total"))
    free = _mapping(raw_balance.get("free"))
    used = _mapping(raw_balance.get("used"))
    usdt = _mapping(raw_balance.get("USDT"))

    current_capital = _first_number(
        account_row.get("totalEq"),
        account_row.get("adjEq"),
        usdt_detail.get("eqUsd"),
        usdt_detail.get("eq"),
        total.get("USDT"),
        total.get("USD"),
        usdt.get("total"),
        default=None,
    )
    if current_capital is None or current_capital <= 0:
        errors.append("account_equity_unavailable")
        return journal_account_state(journal_stats, errors=errors)

    available_balance = _first_number(
        usdt_detail.get("availEq"),
        usdt_detail.get("availBal"),
        free.get("USDT"),
        free.get("USD"),
        usdt.get("free"),
        default=None,
    )
    margin_used = _first_number(
        account_row.get("imr"),
        usdt_detail.get("imr"),
        used.get("USDT"),
        used.get("USD"),
        usdt.get("used"),
        default=None,
    )
    position_upl = sum(
        _first_number(position.get("unrealized_pnl"), default=0.0)
        for position in positions or []
    )
    unrealized_pnl = _first_number(
        usdt_detail.get("upl"),
        account_row.get("upl"),
        default=position_upl,
    )

    account = {
        "source": "okx_demo",
        "mode": mode or "demo",
        "synced_at": fetched_at,
        "starting_capital_usd": round(starting_capital, 2),
        "current_capital_usd": round(current_capital, 2),
        "total_pnl_usd": round(current_capital - starting_capital, 2),
        "unrealized_pnl_usd": round(unrealized_pnl, 2),
        "journal_realized_pnl_usd": round(journal_realized, 2),
        "available_balance_usd": round(available_balance, 2) if available_balance is not None else None,
        "margin_used_usd": round(margin_used, 2) if margin_used is not None else None,
        "errors": errors,
    }
    return _equity.apply_equity_cap(account)


def journal_account_state(
    journal_stats: Mapping[str, Any],
    *,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Return a dashboard-compatible account state from local journal stats."""
    starting_capital = _first_number(
        journal_stats.get("starting_capital"),
        os.getenv("AUTO_CAPITAL"),
        default=10_000.0,
    )
    current_capital = _first_number(
        journal_stats.get("current_capital"),
        default=starting_capital + _first_number(journal_stats.get("total_pnl_usd"), default=0.0),
    )
    realized = _first_number(journal_stats.get("total_pnl_usd"), default=current_capital - starting_capital)
    account = {
        "source": "journal_fallback",
        "mode": "journal",
        "synced_at": utc_now(),
        "starting_capital_usd": round(starting_capital, 2),
        "current_capital_usd": round(current_capital, 2),
        "total_pnl_usd": round(realized, 2),
        "unrealized_pnl_usd": 0.0,
        "journal_realized_pnl_usd": round(realized, 2),
        "available_balance_usd": None,
        "margin_used_usd": None,
        "errors": list(errors or []),
    }
    return _equity.apply_equity_cap(account)


def _sync_status(
    *,
    snapshot: Mapping[str, Any],
    journal_positions: list[Mapping[str, Any]],
    missing_in_journal: list[str],
    missing_on_exchange: list[str],
    errors: list[str],
) -> dict[str, Any]:
    if errors:
        status = "error"
    elif missing_in_journal:
        status = "journal_missing"
    elif missing_on_exchange:
        status = "exchange_missing"
    else:
        status = "in_sync"
    return {
        "status": status,
        "fetched_at": snapshot.get("fetched_at"),
        "exchange": snapshot.get("exchange", "okx"),
        "mode": snapshot.get("mode", "demo"),
        "positions_on_exchange": len(snapshot.get("positions") or []),
        "positions_in_journal": len(journal_positions),
        "missing_in_journal": missing_in_journal,
        "missing_on_exchange": missing_on_exchange,
        "errors": errors,
    }


def _update_existing_position(
    journal_module: JournalModule,
    journal_position: Mapping[str, Any],
    exchange_position: Mapping[str, Any],
) -> None:
    updates = {
        "entry_filled": True,
        "status": "open",
        "sync_status": "in_sync",
        "broker_sync_at": exchange_position.get("broker_sync_at"),
        "mark_price": exchange_position.get("mark_price"),
        "unrealized_pnl": exchange_position.get("unrealized_pnl"),
        "contracts": exchange_position.get("contracts"),
        "contract_size": exchange_position.get("contract_size"),
        "position_size": exchange_position.get("position_size"),
        "notional": exchange_position.get("notional"),
        "leverage": exchange_position.get("leverage"),
        "margin_mode": exchange_position.get("margin_mode"),
        "instId": exchange_position.get("instId"),
        "ccxt_symbol": exchange_position.get("ccxt_symbol"),
        "protective_orders": exchange_position.get("protective_orders", []),
        "exchange_missing_confirmed_at": None,
    }
    if exchange_position.get("stop_loss"):
        updates["stop_loss"] = exchange_position.get("stop_loss")
    if exchange_position.get("take_profit"):
        updates["take_profit"] = exchange_position.get("take_profit")
    journal_module.update_position(str(journal_position.get("symbol")), updates)


def _requires_active_exchange_position(position: Mapping[str, Any]) -> bool:
    """Return whether a local journal row should already exist on exchange."""
    if position.get("entry_filled") is False:
        return False
    if str(position.get("status") or "").strip().lower() == "pending_entry":
        return False
    return True


def _is_pending_entry(position: Mapping[str, Any]) -> bool:
    return (
        position.get("entry_filled") is False
        or str(position.get("status") or "").strip().lower() == "pending_entry"
    )


def _pending_entry_expiry(position: Mapping[str, Any], *, ttl_s: int) -> datetime | None:
    explicit = _parse_utc_datetime(position.get("pending_entry_expires_at"))
    if explicit is not None:
        return explicit
    opened_at = _parse_utc_datetime(position.get("opened_at"))
    return opened_at + timedelta(seconds=ttl_s) if opened_at is not None else None


def _parse_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_order_not_found_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("51603", "order does not exist", "order not found", "unknown order")
    )


def _remove_pending_entry(
    journal_module: JournalModule,
    position: Mapping[str, Any],
    *,
    reason: str,
    resolved_at: datetime,
    outcome_status: str = "not_opened",
    broker_evidence: Mapping[str, Any] | None = None,
) -> bool:
    symbol = str(position.get("symbol") or "")
    position_id = str(position.get("position_id") or position.get("decision_id") or "") or None
    removed = journal_module.remove_position(symbol, position_id=position_id)
    if removed is None:
        return False
    orders = position.get("orders") if isinstance(position.get("orders"), Mapping) else {}
    _safe_append_decision(
        journal_module,
        "pending_entry_resolved",
        {
            "symbol": canonical_symbol(symbol),
            "position_id": position_id,
            "order_id": orders.get("entry_id"),
            "reason": reason,
            "outcome_status": outcome_status,
            "performance_eligible": False,
            "broker_evidence": dict(broker_evidence or {}),
            "resolved_at": resolved_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "closed_trade_recorded": False,
        },
    )
    return True


def resolve_pending_entry(
    journal_module: JournalModule,
    position: Mapping[str, Any],
    *,
    reason: str,
    outcome_status: str = "not_opened",
    broker_evidence: Mapping[str, Any] | None = None,
) -> bool:
    """Archive a broker-resolved pending entry without creating performance."""
    return _remove_pending_entry(
        journal_module,
        position,
        reason=reason,
        resolved_at=datetime.now(timezone.utc),
        outcome_status=outcome_status,
        broker_evidence=broker_evidence,
    )


def _pending_order_evidence(order: Any) -> dict[str, Any]:
    if not isinstance(order, Mapping):
        return {}
    fields = (
        "id",
        "clientOrderId",
        "status",
        "symbol",
        "side",
        "type",
        "price",
        "average",
        "filled",
        "remaining",
        "cost",
        "timestamp",
        "datetime",
        "lastTradeTimestamp",
    )
    return {field: order.get(field) for field in fields if order.get(field) is not None}


def _fetch_pending_algo_orders(raw_positions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    symbols = sorted({
        okx_swap_symbol(str(pos.get("symbol") or _mapping(pos.get("info")).get("instId") or ""))
        for pos in raw_positions
        if pos
    })
    symbols = [symbol for symbol in symbols if symbol]
    if not symbols:
        return []
    try:
        from brackets.okx_futures_bracket import _signed_headers, load_okx_config  # type: ignore
        import requests  # type: ignore
    except Exception:
        return []
    cfg = load_okx_config()
    out: list[dict[str, Any]] = []
    for inst_id in symbols:
        path = f"/api/v5/trade/orders-algo-pending?ordType=oco&instType=SWAP&instId={inst_id}"
        headers = _signed_headers(cfg, "GET", path)
        if cfg.get("testnet") or cfg.get("sandbox"):
            headers["x-simulated-trading"] = "1"
        try:
            resp = requests.get("https://www.okx.com" + path, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        if data.get("code") != "0":
            continue
        for row in data.get("data") or []:
            if isinstance(row, dict):
                out.append(row)
    return out


def _protection_summary(
    symbol: str,
    side: str,
    pending_algo: list[Mapping[str, Any]],
) -> dict[str, Any]:
    inst_id = okx_swap_symbol(symbol)
    rows = [
        row for row in pending_algo
        if canonical_symbol(str(row.get("instId") or "")) == canonical_symbol(inst_id)
        and str(row.get("state") or "").lower() in {"", "live", "effective"}
    ]
    protective_orders: list[dict[str, Any]] = []
    take_profits: list[float] = []
    stop_losses: list[float] = []
    for row in rows:
        tp = _float(row.get("tpTriggerPx"))
        sl = _float(row.get("slTriggerPx"))
        if tp > 0:
            take_profits.append(tp)
        if sl > 0:
            stop_losses.append(sl)
        protective_orders.append({
            "algoId": row.get("algoId"),
            "ordType": row.get("ordType"),
            "side": row.get("side"),
            "posSide": row.get("posSide"),
            "sz": row.get("sz"),
            "tpTriggerPx": row.get("tpTriggerPx"),
            "slTriggerPx": row.get("slTriggerPx"),
            "state": row.get("state"),
        })
    if side == "short":
        take_profit = min(take_profits) if take_profits else 0.0
        stop_loss = max(stop_losses) if stop_losses else 0.0
    else:
        take_profit = max(take_profits) if take_profits else 0.0
        stop_loss = min(stop_losses) if stop_losses else 0.0
    return {
        "take_profit": round(take_profit, 8),
        "stop_loss": round(stop_loss, 8),
        "protective_orders": protective_orders,
    }


def _make_okx_exchange() -> Any:
    """Create a read-only CCXT OKX client in sandbox/testnet mode."""
    import ccxt  # type: ignore

    exchange = ccxt.okx({
        "apiKey": os.getenv("OKX_API_KEY", "").strip(),
        "secret": os.getenv("OKX_API_SECRET", "").strip(),
        "password": os.getenv("OKX_PASSPHRASE", "").strip(),
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    if os.getenv("OKX_TESTNET", "true").strip().lower() in {"1", "true", "yes", "on"}:
        exchange.set_sandbox_mode(True)
    return exchange


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _set_startup_guard(
    journal_module: JournalModule,
    reason: str,
    details: dict[str, Any],
) -> None:
    setter = getattr(journal_module, "set_startup_sync_guard", None)
    if callable(setter):
        try:
            setter(reason, details)
            return
        except Exception:
            pass
    _safe_append_decision(
        journal_module,
        "startup_sync_guard_unavailable",
        {"reason": reason, "details": details},
    )


def _clear_startup_guard(journal_module: JournalModule) -> None:
    clearer = getattr(journal_module, "clear_startup_sync_guard", None)
    if callable(clearer):
        try:
            clearer()
        except Exception:
            pass


def _contract_size(symbol: str) -> float:
    try:
        from brackets.okx_futures_bracket import get_symbol_meta  # type: ignore
        return float(get_symbol_meta(okx_swap_symbol(symbol)).contract_size)
    except Exception:
        return {
            "BTC-USDT": 0.01,
            "ETH-USDT": 0.01,
            "BNB-USDT": 0.01,
            "SOL-USDT": 1.0,
        }.get(canonical_symbol(symbol), 1.0)


def _resolved_contract_size(
    raw_position: Mapping[str, Any],
    info: Mapping[str, Any],
    symbol: str,
) -> float:
    for value in (raw_position.get("contractSize"), info.get("ctVal")):
        parsed = _float(value)
        if parsed > 0:
            return parsed
    return _contract_size(symbol)


def _side(raw_position: Mapping[str, Any], info: Mapping[str, Any]) -> str:
    raw_side = str(raw_position.get("side") or info.get("posSide") or "").lower()
    if raw_side in {"short", "sell"}:
        return "short"
    if raw_side in {"long", "buy"}:
        return "long"
    signed_pos = _float(info.get("pos"), signed=True)
    return "short" if signed_pos < 0 else "long"


def _position_open_time(info: Mapping[str, Any], fallback: str) -> str:
    raw = str(info.get("cTime") or info.get("uTime") or "").strip()
    try:
        if raw:
            value = int(raw)
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        pass
    return fallback


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _okx_account_row(raw_balance: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the first OKX account balance row from raw CCXT or REST shape."""
    direct_data = raw_balance.get("data")
    info_data = _mapping(raw_balance.get("info")).get("data")
    for data in (direct_data, info_data):
        if isinstance(data, list) and data and isinstance(data[0], Mapping):
            return data[0]
    return {}


def _okx_currency_detail(raw_balance: Mapping[str, Any], currency: str) -> Mapping[str, Any]:
    """Return one OKX currency detail row from raw CCXT or REST shape."""
    target = currency.strip().upper()
    account_row = _okx_account_row(raw_balance)
    details = account_row.get("details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, Mapping) and str(detail.get("ccy") or "").upper() == target:
                return detail
    raw_currency = raw_balance.get(target)
    return raw_currency if isinstance(raw_currency, Mapping) else {}


def _first_number(*values: Any, default: float | None = 0.0) -> float | None:
    """Return the first finite numeric value, preserving sign."""
    for value in values:
        if value is None or value == "":
            continue
        try:
            out = float(value)
        except (TypeError, ValueError):
            continue
        if out == out and out not in {float("inf"), float("-inf")}:
            return out
    return default


def _float(value: Any, *, signed: bool = False) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        out = 0.0
    return out if signed else abs(out)


def _safe_append_decision(
    journal_module: JournalModule,
    decision_type: str,
    payload: dict[str, Any],
) -> None:
    try:
        journal_module.append_decision(decision_type, payload)
    except Exception:
        return
