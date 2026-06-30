"""Replay metrics for LLM-governed decision records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def compute_replay_metrics(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute quality and outcome metrics from replay records."""
    rows = [dict(record) for record in records]
    total = len(rows)
    pnl_values = [_number_or_none(row.get("pnl_usd")) for row in rows]
    realized_pnls = [value for value in pnl_values if value is not None]
    r_values = [
        value for value in (_number_or_none(row.get("r_multiple")) for row in rows)
        if value is not None
    ]

    verifier_reasons: dict[str, int] = {}
    for row in rows:
        for violation in _violations(row):
            reason = str(violation.get("rule_id") or violation.get("reason") or "unknown")
            verifier_reasons[reason] = verifier_reasons.get(reason, 0) + 1

    metrics = {
        "total_decisions": total,
        "json_validity_rate": _rate(rows, _json_valid),
        "rule_citation_validity_rate": _rate(rows, _citation_valid),
        "hallucinated_rule_rate": _rate(rows, _has_hallucinated_rules),
        "hold_rate": _rate(rows, _is_hold),
        "rejected_ticket_rate": _rate(rows, _is_rejected),
        "verifier_rejection_reasons": dict(sorted(verifier_reasons.items())),
        "win_rate": _win_rate(realized_pnls),
        "profit_factor": _profit_factor(realized_pnls),
        "max_drawdown": _max_drawdown(realized_pnls),
        "average_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
        "performance_by_playbook": _performance_breakdown(rows, "playbook_id"),
        "performance_by_regime": _performance_breakdown(rows, "regime"),
        "decision_stability": _decision_stability(rows),
    }
    return metrics


def write_replay_report(
    metrics: Mapping[str, Any],
    output_dir: str | Path,
    *,
    run_id: str = "mock_replay",
) -> dict[str, str]:
    """Write JSON and Markdown replay reports."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    md_path = out_dir / f"{run_id}.md"
    json_path.write_text(
        json.dumps(dict(metrics), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(_markdown_report(metrics, run_id), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _json_valid(row: Mapping[str, Any]) -> bool:
    return bool(row.get("ticket_json_valid", row.get("json_valid", False)))


def _citation_valid(row: Mapping[str, Any]) -> bool:
    hallucinated = row.get("hallucinated_rule_ids", [])
    return bool(row.get("rule_citations_valid", not bool(hallucinated)))


def _has_hallucinated_rules(row: Mapping[str, Any]) -> bool:
    hallucinated = row.get("hallucinated_rule_ids", [])
    return bool(hallucinated)


def _is_hold(row: Mapping[str, Any]) -> bool:
    action = row.get("action")
    if action is None and isinstance(row.get("ticket"), Mapping):
        action = row["ticket"].get("action")
    return str(action or "").upper() == "HOLD"


def _is_rejected(row: Mapping[str, Any]) -> bool:
    if row.get("critic_verdict") == "REJECT":
        return True
    if row.get("verifier_passed") is False:
        return True
    return bool(_violations(row))


def _violations(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = row.get("verifier_violations", [])
    if isinstance(values, list):
        return [item for item in values if isinstance(item, Mapping)]
    verifier_result = row.get("verifier_result")
    if isinstance(verifier_result, Mapping):
        nested = verifier_result.get("violations", [])
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, Mapping)]
    return []


def _rate(rows: list[dict[str, Any]], predicate) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if predicate(row)) / len(rows), 4)


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _win_rate(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    return round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4)


def _profit_factor(pnls: list[float]) -> float | None:
    wins = sum(pnl for pnl in pnls if pnl > 0)
    losses = abs(sum(pnl for pnl in pnls if pnl < 0))
    if wins == 0 and losses == 0:
        return None
    if losses == 0:
        return None
    return round(wins / losses, 4)


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def _performance_breakdown(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = str(row.get(key) or "unknown")
        slot = out.setdefault(group, {"n": 0, "pnl_usd": 0.0, "wins": 0, "losses": 0})
        slot["n"] += 1
        pnl = _number_or_none(row.get("pnl_usd"))
        if pnl is None:
            continue
        slot["pnl_usd"] = round(slot["pnl_usd"] + pnl, 4)
        if pnl > 0:
            slot["wins"] += 1
        elif pnl < 0:
            slot["losses"] += 1
    for slot in out.values():
        finished = slot["wins"] + slot["losses"]
        slot["win_rate"] = round(slot["wins"] / finished, 4) if finished else None
    return dict(sorted(out.items()))


def _decision_stability(rows: list[dict[str, Any]]) -> float | None:
    checked = [row for row in rows if "decision_stable" in row]
    if not checked:
        return None
    return round(sum(1 for row in checked if bool(row.get("decision_stable"))) / len(checked), 4)


def _markdown_report(metrics: Mapping[str, Any], run_id: str) -> str:
    lines = [
        f"# Replay Report: {run_id}",
        "",
        f"- Total decisions: {metrics.get('total_decisions', 0)}",
        f"- JSON validity rate: {metrics.get('json_validity_rate')}",
        f"- Rule citation validity rate: {metrics.get('rule_citation_validity_rate')}",
        f"- Hallucinated rule rate: {metrics.get('hallucinated_rule_rate')}",
        f"- HOLD rate: {metrics.get('hold_rate')}",
        f"- Rejected ticket rate: {metrics.get('rejected_ticket_rate')}",
        f"- Win rate: {metrics.get('win_rate')}",
        f"- Profit factor: {metrics.get('profit_factor')}",
        f"- Max drawdown: {metrics.get('max_drawdown')}",
        f"- Average R: {metrics.get('average_r')}",
        "",
        "## Verifier Rejection Reasons",
        "",
    ]
    reasons = metrics.get("verifier_rejection_reasons", {})
    if isinstance(reasons, Mapping) and reasons:
        for reason, count in reasons.items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
