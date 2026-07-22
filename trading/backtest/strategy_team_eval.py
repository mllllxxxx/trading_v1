"""Chronological strategy-team evaluation using the runtime feature engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

try:
    from auto.adaptive_hybrid import DecisionPolicy, load_decision_policy
except ImportError:  # pragma: no cover - direct test/script import fallback
    from adaptive_hybrid import DecisionPolicy, load_decision_policy  # type: ignore
from market_features import (
    Candle,
    classify_market_regime,
    compute_timeframe_features,
    compute_trend_confluence,
    evaluate_strategy_setup,
)


@dataclass(frozen=True)
class StrategyBacktestTrade:
    """One fee-aware chronological simulation result."""

    team_id: str
    side: str
    entry_index: int
    exit_index: int
    entry: float
    stop_loss: float
    take_profit: float
    exit_price: float
    risk_usd: float
    pnl_usd: float
    r_multiple: float
    exit_reason: str
    rule_score: float | None = None
    decision_zone: str | None = None
    decision_lane: str | None = None
    evaluation_source: str = "backtest"
    counterfactual_eligible: bool = True
    counterfactual_score_floor: float = 0.0
    regime: str | None = None


@dataclass(frozen=True)
class StrategyBacktestResult:
    """Metrics used by the demo rollout gate."""

    team_id: str
    trades: list[StrategyBacktestTrade]
    starting_equity: float
    final_equity: float
    total_return_pct: float
    winrate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_pct: float
    gate_passed: bool
    gate_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["trades"] = [asdict(trade) for trade in self.trades]
        return payload


def run_strategy_backtest(
    frame: pd.DataFrame,
    team_id: str,
    *,
    starting_equity: float = 200.0,
    target_risk_pct: float = 0.03,
    fee_rate: float = 0.0005,
    slippage_bps: float = 2.0,
    max_hold_bars: int = 192,
) -> StrategyBacktestResult:
    """Run one team on 15m OHLCV without using future bars for features."""
    candles = _candles_from_frame(frame)
    if len(candles) < 3_600:
        raise ValueError("strategy backtest requires at least 3600 15m candles")
    policy = load_decision_policy()
    equity = starting_equity
    peak = equity
    max_drawdown = 0.0
    trades: list[StrategyBacktestTrade] = []
    index = 3_359
    while index < len(candles) - 1:
        # Four-hour boundaries keep every 1H/4H aggregate fully closed.
        if (index + 1) % 16:
            index += 1
            continue
        visible = candles[: index + 1]
        one_hour = _aggregate_candles(visible, 4)
        four_hour = _aggregate_candles(visible, 16)
        if len(one_hour) < 210 or len(four_hour) < 210:
            index += 1
            continue
        features = {
            "15m": compute_timeframe_features(visible[-260:]),
            "1H": compute_timeframe_features(one_hour[-260:]),
            "4H": compute_timeframe_features(four_hour[-260:]),
        }
        regime, regime_evidence = classify_market_regime(features)
        snapshot = {
            "data_age_s": 0.0,
            "regime": regime,
            "regime_evidence": regime_evidence,
            "trend_confluence_score": compute_trend_confluence(features),
            "features": features,
        }
        recent = visible[-96:]
        quote_volume = sum(item.close * item.volume for item in recent)
        setup = evaluate_strategy_setup(
            snapshot,
            team_id,
            spread_bps=2.0,
            volume_usd_24h=quote_volume,
            strong_min_score=policy.strong_min_score,
            gray_min_score=policy.gray_min_score,
        )
        setup = _route_setup_with_canonical_policy(setup, policy)
        if not setup["eligible"]:
            index += 16
            continue
        trade = _simulate_trade(
            candles,
            index,
            team_id=team_id,
            setup=setup,
            equity=equity,
            target_risk_pct=target_risk_pct,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            max_hold_bars=max_hold_bars,
        )
        if trade is None:
            index += 16
            continue
        trades.append(trade)
        equity += trade.pnl_usd
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        index = max(index + 1, trade.exit_index + 1)
    return _result_from_trades(
        team_id,
        trades,
        starting_equity=starting_equity,
        final_equity=equity,
        max_drawdown=max_drawdown,
        peak_equity=peak,
    )


def _simulate_trade(
    candles: list[Candle],
    entry_index: int,
    *,
    team_id: str,
    setup: dict[str, Any],
    equity: float,
    target_risk_pct: float,
    fee_rate: float,
    slippage_bps: float,
    max_hold_bars: int,
) -> StrategyBacktestTrade | None:
    levels = setup["levels"]
    side = str(setup["direction"])
    entry = float(levels["entry"])
    stop = float(levels["stop_loss"])
    target = float(levels["take_profit"])
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return None
    slip = slippage_bps / 10_000.0
    filled_entry = entry * (1 + slip if side == "long" else 1 - slip)
    requested_risk = equity * min(max(target_risk_pct, 0.0), 0.05)
    units = requested_risk / stop_distance
    max_notional = equity * 0.60
    units = min(units, max_notional / filled_entry)
    risk_usd = units * abs(filled_entry - stop)
    if units <= 0 or risk_usd <= 0:
        return None
    end = min(len(candles), entry_index + max_hold_bars + 1)
    exit_price = candles[end - 1].close
    exit_reason = "timeout"
    exit_index = end - 1
    for future_index in range(entry_index + 1, end):
        candle = candles[future_index]
        if side == "long":
            sl_hit = candle.low <= stop
            tp_hit = candle.high >= target
        else:
            sl_hit = candle.high >= stop
            tp_hit = candle.low <= target
        if sl_hit:
            exit_price = stop * (1 - slip if side == "long" else 1 + slip)
            exit_reason = "stop_loss"
            exit_index = future_index
            break
        if tp_hit:
            exit_price = target * (1 - slip if side == "long" else 1 + slip)
            exit_reason = "take_profit"
            exit_index = future_index
            break
    gross = (
        (exit_price - filled_entry) * units
        if side == "long"
        else (filled_entry - exit_price) * units
    )
    fees = (filled_entry + exit_price) * units * fee_rate
    pnl = gross - fees
    return StrategyBacktestTrade(
        team_id=team_id,
        side=side,
        entry_index=entry_index,
        exit_index=exit_index,
        entry=filled_entry,
        stop_loss=stop,
        take_profit=target,
        exit_price=exit_price,
        risk_usd=risk_usd,
        pnl_usd=pnl,
        r_multiple=pnl / risk_usd,
        exit_reason=exit_reason,
        rule_score=float(setup["score"]),
        decision_zone=str(setup["decision_zone"]),
        decision_lane=str(setup["decision_lane"]),
        counterfactual_score_floor=float(setup["counterfactual_score_floor"]),
        regime=str(setup.get("regime")) if setup.get("regime") is not None else None,
    )


def _route_setup_with_canonical_policy(
    setup: dict[str, Any],
    policy: DecisionPolicy,
) -> dict[str, Any]:
    """Route a scored backtest setup with the canonical adaptive thresholds."""
    routed = dict(setup)
    score = max(0.0, min(100.0, float(routed.get("score", 0.0))))
    direction = str(routed.get("direction") or "neutral")
    hard_blockers = list(routed.get("hard_blockers") or routed.get("blockers") or [])
    if hard_blockers or direction not in {"long", "short"} or score < policy.gray_min_score:
        zone = "reject"
        lane = policy.reject_lane
    elif score >= policy.strong_min_score:
        zone = "strong"
        lane = policy.strong_lane
    else:
        zone = "gray"
        lane = policy.gray_lane
    routed.update(
        {
            "score": score,
            "decision_zone": zone,
            "decision_lane": lane,
            "eligible": zone != "reject",
            "counterfactual_score_floor": policy.gray_min_score,
        }
    )
    return routed


def _result_from_trades(
    team_id: str,
    trades: list[StrategyBacktestTrade],
    *,
    starting_equity: float,
    final_equity: float,
    max_drawdown: float,
    peak_equity: float,
) -> StrategyBacktestResult:
    wins = [trade for trade in trades if trade.pnl_usd > 0]
    losses = [trade for trade in trades if trade.pnl_usd <= 0]
    gross_profit = sum(trade.pnl_usd for trade in wins)
    gross_loss = abs(sum(trade.pnl_usd for trade in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (2.0 if gross_profit > 0 else 0.0)
    expectancy = sum(trade.r_multiple for trade in trades) / len(trades) if trades else 0.0
    drawdown_pct = max_drawdown / peak_equity if peak_equity > 0 else 0.0
    reasons: list[str] = []
    if len(trades) < 50:
        reasons.append("fewer_than_50_closed_simulations")
    if expectancy <= 0:
        reasons.append("non_positive_expectancy_r")
    if profit_factor <= 1.05:
        reasons.append("profit_factor_not_above_1_05")
    if drawdown_pct > 0.20:
        reasons.append("max_drawdown_above_20_pct")
    return StrategyBacktestResult(
        team_id=team_id,
        trades=trades,
        starting_equity=starting_equity,
        final_equity=final_equity,
        total_return_pct=(final_equity - starting_equity) / starting_equity * 100,
        winrate=len(wins) / len(trades) if trades else 0.0,
        expectancy_r=expectancy,
        profit_factor=profit_factor,
        max_drawdown_pct=drawdown_pct,
        gate_passed=not reasons,
        gate_reasons=reasons,
    )


def _candles_from_frame(frame: pd.DataFrame) -> list[Candle]:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {', '.join(sorted(missing))}")
    output: list[Candle] = []
    for timestamp, row in frame.sort_index().iterrows():
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        output.append(
            Candle(
                timestamp_ms=int(ts.timestamp() * 1000),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return output


def _aggregate_candles(candles: list[Candle], factor: int) -> list[Candle]:
    """Aggregate only complete groups, preserving chronological boundaries."""
    complete = len(candles) - len(candles) % factor
    output: list[Candle] = []
    for start in range(0, complete, factor):
        group = candles[start:start + factor]
        output.append(
            Candle(
                timestamp_ms=group[0].timestamp_ms,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
            )
        )
    return output
