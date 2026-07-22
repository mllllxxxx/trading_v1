"""Strategy-team catalog and tournament metrics for demo trading."""

from __future__ import annotations

import os
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class StrategyTeam:
    """Static strategy-team metadata used by scanners, journal, and UI."""

    team_id: str
    team_name: str
    strategy_id: str
    strategy_name: str
    scanner_source: str
    method: str
    color: str
    team_capital_usd: float = 200.0
    risk_min_pct_equity: float = 0.03
    risk_max_pct_equity: float = 0.05
    target_risk_pct_equity: float = 0.03
    preferred_playbook_ids: tuple[str, ...] = ()
    required_soft_policy_ids: tuple[str, ...] = ()
    entry_style: str = ""
    avoid_conditions: tuple[str, ...] = ()
    llm_guidance: str = ""
    risk_personality: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable metadata."""
        data = asdict(self)
        data["preferred_playbook_ids"] = list(self.preferred_playbook_ids)
        data["required_soft_policy_ids"] = list(self.required_soft_policy_ids)
        data["avoid_conditions"] = list(self.avoid_conditions)
        return data

    def signal_metadata(self) -> dict[str, Any]:
        """Return the fields embedded into SignalCandidate records."""
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "team_capital_usd": self.team_capital_usd,
            "risk_min_pct_equity": self.risk_min_pct_equity,
            "risk_max_pct_equity": self.risk_max_pct_equity,
            "target_risk_pct_equity": self.target_risk_pct_equity,
            "preferred_playbook_ids": list(self.preferred_playbook_ids),
            "required_soft_policy_ids": list(self.required_soft_policy_ids),
            "entry_style": self.entry_style,
            "avoid_conditions": list(self.avoid_conditions),
            "llm_guidance": self.llm_guidance,
            "risk_personality": self.risk_personality,
        }

    def skill_profile(self) -> dict[str, Any]:
        """Return advisory skill-profile metadata for prompts and journals."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "preferred_playbook_ids": list(self.preferred_playbook_ids),
            "required_soft_policy_ids": list(self.required_soft_policy_ids),
            "entry_style": self.entry_style,
            "avoid_conditions": list(self.avoid_conditions),
            "llm_guidance": self.llm_guidance,
            "risk_personality": self.risk_personality,
        }


TEAM_ORDER = (
    "berkshire",
    "momentum",
    "mean_reversion",
    "volatility_breakout",
)

TEAMS: dict[str, StrategyTeam] = {
    "berkshire": StrategyTeam(
        team_id="berkshire",
        team_name="Berkshire",
        strategy_id="quality_directional",
        strategy_name="Quality Directional",
        scanner_source="berkshire_crypto_scanner",
        method="liquidity and spread quality with aligned 4H trend and 1H confirmation",
        color="green",
        target_risk_pct_equity=0.03,
        preferred_playbook_ids=("PB_CRYPTO_TREND_CONTINUATION_001",),
        required_soft_policy_ids=("SOFT_CRYPTO_001", "SOFT_CRYPTO_002", "SOFT_REGIME_001"),
        entry_style="Prefer quality directional entries after liquidity, spread, and trend evidence agree.",
        avoid_conditions=("weak evidence", "thin liquidity", "wide spread"),
        llm_guidance="Berkshire quality signals are advisory evidence only; prefer HOLD when quality or risk evidence is unclear.",
        risk_personality="quality-first directional allocator with the lowest tournament target risk.",
    ),
    "momentum": StrategyTeam(
        team_id="momentum",
        team_name="Momentum",
        strategy_id="crypto_momentum_breakout",
        strategy_name="Momentum Breakout",
        scanner_source="team_momentum_scanner",
        method="4H trend continuation after a 1H/15m pullback or reclaim",
        color="blue",
        target_risk_pct_equity=0.04,
        preferred_playbook_ids=("PB_CRYPTO_TREND_CONTINUATION_001",),
        required_soft_policy_ids=("SOFT_CRYPTO_001", "SOFT_CRYPTO_002", "SOFT_REGIME_001", "SOFT_STRATEGY_TEAM_001"),
        entry_style="Wait for a confirmed 1H/15m pullback or EMA20 reclaim inside a 4H trend; do not chase beyond 0.5 ATR.",
        avoid_conditions=("late impulse chase", "thin liquidity", "wide spread", "funding or crowding warning"),
        llm_guidance="Momentum may promote trend continuation only when liquidity, spread, and regime support the impulse. Prefer HOLD over chasing an extended move.",
        risk_personality="medium-high conviction trend follower; reduce confidence when entry is far from retest.",
    ),
    "mean_reversion": StrategyTeam(
        team_id="mean_reversion",
        team_name="Mean Reversion",
        strategy_id="crypto_mean_reversion",
        strategy_name="Mean Reversion",
        scanner_source="team_mean_reversion_scanner",
        method="range-only fade after RSI/Bollinger stretch and a 15m return toward value",
        color="yellow",
        target_risk_pct_equity=0.03,
        preferred_playbook_ids=("PB_CRYPTO_MEAN_REVERSION_001",),
        required_soft_policy_ids=("SOFT_REGIME_002", "SOFT_CORRELATION_001", "SOFT_STRATEGY_TEAM_001"),
        entry_style="Fade a stretched RSI/Bollinger move only in a confirmed 1H range after 15m turns back toward value.",
        avoid_conditions=("strong trending regime", "disorderly range expansion", "missing range structure", "thin liquidity"),
        llm_guidance="Mean Reversion must not fade strong trends by default. It should return HOLD unless range behavior and invalidation are clear.",
        risk_personality="patient contrarian; low target risk unless range quality is clear.",
    ),
    "volatility_breakout": StrategyTeam(
        team_id="volatility_breakout",
        team_name="Volatility Breakout",
        strategy_id="crypto_volatility_breakout",
        strategy_name="Volatility Breakout",
        scanner_source="team_volatility_breakout_scanner",
        method="Donchian expansion after compression, volume confirmation, and a near retest",
        color="red",
        target_risk_pct_equity=0.05,
        preferred_playbook_ids=("PB_CRYPTO_BREAKOUT_PULLBACK_001",),
        required_soft_policy_ids=("SOFT_CRYPTO_001", "SOFT_CRYPTO_002", "SOFT_CORRELATION_001", "SOFT_STRATEGY_TEAM_001"),
        entry_style="Trade range expansion only after directional pressure is visible, preferring retest or pullback over raw chase.",
        avoid_conditions=("range expansion missing", "failed breakout", "overextended breakout", "wide spread"),
        llm_guidance="Volatility Breakout may promote expansion setups, but must prefer pullback entries and reject failed or overextended breakouts.",
        risk_personality="highest tournament risk target, but only for confirmed expansion with clear invalidation.",
    ),
}

UNKNOWN_TEAM_ID = "unassigned"


def all_strategy_teams() -> list[StrategyTeam]:
    """Return all configured tournament teams in stable UI order."""
    return [TEAMS[team_id] for team_id in TEAM_ORDER]


def resolve_team(value: str | None = None) -> StrategyTeam:
    """Resolve a team id or scanner source to a strategy team."""
    if not value:
        return TEAMS["berkshire"]
    normalized = _normalize_key(value)
    if normalized in TEAMS:
        return TEAMS[normalized]
    for team in TEAMS.values():
        if normalized == _normalize_key(team.scanner_source):
            return team
    return TEAMS["berkshire"]


def team_ids_from_env(default: str | None = None) -> tuple[str, ...]:
    """Return configured team ids from STRATEGY_TEAM_IDS."""
    raw = os.getenv("STRATEGY_TEAM_IDS", default or ",".join(TEAM_ORDER))
    values = [_normalize_key(item) for item in raw.split(",") if item.strip()]
    ids = [team_id for team_id in values if team_id in TEAMS]
    return tuple(dict.fromkeys(ids)) or ("berkshire",)


def infer_team_id(record: Mapping[str, Any] | None) -> str:
    """Infer a team id from a journal, signal, position, or closed trade record."""
    if not isinstance(record, Mapping):
        return UNKNOWN_TEAM_ID
    direct = _first_text(record, "team_id", "strategy_team_id")
    if direct and _normalize_key(direct) in TEAMS:
        return _normalize_key(direct)

    for nested_key in ("source_context", "market_context", "decision_context", "open_rationale"):
        nested = record.get(nested_key)
        if isinstance(nested, Mapping):
            nested_id = infer_team_id(nested)
            if nested_id != UNKNOWN_TEAM_ID:
                return nested_id
            exposure = nested.get("portfolio_exposure")
            if isinstance(exposure, Mapping):
                exposure_id = infer_team_id(exposure)
                if exposure_id != UNKNOWN_TEAM_ID:
                    return exposure_id

    source = _first_text(record, "source", "signal_source")
    if source:
        normalized = _normalize_key(source)
        for team in TEAMS.values():
            if normalized == _normalize_key(team.scanner_source):
                return team.team_id

    open_reason = _first_text(record, "open_reason", "reasoning_summary", "thesis")
    if open_reason and "berkshire" in open_reason.lower():
        return "berkshire"
    return UNKNOWN_TEAM_ID


def build_team_dashboard(
    positions: list[Mapping[str, Any]],
    closed_trades: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build leaderboard metrics from journal evidence."""
    metrics: dict[str, dict[str, Any]] = {}
    for team in all_strategy_teams():
        metrics[team.team_id] = {
            **team.to_dict(),
            "open_positions": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0,
            "realized_pnl_usd": 0.0,
            "unrealized_pnl_usd": 0.0,
            "current_equity_usd": team.team_capital_usd,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "wilson_winrate": 0.0,
            "sample_reliability": 0.0,
            "competition_score": 0.0,
            "ranking_status": "provisional",
            "avg_actual_risk_pct_equity": None,
            "rank": None,
        }

    for position in positions:
        team_id = infer_team_id(position)
        if team_id not in metrics:
            continue
        metrics[team_id]["open_positions"] += 1
        metrics[team_id]["unrealized_pnl_usd"] = round(
            float(metrics[team_id]["unrealized_pnl_usd"]) + _float(position.get("unrealized_pnl")),
            2,
        )

    trades_by_team: dict[str, list[Mapping[str, Any]]] = {team_id: [] for team_id in metrics}
    for trade in closed_trades:
        team_id = infer_team_id(trade)
        if team_id in trades_by_team:
            trades_by_team[team_id].append(trade)

    for team_id, trades in trades_by_team.items():
        metric = metrics[team_id]
        ordered = sorted(trades, key=_closed_sort_key)
        equity = float(metric["team_capital_usd"])
        peak = equity
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        gross_profit = 0.0
        gross_loss = 0.0
        r_results: list[float] = []
        actual_risks: list[float] = []
        for trade in ordered:
            pnl = _float(trade.get("pnl_usd"))
            equity += pnl
            peak = max(peak, equity)
            current_drawdown = peak - equity
            max_drawdown = max(max_drawdown, current_drawdown)
            max_drawdown_pct = max(
                max_drawdown_pct,
                current_drawdown / peak if peak > 0 else 0.0,
            )
            metric["closed_trades"] += 1
            metric["realized_pnl_usd"] = round(float(metric["realized_pnl_usd"]) + pnl, 2)
            if pnl > 0:
                metric["wins"] += 1
                gross_profit += pnl
            else:
                metric["losses"] += 1
                gross_loss += abs(pnl)
            risk_amount = _trade_risk_amount(trade)
            if risk_amount > 0:
                r_results.append(pnl / risk_amount)
            actual_risk = _trade_actual_risk_pct(trade)
            if actual_risk is not None:
                actual_risks.append(actual_risk)
        total = int(metric["closed_trades"])
        metric["winrate"] = round((int(metric["wins"]) / total * 100.0) if total else 0.0, 1)
        metric["max_drawdown_usd"] = round(max_drawdown, 2)
        metric["max_drawdown_pct"] = round(max_drawdown_pct, 6)
        metric["expectancy_r"] = round(sum(r_results) / len(r_results), 4) if r_results else 0.0
        metric["profit_factor"] = round(
            min(gross_profit / gross_loss, 2.0) if gross_loss > 0 else (2.0 if gross_profit > 0 else 0.0),
            4,
        )
        metric["wilson_winrate"] = round(_wilson_lower_bound(int(metric["wins"]), total), 6)
        metric["sample_reliability"] = round(min(total / 30.0, 1.0), 4)
        metric["ranking_status"] = "qualified" if total >= 30 else "provisional"
        metric["avg_actual_risk_pct_equity"] = (
            round(sum(actual_risks) / len(actual_risks), 6) if actual_risks else None
        )
        raw_score = (
            0.35 * float(metric["wilson_winrate"]) * 100.0
            + 0.30 * _expectancy_score(float(metric["expectancy_r"]))
            + 0.20 * min(float(metric["profit_factor"]) / 2.0, 1.0) * 100.0
            + 0.15 * max(0.0, 1.0 - float(metric["max_drawdown_pct"]) / 0.20) * 100.0
        )
        metric["competition_score"] = round(
            raw_score * float(metric["sample_reliability"]),
            2,
        )
        metric["current_equity_usd"] = round(
            float(metric["team_capital_usd"])
            + float(metric["realized_pnl_usd"])
            + float(metric["unrealized_pnl_usd"]),
            2,
        )

    ranked = sorted(
        metrics.values(),
        key=lambda item: (
            -float(item["competition_score"]),
            -float(item["sample_reliability"]),
            -float(item["winrate"]),
            -float(item["realized_pnl_usd"]),
            float(item["max_drawdown_usd"]),
            TEAM_ORDER.index(str(item["team_id"])) if str(item["team_id"]) in TEAM_ORDER else 99,
        ),
    )
    for idx, item in enumerate(ranked, start=1):
        item["rank"] = idx
    return [metrics[team_id] for team_id in TEAM_ORDER]


def _first_text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _closed_sort_key(trade: Mapping[str, Any]) -> str:
    value = str(trade.get("closed_at") or trade.get("ts") or "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return value


def _wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = wins / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    )
    return max(0.0, (centre - margin) / denominator)


def _expectancy_score(expectancy_r: float) -> float:
    return max(0.0, min(1.0, (expectancy_r + 0.5) / 1.5)) * 100.0


def _trade_risk_amount(trade: Mapping[str, Any]) -> float:
    direct = _float(trade.get("risk_amount_usd") or trade.get("risk_usd"))
    if direct > 0:
        return direct
    for key in ("risk_context", "open_rationale"):
        nested = trade.get(key)
        if not isinstance(nested, Mapping):
            continue
        risk_context = nested.get("risk_context") if key == "open_rationale" else nested
        if isinstance(risk_context, Mapping):
            compiled = risk_context.get("compiled_order")
            if isinstance(compiled, Mapping):
                value = _float(compiled.get("risk_amount_usd"))
                if value > 0:
                    return value
    return 0.0


def _trade_actual_risk_pct(trade: Mapping[str, Any]) -> float | None:
    for key in ("actual_risk_pct_equity", "risk_pct_equity"):
        raw = trade.get(key)
        if raw is not None:
            value = _float(raw)
            return value if value >= 0 else None
    return None
