"""Telegram bot notifier: alerts + commands via long polling.

Auth: only TELEGRAM_CHAT_ID can interact. Other senders ignored.
Uses pure `requests` (no extra dependency).

Events subscribed: trade_opened, trade_closed, sl_hit, tp_hit,
                    regime_change, decision (STRONG only), error.

Commands:
    /start, /help     show help
    /status           positions + P&L summary
    /positions        open positions detail
    /stats            closed-trade aggregate stats
    /decisions        last 5 LLM decisions
    /history          last 5 closed trades
    /pause            halt auto-trading (touch /data/STOP)
    /resume           resume auto-trading
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import requests

from auto import alerts  # type: ignore

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
POLL_TIMEOUT_S = 30
BASE = "https://api.telegram.org"
MAX_MSG_LEN = 3800  # safe under Telegram's 4096 limit


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not TOKEN or not CHAT_ID or not text:
        return False
    try:
        if len(text) > MAX_MSG_LEN:
            text = text[:MAX_MSG_LEN] + "\n...[truncated]"
        r = requests.post(
            f"{BASE}/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.ok
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] send error: {exc}")
        return False


def send(text: str) -> bool:
    """Public send. Returns True on success."""
    return _send(text)


def _is_authorized(msg: dict) -> bool:
    if not CHAT_ID:
        return False
    chat = msg.get("chat", {}) or {}
    return str(chat.get("id", "")) == str(CHAT_ID)


def _handle_status() -> None:
    from auto import journal  # type: ignore
    positions = journal.read_positions()
    stats = journal.read_stats()
    closed = journal.read_closed_trades()
    recent_pnl = sum(float(t.get("pnl_usd", 0)) for t in closed[-10:])
    txt = (
        "<b>📊 Status</b>\n"
        f"Open positions: {len(positions)} / max {os.getenv('AUTO_MAX_POSITIONS', '3')}\n"
        f"Total trades: {stats.get('total_trades', 0)}\n"
        f"Winrate: {stats.get('winrate', 0):.1f}%\n"
        f"Last 10 PnL: ${recent_pnl:.2f}\n"
        f"Capital: ${stats.get('current_capital', 10000):.2f} / ${stats.get('starting_capital', 10000):.2f}"
    )
    if positions:
        txt += "\n\n<b>Open:</b>\n"
        for p in positions[:5]:
            sym = p.get("symbol", "?")
            side = (p.get("side") or "?").upper()
            txt += f"  {sym} {side} @ {p.get('entry')} (SL {p.get('stop_loss')}, TP {p.get('take_profit')})\n"
    send(txt)


def _handle_positions() -> None:
    from auto import journal  # type: ignore
    positions = journal.read_positions()
    if not positions:
        send("📭 No open positions")
        return
    txt = f"<b>📂 Open positions ({len(positions)})</b>\n"
    for p in positions:
        sym = p.get("symbol", "?")
        side = (p.get("side") or "?").upper()
        txt += (
            f"\n<b>{sym} {side}</b>\n"
            f"  Entry: {p.get('entry')}\n"
            f"  SL: {p.get('stop_loss')} | TP: {p.get('take_profit')}\n"
            f"  Size: {p.get('position_size')} (RR 1:{p.get('rr_ratio', 0):.2f})\n"
            f"  Confluence: {p.get('confluence_score')} · Regime: {p.get('regime')}"
        )
    send(txt)


def _handle_stats() -> None:
    from auto import journal  # type: ignore
    closed = journal.read_closed_trades()
    if not closed:
        send("📈 No closed trades yet")
        return
    pnls = [float(t.get("pnl_usd", 0)) for t in closed]
    wins = sum(1 for p in pnls if p > 0)
    txt = (
        "<b>📈 Stats</b>\n"
        f"Total: {len(closed)}\n"
        f"Wins: {wins} ({wins / len(closed) * 100:.1f}%)\n"
        f"Total PnL: ${sum(pnls):.2f}\n"
        f"Best: ${max(pnls):.2f}\n"
        f"Worst: ${min(pnls):.2f}\n"
        f"Avg RR: 1:{(sum(float(t.get('rr_ratio', 0)) for t in closed) / len(closed)):.2f}"
    )
    send(txt)


def _handle_decisions() -> None:
    from auto import journal  # type: ignore
    decisions: list[dict[str, Any]] = []
    if journal.DECISIONS_LOG.exists():
        with journal.DECISIONS_LOG.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    decisions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    llm_dec = [
        d for d in decisions
        if d.get("type") in ("llm", "llm_override_hold", "llm_decision_used")
    ][-5:]
    if not llm_dec:
        send("🤖 No LLM decisions yet (waiting for STRONG signal)")
        return
    txt = "<b>🤖 Recent LLM decisions</b>\n"
    for d in llm_dec:
        ts = (d.get("ts") or "")[:16].replace("T", " ")
        action = (d.get("action") or d.get("type") or "?").upper()
        reasoning = (d.get("reasoning") or d.get("reasoning_text") or "")[:140]
        sym = d.get("symbol", "")
        sym_part = f" · {sym}" if sym else ""
        conf = d.get("confidence")
        conf_part = f" · conf={conf}" if conf is not None else ""
        txt += f"\n{ts}{sym_part} · <b>{action}</b>{conf_part}\n  {reasoning}\n"
    send(txt)


def _handle_history() -> None:
    from auto import journal  # type: ignore
    closed = journal.read_closed_trades()[-5:]
    if not closed:
        send("📜 No closed trades yet")
        return
    txt = "<b>📜 Last 5 closed trades</b>\n"
    for t in reversed(closed):
        ts = (t.get("closed_at") or "")[:16].replace("T", " ")
        pnl = float(t.get("pnl_usd", 0))
        sign = "+" if pnl >= 0 else ""
        reason_emoji = "🟢" if pnl >= 0 else "🔴"
        txt += (
            f"\n{reason_emoji} {ts} · {t.get('symbol')} {t.get('side', '').upper()}"
            f" → {t.get('exit_reason', '?')}\n"
            f"   ${sign}{pnl:.2f} (RR 1:{t.get('rr_ratio', 0):.1f})"
        )
    send(txt)


def _handle_pause() -> None:
    from auto import journal  # type: ignore
    journal.KILL_SWITCH.touch()
    send("⏸ Paused (kill switch set). Resume with /resume")


def _handle_resume() -> None:
    from auto import journal  # type: ignore
    if journal.KILL_SWITCH.exists():
        journal.KILL_SWITCH.unlink()
    send("▶️ Resumed.")


def _handle_help() -> None:
    send(
        "<b>🤖 Vibe-Trading Auto Bot</b>\n\n"
        "/status - positions + PnL summary\n"
        "/positions - open positions detail\n"
        "/stats - closed trade aggregate stats\n"
        "/decisions - last 5 LLM decisions\n"
        "/history - last 5 closed trades\n"
        "/pause - halt auto-trading\n"
        "/resume - resume auto-trading\n"
        "/help - this message"
    )


COMMANDS: dict[str, Any] = {
    "/start": _handle_help,
    "/help": _handle_help,
    "/status": _handle_status,
    "/positions": _handle_positions,
    "/stats": _handle_stats,
    "/decisions": _handle_decisions,
    "/history": _handle_history,
    "/pause": _handle_pause,
    "/resume": _handle_resume,
}


def _on_alert(event_type: str, payload: dict[str, Any]) -> None:
    """Alert bus subscriber: format events as short Telegram messages."""
    if event_type == "trade_opened":
        sym = payload.get("symbol", "?")
        side = (payload.get("side") or "?").upper()
        send(
            f"🟢 <b>OPENED</b> {sym} {side}\n"
            f"Entry: {payload.get('entry')} · SL: {payload.get('stop_loss')} · "
            f"TP: {payload.get('take_profit')}\n"
            f"Size: {payload.get('position_size')} · "
            f"Confluence: {payload.get('confluence_score')} · Regime: {payload.get('regime')}"
        )
    elif event_type == "trade_closed":
        sym = payload.get("symbol", "?")
        side = (payload.get("side") or "?").upper()
        pnl = float(payload.get("pnl_usd", 0))
        sign = "+" if pnl >= 0 else ""
        emoji = "🟢" if pnl >= 0 else "🔴"
        send(
            f"{emoji} <b>CLOSED</b> {sym} {side}\n"
            f"Exit: {payload.get('exit_price')} ({payload.get('exit_reason')})\n"
            f"PnL: ${sign}{pnl:.2f} · RR 1:{float(payload.get('rr_ratio', 0)):.1f}"
        )
    elif event_type == "sl_hit":
        send(
            f"🔴 <b>STOP-LOSS HIT</b>\n"
            f"{payload.get('symbol')} closed at {payload.get('exit_price')}\n"
            f"Loss: ${float(payload.get('pnl_usd', 0)):.2f}"
        )
    elif event_type == "tp_hit":
        send(
            f"🟢 <b>TAKE-PROFIT HIT</b>\n"
            f"{payload.get('symbol')} closed at {payload.get('exit_price')}\n"
            f"Profit: +${float(payload.get('pnl_usd', 0)):.2f}"
        )
    elif event_type == "regime_change":
        send(
            f"⚠️ <b>REGIME CHANGE</b>\n"
            f"{payload.get('symbol')}: {payload.get('old_regime')} → {payload.get('new_regime')}"
        )
    elif event_type == "decision":
        action = (payload.get("action") or "").lower()
        # Only notify on real decisions, skip HOLD/NO_TRADE noise
        if action not in ("long", "short", "buy", "sell"):
            return
        sym = payload.get("symbol", "?")
        send(
            f"🧠 <b>LLM: {action.upper()}</b> {sym}\n"
            f"Entry: {payload.get('entry')} | SL: {payload.get('stop_loss')} | "
            f"TP: {payload.get('take_profit')}\n"
            f"Confidence: {payload.get('confidence', '?')}"
        )
    elif event_type == "error":
        send(
            f"❌ <b>ERROR</b>\n"
            f"{payload.get('where', '?')}: {str(payload.get('error', '?'))[:300]}"
        )
    elif event_type == "llm_cost_alert":
        # T3F: Notify at 50% / 80% / 100% of daily LLM cost cap.
        pct = int(payload.get("pct", 0))
        cost = float(payload.get("cost_usd", 0))
        cap = float(payload.get("cap_usd", 0))
        monthly = float(payload.get("monthly_cost_usd", 0))
        emoji = "🚨" if pct >= 100 else "⚠️" if pct >= 80 else "🟡"
        msg = (
            f"{emoji} <b>LLM cost {pct}% of daily cap</b>\n"
            f"Today: ${cost:.4f} / ${cap:.2f}\n"
            f"This month: ${monthly:.2f}"
        )
        if pct >= 100:
            msg += "\n\nCap reached. Auto-throttling to rules-only fallback until midnight."
        send(msg)


def _poll_loop() -> None:
    if not TOKEN or not CHAT_ID:
        print("[telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; bot disabled")
        return
    alerts.subscribe("trade_opened", _on_alert)
    alerts.subscribe("trade_closed", _on_alert)
    alerts.subscribe("sl_hit", _on_alert)
    alerts.subscribe("tp_hit", _on_alert)
    alerts.subscribe("regime_change", _on_alert)
    alerts.subscribe("decision", _on_alert)
    alerts.subscribe("error", _on_alert)
    alerts.subscribe("llm_cost_alert", _on_alert)

    print(f"[telegram] bot started, chat_id={CHAT_ID}")
    send("🤖 <b>Vibe-Trading Auto started</b>\nDashboard: http://localhost:8000/trader")

    offset = 0
    while True:
        try:
            r = requests.get(
                f"{BASE}/bot{TOKEN}/getUpdates",
                params={"timeout": POLL_TIMEOUT_S, "offset": offset,
                        "allowed_updates": '["message"]'},
                timeout=POLL_TIMEOUT_S + 5,
            )
            data = r.json()
            if not data.get("ok"):
                print(f"[telegram] getUpdates not ok: {data}")
                time.sleep(5)
                continue
            for update in data.get("result", []):
                # M7: Telegram guarantees monotonic update_ids, but malformed
                # responses (e.g., partial payloads from rate-limit retries)
                # may lack update_id. Skip those — re-polling would either
                # re-process (with offset stuck) or loop forever.
                if "update_id" not in update:
                    print(f"[telegram] skipping update without update_id: {update}")
                    continue
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                msg = update.get("message") or {}
                if not _is_authorized(msg):
                    continue
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                cmd = text.split()[0].lower().split("@")[0]
                handler = COMMANDS.get(cmd)
                if handler:
                    try:
                        handler()
                    except Exception as exc:  # noqa: BLE001
                        send(f"❌ Error handling {cmd}: {str(exc)[:200]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] poll error: {exc}")
            time.sleep(5)


def start_in_thread() -> threading.Thread:
    """Start the bot in a daemon thread. Returns the Thread."""
    t = threading.Thread(target=_poll_loop, name="telegram_bot", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    _poll_loop()
