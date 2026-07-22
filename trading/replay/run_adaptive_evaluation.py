"""CLI for broker-free adaptive threshold evaluation reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from replay.adaptive_evaluation import (
    DEFAULT_POLICY_PATH,
    evaluate_adaptive_thresholds,
    write_adaptive_evaluation_report,
)
from replay.run_replay import load_replay_records


def load_adaptive_records(path: str | Path) -> list[dict[str, Any]]:
    """Load replay rows or flatten strategy-backtest result envelopes."""
    source = Path(path)
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if not text.startswith("{"):
        return load_replay_records(source)
    payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("adaptive evaluation JSON object is invalid")
    trades = payload.get("trades")
    if isinstance(trades, list):
        return [dict(item) for item in trades if isinstance(item, Mapping)]
    results = payload.get("results")
    if isinstance(results, list):
        rows: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, Mapping) or not isinstance(result.get("trades"), list):
                continue
            rows.extend(
                dict(item)
                for item in result["trades"]
                if isinstance(item, Mapping)
            )
        return rows
    raise ValueError("adaptive evaluation JSON object must contain trades or results")


def run_adaptive_evaluation(
    records: Iterable[Mapping[str, Any]],
    *,
    output_dir: str | Path,
    run_id: str = "adaptive_thresholds",
    policy_path: Path = DEFAULT_POLICY_PATH,
    min_total: int = 120,
    min_zone: int = 30,
) -> dict[str, Any]:
    """Evaluate records and write review artifacts without broker access."""
    evaluation = evaluate_adaptive_thresholds(
        records,
        policy_path=policy_path,
        min_total=min_total,
        min_zone=min_zone,
    )
    paths = write_adaptive_evaluation_report(
        evaluation,
        output_dir,
        run_id=run_id,
    )
    return {
        "mode": "adaptive_evaluation",
        "broker_calls": 0,
        "evaluation": evaluation,
        "artifacts": paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Replay/backtest JSON or JSONL records")
    parser.add_argument("--output-dir", type=Path, default=Path("replay/reports"))
    parser.add_argument("--run-id", default="adaptive_thresholds")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--min-total", type=int, default=120)
    parser.add_argument("--min-zone", type=int, default=30)
    args = parser.parse_args()
    result = run_adaptive_evaluation(
        load_adaptive_records(args.input),
        output_dir=args.output_dir,
        run_id=args.run_id,
        policy_path=args.policy,
        min_total=args.min_total,
        min_zone=args.min_zone,
    )
    evaluation = result["evaluation"]
    print(
        f"status={evaluation['status']} eligible={evaluation['eligible_records']} "
        f"excluded={evaluation['excluded_records']} artifacts={result['artifacts']}"
    )


if __name__ == "__main__":
    main()
