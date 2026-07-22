"""Dashboard HTTP server: serves dashboard.html + /api/status endpoint.

Run on port 8001 (Vibe-Trading UI is on 8000).
Reads journal files; never writes. Real-time data.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal  # type: ignore
import exchange_reconciler  # type: ignore

DASHBOARD_HTML = Path(__file__).resolve().parent / "dashboard.html"
PORT = int(os.getenv("AUTO_DASHBOARD_PORT", "8001"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence default access log
        return

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_file(DASHBOARD_HTML, "text/html; charset=utf-8")
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/kill":
            # Create kill switch
            journal.ensure_dirs()
            journal.KILL_SWITCH.touch()
            self._json({"ok": True, "msg": "kill switch set. Auto-trader will halt on next check."})
        elif path == "/api/resume":
            sync_status = exchange_reconciler.run_startup_reconciliation(
                trigger="dashboard_resume",
                journal_module=journal,
            )
            if sync_status.get("status") == "error":
                self._json({
                    "ok": False,
                    "msg": "resume blocked until exchange reconciliation succeeds.",
                    "sync_status": sync_status,
                })
            else:
                journal.clear_kill_switch()
                self._json({"ok": True, "msg": "kill switch cleared.", "sync_status": sync_status})
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500)

    def _serve_status(self) -> None:
        journal.ensure_dirs()
        try:
            with journal.DECISIONS_LOG.open("r", encoding="utf-8") as f:
                decisions = [json.loads(line) for line in f if line.strip()][-200:]
        except (OSError, json.JSONDecodeError):
            decisions = []
        # Include lifecycle TradeDecisionTicket events so signal-pipeline LLM
        # decisions are visible alongside legacy brain events.
        llm_decisions = journal.read_llm_decisions(limit=50, event_limit=20000)
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "positions": journal.read_positions(),
            "closed_trades": journal.read_closed_trades(),
            "stats": journal.read_stats(),
            "decisions": decisions,
            "llm_decisions": llm_decisions,
            "kill_switch_active": journal.is_killed(),
        }
        self._json(payload)

    def _json(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    journal.ensure_dirs()
    journal.append_decision("dashboard_start", {"port": PORT})
    print(f"[dashboard] serving http://0.0.0.0:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
