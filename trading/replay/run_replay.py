"""Broker-free replay runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .metrics import compute_replay_metrics, write_replay_report
except ImportError:  # pragma: no cover - direct script import fallback
    from metrics import compute_replay_metrics, write_replay_report  # type: ignore


def run_mock_replay(
    records: Sequence[Mapping[str, Any]],
    *,
    output_dir: str | Path,
    run_id: str = "mock_replay",
) -> dict[str, Any]:
    """Run broker-free replay metrics and write reports."""
    metrics = compute_replay_metrics(records)
    paths = write_replay_report(metrics, output_dir, run_id=run_id)
    return {"mode": "mock", "broker_calls": 0, "metrics": metrics, "paths": paths}


def load_replay_records(path: str | Path) -> list[dict[str, Any]]:
    """Load replay records from JSON array or JSONL."""
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("replay JSON input must be a list")
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, Mapping):
            rows.append(dict(item))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run broker-free replay metrics.")
    parser.add_argument("--input", required=True, help="Replay records JSON or JSONL")
    parser.add_argument("--output-dir", required=True, help="Report output directory")
    parser.add_argument("--run-id", default="mock_replay")
    args = parser.parse_args(argv)

    result = run_mock_replay(
        load_replay_records(args.input),
        output_dir=args.output_dir,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
