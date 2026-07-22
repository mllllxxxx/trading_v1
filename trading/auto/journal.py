"""Trade journal: append-only decision log + current positions + closed trades.

File-based (no database). All paths under /data (or $VIBE_TRADING_HOME).

Files:
  decisions.jsonl      - every scheduler/monitor decision (append-only)
  positions.json       - currently open positions (replaced on update)
  closed_trades.jsonl  - every closed position with PnL (append-only)
  stats.json           - aggregate metrics (replaced on update)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas.models import JournalEvent

DATA_DIR = Path(os.getenv("VIBE_TRADING_HOME", "/data"))
JOURNAL_DIR = DATA_DIR / "journal"
DECISIONS_LOG = JOURNAL_DIR / "decisions.jsonl"
POSITIONS_FILE = JOURNAL_DIR / "positions.json"
CLOSED_LOG = JOURNAL_DIR / "closed_trades.jsonl"
SHADOW_POSITIONS_FILE = JOURNAL_DIR / "shadow_positions.json"
SHADOW_OUTCOMES_LOG = JOURNAL_DIR / "shadow_outcomes.jsonl"
STATS_FILE = JOURNAL_DIR / "stats.json"
SNAPSHOTS_DIR = JOURNAL_DIR / "snapshots"
KILL_SWITCH = DATA_DIR / "STOP"
STARTUP_SYNC_GUARD = DATA_DIR / "STARTUP_SYNC_BLOCK"

LIFECYCLE_EVENT_TYPES = {
    "signal_candidate",
    "market_dossier",
    "rule_retrieval",
    "rule_proposal",
    "hybrid_route",
    "llm_context_review",
    "llm_draft_ticket",
    "llm_context_review",
    "critic_review",
    "final_ticket",
    "rule_verification",
    "risk_compilation",
    "trade_open_rationale",
    "execution_result",
    "fail_closed_skip",
    "trade_outcome_review",
    "optimization_snapshot",
    "live_readiness_snapshot",
    "shadow_candidate",
    "shadow_outcome",
}

LLM_DECISION_EVENT_TYPES = {
    "llm",
    "llm_override_hold",
    "llm_override_no_trade",
    "llm_decision_used",
    "llm_error",
    "llm_draft_ticket",
    "llm_budget_skip",
}


class JournalCorruptError(RuntimeError):
    """Raised when a journal file cannot be parsed; signals caller to halt."""


# H1: Serializes all read-modify-write sections across threads so that
# scheduler + monitor never trample each other's positions/stats on disk.
# RLock (not Lock) because add_position/remove_position call read_positions
# then write_positions, both of which lock — a non-reentrant Lock would
# deadlock the same thread.
_FILE_LOCK = threading.RLock()

# Apply TZ env var (e.g., Asia/Ho_Chi_Minh) at import time so that
# time.localtime() / time.strftime() reflect the configured offset.
# Idempotent and safe to call multiple times.
if hasattr(time, "tzset"):
    try:
        time.tzset()
    except Exception:  # noqa: BLE001
        pass


def ensure_dirs() -> None:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if not DECISIONS_LOG.exists():
        DECISIONS_LOG.write_text("", encoding="utf-8")
    if not CLOSED_LOG.exists():
        CLOSED_LOG.write_text("", encoding="utf-8")
    if not SHADOW_OUTCOMES_LOG.exists():
        SHADOW_OUTCOMES_LOG.write_text("", encoding="utf-8")
    if not POSITIONS_FILE.exists():
        POSITIONS_FILE.write_text("[]", encoding="utf-8")
    if not SHADOW_POSITIONS_FILE.exists():
        SHADOW_POSITIONS_FILE.write_text("[]", encoding="utf-8")
    if not STATS_FILE.exists():
        STATS_FILE.write_text(json.dumps({
            "total_trades": 0, "wins": 0, "losses": 0,
            "total_pnl_usd": 0.0, "open_count": 0,
            "max_drawdown_usd": 0.0, "starting_capital": 10000.0,
            "current_capital": 10000.0,
        }, indent=2), encoding="utf-8")


def _now() -> str:
    """L1: Return strict ISO 8601 with timezone offset.

    Previously used time.strftime("%z") which returns '+0700' (no colon).
    datetime.fromisoformat() in Python 3.11+ accepts both, but downstream
    parsers (api_server, dashboard) sometimes break on the no-colon form.
    Now returns '2026-06-21T09:59:00+07:00' which round-trips with
    datetime.fromisoformat() across Python 3.10+.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _utc_now() -> str:
    """Return UTC ISO 8601 timestamp for schema-level journal events."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_fragment(value: str) -> str:
    """Return a filesystem-safe snapshot filename fragment."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


def append_decision(decision_type: str, payload: dict[str, Any]) -> None:
    """Append a decision event. decision_type: 'check', 'open', 'cancel', 'fill', 'skip'."""
    ensure_dirs()
    entry = {"ts": _now(), "type": decision_type, **payload}
    with _FILE_LOCK:
        with DECISIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_lifecycle_event(
    event_type: str,
    *,
    decision_id: str,
    payload: dict[str, Any],
    snapshots: dict[str, Any] | None = None,
) -> JournalEvent:
    """Append a replayable lifecycle event and optional snapshot artifacts."""
    if event_type not in LIFECYCLE_EVENT_TYPES:
        raise ValueError(f"unknown lifecycle event_type: {event_type}")
    if not decision_id.strip():
        raise ValueError("decision_id is required")

    snapshot_refs = write_lifecycle_snapshots(decision_id, snapshots or {})
    event_payload = dict(payload)
    if snapshot_refs:
        event_payload["snapshot_refs"] = snapshot_refs

    event = JournalEvent(
        event_id=str(uuid.uuid4()),
        timestamp_utc=_utc_now(),
        event_type=event_type,
        decision_id=decision_id,
        payload=event_payload,
    )
    append_decision(event_type, {
        "event_id": event.event_id,
        "timestamp_utc": event.timestamp_utc,
        "event_type": event.event_type,
        "decision_id": event.decision_id,
        "payload": event.payload,
    })
    return event


def write_lifecycle_snapshots(
    decision_id: str,
    snapshots: dict[str, Any],
    *,
    date_key: str | None = None,
) -> dict[str, str]:
    """Write replay snapshots and return journal-relative references."""
    ensure_dirs()
    if not snapshots:
        return {}
    safe_id = _safe_fragment(decision_id)
    day = date_key or _today_key()
    snapshot_dir = SNAPSHOTS_DIR / day
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    refs: dict[str, str] = {}
    with _FILE_LOCK:
        for artifact_type, artifact_payload in snapshots.items():
            safe_artifact = _safe_fragment(str(artifact_type))
            path = snapshot_dir / f"{safe_id}.{safe_artifact}.json"
            path.write_text(
                json.dumps(artifact_payload, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            refs[safe_artifact] = path.relative_to(JOURNAL_DIR).as_posix()
    return refs


def read_lifecycle_snapshots(
    decision_id: str,
    *,
    date_key: str | None = None,
) -> dict[str, Any]:
    """Load all snapshots for a decision ID."""
    ensure_dirs()
    safe_id = _safe_fragment(decision_id)
    roots = [SNAPSHOTS_DIR / date_key] if date_key else sorted(SNAPSHOTS_DIR.glob("*"))
    snapshots: dict[str, Any] = {}
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob(f"{safe_id}.*.json")):
            artifact_type = path.name[len(safe_id) + 1:-5]
            try:
                snapshots[artifact_type] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise JournalCorruptError(f"snapshot corrupt: {path}") from exc
    return snapshots


def read_positions() -> list[dict[str, Any]]:
    """Read current open positions.

    H4: On JSON parse failure, back up the corrupt bytes by content fingerprint
    and raise JournalCorruptError instead of silently returning []. Returning
    [] would let the scheduler think the book is flat and open a duplicate
    position while OKX still holds the original. Repeated readers reuse the
    same backup so dashboard polling cannot create an unbounded backup storm.
    """
    ensure_dirs()
    try:
        raw = POSITIONS_FILE.read_bytes()
    except OSError:
        return []
    try:
        positions = json.loads(raw.decode("utf-8"))
        if not isinstance(positions, list):
            raise ValueError("positions.json must contain a list")
        return positions
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        backup = _backup_corrupt_snapshot(POSITIONS_FILE, raw)
        raise JournalCorruptError(
            f"positions.json corrupt (backup at {backup}): {exc}"
        ) from exc


def _backup_corrupt_snapshot(path: Path, raw: bytes) -> Path:
    """Persist one backup for identical corrupt bytes and return its path."""
    fingerprint = hashlib.sha256(raw).hexdigest()[:20]
    backup = path.with_name(f"{path.stem}.corrupt.sha256-{fingerprint}.bak")
    try:
        with backup.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        pass
    except OSError:
        pass
    return backup


def read_llm_decisions(*, limit: int = 50, event_limit: int = 20_000) -> list[dict[str, Any]]:
    """Return recent LLM activity, including lifecycle TradeDecisionTicket events."""
    ensure_dirs()
    events = _read_jsonl_tail(DECISIONS_LOG, event_limit)
    llm_events = [
        event
        for event in events
        if event.get("type") in LLM_DECISION_EVENT_TYPES
    ][-limit:]
    return [_normalize_llm_decision_event(event) for event in llm_events]


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read recent JSONL objects from a journal file."""
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        return []
    return out[-limit:]


def _normalize_llm_decision_event(event: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy and lifecycle LLM events into a UI-friendly shape."""
    if event.get("type") != "llm_draft_ticket":
        return event

    payload = event.get("payload")
    payload_dict = payload if isinstance(payload, dict) else {}
    decision_id = str(event.get("decision_id") or "").strip()
    ticket: dict[str, Any] = {}
    if decision_id:
        try:
            snapshots = read_lifecycle_snapshots(decision_id)
            raw_ticket = snapshots.get("ticket")
            if isinstance(raw_ticket, dict):
                ticket = raw_ticket
        except JournalCorruptError:
            ticket = {}

    reasoning = str(
        ticket.get("reasoning_summary")
        or ticket.get("thesis")
        or payload_dict.get("reasoning")
        or ""
    )
    ticket_decision_id = (
        ticket.get("decision_id")
        or payload_dict.get("ticket_decision_id")
    )
    normalized = {
        "ts": event.get("ts") or event.get("timestamp_utc"),
        "type": "llm_draft_ticket",
        "decision_id": decision_id or None,
        "ticket_decision_id": ticket_decision_id,
        "signal_id": payload_dict.get("signal_id"),
        "team_id": payload_dict.get("team_id"),
        "team_name": payload_dict.get("team_name"),
        "strategy_id": payload_dict.get("strategy_id"),
        "strategy_name": payload_dict.get("strategy_name"),
        "symbol": ticket.get("symbol"),
        "action": ticket.get("action"),
        "confidence": ticket.get("confidence"),
        "playbook_id": ticket.get("playbook_id"),
        "reasoning": reasoning,
        "model": os.getenv("AUTO_LLM_MODEL") or os.getenv("LLM_MODEL"),
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _log_corrupt_positions(exc: Exception) -> None:
    """Log a corrupt_positions event. Called by callers who already hold the lock
    or who need to surface the corruption to journal readers without re-acquiring.
    """
    append_decision("corrupt_journal", {
        "file": str(POSITIONS_FILE),
        "error": str(exc),
        "action": "halt_cycle",
    })


def write_positions(positions: list[dict[str, Any]]) -> None:
    """Atomically replace the open-position snapshot."""
    ensure_dirs()
    with _FILE_LOCK:
        _atomic_write_json_locked(POSITIONS_FILE, positions)


def _atomic_write_json_locked(path: Path, payload: Any) -> None:
    """Durably write JSON to a unique sibling and atomically replace *path*."""
    temporary = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_snapshot_with_retry(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _replace_snapshot_with_retry(source: Path, target: Path) -> None:
    """Replace a snapshot, tolerating short-lived Windows file locks."""
    attempts = 5
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.01 * (attempt + 1))


def add_position(position: dict[str, Any]) -> None:
    with _FILE_LOCK:
        positions = read_positions()
        positions.append(position)
        write_positions(positions)
    append_decision("open", {"symbol": position["symbol"],
                              "side": position["side"],
                              "entry": position["entry"],
                              "stop_loss": position["stop_loss"],
                              "take_profit": position["take_profit"],
                              "position_size": position["position_size"],
                              "risk_usd": position["risk_usd"],
                              "position_id": position.get("position_id"),
                              "team_id": position.get("team_id"),
                              "team_name": position.get("team_name"),
                              "strategy_id": position.get("strategy_id"),
                              "strategy_name": position.get("strategy_name")})


def remove_position(symbol: str, position_id: str | None = None) -> dict[str, Any] | None:
    with _FILE_LOCK:
        positions = read_positions()
        for i, p in enumerate(positions):
            if p["symbol"] == symbol and _position_id_matches(p, position_id):
                removed = positions.pop(i)
                write_positions(positions)
                return removed
    return None


def update_position(symbol: str, updates: dict[str, Any], position_id: str | None = None) -> None:
    with _FILE_LOCK:
        positions = read_positions()
        for p in positions:
            if p["symbol"] == symbol and _position_id_matches(p, position_id):
                p.update(updates)
                write_positions(positions)
                break


def _position_id_matches(position: dict[str, Any], position_id: str | None) -> bool:
    """Return whether a position matches an optional stable id."""
    if not position_id:
        return True
    return str(position.get("position_id") or position.get("decision_id") or "") == str(position_id)


def append_closed_trade(trade: dict[str, Any]) -> None:
    ensure_dirs()
    with _FILE_LOCK:
        with CLOSED_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")
    append_decision("fill", {"symbol": trade["symbol"], "pnl_usd": trade["pnl_usd"],
                              "exit_price": trade["exit_price"], "exit_reason": trade["exit_reason"]})


def read_closed_trades() -> list[dict[str, Any]]:
    ensure_dirs()
    if not CLOSED_LOG.exists():
        return []
    out: list[dict[str, Any]] = []
    with CLOSED_LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def read_shadow_positions() -> list[dict[str, Any]]:
    """Return unresolved broker-free shadow records."""
    ensure_dirs()
    with _FILE_LOCK:
        try:
            payload = json.loads(SHADOW_POSITIONS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            backup = SHADOW_POSITIONS_FILE.with_suffix(
                f".corrupt.{int(time.time())}.bak"
            )
            try:
                shutil.copy2(SHADOW_POSITIONS_FILE, backup)
            except OSError:
                pass
            raise JournalCorruptError(
                f"shadow_positions.json corrupt (backup at {backup}): {exc}"
            ) from exc
        except OSError:
            return []
    if not isinstance(payload, list):
        raise JournalCorruptError("shadow_positions.json must contain a list")
    return [dict(item) for item in payload if isinstance(item, dict)]


def add_shadow_position(position: dict[str, Any]) -> bool:
    """Persist one pending shadow candidate idempotently."""
    shadow_id = str(position.get("shadow_id") or "").strip()
    if not shadow_id:
        raise ValueError("shadow_id is required")
    with _FILE_LOCK:
        positions = read_shadow_positions()
        if any(str(item.get("shadow_id")) == shadow_id for item in positions):
            return False
        positions.append(dict(position))
        _write_shadow_positions_locked(positions)
    append_lifecycle_event(
        "shadow_candidate",
        decision_id=shadow_id,
        payload={
            "shadow_id": shadow_id,
            "signal_id": position.get("signal_id"),
            "symbol": position.get("symbol"),
            "team_id": position.get("team_id"),
            "rule_score": position.get("rule_score"),
            "decision_zone": position.get("decision_zone"),
        },
    )
    return True


def update_shadow_position(shadow_id: str, updates: dict[str, Any]) -> bool:
    """Update operational metadata on one pending shadow record."""
    with _FILE_LOCK:
        positions = read_shadow_positions()
        for position in positions:
            if str(position.get("shadow_id")) != shadow_id:
                continue
            position.update(dict(updates))
            _write_shadow_positions_locked(positions)
            return True
    return False


def resolve_shadow_position(shadow_id: str, outcome: dict[str, Any]) -> bool:
    """Move one shadow row to the append-only outcome log idempotently."""
    ensure_dirs()
    payload = {**dict(outcome), "shadow_id": shadow_id}
    appended = False
    removed = False
    with _FILE_LOCK:
        positions = read_shadow_positions()
        remaining = [
            item for item in positions if str(item.get("shadow_id")) != shadow_id
        ]
        removed = len(remaining) != len(positions)
        existing = {
            str(item.get("shadow_id"))
            for item in _read_jsonl_locked(SHADOW_OUTCOMES_LOG)
        }
        if removed and shadow_id not in existing:
            with SHADOW_OUTCOMES_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            appended = True
        if removed:
            _write_shadow_positions_locked(remaining)
    if appended:
        append_lifecycle_event(
            "shadow_outcome",
            decision_id=shadow_id,
            payload={
                "shadow_id": shadow_id,
                "symbol": payload.get("symbol"),
                "exit_reason": payload.get("exit_reason"),
                "r_multiple": payload.get("r_multiple"),
                "counterfactual_eligible": payload.get("counterfactual_eligible"),
            },
        )
    return appended or removed


def read_shadow_outcomes(*, limit: int | None = None) -> list[dict[str, Any]]:
    """Return resolved shadow evidence, optionally bounded to recent rows."""
    ensure_dirs()
    with _FILE_LOCK:
        rows = _read_jsonl_locked(SHADOW_OUTCOMES_LOG)
    if limit is not None:
        rows = rows[-max(0, int(limit)):]
    return rows


def _write_shadow_positions_locked(positions: list[dict[str, Any]]) -> None:
    """Atomically replace shadow pending state while the journal lock is held."""
    _atomic_write_json_locked(SHADOW_POSITIONS_FILE, positions)


def _read_jsonl_locked(path: Path) -> list[dict[str, Any]]:
    """Read valid mapping rows from an append-only journal file."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def write_stats(stats: dict[str, Any]) -> None:
    """Atomically replace aggregate journal statistics."""
    ensure_dirs()
    with _FILE_LOCK:
        _atomic_write_json_locked(STATS_FILE, stats)


def read_stats() -> dict[str, Any]:
    ensure_dirs()
    try:
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def update_stats_on_close(trade: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    """Recompute aggregate stats after a trade closes. Mutates and returns stats."""
    pnl = trade["pnl_usd"]
    stats["total_trades"] = stats.get("total_trades", 0) + 1
    if pnl > 0:
        stats["wins"] = stats.get("wins", 0) + 1
    else:
        stats["losses"] = stats.get("losses", 0) + 1
    stats["total_pnl_usd"] = stats.get("total_pnl_usd", 0.0) + pnl
    stats["current_capital"] = stats.get("starting_capital", 10000.0) + stats["total_pnl_usd"]
    if "peak_capital" not in stats:
        stats["peak_capital"] = stats["current_capital"]
    peak = stats["peak_capital"]
    if stats["current_capital"] > peak:
        stats["peak_capital"] = stats["current_capital"]
    dd = stats["peak_capital"] - stats["current_capital"]
    if dd > stats.get("max_drawdown_usd", 0.0):
        stats["max_drawdown_usd"] = dd
    wins = stats.get("wins", 0)
    total = stats.get("total_trades", 0)
    stats["winrate"] = round(wins / total * 100, 2) if total else 0.0
    # Phase 5: rebuild breakdowns + Sharpe each close (cheap because just closed trades re-read)
    closed = read_closed_trades()
    stats["breakdowns"] = _compute_breakdowns(closed)
    stats["sharpe"] = _compute_sharpe(closed, stats.get("starting_capital", 10000.0))
    stats["skill_usage"] = _compute_skill_usage(closed)
    return stats


def _compute_breakdowns(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Win rate by alpha, regime, confluence score, exit_reason."""
    out: dict[str, Any] = {
        "by_regime": {},
        "by_confluence_bucket": {},
        "by_exit_reason": {},
        "by_decision_lane": {},
    }
    if not closed:
        return out
    for t in closed:
        pnl = float(t.get("pnl_usd", 0))
        win = pnl > 0
        regime = t.get("regime", "unknown")
        b = out["by_regime"].setdefault(regime, {"wins": 0, "losses": 0, "pnl": 0.0, "n": 0})
        b["wins" if win else "losses"] += 1
        b["pnl"] = round(b["pnl"] + pnl, 2)
        b["n"] += 1
        conf = t.get("confluence_score", 0)
        if conf >= 3:
            bucket = "+3_or_better"
        elif conf >= 1:
            bucket = "+1_to_+2"
        elif conf <= -3:
            bucket = "-3_or_worse"
        elif conf <= -1:
            bucket = "-1_to_-2"
        else:
            bucket = "neutral"
        b2 = out["by_confluence_bucket"].setdefault(bucket, {"wins": 0, "losses": 0, "n": 0})
        b2["wins" if win else "losses"] += 1
        b2["n"] += 1
        reason = t.get("exit_reason", "unknown")
        b3 = out["by_exit_reason"].setdefault(reason, {"n": 0, "pnl": 0.0})
        b3["n"] += 1
        b3["pnl"] = round(b3["pnl"] + pnl, 2)
        lane = str(t.get("decision_lane") or "legacy_unknown")
        b4 = out["by_decision_lane"].setdefault(
            lane,
            {"wins": 0, "losses": 0, "pnl": 0.0, "n": 0, "gross_profit": 0.0, "gross_loss": 0.0},
        )
        b4["wins" if win else "losses"] += 1
        b4["pnl"] = round(b4["pnl"] + pnl, 2)
        b4["gross_profit" if pnl > 0 else "gross_loss"] += abs(pnl)
        b4["n"] += 1
    for grp in out.values():
        for k, v in grp.items():
            if isinstance(v, dict) and v.get("n", 0) > 0:
                v["winrate_pct"] = round(v.get("wins", 0) / v["n"] * 100, 1)
                if "gross_profit" in v:
                    gross_loss = float(v.get("gross_loss", 0))
                    gross_profit = float(v.get("gross_profit", 0))
                    v["profit_factor"] = round(gross_profit / gross_loss, 3) if gross_loss else None
                    v["avg_pnl_usd"] = round(float(v.get("pnl", 0)) / v["n"], 2)
    return out


def _compute_sharpe(closed: list[dict[str, Any]], starting_capital: float) -> dict[str, Any]:
    """Annualized Sharpe ratio. Simplified: assume 252 trading days/year.

    trade_return = pnl_usd / capital_at_trade_time
    We approximate capital_at_trade_time as starting_capital + cumulative_pnl_before_this_trade.
    """
    if len(closed) < 2:
        return {"ratio": None, "annualized_ratio": None, "trade_count": len(closed)}
    returns: list[float] = []
    running_cap = float(starting_capital)
    for t in closed:
        pnl = float(t.get("pnl_usd", 0))
        if running_cap > 0:
            r = pnl / running_cap
            returns.append(r)
        running_cap += pnl
    if not returns:
        return {"ratio": None, "trade_count": 0}
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
    std_r = var ** 0.5
    if std_r == 0:
        return {"ratio": 0.0, "annualized_ratio": 0.0, "trade_count": len(closed)}
    sharpe = mean_r / std_r
    return {
        "ratio": round(sharpe, 3),
        "annualized_ratio": round(sharpe * (252 ** 0.5), 3),
        "mean_return": round(mean_r * 100, 4),
        "std_return": round(std_r * 100, 4),
        "trade_count": len(closed),
    }


def _compute_skill_usage(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Track which soft skills LLM applied (extracted from reasoning text) and PnL."""
    out: dict[str, dict[str, int]] = {}
    if not closed:
        return out
    for t in closed:
        skills_text = t.get("skills_applied") or t.get("llm_reasoning", "")
        if not skills_text:
            continue
        text_lower = str(skills_text).lower()
        # Re-derive keyword list from skills.json on each call? Cheap enough.
        try:
            import skills  # type: ignore
            soft = skills.get_soft_skills()
        except Exception:
            soft = {}
        for skill_id in soft:
            if skill_id in text_lower:
                slot = out.setdefault(skill_id, {"applied": 0, "wins": 0, "losses": 0})
                slot["applied"] += 1
                pnl = float(t.get("pnl_usd", 0))
                if pnl > 0:
                    slot["wins"] += 1
                else:
                    slot["losses"] += 1
    for k, v in out.items():
        if v.get("applied", 0) > 0:
            v["winrate_pct"] = round(v["wins"] / v["applied"] * 100, 1)
    return out


def get_consecutive_losses(closed: list[dict[str, Any]] | None = None,
                            n: int = 3) -> dict[str, Any]:
    """H5: Check for N consecutive losses. If triggered, kill switch should activate.

    Args:
      closed: list of closed trade dicts (or None to read from file)
      n: number of consecutive losses that triggers (default 3)

    Returns: {
      'consecutive_losses': int (most recent run),
      'triggered': bool (>= n consecutive),
      'threshold': n,
      'last_3_results': [pnl_usd, ...]
    }
    """
    if closed is None:
        closed = read_closed_trades()
    if not closed:
        return {"consecutive_losses": 0, "triggered": False, "threshold": n,
                "last_3_results": []}
    # Take last N trades (most recent first)
    recent = closed[-n:]
    pnls = [float(t.get("pnl_usd", 0)) for t in recent]
    # Count consecutive losses from the most recent
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break
    return {
        "consecutive_losses": streak,
        "triggered": streak >= n,
        "threshold": n,
        "last_results": pnls,
    }


def check_loss_streak_kill() -> bool:
    """H5: If 3+ consecutive losses, auto-set kill switch and return True.

    Returns True if kill switch was newly set.
    """
    streak = get_consecutive_losses()
    if streak["triggered"] and not KILL_SWITCH.exists():
        KILL_SWITCH.touch()
        append_decision("h5_loss_streak_kill", {
            "consecutive_losses": streak["consecutive_losses"],
            "threshold": streak["threshold"],
            "last_results": streak["last_results"],
            "msg": "Auto kill switch activated - 3+ consecutive losses",
        })
        return True
    return False


def is_killed() -> bool:
    """Return whether the manual /data/STOP kill switch is active."""
    return KILL_SWITCH.exists()


def startup_sync_guard_active() -> bool:
    """Return whether startup/resume reconciliation is blocking new entries."""
    return STARTUP_SYNC_GUARD.exists()


def read_startup_sync_guard() -> dict[str, Any] | None:
    """Read the startup sync guard metadata when present."""
    if not STARTUP_SYNC_GUARD.exists():
        return None
    try:
        payload = json.loads(STARTUP_SYNC_GUARD.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"raw": payload}
    except (OSError, json.JSONDecodeError) as exc:
        return {"reason": "startup_sync_guard_unreadable", "error": str(exc)}


def set_startup_sync_guard(reason: str, details: dict[str, Any] | None = None) -> None:
    """Block new entries until a later exchange reconciliation succeeds."""
    ensure_dirs()
    payload = {
        "reason": reason,
        "set_at": _utc_now(),
        "details": details or {},
    }
    with _FILE_LOCK:
        STARTUP_SYNC_GUARD.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    append_decision("startup_sync_guard_set", payload)


def clear_startup_sync_guard() -> None:
    """Clear only the automatic startup sync guard, not the manual STOP file."""
    try:
        if STARTUP_SYNC_GUARD.exists():
            STARTUP_SYNC_GUARD.unlink()
            append_decision("startup_sync_guard_cleared", {"cleared_at": _utc_now()})
    except OSError:
        pass


def trading_block_reason() -> str:
    """Return the active new-entry block reason, or an empty string."""
    if KILL_SWITCH.exists():
        return "kill_switch_active"
    if STARTUP_SYNC_GUARD.exists():
        return "startup_sync_blocked"
    return ""


def is_trading_blocked() -> bool:
    """Return whether new trade entries must be blocked."""
    return bool(trading_block_reason())


def clear_kill_switch() -> None:
    """Clear the manual STOP file only.

    Startup-sync blocks are cleared by exchange reconciliation, not by a manual
    resume click, so a resume cannot accidentally trade while broker state is
    unknown.
    """
    try:
        if KILL_SWITCH.exists():
            KILL_SWITCH.unlink()
    except OSError:
        pass  # Race: another process already removed it, or permission denied.


# ============= Cooldown (gap C2: protect against revenge-trade after loss) =============
# Stored in stats.json under keys:
#   cooldown_until  - ISO timestamp; trades blocked until then
#   cooldown_reason - human-readable string
#
# Thread-safe via _FILE_LOCK + write_stats().

def _cooldown_from_stats(stats: dict[str, Any]) -> tuple[str | None, str | None]:
    return stats.get("cooldown_until"), stats.get("cooldown_reason")


def set_cooldown(minutes: float, reason: str = "") -> None:
    """Block new trade entries for `minutes` from now.

    Persists to stats.json so it survives monitor restart.
    """
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        from datetime import datetime, timedelta
        until = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        stats["cooldown_until"] = until
        stats["cooldown_reason"] = reason
        write_stats(stats)
    append_decision("cooldown_set", {"minutes": minutes, "until": until, "reason": reason})


def clear_cooldown() -> None:
    """Remove any active cooldown (e.g., after a profitable trade)."""
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        if "cooldown_until" in stats or "cooldown_reason" in stats:
            stats.pop("cooldown_until", None)
            stats.pop("cooldown_reason", None)
            write_stats(stats)
    append_decision("cooldown_cleared", {})


def is_in_cooldown() -> tuple[bool, str | None, int]:
    """Return (in_cooldown, reason, seconds_remaining).

    seconds_remaining is non-negative; 0 if cooldown expired.
    Auto-clears expired cooldowns (no separate cleanup pass needed).
    """
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        until_str, reason = _cooldown_from_stats(stats)
    if not until_str:
        return (False, None, 0)
    try:
        from datetime import datetime
        until = datetime.fromisoformat(until_str)
    except (ValueError, TypeError):
        return (False, None, 0)
    now = datetime.now()
    remaining_s = int((until - now).total_seconds())
    if remaining_s <= 0:
        # Expired — clean up so future reads are cheap.
        clear_cooldown()
        return (False, None, 0)
    return (True, reason, remaining_s)


# ============= LLM cost tracking (T3F: enforce daily cost cap) =============
# Stored in stats.json under "daily_llm_cost":
#   {date: "YYYY-MM-DD", cost_usd: float, calls: int,
#    alerted_50: bool, alerted_80: bool, alerted_100: bool,
#    monthly_cost_usd: float, monthly_date: "YYYY-MM"}
#
# Auto-resets daily at local midnight. Monthly is cumulative.

def _today_key() -> str:
    """Current local date key."""
    return time.strftime("%Y-%m-%d")


def _month_key() -> str:
    """Current local month key."""
    return time.strftime("%Y-%m")


def _hour_key() -> str:
    """Current local hour key for hourly LLM caps."""
    return time.strftime("%Y-%m-%dT%H")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _llm_budget_caps() -> dict[str, float | int | str]:
    """Return current LLM budget caps from env."""
    return {
        "cap_usd": _env_float("AUTO_DAILY_LLM_COST_CAP_USD", 0.20),
        "call_cap": _env_int("AUTO_DAILY_LLM_CALL_CAP", 160),
        "hourly_call_cap": _env_int("AUTO_HOURLY_LLM_CALL_CAP", 16),
        "hourly_call_cap_per_source": _env_int(
            "AUTO_HOURLY_LLM_CALL_CAP_PER_SOURCE", 4
        ),
        "behavior": os.getenv("AUTO_LLM_OVER_CAP_BEHAVIOR", "fail_closed").strip()
        or "fail_closed",
    }


def _normal_source(source: str | None) -> str:
    value = (source or "unknown").strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    return value.strip("._-") or "unknown"


def _source_bucket(state: dict[str, Any], source: str) -> dict[str, Any]:
    breakdown = state.setdefault("source_breakdown", {})
    if not isinstance(breakdown, dict):
        breakdown = {}
        state["source_breakdown"] = breakdown
    key = _normal_source(source)
    bucket = breakdown.setdefault(
        key,
        {
            "calls": 0,
            "hourly_calls": 0,
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "budget_skips": 0,
        },
    )
    if not isinstance(bucket, dict):
        bucket = {
            "calls": 0,
            "hourly_calls": 0,
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "budget_skips": 0,
        }
        breakdown[key] = bucket
    return bucket


def _normalize_cost_state(cost: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Ensure cost state has the current budget fields."""
    before = json.dumps(cost, sort_keys=True, default=str)
    caps = _llm_budget_caps()
    hourly_key = _hour_key()

    cost.setdefault("cost_usd", 0.0)
    cost.setdefault("calls", 0)
    cost.setdefault("alerted_50", False)
    cost.setdefault("alerted_80", False)
    cost.setdefault("alerted_100", False)
    cost.setdefault("monthly_cost_usd", 0.0)
    cost.setdefault("monthly_date", _month_key())
    cost.setdefault("source_breakdown", {})
    cost.setdefault("budget_skips", 0)
    cost.setdefault("last_budget_skip", None)

    if cost.get("hourly_key") != hourly_key:
        cost["hourly_key"] = hourly_key
        cost["hourly_calls"] = 0
        breakdown = cost.get("source_breakdown", {})
        if isinstance(breakdown, dict):
            for bucket in breakdown.values():
                if isinstance(bucket, dict):
                    bucket["hourly_calls"] = 0
    else:
        cost.setdefault("hourly_calls", 0)

    breakdown = cost.get("source_breakdown", {})
    if isinstance(breakdown, dict):
        for bucket in breakdown.values():
            if isinstance(bucket, dict):
                bucket.setdefault("hourly_calls", 0)

    call_cap = int(caps["call_cap"])
    hourly_call_cap = int(caps["hourly_call_cap"])
    hourly_call_cap_per_source = int(caps["hourly_call_cap_per_source"])
    cost["cap_usd"] = float(caps["cap_usd"])
    cost["call_cap"] = call_cap
    cost["hourly_call_cap"] = hourly_call_cap
    cost["hourly_call_cap_per_source"] = hourly_call_cap_per_source
    cost["remaining_usd"] = max(
        0.0,
        round(float(cost["cap_usd"]) - float(cost.get("cost_usd", 0.0)), 6),
    )
    cost["remaining_calls"] = (
        max(0, call_cap - int(cost.get("calls", 0))) if call_cap > 0 else None
    )
    cost["remaining_hourly_calls"] = (
        max(0, hourly_call_cap - int(cost.get("hourly_calls", 0)))
        if hourly_call_cap > 0
        else None
    )
    return cost, json.dumps(cost, sort_keys=True, default=str) != before


def _load_cost_state() -> dict[str, Any]:
    """Read or initialize today's cost + monthly accumulator."""
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
    cost = stats.get("daily_llm_cost", {})
    if not isinstance(cost, dict):
        cost = {}
    today = _today_key()
    if cost.get("date") != today:
        # Roll over — carry monthly bucket across days.
        prev_month = cost.get("monthly_date")
        if prev_month == _month_key():
            monthly = float(cost.get("monthly_cost_usd", 0.0))
        else:
            monthly = 0.0
        cost = {
            "date": today,
            "cost_usd": 0.0,
            "calls": 0,
            "alerted_50": False,
            "alerted_80": False,
            "alerted_100": False,
            "monthly_cost_usd": round(monthly, 6),
            "monthly_date": _month_key(),
            "source_breakdown": {},
            "budget_skips": 0,
            "last_budget_skip": None,
        }
        changed = True
    else:
        changed = False
    cost, normalized_changed = _normalize_cost_state(cost)
    if changed or normalized_changed:
        with _FILE_LOCK:
            stats["daily_llm_cost"] = cost
            write_stats(stats)
    return cost


def add_llm_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    source: str = "unknown",
) -> tuple[float, dict[str, Any]]:
    """Record cost for a single LLM call. Return (cost_usd, updated_state).

    Cost = input_tokens * AUTO_LLM_INPUT_PRICE_PER_M + output_tokens * AUTO_LLM_OUTPUT_PRICE_PER_M
    All in USD per million tokens (DeepSeek v4-flash: $0.14 in / $0.28 out).
    """
    price_in = float(os.getenv("AUTO_LLM_INPUT_PRICE_PER_M", "0.14")) / 1_000_000.0
    price_out = float(os.getenv("AUTO_LLM_OUTPUT_PRICE_PER_M", "0.28")) / 1_000_000.0
    cost = max(0, input_tokens) * price_in + max(0, output_tokens) * price_out
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        state = _load_cost_state()  # also writes reset if needed
        state["cost_usd"] = round(float(state.get("cost_usd", 0.0)) + cost, 6)
        state["calls"] = int(state.get("calls", 0)) + 1
        state["hourly_calls"] = int(state.get("hourly_calls", 0)) + 1
        state["monthly_cost_usd"] = round(
            float(state.get("monthly_cost_usd", 0.0)) + cost, 6
        )
        bucket = _source_bucket(state, source)
        bucket["calls"] = int(bucket.get("calls", 0)) + 1
        bucket["hourly_calls"] = int(bucket.get("hourly_calls", 0)) + 1
        bucket["cost_usd"] = round(float(bucket.get("cost_usd", 0.0)) + cost, 6)
        bucket["input_tokens"] = int(bucket.get("input_tokens", 0)) + max(0, input_tokens)
        bucket["output_tokens"] = int(bucket.get("output_tokens", 0)) + max(0, output_tokens)
        state, _ = _normalize_cost_state(state)
        stats["daily_llm_cost"] = state
        write_stats(stats)
    # Telegram alerts at 50% / 80% / 100% of daily cap (fire-once per day each).
    try:
        cap = float(os.getenv("AUTO_DAILY_LLM_COST_CAP_USD", "0.20"))
        if cap > 0 and cost > 0:
            new_total = float(state.get("cost_usd", 0.0))
            pct = (new_total / cap) * 100.0
            threshold_to_fire = None
            if pct >= 100 and not state.get("alerted_100", False):
                threshold_to_fire = 100
            elif pct >= 80 and not state.get("alerted_80", False):
                threshold_to_fire = 80
            elif pct >= 50 and not state.get("alerted_50", False):
                threshold_to_fire = 50
            if threshold_to_fire is not None:
                import alerts as _alerts  # type: ignore
                _alerts.emit("llm_cost_alert", {
                    "pct": threshold_to_fire,
                    "cost_usd": round(new_total, 6),
                    "cap_usd": cap,
                    "monthly_cost_usd": float(state.get("monthly_cost_usd", 0.0)),
                    "calls_today": int(state.get("calls", 0)),
                })
                mark_cost_alert_sent(threshold_to_fire)
    except Exception:  # noqa: BLE001
        pass  # alerts are best-effort; never break cost tracking
    return (cost, state)


def daily_cost_status() -> dict[str, Any]:
    """Return today's cost + cap + monthly accumulator.

    Used by scheduler (cap gate) and dashboard widget.
    """
    state = _load_cost_state()
    caps = _llm_budget_caps()
    cap = float(caps["cap_usd"])
    call_cap = int(caps["call_cap"])
    hourly_call_cap = int(caps["hourly_call_cap"])
    hourly_call_cap_per_source = int(caps["hourly_call_cap_per_source"])
    cost = float(state.get("cost_usd", 0.0))
    calls = int(state.get("calls", 0))
    hourly_calls = int(state.get("hourly_calls", 0))
    cost_cap_reached = cap > 0 and cost >= cap
    call_cap_reached = call_cap > 0 and calls >= call_cap
    hourly_call_cap_reached = hourly_call_cap > 0 and hourly_calls >= hourly_call_cap
    cap_reason = ""
    if cost_cap_reached:
        cap_reason = "daily_cost_cap"
    elif call_cap_reached:
        cap_reason = "daily_call_cap"
    elif hourly_call_cap_reached:
        cap_reason = "hourly_call_cap"
    return {
        "date": state.get("date", _today_key()),
        "cost_usd": cost,
        "calls": calls,
        "cap_usd": cap,
        "remaining_usd": max(0.0, round(cap - cost, 6)),
        "pct_of_cap": round((cost / cap * 100.0) if cap > 0 else 0.0, 2),
        "cap_reached": bool(cost_cap_reached or call_cap_reached or hourly_call_cap_reached),
        "cap_reason": cap_reason,
        "cost_cap_reached": cost_cap_reached,
        "call_cap": call_cap,
        "call_cap_reached": call_cap_reached,
        "remaining_calls": max(0, call_cap - calls) if call_cap > 0 else None,
        "hourly_key": state.get("hourly_key", _hour_key()),
        "hourly_calls": hourly_calls,
        "hourly_call_cap": hourly_call_cap,
        "hourly_call_cap_per_source": hourly_call_cap_per_source,
        "hourly_call_cap_reached": hourly_call_cap_reached,
        "remaining_hourly_calls": (
            max(0, hourly_call_cap - hourly_calls) if hourly_call_cap > 0 else None
        ),
        "over_cap_behavior": caps["behavior"],
        "source_breakdown": state.get("source_breakdown", {}),
        "budget_skips": int(state.get("budget_skips", 0)),
        "last_budget_skip": state.get("last_budget_skip"),
        "monthly_cost_usd": float(state.get("monthly_cost_usd", 0.0)),
        "monthly_date": state.get("monthly_date", _month_key()),
        "alerted_50": bool(state.get("alerted_50", False)),
        "alerted_80": bool(state.get("alerted_80", False)),
        "alerted_100": bool(state.get("alerted_100", False)),
    }


def check_llm_budget(*, source: str = "unknown") -> dict[str, Any]:
    """Return whether a new LLM call is allowed under daily/hourly caps."""
    status = daily_cost_status()
    src = _normal_source(source)
    breakdown = status.get("source_breakdown", {})
    bucket = breakdown.get(src, {}) if isinstance(breakdown, dict) else {}
    source_hourly_calls = int(bucket.get("hourly_calls", 0)) if isinstance(bucket, dict) else 0
    source_hourly_cap = int(status.get("hourly_call_cap_per_source", 0))
    source_hourly_cap_reached = (
        source_hourly_cap > 0 and source_hourly_calls >= source_hourly_cap
    )
    global_cap_reached = bool(status.get("cap_reached", False))
    allowed = not global_cap_reached and not source_hourly_cap_reached
    reason = ""
    if global_cap_reached:
        reason = str(status.get("cap_reason") or "llm_budget_cap")
    elif source_hourly_cap_reached:
        reason = "source_hourly_call_cap"
    return {
        **status,
        "source": src,
        "source_hourly_calls": source_hourly_calls,
        "source_hourly_call_cap": source_hourly_cap,
        "source_hourly_call_cap_reached": source_hourly_cap_reached,
        "remaining_source_hourly_calls": (
            max(0, source_hourly_cap - source_hourly_calls)
            if source_hourly_cap > 0
            else None
        ),
        "allowed": allowed,
        "reason": reason,
    }


def record_llm_budget_skip(
    *,
    source: str = "unknown",
    reason: str = "llm_budget_cap",
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a fail-closed LLM budget denial."""
    ensure_dirs()
    src = _normal_source(source)
    base_status = status or daily_cost_status()
    skip = {
        "ts": _now(),
        "source": src,
        "reason": reason,
        "behavior": str(base_status.get("over_cap_behavior", "fail_closed")),
        "cost_usd": float(base_status.get("cost_usd", 0.0)),
        "cap_usd": float(base_status.get("cap_usd", 0.0)),
        "calls": int(base_status.get("calls", 0)),
        "call_cap": int(base_status.get("call_cap", 0)),
        "hourly_calls": int(base_status.get("hourly_calls", 0)),
        "hourly_call_cap": int(base_status.get("hourly_call_cap", 0)),
        "source_hourly_calls": int(base_status.get("source_hourly_calls", 0)),
        "source_hourly_call_cap": int(base_status.get("source_hourly_call_cap", 0)),
    }
    with _FILE_LOCK:
        stats = read_stats()
        state = _load_cost_state()
        state["budget_skips"] = int(state.get("budget_skips", 0)) + 1
        state["last_budget_skip"] = skip
        bucket = _source_bucket(state, src)
        bucket["budget_skips"] = int(bucket.get("budget_skips", 0)) + 1
        state, _ = _normalize_cost_state(state)
        stats["daily_llm_cost"] = state
        write_stats(stats)
    append_decision("llm_budget_skip", {**skip, "budget": daily_cost_status()})
    return skip


def mark_cost_alert_sent(threshold: int) -> None:
    """Mark a threshold (50/80/100) as already-alerted-today so we don't spam."""
    key = f"alerted_{threshold}"
    ensure_dirs()
    with _FILE_LOCK:
        stats = read_stats()
        state = _load_cost_state()
        state[key] = True
        stats["daily_llm_cost"] = state
        write_stats(stats)
