"""Contract tests for chronological strategy-team evaluation."""

from __future__ import annotations

from backtest.strategy_team_eval import (
    StrategyBacktestTrade,
    _aggregate_candles,
    _result_from_trades,
    _simulate_trade,
)
from market_features import Candle


def test_aggregate_candles_ignores_incomplete_future_group() -> None:
    candles = [
        Candle(index, 100 + index, 102 + index, 99 + index, 101 + index, 10)
        for index in range(5)
    ]

    aggregated = _aggregate_candles(candles, 4)

    assert len(aggregated) == 1
    assert aggregated[0].close == candles[3].close
    assert aggregated[0].high == max(item.high for item in candles[:4])


def test_backtest_gate_requires_sample_expectancy_pf_and_drawdown() -> None:
    trades = [
        StrategyBacktestTrade("momentum", "long", index, index + 1, 100, 98, 104, 104, 2, 3, 1.5, "take_profit")
        for index in range(50)
    ]

    result = _result_from_trades(
        "momentum",
        trades,
        starting_equity=200,
        final_equity=350,
        max_drawdown=10,
        peak_equity=350,
    )

    assert result.gate_passed is True
    assert result.expectancy_r > 0
    assert result.profit_factor == 2.0


def test_simulated_trade_keeps_adaptive_calibration_metadata() -> None:
    candles = [
        Candle(0, 100, 101, 99, 100, 10),
        Candle(1, 100, 103, 99.5, 102, 10),
    ]
    setup = {
        "direction": "long",
        "score": 74,
        "decision_zone": "gray",
        "decision_lane": "rules_plus_llm",
        "regime": "TRENDING_UP",
        "counterfactual_score_floor": 60,
        "levels": {"entry": 100, "stop_loss": 98, "take_profit": 102},
    }

    trade = _simulate_trade(
        candles,
        0,
        team_id="momentum",
        setup=setup,
        equity=200,
        target_risk_pct=0.03,
        fee_rate=0,
        slippage_bps=0,
        max_hold_bars=1,
    )

    assert trade is not None
    assert trade.rule_score == 74
    assert trade.decision_zone == "gray"
    assert trade.decision_lane == "rules_plus_llm"
    assert trade.evaluation_source == "backtest"
    assert trade.counterfactual_eligible is True
    assert trade.counterfactual_score_floor == 60
    assert trade.regime == "TRENDING_UP"
