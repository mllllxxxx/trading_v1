"""Main orchestrator: single container, multiple services.

Runs in one process via threads:
  - Vibe-Trading UI server (port 8000)  - chat with LLM + auto-trader dashboard at /trader
  - Auto-trader scheduler (every 5 min)  - check confluence, call LLM, place orders
  - Auto-trader monitor (every 30s)      - poll OKX, auto-cancel opposite

Dashboard now served by Vibe-Trading at http://localhost:8000/trader

Tested for paper trading on OKX testnet.
To stop everything: touch /data/STOP
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # type: ignore

import scheduler  # type: ignore
import monitor  # type: ignore

VIBE_PORT = int(os.getenv("VIBE_PORT", "8000"))


def _signal_handler(signum, frame):  # noqa: ARG001
    journal.append_decision("shutdown", {"signal": signum})
    sys.exit(0)


def _run_vibe_trading() -> None:
    """Run Vibe-Trading UI server in a thread (uvicorn blocks).

    Serves BOTH Vibe-Trading UI (/) AND auto-trader dashboard (/trader).
    """
    try:
        from cli._legacy import serve_main
        journal.append_decision("vibe_starting", {"port": VIBE_PORT})
        serve_main(["--host", "0.0.0.0", "--port", str(VIBE_PORT)])
    except Exception as exc:  # noqa: BLE001
        import traceback
        journal.append_decision("vibe_error", {
            "error": str(exc),
            "traceback": traceback.format_exc()[:1000],
        })


def _wait_for_port(port: int, timeout_s: int = 30) -> bool:
    """Wait until a TCP port is listening (server ready)."""
    import socket
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (OSError, socket.timeout):
            time.sleep(0.5)
    return False


def _start_telegram() -> threading.Thread | None:
    """Start Telegram notifier thread if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set.

    Returns the Thread, or None if disabled.
    """
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        journal.append_decision("telegram_disabled", {
            "reason": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set",
        })
        return None
    try:
        import telegram  # type: ignore
        t = telegram.start_in_thread()
        journal.append_decision("telegram_started", {
            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        })
        return t
    except Exception as exc:  # noqa: BLE001
        import traceback
        journal.append_decision("telegram_error", {
            "error": str(exc),
            "traceback": traceback.format_exc()[:600],
        })
        return None


def main() -> None:
    # Apply TZ env var so datetime.now() / time.localtime() use the right offset.
    if hasattr(time, "tzset"):
        try:
            time.tzset()
        except Exception:  # noqa: BLE001
            pass
    journal.ensure_dirs()
    journal.append_decision("auto_start", {
        "mode": "unified_single_container",
        "services": ["vibe_trading_ui", "scheduler", "monitor", "telegram"],
        "vibe_port": VIBE_PORT,
        "dashboard_url": f"http://localhost:{VIBE_PORT}/trader",
        "scheduler_interval_s": int(os.getenv("AUTO_INTERVAL_S", "300")),
        "monitor_interval_s": int(os.getenv("AUTO_MONITOR_INTERVAL_S", "30")),
        "symbols": os.getenv("AUTO_SYMBOLS", "BTC-USDT").split(","),
        "capital": float(os.getenv("AUTO_CAPITAL", "10000")),
    })
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start Vibe-Trading UI (serves Vibe-Trading at / + dashboard at /trader)
    vibe_thread = threading.Thread(target=_run_vibe_trading, name="vibe_trading",
                                    daemon=True)
    vibe_thread.start()

    # Wait for Vibe-Trading to be ready
    if _wait_for_port(VIBE_PORT, timeout_s=30):
        journal.append_decision("vibe_ready", {"port": VIBE_PORT})
    else:
        journal.append_decision("vibe_not_ready", {"port": VIBE_PORT,
                                                     "msg": "timeout waiting for port"})

    # Start auto-trader threads
    auto_threads = [
        threading.Thread(target=scheduler.main_loop, name="scheduler", daemon=True),
        threading.Thread(target=monitor.main_loop, name="monitor", daemon=True),
    ]
    for t in auto_threads:
        t.start()

    # Start Telegram notifier (4th thread; optional, no-op if env not set)
    tg_thread = _start_telegram()
    all_threads = [vibe_thread.name] + [t.name for t in auto_threads]
    if tg_thread:
        all_threads.append(tg_thread.name)

    journal.append_decision("unified_ready", {
        "vibe_port": VIBE_PORT,
        "all_threads": all_threads,
        "dashboard_url": f"http://localhost:{VIBE_PORT}/trader",
    })

    # Keep main thread alive (Vibe-Trading + auto-trader + telegram run in background)
    while True:
        time.sleep(60)
        if journal.is_killed():
            journal.append_decision("auto_stopped", {"reason": "kill_switch"})
            sys.exit(0)


if __name__ == "__main__":
    main()
