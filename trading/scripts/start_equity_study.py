"""Create a capped-equity study baseline in the runtime journal.

Run inside the Docker container, for example:

    python /app/scripts/start_equity_study.py --equity 200 --profile demo_small_200
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def main() -> int:
    """Create or replace the active capped-equity study baseline."""
    parser = argparse.ArgumentParser(description="Start a capped-equity performance study")
    parser.add_argument("--equity", type=float, default=_env_float("TRADING_EQUITY_CAP_USD", 200.0))
    parser.add_argument("--profile", default=os.getenv("TRADING_RISK_PROFILE", "demo_small_200"))
    parser.add_argument("--baseline", type=float, default=None, help="Override baseline total PnL")
    parser.add_argument("--force", action="store_true", help="Replace an existing baseline file")
    args = parser.parse_args()

    data_dir = Path(os.getenv("VIBE_TRADING_HOME", "/data"))
    journal_dir = data_dir / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / "equity_study_baseline.json"
    if path.exists() and not args.force:
        raise SystemExit(f"baseline already exists at {path}; pass --force to replace it")

    baseline = float(args.baseline) if args.baseline is not None else _compute_current_pre_cap_pnl()
    payload: dict[str, Any] = {
        "schema_version": "equity_study_baseline.v1",
        "risk_profile": str(args.profile),
        "equity_cap_usd": round(float(args.equity), 2),
        "baseline_total_pnl_usd": round(baseline, 2),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": "Subtract this PnL baseline from capped-equity dashboard metrics.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def _compute_current_pre_cap_pnl() -> float:
    """Return the current pre-cap PnL from journal plus synced open-position UPL."""
    baseline = 0.0
    try:
        from auto import journal  # type: ignore

        stats = journal.read_stats()
        baseline = float(stats.get("total_pnl_usd") or 0.0)
    except Exception:
        return 0.0

    try:
        from auto import exchange_reconciler  # type: ignore

        try:
            snapshot = exchange_reconciler.fetch_okx_demo_snapshot()
        except Exception:
            snapshot = None
        baseline += sum(
            float(position.get("unrealized_pnl") or 0.0)
            for position in (snapshot or {}).get("positions", [])
        )
    except Exception:
        pass
    return baseline


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(main())
