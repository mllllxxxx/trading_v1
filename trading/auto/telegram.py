"""Private Telegram trading cockpit, lifecycle alerts, and operator commands.

The pinned dashboard is read-only. Typed ``/pause`` and ``/resume`` commands
remain available for the configured private operator and retain fail-closed
exchange reconciliation behavior.
"""
from __future__ import annotations

import html
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests

try:
    from . import alerts, journal
    from .telegram_dashboard import (
        DashboardRender,
        DashboardStateStore,
        TelegramSnapshotProvider,
        content_hash,
        parse_dashboard_callback,
        render_dashboard,
    )
except ImportError:  # pragma: no cover - direct script/test import fallback
    import alerts  # type: ignore
    import journal  # type: ignore
    from telegram_dashboard import (  # type: ignore
        DashboardRender,
        DashboardStateStore,
        TelegramSnapshotProvider,
        content_hash,
        parse_dashboard_callback,
        render_dashboard,
    )

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
USER_ID = os.getenv("TELEGRAM_USER_ID", "").strip()
POLL_TIMEOUT_S = 30
BASE = "https://api.telegram.org"
MAX_MSG_LEN = 3900


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _journal_delivery_error(method: str, status: Any, description: Any) -> None:
    """Journal a sanitized Telegram delivery failure without message content."""
    try:
        journal.append_decision(
            "telegram_delivery_error",
            {
                "method": method,
                "status": str(status or "unknown")[:40],
                "description": str(description or "unknown").replace("\n", " ")[:240],
            },
        )
    except Exception:  # noqa: BLE001 - logging must never recurse into runtime failure
        pass


def _journal_dashboard_refresh_error(exc: Exception) -> None:
    """Journal a sanitized dashboard-worker failure without killing the bot."""
    try:
        journal.append_decision(
            "telegram_dashboard_refresh_error",
            {
                "error_type": type(exc).__name__,
                "error": str(exc).replace("\n", " ")[:240],
                "action": "retry_periodically",
            },
        )
    except Exception:  # noqa: BLE001 - worker recovery must not depend on logging
        pass


def _api_request(
    method: str,
    payload: dict[str, Any],
    *,
    timeout: int = 10,
    journal_error: bool = True,
) -> dict[str, Any]:
    """Call one Telegram Bot API method and return its decoded response."""
    if not TOKEN:
        return {"ok": False, "description": "telegram token missing"}
    try:
        response = requests.post(
            f"{BASE}/bot{TOKEN}/{method}",
            json=payload,
            timeout=timeout,
        )
        try:
            data = response.json()
        except ValueError:
            data = {"ok": False, "description": f"invalid JSON response ({response.status_code})"}
        if not isinstance(data, dict):
            data = {"ok": False, "description": "invalid response object"}
        if not response.ok or not data.get("ok"):
            description = data.get("description") or f"HTTP {response.status_code}"
            if journal_error and "message is not modified" not in str(description).lower():
                _journal_delivery_error(method, response.status_code, description)
        return data
    except Exception as exc:  # noqa: BLE001 - network boundary
        if journal_error:
            _journal_delivery_error(method, "exception", exc)
        return {"ok": False, "description": str(exc)[:240]}


def _send_message(
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str = "HTML",
) -> int | None:
    """Send a message and return its message ID on success."""
    if not CHAT_ID or not text:
        return None
    payload: dict[str, Any] = {
        "chat_id": CHAT_ID,
        "text": text[:MAX_MSG_LEN],
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = _api_request("sendMessage", payload)
    result = data.get("result") if isinstance(data, dict) else None
    if not data.get("ok") or not isinstance(result, dict):
        return None
    try:
        return int(result.get("message_id"))
    except (TypeError, ValueError):
        return None


def _edit_message(message_id: int, rendered: DashboardRender) -> bool:
    """Edit the pinned dashboard message in place."""
    data = _api_request(
        "editMessageText",
        {
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "text": rendered.text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": rendered.reply_markup,
        },
    )
    if data.get("ok"):
        return True
    return "message is not modified" in str(data.get("description") or "").lower()


def _pin_message(message_id: int) -> bool:
    """Pin a dashboard message without producing a notification."""
    data = _api_request(
        "pinChatMessage",
        {
            "chat_id": CHAT_ID,
            "message_id": message_id,
            "disable_notification": True,
        },
    )
    return bool(data.get("ok"))


def _answer_callback(callback_id: str, text: str = "Đã cập nhật") -> None:
    """Acknowledge an inline callback so Telegram clears its progress state."""
    _api_request(
        "answerCallbackQuery",
        {"callback_query_id": callback_id, "text": text[:160]},
        journal_error=False,
    )


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Compatibility send helper used by lifecycle alerts and commands."""
    return _send_message(text, parse_mode=parse_mode) is not None


def send(text: str) -> bool:
    """Public send helper. Returns ``True`` on Telegram acceptance."""
    return _send(text)


def _private_operator_id(chat: dict[str, Any]) -> str:
    """Resolve the expected user ID with safe private-chat compatibility."""
    if USER_ID:
        return USER_ID
    if str(chat.get("type") or "") == "private":
        return CHAT_ID
    return ""


def _is_authorized(message: dict[str, Any], actor: dict[str, Any] | None = None) -> bool:
    """Authorize both the configured private chat and operator user."""
    if not CHAT_ID:
        return False
    chat = message.get("chat", {}) or {}
    if str(chat.get("id", "")) != CHAT_ID:
        return False
    expected_user_id = _private_operator_id(chat)
    if not expected_user_id:
        return False
    user = actor or message.get("from", {}) or {}
    return str(user.get("id", "")) == expected_user_id


class TelegramDashboardController:
    """Own the pinned dashboard message, refresh cadence, and persisted state."""

    def __init__(self) -> None:
        try:
            state_path = journal.DATA_DIR / "telegram" / "dashboard_state.json"
        except Exception:  # noqa: BLE001 - safe local fallback for standalone use
            state_path = os.getenv("VIBE_TRADING_HOME", "/data")
            from pathlib import Path

            state_path = Path(state_path) / "telegram" / "dashboard_state.json"
        self.store = DashboardStateStore(state_path)
        self.state = self.store.load()
        self.provider = TelegramSnapshotProvider()
        self.refresh_s = _env_int("TELEGRAM_DASHBOARD_REFRESH_S", 60, minimum=15)
        self.heartbeat_s = _env_int("TELEGRAM_DASHBOARD_HEARTBEAT_S", 300, minimum=60)
        self.coalesce_s = _env_int("TELEGRAM_DASHBOARD_COALESCE_S", 5, minimum=1)
        self._dirty = threading.Event()
        self._lock = threading.Lock()
        self._last_edit_monotonic = 0.0
        self._last_snapshot_monotonic = 0.0
        self._last_heartbeat_monotonic = 0.0
        self._last_refresh_error = ""
        self._last_refresh_error_log_monotonic = 0.0

    def mark_dirty(self) -> None:
        """Request a coalesced dashboard refresh."""
        self._dirty.set()

    def set_view(
        self,
        view: str,
        page: int = 0,
        detail_key: str | None = None,
        *,
        refresh_now: bool = False,
    ) -> bool:
        """Switch view and optionally refresh the pinned message immediately."""
        with self._lock:
            self.state.view = view
            self.state.page = max(0, page)
            self.state.detail_key = detail_key
            self.store.save(self.state)
        if refresh_now:
            return self._refresh_safely(force=True)
        self.mark_dirty()
        return True

    def refresh(self, *, force: bool = False) -> bool:
        """Load, render, and create/edit the dashboard message."""
        if not _env_bool("TELEGRAM_DASHBOARD_ENABLED", True):
            return False
        with self._lock:
            snapshot = self.provider.load()
            rendered = render_dashboard(
                snapshot,
                view=self.state.view,
                page=self.state.page,
                detail_key=self.state.detail_key,
            )
            digest = content_hash(rendered)
            now = time.monotonic()
            heartbeat_due = now - self._last_heartbeat_monotonic >= self.heartbeat_s
            if (
                self.state.message_id is not None
                and digest == self.state.last_content_hash
                and not force
                and not heartbeat_due
            ):
                self._last_snapshot_monotonic = now
                return True

            message_id = self.state.message_id
            delivered = bool(message_id and _edit_message(message_id, rendered))
            if not delivered:
                message_id = _send_message(rendered.text, reply_markup=rendered.reply_markup)
                if message_id is None:
                    return False
                _pin_message(message_id)
            self.state.message_id = message_id
            self.state.last_content_hash = digest
            self.state.last_update_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self.store.save(self.state)
            self._last_edit_monotonic = now
            self._last_snapshot_monotonic = now
            self._last_heartbeat_monotonic = now
            return True

    def loop(self) -> None:
        """Run periodic and event-driven dashboard refreshes forever."""
        self._dirty.set()
        while True:
            self._dirty.wait(timeout=float(self.coalesce_s))
            now = time.monotonic()
            periodic_due = now - self._last_snapshot_monotonic >= self.refresh_s
            coalesce_ready = now - self._last_edit_monotonic >= self.coalesce_s
            if periodic_due or (self._dirty.is_set() and coalesce_ready):
                self._dirty.clear()
                self._refresh_safely()

    def _refresh_safely(self, *, force: bool = False) -> bool:
        """Contain one refresh failure and keep the dashboard worker alive."""
        try:
            refreshed = self.refresh(force=force)
            self._last_snapshot_monotonic = time.monotonic()
            if refreshed:
                self._last_refresh_error = ""
            return refreshed
        except Exception as exc:  # noqa: BLE001 - top-level worker boundary
            now = time.monotonic()
            self._last_snapshot_monotonic = now
            signature = f"{type(exc).__name__}:{str(exc)[:180]}"
            should_log = (
                signature != self._last_refresh_error
                or now - self._last_refresh_error_log_monotonic >= self.heartbeat_s
            )
            if should_log:
                print(f"[telegram] dashboard refresh error: {signature}")
                _journal_dashboard_refresh_error(exc)
                self._last_refresh_error = signature
                self._last_refresh_error_log_monotonic = now
            return False

    def start_in_thread(self) -> threading.Thread:
        """Start the dashboard refresh loop in a daemon thread."""
        thread = threading.Thread(target=self.loop, name="telegram_dashboard", daemon=True)
        thread.start()
        return thread


_DASHBOARD: TelegramDashboardController | None = None

VIEW_LABELS = {
    "overview": "Tổng quan",
    "positions": "Lệnh",
    "decisions": "Decisions",
    "performance": "Hiệu suất",
    "teams": "Đội",
    "system": "Hệ thống",
    "decision": "Decision detail",
}


def _dashboard() -> TelegramDashboardController | None:
    return _DASHBOARD


def _show_view(
    view: str,
    page: int = 0,
    detail_key: str | None = None,
    *,
    acknowledge: bool = True,
) -> bool:
    """Refresh one pinned view now and optionally acknowledge typed commands."""
    controller = _dashboard()
    if controller is None:
        send("Dashboard chưa sẵn sàng.")
        return False
    refreshed = controller.set_view(
        view,
        page,
        detail_key,
        refresh_now=True,
    )
    if acknowledge:
        label = VIEW_LABELS.get(view, view)
        if refreshed:
            send(f"✅ Dashboard ghim đã mở: <b>{_escape(label)}</b>.")
        else:
            send(
                f"⚠️ Đã nhận lệnh nhưng chưa cập nhật được "
                f"<b>{_escape(label)}</b>. Dùng /refresh để thử lại."
            )
    return refreshed


def _handle_start() -> bool:
    helped = _handle_help()
    refreshed = _show_view("overview", acknowledge=False)
    return helped and refreshed


def _handle_status() -> bool:
    return _show_view("overview")


def _handle_positions() -> bool:
    return _show_view("positions")


def _handle_stats() -> bool:
    return _show_view("performance", 0)


def _handle_decisions() -> bool:
    return _show_view("decisions")


def _handle_history() -> bool:
    return _show_view("performance", 3)


def _handle_teams() -> bool:
    return _show_view("teams")


def _handle_system() -> bool:
    return _show_view("system")


def _handle_refresh() -> bool:
    controller = _dashboard()
    if controller is None:
        send("Dashboard chưa sẵn sàng.")
        return False
    refreshed = controller._refresh_safely(force=True)
    send("✅ Dashboard ghim đã refresh." if refreshed else "⚠️ Refresh dashboard thất bại; bot sẽ tự retry.")
    return refreshed


def _handle_pause() -> bool:
    journal.KILL_SWITCH.touch()
    journal.append_decision("telegram_pause", {"source": "private_operator"})
    controller = _dashboard()
    if controller is not None:
        controller.mark_dirty()
    return send("⏸ Đã chặn lệnh mới. Dashboard và giám sát vị thế vẫn hoạt động.")


def _handle_resume() -> bool:
    try:
        from . import exchange_reconciler
    except ImportError:  # pragma: no cover - direct script/runtime fallback
        import exchange_reconciler  # type: ignore

    sync_status = exchange_reconciler.run_startup_reconciliation(
        trigger="telegram_resume",
        journal_module=journal,
    )
    if sync_status.get("status") == "error":
        send("❌ Resume bị chặn: không reconcile được OKX demo. Journal được giữ nguyên.")
        return False
    journal.clear_kill_switch()
    journal.append_decision("telegram_resume", {"source": "private_operator", "sync_status": sync_status})
    controller = _dashboard()
    if controller is not None:
        controller.mark_dirty()
    return send("▶️ Đã resume sau khi đồng bộ trạng thái sàn.")


def _handle_help() -> bool:
    return send(
        "<b>🤖 Trade_V1 Telegram Cockpit</b>\n\n"
        "/dashboard hoặc /status · tổng quan\n"
        "/positions · lệnh open/pending\n"
        "/decisions · decision lifecycle\n"
        "/stats · hiệu suất hôm nay\n"
        "/history · hiệu suất toàn bộ\n"
        "/teams · leaderboard\n"
        "/system · sync, guard, quota, lỗi\n"
        "/refresh · làm mới dashboard\n"
        "/pause · chặn lệnh mới\n"
        "/resume · reconcile rồi mở lại\n"
        "/help · trợ giúp"
    )


COMMANDS: dict[str, Callable[[], bool]] = {
    "/start": _handle_start,
    "/help": _handle_help,
    "/dashboard": _handle_status,
    "/status": _handle_status,
    "/positions": _handle_positions,
    "/stats": _handle_stats,
    "/decisions": _handle_decisions,
    "/history": _handle_history,
    "/teams": _handle_teams,
    "/system": _handle_system,
    "/refresh": _handle_refresh,
    "/pause": _handle_pause,
    "/resume": _handle_resume,
}

BOT_COMMAND_MENU = [
    {"command": "dashboard", "description": "Mở tổng quan dashboard"},
    {"command": "status", "description": "Trạng thái hệ thống"},
    {"command": "positions", "description": "Lệnh open và pending"},
    {"command": "decisions", "description": "Decision lifecycle"},
    {"command": "stats", "description": "Hiệu suất hôm nay"},
    {"command": "history", "description": "Hiệu suất toàn bộ"},
    {"command": "teams", "description": "Leaderboard đội"},
    {"command": "system", "description": "Sync, guard và quota"},
    {"command": "refresh", "description": "Refresh dashboard ngay"},
    {"command": "pause", "description": "Chặn lệnh mới"},
    {"command": "resume", "description": "Reconcile và resume"},
    {"command": "help", "description": "Danh sách lệnh"},
]


def _register_commands() -> bool:
    """Register the private cockpit command menu with Telegram."""
    data = _api_request("setMyCommands", {"commands": BOT_COMMAND_MENU})
    return bool(data.get("ok"))


def _journal_command(command: str, status: str, error: str = "") -> None:
    """Write sanitized command telemetry without operator identifiers or text."""
    try:
        payload = {"command": command[:64], "status": status[:32]}
        if error:
            payload["error"] = error.replace("\n", " ")[:200]
        journal.append_decision("telegram_command", payload)
    except Exception:  # noqa: BLE001 - telemetry must not break command handling
        pass


def _handle_message(message: dict[str, Any]) -> bool:
    """Handle one authorized Telegram message and provide command feedback."""
    if not _is_authorized(message):
        return False
    text = str(message.get("text") or "").strip()
    if not text:
        return False
    command = text.split()[0].lower().split("@")[0]
    handler = COMMANDS.get(command)
    if handler is None:
        delivered = send(
            "ℹ️ Bot này là trading cockpit theo command, không phải chatbot. "
            "Dùng /help để xem lệnh hỗ trợ."
        )
        _journal_command(command, "unsupported_delivered" if delivered else "unsupported_delivery_failed")
        return True
    _journal_command(command, "received")
    try:
        succeeded = handler()
        _journal_command(command, "succeeded" if succeeded else "failed")
    except Exception as exc:  # noqa: BLE001 - command isolation
        _journal_command(command, "error", str(exc))
        send(f"❌ Lỗi xử lý {_escape(command)}: {_escape(str(exc)[:200])}")
    return True


def _on_alert(event_type: str, payload: dict[str, Any]) -> None:
    """Refresh the cockpit and push only important lifecycle alerts."""
    controller = _dashboard()
    if controller is not None:
        controller.mark_dirty()
    symbol = _escape(payload.get("symbol") or "?")
    team = _escape(payload.get("team_name") or payload.get("team_id") or "system")
    side = _escape(str(payload.get("side") or "?").upper())
    if event_type == "trade_opened":
        send(
            f"🟢 <b>OPENED</b> · {team}\n"
            f"{symbol} {side} · Entry {_escape(payload.get('entry'))}\n"
            f"SL {_escape(payload.get('stop_loss'))} · TP {_escape(payload.get('take_profit'))}\n"
            f"Risk {_money(payload.get('risk_usd'))} · Size {_escape(payload.get('position_size'))}"
        )
    elif event_type == "trade_entry_filled":
        send(f"✅ <b>ENTRY FILLED</b> · {team}\n{symbol} {side} @ {_escape(payload.get('entry') or payload.get('fill_price'))}")
    elif event_type == "trade_closed":
        pnl = _float(payload.get("pnl_usd"), 0.0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        send(
            f"{emoji} <b>CLOSED</b> · {team}\n"
            f"{symbol} {side} · {_escape(payload.get('exit_reason') or '?')}\n"
            f"Net PnL {_signed_money(pnl)} · Fees {_money(payload.get('fees_usd'))}"
        )
    elif event_type == "sl_hit":
        send(f"🔴 <b>STOP-LOSS</b> · {team}\n{symbol} · Net {_signed_money(payload.get('pnl_usd'))}")
    elif event_type == "tp_hit":
        send(f"🟢 <b>TAKE-PROFIT</b> · {team}\n{symbol} · Net {_signed_money(payload.get('pnl_usd'))}")
    elif event_type in {"execution_failed", "reconciliation_error", "error"}:
        where = _escape(payload.get("where") or event_type)
        error = _escape(str(payload.get("error") or payload.get("reason") or "unknown")[:300])
        send(f"❌ <b>{_escape(event_type.upper())}</b>\n{where}: {error}")
    elif event_type in {"kill_switch", "daily_loss_cap"}:
        send(f"🚨 <b>{_escape(event_type.upper())}</b>\nĐã chặn lệnh mới. Kiểm tra dashboard System.")
    elif event_type == "llm_cost_alert":
        pct = int(_float(payload.get("pct"), 0.0))
        if pct < 80:
            return
        emoji = "🚨" if pct >= 100 else "⚠️"
        send(
            f"{emoji} <b>LLM budget {pct}%</b>\n"
            f"Hôm nay {_money(payload.get('cost_usd'), digits=4)} / {_money(payload.get('cap_usd'))}"
        )


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else "N/A"), quote=False)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: Any, *, digits: int = 2) -> str:
    try:
        return f"${float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def _signed_money(value: Any) -> str:
    try:
        return f"{float(value):+,.2f}$"
    except (TypeError, ValueError):
        return "N/A"


def _handle_callback(query: dict[str, Any]) -> None:
    message = query.get("message") or {}
    actor = query.get("from") or {}
    callback_id = str(query.get("id") or "")
    if not _is_authorized(message, actor):
        if callback_id:
            _answer_callback(callback_id, "Không được phép")
        return
    parsed = parse_dashboard_callback(str(query.get("data") or ""))
    if parsed is None:
        if callback_id:
            _answer_callback(callback_id, "Callback không hợp lệ")
        return
    view, page, detail_key = parsed
    if callback_id:
        _answer_callback(callback_id)
    _show_view(view, page, detail_key, acknowledge=False)


def _subscribe_alerts() -> None:
    for event_type in (
        "trade_opened",
        "trade_entry_filled",
        "trade_closed",
        "decision",
        "final_ticket",
        "execution_result",
        "execution_failed",
        "fail_closed_skip",
        "reconciliation_error",
        "regime_change",
        "error",
        "kill_switch",
        "daily_loss_cap",
        "llm_cost_alert",
    ):
        alerts.subscribe(event_type, _on_alert)


def _poll_loop() -> None:
    if not TOKEN or not CHAT_ID:
        print("[telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; bot disabled")
        return
    global _DASHBOARD
    _subscribe_alerts()
    if not _register_commands():
        print("[telegram] setMyCommands failed; polling will continue")
    _DASHBOARD = TelegramDashboardController()
    _DASHBOARD.start_in_thread()

    print("[telegram] private cockpit started")
    offset = 0
    while True:
        try:
            response = requests.get(
                f"{BASE}/bot{TOKEN}/getUpdates",
                params={
                    "timeout": POLL_TIMEOUT_S,
                    "offset": offset,
                    "allowed_updates": '["message","callback_query"]',
                },
                timeout=POLL_TIMEOUT_S + 5,
            )
            data = response.json()
            if not data.get("ok"):
                print(f"[telegram] getUpdates not ok: {str(data)[:300]}")
                time.sleep(5)
                continue
            for update in data.get("result", []):
                if "update_id" not in update:
                    print(f"[telegram] skipping update without update_id: {str(update)[:300]}")
                    continue
                offset = max(offset, int(update["update_id"]) + 1)
                callback_query = update.get("callback_query")
                if isinstance(callback_query, dict):
                    _handle_callback(callback_query)
                    continue
                message = update.get("message") or {}
                _handle_message(message)
        except Exception as exc:  # noqa: BLE001 - long-poll reliability boundary
            print(f"[telegram] poll error: {exc}")
            time.sleep(5)


def start_in_thread() -> threading.Thread:
    """Start Telegram polling and dashboard workers in daemon threads."""
    thread = threading.Thread(target=_poll_loop, name="telegram_bot", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    _poll_loop()
