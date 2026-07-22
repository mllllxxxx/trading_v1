"""LLM override tracker — dynamic gate for the hybrid mode.

In ``AUTO_OVERRIDE_ALLOWED=true`` static mode the LLM can always override the
hard rules. In hybrid mode we ONLY allow override when the LLM has earned it:
its rolling win-rate on past overrides must exceed a threshold AND we have
enough samples to be statistically meaningful.

Cold start (no history): override = false. The system starts safe and
gradually allows the LLM to take more autonomy as it demonstrates skill.

Storage: append-only NDJSON at ``$VIBE_TRADING_HOME/llm_overrides.jsonl``.
Each row looks like:
  {"ts": "2026-06-23T10:00:00Z", "symbol": "BTC-USDT-SWAP",
   "llm_action": "long", "rules_action": "no_trade",
   "llm_overrode": true, "reasoning": "...",
   "closed_at": "2026-06-23T14:30:00Z", "pnl_usd": 12.5, "win": true}
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config (env-overridable)
# ---------------------------------------------------------------------------

LLM_OVERRIDE_ENABLED = os.getenv("LLM_OVERRIDE_ENABLED", "true").lower() in ("true", "1", "yes")
LLM_OVERRIDE_MIN_SAMPLES = int(os.getenv("LLM_OVERRIDE_MIN_SAMPLES", "20"))
LLM_OVERRIDE_WINRATE_THRESHOLD = float(os.getenv("LLM_OVERRIDE_WINRATE_THRESHOLD", "0.60"))
LLM_OVERRIDE_LOOKBACK = int(os.getenv("LLM_OVERRIDE_LOOKBACK", "30"))


def _data_dir() -> Path:
    return Path(os.getenv("VIBE_TRADING_HOME", "/data"))


def _log_path() -> Path:
    return _data_dir() / "llm_overrides.jsonl"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class OverrideRecord:
    """One row in the override log. Append-only."""
    ts: str                                  # ISO8601 UTC of decision
    symbol: str
    llm_action: str                          # "long" | "short" | "no_trade"
    rules_action: str                        # what rules would have done
    llm_overrode: bool                       # True if LLM action != rules_action
    reasoning: str = ""
    used_override: bool = False              # True if gate said yes (we let LLM trade)
    closed_at: str | None = None             # filled when trade closes
    pnl_usd: float | None = None
    win: bool | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str) -> "OverrideRecord":
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class OverrideTracker:
    """Thread-safe append + recent-overrides query.

    All writes go through the file lock so concurrent scheduler/monitor threads
    don't interleave partial lines.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _log_path()
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, record: OverrideRecord) -> None:
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(record.to_json() + "\n")

    def iter_all(self) -> Iterable[OverrideRecord]:
        """Yield every record, oldest first. Skips corrupt lines with a warning."""
        with self._lock:
            if not self.path.exists():
                return
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    yield OverrideRecord.from_json(line)
                except Exception as exc:  # noqa: BLE001
                    log.warning("override log: skipping corrupt line: %s", exc)

    def mark_closed(self, symbol: str, pnl_usd: float, win: bool,
                    closed_at: str | None = None) -> int:
        """Update the most-recent unclosed record for ``symbol`` with close info.

        Returns the number of records updated (0 if none found).
        """
        if closed_at is None:
            closed_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            if not self.path.exists():
                return 0
            lines = self.path.read_text(encoding="utf-8").splitlines()
            updated = 0
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i].strip()
                if not line:
                    continue
                try:
                    rec = OverrideRecord.from_json(line)
                except Exception:  # noqa: BLE001
                    continue
                if rec.symbol == symbol and rec.closed_at is None:
                    rec.closed_at = closed_at
                    rec.pnl_usd = pnl_usd
                    rec.win = win
                    lines[i] = rec.to_json()
                    updated += 1
                    break  # only update the most recent
            self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return updated

    def get_recent_overrides(
        self,
        symbol: str | None = None,
        n: int = LLM_OVERRIDE_LOOKBACK,
        only_used: bool = True,
        only_closed: bool = True,
    ) -> list[OverrideRecord]:
        """Return last N override records, optionally filtered.

        Default: only records where ``used_override=True`` (LLM actually overrode)
        AND ``closed_at`` is set (we know the outcome). This is what the gate
        uses to compute win-rate.
        """
        out: list[OverrideRecord] = []
        for rec in self.iter_all():
            if only_used and not rec.used_override:
                continue
            if only_closed and rec.closed_at is None:
                continue
            if symbol is not None and rec.symbol != symbol:
                continue
            out.append(rec)
        return out[-n:]

    def winrate(self, symbol: str | None = None) -> tuple[float, int]:
        """Return (win_rate, sample_count) for the most recent overrides.

        Returns (0.0, 0) if no samples.
        """
        recent = self.get_recent_overrides(symbol=symbol)
        if not recent:
            return 0.0, 0
        wins = sum(1 for r in recent if r.win)
        return wins / len(recent), len(recent)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class HybridOverrideGate:
    """Decides whether the LLM is allowed to override rules this cycle.

    Pure function on top of ``OverrideTracker``. Cached for a short window to
    avoid hammering the disk every cycle.
    """

    def __init__(
        self,
        tracker: OverrideTracker | None = None,
        enabled: bool = LLM_OVERRIDE_ENABLED,
        min_samples: int = LLM_OVERRIDE_MIN_SAMPLES,
        threshold: float = LLM_OVERRIDE_WINRATE_THRESHOLD,
        lookback: int = LLM_OVERRIDE_LOOKBACK,
    ) -> None:
        self.tracker = tracker or OverrideTracker()
        self.enabled = enabled
        self.min_samples = min_samples
        self.threshold = threshold
        self.lookback = lookback
        self._cache: dict[str, tuple[float, int, float]] = {}  # symbol -> (winrate, n, ts)
        self._cache_ttl_s = 60.0

    def allow(self, symbol: str) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        if not self.enabled:
            return False, "disabled (LLM_OVERRIDE_ENABLED=false)"

        now = time.time()
        cached = self._cache.get(symbol)
        if cached and (now - cached[2]) < self._cache_ttl_s:
            winrate, n = cached[0], cached[1]
        else:
            winrate, n = self.tracker.winrate(symbol=symbol)
            self._cache[symbol] = (winrate, n, now)

        if n < self.min_samples:
            return False, (
                f"cold start: {n} samples < {self.min_samples} required "
                f"(cold-start: rules always win)"
            )

        if winrate >= self.threshold:
            return True, (
                f"override allowed: winrate={winrate:.2%} >= {self.threshold:.2%} "
                f"over {n} samples"
            )

        return False, (
            f"LLM underperforming: winrate={winrate:.2%} < {self.threshold:.2%} "
            f"over {n} samples (force rules)"
        )

    def record(self, record: OverrideRecord) -> None:
        """Append a record and invalidate cache for its symbol."""
        self.tracker.append(record)
        self._cache.pop(record.symbol, None)

    def mark_trade_closed(self, symbol: str, pnl_usd: float, win: bool) -> None:
        """Update most-recent unclosed record for symbol with close info."""
        self.tracker.mark_closed(symbol, pnl_usd, win)
        self._cache.pop(symbol, None)


# ---------------------------------------------------------------------------
# Module-level singleton (cheap to construct, safe to share)
# ---------------------------------------------------------------------------

_gate: HybridOverrideGate | None = None


def get_gate() -> HybridOverrideGate:
    global _gate
    if _gate is None:
        _gate = HybridOverrideGate()
    return _gate


def should_allow_llm_override(symbol: str) -> tuple[bool, str]:
    """Module-level convenience for scheduler."""
    return get_gate().allow(symbol)
