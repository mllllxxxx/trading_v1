"""Read-only Telegram trading cockpit snapshot, metrics, and rendering.

The primary snapshot comes from the same loopback API read model used by the
web cockpit. Local journal reads are a labelled compatibility fallback only.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

import requests

MAX_TEXT_LEN = 3900
PAGE_SIZE = 5
VALID_VIEWS = {"overview", "positions", "decisions", "performance", "teams", "system", "decision"}
PERFORMANCE_WINDOWS = ("today", "7d", "30d", "all")
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass(slots=True)
class DashboardState:
    """Persisted state for the single pinned Telegram dashboard message."""

    message_id: int | None = None
    view: str = "overview"
    page: int = 0
    detail_key: str | None = None
    last_content_hash: str = ""
    last_update_utc: str | None = None


@dataclass(slots=True)
class DashboardRender:
    """Rendered Telegram message and inline keyboard payload."""

    text: str
    reply_markup: dict[str, Any]


class DashboardStateStore:
    """Atomically persist dashboard presentation state outside the journal."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DashboardState:
        """Return stored state, or a safe default when absent/corrupt."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return DashboardState()
            message_id = raw.get("message_id")
            return DashboardState(
                message_id=int(message_id) if message_id is not None else None,
                view=str(raw.get("view") or "overview"),
                page=max(0, int(raw.get("page") or 0)),
                detail_key=str(raw.get("detail_key")) if raw.get("detail_key") else None,
                last_content_hash=str(raw.get("last_content_hash") or ""),
                last_update_utc=str(raw.get("last_update_utc")) if raw.get("last_update_utc") else None,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return DashboardState()

    def save(self, state: DashboardState) -> None:
        """Write state through an adjacent temporary file and atomic replace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)


class TelegramSnapshotProvider:
    """Load the canonical trader-status snapshot with journal fallback."""

    def __init__(self, status_url: str | None = None, timeout_s: float = 6.0) -> None:
        self.status_url = status_url or os.getenv(
            "TELEGRAM_TRADER_STATUS_URL",
            "http://127.0.0.1:8000/api/trader/status",
        )
        self.timeout_s = timeout_s

    def load(self) -> dict[str, Any]:
        """Return a normalized snapshot and attach Telegram source metadata."""
        try:
            response = requests.get(self.status_url, timeout=self.timeout_s)
            payload = response.json()
            if not response.ok or not isinstance(payload, dict) or payload.get("error"):
                detail = _safe_error(payload.get("error") if isinstance(payload, dict) else response.status_code)
                raise RuntimeError(detail or f"status_http_{response.status_code}")
            payload["_telegram_source"] = {
                "source": "trader_status_api",
                "fallback": False,
                "loaded_at": _now_iso(),
            }
            return payload
        except Exception as exc:  # noqa: BLE001 - fallback is the reliability boundary
            primary_error = _safe_error(exc)
            try:
                return build_local_snapshot(error=primary_error)
            except Exception as fallback_exc:  # noqa: BLE001 - last-resort snapshot
                return build_minimal_snapshot(
                    primary_error=primary_error,
                    fallback_error=_safe_error(fallback_exc),
                )


def build_local_snapshot(*, error: str = "") -> dict[str, Any]:
    """Build a labelled journal fallback with isolated component reads."""
    try:
        from . import journal
    except ImportError:  # pragma: no cover - top-level script/runtime compatibility
        import journal  # type: ignore

    component_errors: dict[str, str] = {}
    _safe_component_read(
        "journal",
        journal.ensure_dirs,
        None,
        component_errors,
    )
    positions = _safe_component_read(
        "positions",
        journal.read_positions,
        [],
        component_errors,
    )
    closed_trades = _safe_component_read(
        "closed_trades",
        journal.read_closed_trades,
        [],
        component_errors,
    )
    stats = _safe_component_read(
        "stats",
        journal.read_stats,
        {},
        component_errors,
    )
    stats = dict(stats) if isinstance(stats, Mapping) else {}
    stats["daily_llm_cost"] = _safe_component_read(
        "llm_cost",
        journal.daily_cost_status,
        {},
        component_errors,
    )
    decisions = _safe_component_read(
        "decisions",
        lambda: _read_jsonl_tail(journal.DECISIONS_LOG, 200),
        [],
        component_errors,
    )
    llm_decisions = _safe_component_read(
        "llm_decisions",
        lambda: journal.read_llm_decisions(limit=50, event_limit=20_000),
        [],
        component_errors,
    )
    strategy_teams: list[dict[str, Any]] = []
    if "positions" in component_errors or "closed_trades" in component_errors:
        component_errors["strategy_teams"] = "dependent position or closed-trade data unavailable"
    else:
        try:
            from strategy_teams import build_team_dashboard  # type: ignore

            strategy_teams = build_team_dashboard(positions, closed_trades)
        except Exception as exc:  # noqa: BLE001 - degraded dashboard should still render
            component_errors["strategy_teams"] = _safe_error(exc)

    kill_switch_active = bool(
        _safe_component_read("kill_switch", journal.is_killed, False, component_errors)
    )
    trading_blocked = bool(
        _safe_component_read(
            "trading_blocked",
            getattr(journal, "is_trading_blocked", journal.is_killed),
            kill_switch_active,
            component_errors,
        )
    )
    trading_block_reason = _safe_component_read(
        "trading_block_reason",
        getattr(journal, "trading_block_reason", lambda: ""),
        "",
        component_errors,
    )
    startup_sync_guard_active = bool(
        _safe_component_read(
            "startup_sync_guard",
            getattr(journal, "startup_sync_guard_active", lambda: False),
            False,
            component_errors,
        )
    )
    fallback_errors = [item for item in [error, *component_errors.values()] if item]
    return {
        "running": True,
        "started_at": getattr(journal, "SESSION_START", None).isoformat()
        if getattr(journal, "SESSION_START", None)
        else None,
        "kill_switch_active": kill_switch_active,
        "trading_blocked": trading_blocked,
        "trading_block_reason": trading_block_reason,
        "startup_sync_guard_active": startup_sync_guard_active,
        "timestamp": _now_iso(),
        "positions": positions,
        "exchange_positions": [],
        "closed_trades": closed_trades,
        "stats": stats,
        "strategy_teams": strategy_teams,
        "account_state": {
            "source": "journal_fallback",
            "mode": "journal",
            "synced_at": _now_iso(),
            "starting_capital_usd": _number(stats.get("starting_capital")),
            "current_capital_usd": _number(stats.get("current_capital")),
            "total_pnl_usd": _number(stats.get("total_pnl_usd")),
            "journal_realized_pnl_usd": _number(stats.get("total_pnl_usd")),
            "unrealized_pnl_usd": None,
            "available_balance_usd": None,
            "margin_used_usd": None,
            "errors": fallback_errors,
        },
        "sync_status": {
            "status": "degraded" if component_errors else "fallback",
            "error": error or next(iter(component_errors.values()), None),
        },
        "decisions": decisions,
        "llm_decisions": llm_decisions,
        "_telegram_source": {
            "source": "journal_fallback",
            "fallback": True,
            "error": error,
            "component_errors": component_errors,
            "loaded_at": _now_iso(),
        },
    }


def build_minimal_snapshot(*, primary_error: str, fallback_error: str) -> dict[str, Any]:
    """Return a renderable last-resort snapshot when all data reads fail."""
    now = _now_iso()
    unavailable = fallback_error or "unavailable"
    component_errors = {
        "journal_fallback": unavailable,
        "positions": unavailable,
        "closed_trades": unavailable,
        "llm_decisions": unavailable,
        "strategy_teams": unavailable,
    }
    errors = [item for item in (primary_error, fallback_error) if item]
    return {
        "running": True,
        "state_unknown": True,
        "timestamp": now,
        "trading_blocked": None,
        "trading_block_reason": "observability_unavailable",
        "positions": [],
        "exchange_positions": [],
        "closed_trades": [],
        "stats": {},
        "strategy_teams": [],
        "decisions": [],
        "llm_decisions": [],
        "account_state": {
            "source": "unavailable",
            "mode": "degraded",
            "synced_at": now,
            "errors": errors,
        },
        "sync_status": {"status": "error", "error": fallback_error or primary_error},
        "_telegram_source": {
            "source": "minimal_fallback",
            "fallback": True,
            "error": primary_error,
            "component_errors": component_errors,
            "loaded_at": now,
        },
    }


def _safe_component_read(
    name: str,
    reader: Callable[[], Any],
    default: Any,
    errors: dict[str, str],
) -> Any:
    """Read one fallback component without allowing it to abort the snapshot."""
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 - observability must degrade, not die
        errors[name] = _safe_error(exc)
        return default


def render_dashboard(
    snapshot: Mapping[str, Any],
    *,
    view: str = "overview",
    page: int = 0,
    detail_key: str | None = None,
) -> DashboardRender:
    """Render one dashboard view and its read-only inline keyboard."""
    safe_view = view if view in VALID_VIEWS else "overview"
    safe_page = max(0, page)
    if safe_view == "positions":
        body, page_count = _render_positions(snapshot, safe_page)
    elif safe_view == "decisions":
        body, page_count = _render_decisions(snapshot, safe_page)
    elif safe_view == "decision":
        body, page_count = _render_decision_detail(snapshot, detail_key), 1
    elif safe_view == "performance":
        body, page_count = _render_performance(snapshot, safe_page), len(PERFORMANCE_WINDOWS)
    elif safe_view == "teams":
        body, page_count = _render_teams(snapshot), 1
    elif safe_view == "system":
        body, page_count = _render_system(snapshot), 1
    else:
        body, page_count = _render_overview(snapshot), 1
    header = _render_header(snapshot, safe_view)
    text = _limit_text(f"{header}\n\n{body}")
    keyboard = _build_keyboard(
        snapshot,
        view=safe_view,
        page=safe_page,
        page_count=page_count,
        detail_key=detail_key,
    )
    return DashboardRender(text=text, reply_markup={"inline_keyboard": keyboard})


def parse_dashboard_callback(data: str) -> tuple[str, int, str | None] | None:
    """Parse and validate a namespaced read-only dashboard callback."""
    parts = data.split(":", 3)
    if len(parts) < 2 or parts[0] != "dash":
        return None
    view = parts[1]
    if view == "refresh":
        return "overview", 0, None
    if view not in VALID_VIEWS:
        return None
    try:
        page = max(0, int(parts[2])) if len(parts) >= 3 and parts[2] else 0
    except ValueError:
        return None
    detail_key = parts[3] if len(parts) == 4 and parts[3] else None
    return view, page, detail_key


def content_hash(rendered: DashboardRender) -> str:
    """Return a stable hash of text and keyboard used to suppress no-op edits."""
    raw = json.dumps(
        {"text": rendered.text, "reply_markup": rendered.reply_markup},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decision_key(decision: Mapping[str, Any]) -> str:
    """Create a compact stable callback key for a decision record."""
    identity = "|".join(
        str(decision.get(key) or "")
        for key in ("decision_id", "ticket_decision_id", "ts", "timestamp_utc", "symbol", "action")
    )
    return hashlib.sha1(identity.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def performance_metrics(
    trades: Sequence[Mapping[str, Any]],
    *,
    window: str = "all",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute fee-aware journal performance for a supported time window."""
    current = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    selected = [trade for trade in trades if _within_window(trade, window, current)]
    pnls = [_number(trade.get("pnl_usd"), 0.0) or 0.0 for trade in selected]
    gross_values = [
        _number(trade.get("gross_pnl_usd"), pnl) or 0.0
        for trade, pnl in zip(selected, pnls, strict=False)
    ]
    fees = [_number(trade.get("fees_usd"), 0.0) or 0.0 for trade in selected]
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl <= 0)
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    r_values = []
    for trade, pnl in zip(selected, pnls, strict=False):
        risk = _number(trade.get("risk_usd"), 0.0) or 0.0
        if risk > 0:
            r_values.append(pnl / risk)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    streak = 0
    streak_kind = "none"
    for pnl in reversed(pnls):
        kind = "win" if pnl > 0 else "loss"
        if streak_kind == "none":
            streak_kind = kind
        if kind != streak_kind:
            break
        streak += 1
    return {
        "window": window,
        "trades": len(selected),
        "wins": wins,
        "losses": losses,
        "winrate": wins / len(selected) * 100.0 if selected else 0.0,
        "gross_pnl_usd": sum(gross_values),
        "fees_usd": sum(fees),
        "net_pnl_usd": sum(pnls),
        "avg_pnl_usd": sum(pnls) / len(pnls) if pnls else 0.0,
        "best_trade_usd": max(pnls) if pnls else 0.0,
        "worst_trade_usd": min(pnls) if pnls else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        "expectancy_r": sum(r_values) / len(r_values) if r_values else 0.0,
        "max_drawdown_usd": max_drawdown,
        "streak": streak,
        "streak_kind": streak_kind,
    }


def _render_header(snapshot: Mapping[str, Any], view: str) -> str:
    blocked = bool(snapshot.get("trading_blocked") or snapshot.get("kill_switch_active"))
    state = (
        "⚠️ TRẠNG THÁI KHÔNG RÕ"
        if snapshot.get("state_unknown")
        else "⛔ ĐANG DỪNG" if blocked else "🟢 DEMO ĐANG CHẠY"
    )
    source = _mapping(snapshot.get("_telegram_source"))
    source_label = "journal fallback" if source.get("fallback") else "trader status"
    if _mapping(source.get("component_errors")):
        source_label += " · degraded"
    updated = _format_time(snapshot.get("timestamp") or source.get("loaded_at"))
    return (
        f"<b>TRADE_V1 · TELEGRAM COCKPIT</b>\n"
        f"{state} · <code>{_escape(view.upper())}</code>\n"
        f"Nguồn: {_escape(source_label)} · {_escape(updated)}"
    )


def _render_overview(snapshot: Mapping[str, Any]) -> str:
    account = _mapping(snapshot.get("account_state"))
    stats = _mapping(snapshot.get("stats"))
    positions = _list_of_mappings(snapshot.get("positions"))
    teams = _list_of_mappings(snapshot.get("strategy_teams"))
    pending = sum(1 for item in positions if str(item.get("status") or "").lower() == "pending_entry")
    realized = account.get("journal_realized_pnl_usd", stats.get("total_pnl_usd"))
    unrealized = account.get("unrealized_pnl_usd")
    team_equity = sum(_number(team.get("current_equity_usd"), 0.0) or 0.0 for team in teams)
    team_capital = sum(_number(team.get("team_capital_usd"), 0.0) or 0.0 for team in teams)
    budget = _mapping(stats.get("daily_llm_cost"))
    block_reason = str(snapshot.get("trading_block_reason") or "none")
    positions_error = _component_error(snapshot, "positions")
    positions_summary = (
        "N/A · position data unavailable"
        if positions_error
        else f"{len(positions)} open/pending · {pending} pending"
    )
    return (
        "<b>📊 Tổng quan</b>\n"
        f"Equity broker/cap: {_money(account.get('current_capital_usd'))}\n"
        f"Available: {_money(account.get('available_balance_usd'))} · Margin: {_money(account.get('margin_used_usd'))}\n"
        f"Realized: {_signed_money(realized)} · Unrealized: {_signed_money(unrealized)}\n"
        f"Tournament: {_money(team_equity)} / {_money(team_capital)}\n"
        f"Lệnh: {positions_summary}\n"
        f"Winrate: {_percent(stats.get('winrate'))} · DD: {_money(stats.get('max_drawdown_usd'))}\n"
        f"LLM: {_money(budget.get('cost_usd'), digits=4)} / {_money(budget.get('cap_usd'))} "
        f"({_percent(budget.get('pct_of_cap'))})\n"
        f"Guard: <code>{_escape(block_reason)}</code>"
    )


def _render_positions(snapshot: Mapping[str, Any], page: int) -> tuple[str, int]:
    positions_error = _component_error(snapshot, "positions")
    if positions_error:
        return (
            "<b>📂 Lệnh đang theo dõi</b>\n"
            "⚠️ Dữ liệu vị thế không khả dụng; không được hiểu là tài khoản đang flat.\n"
            f"<code>{_escape(_truncate(positions_error, 240))}</code>",
            1,
        )
    positions = _list_of_mappings(snapshot.get("positions"))
    if not positions:
        return "<b>📂 Lệnh đang theo dõi</b>\nKhông có lệnh open hoặc pending.", 1
    page_count = max(1, (len(positions) + PAGE_SIZE - 1) // PAGE_SIZE)
    current = min(page, page_count - 1)
    chunk = positions[current * PAGE_SIZE:(current + 1) * PAGE_SIZE]
    lines = [f"<b>📂 Lệnh · trang {current + 1}/{page_count}</b>"]
    for position in chunk:
        team = position.get("team_name") or position.get("team_id") or "legacy"
        status = str(position.get("status") or ("open" if position.get("entry_filled", True) else "pending"))
        mark = position.get("mark_price", position.get("markPx"))
        lines.extend(
            [
                "",
                f"<b>{_escape(team)} · {_escape(position.get('symbol') or '?')} {_escape(str(position.get('side') or '?').upper())}</b>",
                f"{_escape(status)} · Entry {_price(position.get('entry'))} · Mark {_price(mark)}",
                f"SL {_price(position.get('stop_loss'))} · TP {_price(position.get('take_profit'))}",
                f"Size {_value(position.get('position_size'))} · Contracts {_value(position.get('broker_contracts'))} · Lev {_value(position.get('leverage'))}x",
                f"Risk {_money(position.get('risk_usd'))} · Margin {_money(position.get('margin_used_usd'))} · uPnL {_signed_money(position.get('unrealized_pnl', position.get('unrealized_pnl_usd')))}",
            ]
        )
    return "\n".join(lines), page_count


def _render_decisions(snapshot: Mapping[str, Any], page: int) -> tuple[str, int]:
    decisions_error = _component_error(snapshot, "llm_decisions")
    if decisions_error:
        return (
            "<b>🧠 Decision log</b>\n"
            "⚠️ Decision data không khả dụng.\n"
            f"<code>{_escape(_truncate(decisions_error, 240))}</code>",
            1,
        )
    decisions = list(reversed(_list_of_mappings(snapshot.get("llm_decisions"))))
    if not decisions:
        return "<b>🧠 Decision log</b>\nChưa có quyết định LLM.", 1
    page_count = max(1, (len(decisions) + PAGE_SIZE - 1) // PAGE_SIZE)
    current = min(page, page_count - 1)
    chunk = decisions[current * PAGE_SIZE:(current + 1) * PAGE_SIZE]
    lines = [f"<b>🧠 Decisions · trang {current + 1}/{page_count}</b>"]
    for decision in chunk:
        team = decision.get("team_name") or decision.get("team_id") or decision.get("source") or "system"
        action = decision.get("action") or decision.get("type") or "?"
        confidence = decision.get("confidence")
        reasoning = decision.get("reasoning") or decision.get("reasoning_text") or decision.get("thesis") or ""
        lines.extend(
            [
                "",
                f"<b>{_escape(team)} · {_escape(decision.get('symbol') or '?')} · {_escape(str(action).upper())}</b>",
                f"Conf {_percent(_confidence_pct(confidence))} · {_escape(_format_time(decision.get('ts') or decision.get('timestamp_utc')))}",
                _escape(_truncate(str(reasoning), 190)) or "—",
            ]
        )
    return "\n".join(lines), page_count


def _render_decision_detail(snapshot: Mapping[str, Any], key: str | None) -> str:
    decisions = list(reversed(_list_of_mappings(snapshot.get("llm_decisions"))))
    decision = next((item for item in decisions if decision_key(item) == key), None)
    if decision is None:
        return "<b>🧠 Decision detail</b>\nQuyết định không còn trong cửa sổ hiện tại."
    decision_id = str(decision.get("decision_id") or decision.get("ticket_decision_id") or "")
    raw_events = _list_of_mappings(snapshot.get("decisions"))
    timeline = [item for item in raw_events if decision_id and str(item.get("decision_id") or "") == decision_id]
    lines = [
        "<b>🧠 Decision detail</b>",
        f"ID: <code>{_escape(_truncate(decision_id or 'N/A', 80))}</code>",
        f"Team: {_escape(decision.get('team_name') or decision.get('team_id') or decision.get('source') or 'system')}",
        f"Symbol: {_escape(decision.get('symbol') or '?')}",
        f"Action: <b>{_escape(str(decision.get('action') or decision.get('type') or '?').upper())}</b>",
        f"Confidence: {_percent(_confidence_pct(decision.get('confidence')))}",
        f"Playbook: <code>{_escape(decision.get('playbook_id') or 'N/A')}</code>",
        "",
        _escape(_truncate(str(decision.get("reasoning") or decision.get("thesis") or "Không có thesis."), 700)),
    ]
    if timeline:
        lines.append("\n<b>Lifecycle</b>")
        for event in timeline[-10:]:
            label = event.get("event_type") or event.get("type") or "event"
            reason = _mapping(event.get("payload")).get("reason") or event.get("reason") or ""
            suffix = f" · {_truncate(str(reason), 80)}" if reason else ""
            lines.append(f"• {_escape(label)}{_escape(suffix)}")
    return "\n".join(lines)


def _render_performance(snapshot: Mapping[str, Any], page: int) -> str:
    closed_error = _component_error(snapshot, "closed_trades")
    if closed_error:
        return (
            "<b>📈 Hiệu suất</b>\n"
            "⚠️ Closed-trade data không khả dụng.\n"
            f"<code>{_escape(_truncate(closed_error, 240))}</code>"
        )
    window = PERFORMANCE_WINDOWS[min(page, len(PERFORMANCE_WINDOWS) - 1)]
    metrics = performance_metrics(_list_of_mappings(snapshot.get("closed_trades")), window=window)
    pf = metrics["profit_factor"]
    pf_text = "∞" if pf == float("inf") else f"{pf:.2f}"
    label = {"today": "Hôm nay", "7d": "7 ngày", "30d": "30 ngày", "all": "Toàn bộ"}[window]
    return (
        f"<b>📈 Hiệu suất · {label}</b>\n"
        f"Trades: {metrics['trades']} · W/L {metrics['wins']}/{metrics['losses']} · WR {metrics['winrate']:.1f}%\n"
        f"Gross: {_signed_money(metrics['gross_pnl_usd'])} · Fees: {_money(metrics['fees_usd'])}\n"
        f"Net: <b>{_signed_money(metrics['net_pnl_usd'])}</b> · Avg: {_signed_money(metrics['avg_pnl_usd'])}\n"
        f"Best/Worst: {_signed_money(metrics['best_trade_usd'])} / {_signed_money(metrics['worst_trade_usd'])}\n"
        f"Expectancy: {metrics['expectancy_r']:.2f}R · PF: {pf_text}\n"
        f"Max DD: {_money(metrics['max_drawdown_usd'])} · Streak: {metrics['streak']} {metrics['streak_kind']}"
    )


def _render_teams(snapshot: Mapping[str, Any]) -> str:
    teams_error = _component_error(snapshot, "strategy_teams")
    if teams_error:
        return (
            "<b>🏁 Tournament</b>\n"
            "⚠️ Leaderboard không khả dụng vì dữ liệu phụ thuộc đang lỗi.\n"
            f"<code>{_escape(_truncate(teams_error, 240))}</code>"
        )
    teams = sorted(
        _list_of_mappings(snapshot.get("strategy_teams")),
        key=lambda item: int(item.get("rank") or 999),
    )
    if not teams:
        return "<b>🏁 Tournament</b>\nChưa có dữ liệu đội."
    lines = ["<b>🏁 Tournament leaderboard</b>"]
    for team in teams:
        name = team.get("team_name") or team.get("team_id") or "?"
        lines.extend(
            [
                "",
                f"<b>#{int(team.get('rank') or 0)} {_escape(name)}</b> · score {_value(team.get('competition_score'))}",
                f"Equity {_money(team.get('current_equity_usd'))} · PnL {_signed_money(team.get('realized_pnl_usd'))} / uPnL {_signed_money(team.get('unrealized_pnl_usd'))}",
                f"Trades {int(team.get('closed_trades') or 0)}/30 · WR {_percent(team.get('winrate'))} · Exp {_value(team.get('expectancy_r'))}R",
                f"PF {_value(team.get('profit_factor'))} · DD {_money(team.get('max_drawdown_usd'))} · {_escape(team.get('ranking_status') or 'provisional')}",
            ]
        )
    return "\n".join(lines)


def _render_system(snapshot: Mapping[str, Any]) -> str:
    sync = _mapping(snapshot.get("sync_status"))
    account = _mapping(snapshot.get("account_state"))
    cache = _mapping(account.get("cache"))
    stats = _mapping(snapshot.get("stats"))
    budget = _mapping(stats.get("daily_llm_cost"))
    decisions = list(reversed(_list_of_mappings(snapshot.get("decisions"))))
    error_types = {"error", "llm_error", "fail_closed_skip", "telegram_delivery_error", "startup_sync_guard_set"}
    recent_errors = [item for item in decisions if str(item.get("type") or item.get("event_type")) in error_types][:5]
    component_errors = _mapping(
        _mapping(snapshot.get("_telegram_source")).get("component_errors")
    )
    lines = [
        "<b>🛠 Hệ thống</b>",
        f"Running: {_yes_no(snapshot.get('running'))} · Blocked: {_yes_no(snapshot.get('trading_blocked'))}",
        f"Guard: <code>{_escape(snapshot.get('trading_block_reason') or 'none')}</code>",
        f"Sync: {_escape(sync.get('status') or 'unknown')} · {_escape(_format_time(sync.get('synced_at') or account.get('synced_at')))}",
        f"Account source: {_escape(account.get('source') or 'unknown')} · Cache: {_escape(cache.get('status') or 'N/A')}",
        f"LLM calls: {_value(budget.get('calls'))}/{_value(budget.get('call_cap'))} · hour {_value(budget.get('hourly_calls'))}/{_value(budget.get('hourly_call_cap'))}",
        f"LLM cost: {_money(budget.get('cost_usd'), digits=4)} / {_money(budget.get('cap_usd'))}",
    ]
    if recent_errors:
        lines.append("\n<b>Lỗi/fail-closed gần nhất</b>")
        for item in recent_errors:
            label = item.get("type") or item.get("event_type") or "error"
            payload = _mapping(item.get("payload"))
            message = item.get("error") or item.get("reason") or payload.get("reason") or payload.get("error") or ""
            lines.append(f"• {_escape(label)} · {_escape(_truncate(str(message), 120))}")
    if component_errors:
        lines.append("\n<b>Fallback components unavailable</b>")
        for name, message in list(component_errors.items())[:5]:
            lines.append(
                f"• {_escape(name)} · {_escape(_truncate(str(message), 120))}"
            )
    return "\n".join(lines)


def _build_keyboard(
    snapshot: Mapping[str, Any],
    *,
    view: str,
    page: int,
    page_count: int,
    detail_key: str | None,
) -> list[list[dict[str, str]]]:
    rows = [
        [_button("📊 Tổng quan", "overview", view), _button("📂 Lệnh", "positions", view), _button("🧠 Decisions", "decisions", view)],
        [_button("📈 Hiệu suất", "performance", view), _button("🏁 Đội", "teams", view), _button("🛠 System", "system", view)],
    ]
    if view == "decisions":
        decisions = list(reversed(_list_of_mappings(snapshot.get("llm_decisions"))))
        chunk = decisions[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        for index, decision in enumerate(chunk, start=1):
            symbol = str(decision.get("symbol") or "?")
            action = str(decision.get("action") or decision.get("type") or "?").upper()
            rows.append([
                {
                    "text": _truncate(f"#{page * PAGE_SIZE + index} {symbol} {action}", 38),
                    "callback_data": f"dash:decision:0:{decision_key(decision)}",
                }
            ])
    if view == "decision" and detail_key:
        rows.append([{"text": "← Decisions", "callback_data": "dash:decisions:0"}])
    if view == "performance":
        rows.append(
            [
                {"text": "Hôm nay", "callback_data": "dash:performance:0"},
                {"text": "7D", "callback_data": "dash:performance:1"},
                {"text": "30D", "callback_data": "dash:performance:2"},
                {"text": "All", "callback_data": "dash:performance:3"},
            ]
        )
    elif page_count > 1:
        nav: list[dict[str, str]] = []
        if page > 0:
            nav.append({"text": "←", "callback_data": f"dash:{view}:{page - 1}"})
        nav.append({"text": f"{min(page + 1, page_count)}/{page_count}", "callback_data": f"dash:{view}:{page}"})
        if page + 1 < page_count:
            nav.append({"text": "→", "callback_data": f"dash:{view}:{page + 1}"})
        rows.append(nav)
    rows.append([{"text": "↻ Làm mới", "callback_data": f"dash:{view}:{page}"}])
    return rows


def _button(label: str, target: str, active: str) -> dict[str, str]:
    return {
        "text": f"• {label}" if target == active else label,
        "callback_data": f"dash:{target}:0",
    }


def _within_window(trade: Mapping[str, Any], window: str, now: datetime) -> bool:
    if window == "all":
        return True
    timestamp = _trade_time(trade)
    if timestamp is None:
        return False
    local = timestamp.astimezone(LOCAL_TZ)
    if window == "today":
        return local.date() == now.date()
    days = 7 if window == "7d" else 30
    return local >= now - timedelta(days=days)


def _trade_time(trade: Mapping[str, Any]) -> datetime | None:
    for key in ("closed_at", "exit_at", "timestamp_utc", "ts", "timestamp"):
        value = trade.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            return parsed
        except ValueError:
            continue
    return None


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        return []
    return out[-limit:]


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _component_error(snapshot: Mapping[str, Any], name: str) -> str:
    """Return a labelled fallback component error, if present."""
    source = _mapping(snapshot.get("_telegram_source"))
    errors = _mapping(source.get("component_errors"))
    return str(errors.get(name) or "")


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _value(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "N/A"
    if number.is_integer():
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _money(value: Any, *, digits: int = 2) -> str:
    number = _number(value)
    return "N/A" if number is None else f"${number:,.{digits}f}"


def _signed_money(value: Any) -> str:
    number = _number(value)
    return "N/A" if number is None else f"{number:+,.2f}$"


def _percent(value: Any) -> str:
    number = _number(value)
    return "N/A" if number is None else f"{number:.1f}%"


def _confidence_pct(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 100.0 if 0 <= number <= 1 else number


def _price(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:,.8f}".rstrip("0").rstrip(".")


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def _limit_text(value: str) -> str:
    if len(value) <= MAX_TEXT_LEN:
        return value
    candidate = value[: MAX_TEXT_LEN - 30]
    newline = candidate.rfind("\n")
    if newline > 0:
        candidate = candidate[:newline]
    return candidate + "\n… dữ liệu còn lại đã phân trang"


def _format_time(value: Any) -> str:
    if not value:
        return "N/A"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TZ)
        return parsed.astimezone(LOCAL_TZ).strftime("%d/%m %H:%M:%S")
    except ValueError:
        return _truncate(str(value), 24)


def _now_iso() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _safe_error(value: Any) -> str:
    text = str(value or "").replace("\n", " ")
    return _truncate(text, 240)
