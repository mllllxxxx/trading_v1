"""Tests for confirmed-candle features and independent team setups."""

from __future__ import annotations

from adaptive_hybrid import load_decision_policy
from market_features import Candle, compute_timeframe_features, evaluate_strategy_setup


def _timeframe(
    *,
    close: float = 100.0,
    previous_close: float = 99.8,
    trend: str = "mixed",
    adx: float = 18.0,
    rsi: float = 50.0,
    bb_z: float = 0.0,
    previous_bb_z: float = 0.0,
    distance: float = 0.3,
    compression: float = 0.2,
    volume_z: float = 1.5,
) -> dict:
    return {
        "close": close,
        "previous_close": previous_close,
        "ema20": 100.0,
        "ema50": 101.0 if trend == "up" else 99.0,
        "ema200": 99.0 if trend == "up" else 101.0,
        "ema50_slope_pct_5": 1.0 if trend == "up" else -1.0 if trend == "down" else 0.0,
        "adx14": adx,
        "atr14": 4.0,
        "atr_pct": 4.0,
        "atr_percentile": 0.5,
        "rsi14": rsi,
        "bb_mid": 100.0,
        "bb_upper": 108.0,
        "bb_lower": 92.0,
        "bb_z": bb_z,
        "previous_bb_z": previous_bb_z,
        "bb_width_pct": 8.0,
        "bb_width_percentile": 0.4,
        "prior_compression_percentile": compression,
        "donchian20_high": 110.0,
        "donchian20_low": 90.0,
        "volume_z20": volume_z,
        "efficiency_ratio20": 0.2,
        "distance_ema20_atr": distance,
        "swing_high10": 104.0,
        "swing_low10": 96.0,
        "trend": trend,
    }


def _snapshot(regime: str, one: dict, fifteen: dict, four: dict) -> dict:
    return {
        "data_age_s": 30.0,
        "regime": regime,
        "features": {"1H": one, "15m": fifteen, "4H": four},
    }


def test_confirmed_15m_candle_remains_fresh_during_normal_bar_cycle() -> None:
    setup = evaluate_strategy_setup(
        {
            **_snapshot(
                "TRENDING_UP",
                _timeframe(trend="up", adx=32, distance=0.4),
                _timeframe(close=101, previous_close=100.5, trend="up"),
                _timeframe(trend="up", adx=30),
            ),
            "data_age_s": 900.0,
        },
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is True


def test_strategy_setup_uses_injected_canonical_zone_thresholds() -> None:
    snapshot = _snapshot(
        "TRENDING_UP",
        _timeframe(trend="up", adx=32, distance=0.4),
        _timeframe(close=101, previous_close=100.5, trend="up"),
        _timeframe(trend="up", adx=30),
    )

    default_setup = evaluate_strategy_setup(
        snapshot,
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )
    reviewed_setup = evaluate_strategy_setup(
        snapshot,
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
        strong_min_score=75,
        gray_min_score=55,
    )

    assert default_setup["decision_zone"] == "gray"
    assert reviewed_setup["decision_zone"] == "strong"
    assert reviewed_setup["score"] == default_setup["score"]


def test_confirmed_candle_older_than_freshness_limit_is_blocked() -> None:
    setup = evaluate_strategy_setup(
        {
            **_snapshot(
                "TRENDING_UP",
                _timeframe(trend="up", adx=32, distance=0.4),
                _timeframe(close=101, previous_close=100.5, trend="up"),
                _timeframe(trend="up", adx=30),
            ),
            "data_age_s": 1081.0,
        },
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is False
    assert "stale_confirmed_candles" in setup["blockers"]


def test_mean_reversion_passes_in_range_with_returning_stretch() -> None:
    one = _timeframe(adx=16, rsi=29, bb_z=-2.1)
    fifteen = _timeframe(close=101, previous_close=100, bb_z=-1.5, previous_bb_z=-2.0)
    setup = evaluate_strategy_setup(
        _snapshot("RANGING", one, fifteen, _timeframe()),
        "mean_reversion",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is True
    assert setup["direction"] == "long"
    assert setup["setup_confluence_score"] > 2
    assert setup["levels"]["stop_loss"] < setup["levels"]["entry"] < setup["levels"]["take_profit"]


def test_mean_reversion_trend_conflict_lowers_score_without_hard_blocking() -> None:
    one = _timeframe(adx=31, rsi=29, bb_z=-2.1, trend="down")
    fifteen = _timeframe(close=101, previous_close=100, bb_z=-1.5, previous_bb_z=-2.0)
    setup = evaluate_strategy_setup(
        _snapshot("TRENDING_DOWN", one, fifteen, _timeframe(trend="down")),
        "mean_reversion",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is True
    assert "mean_reversion_requires_ranging_regime" in setup["conflicts"]
    assert setup["decision_zone"] in {"gray", "reject"}
    assert setup["confidence_calibrated"] is False


def test_strategy_setup_routes_hard_data_failure_to_reject() -> None:
    setup = evaluate_strategy_setup(
        {
            **_snapshot(
                "TRENDING_UP",
                _timeframe(trend="up", adx=32, distance=0.4),
                _timeframe(close=101, previous_close=100.5, trend="up"),
                _timeframe(trend="up", adx=30),
            ),
            "data_age_s": 1081.0,
        },
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["decision_zone"] == "reject"
    assert "stale_confirmed_candles" in setup["hard_blockers"]


def test_momentum_requires_trend_adx_and_non_chasing_entry() -> None:
    setup = evaluate_strategy_setup(
        _snapshot(
            "TRENDING_UP",
            _timeframe(trend="up", adx=32, distance=0.4),
            _timeframe(close=101, previous_close=100.5, trend="up"),
            _timeframe(trend="up", adx=30),
        ),
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is True
    assert setup["direction"] == "long"


def test_volatility_breakout_requires_compression_volume_and_near_retest() -> None:
    one = _timeframe(close=111, previous_close=109, trend="up", compression=0.2, volume_z=1.5)
    one["donchian20_high"] = 110.0
    setup = evaluate_strategy_setup(
        _snapshot("HIGH_VOLATILITY", one, _timeframe(close=111, trend="up"), _timeframe(trend="up")),
        "volatility_breakout",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )

    assert setup["eligible"] is True
    assert setup["direction"] == "long"


def test_continuous_shadow_score_moves_smoothly_across_numeric_boundary() -> None:
    experiment = load_decision_policy().shadow_scoring_experiment
    assert experiment is not None

    def evaluate(adx: float) -> dict:
        return evaluate_strategy_setup(
            _snapshot(
                "TRENDING_UP",
                _timeframe(trend="up", adx=adx, distance=0.4),
                _timeframe(close=101, previous_close=100.5, trend="up"),
                _timeframe(trend="up", adx=30),
            ),
            "momentum",
            spread_bps=2.0,
            volume_usd_24h=500_000_000,
            shadow_scoring_experiment=experiment.to_dict(),
        )

    nearer = evaluate(24.99)
    farther = evaluate(24.98)
    nearer_v2 = nearer["experimental_scores"]["continuous_conflict_v2"]
    farther_v2 = farther["experimental_scores"]["continuous_conflict_v2"]

    assert nearer["score"] == farther["score"] == 64
    assert nearer["decision_zone"] == farther["decision_zone"] == "gray"
    assert 0 < nearer_v2["score"] - farther_v2["score"] < 0.1
    assert nearer_v2["active_for_routing"] is False


def test_continuous_shadow_score_keeps_binary_conflict_at_full_penalty() -> None:
    experiment = load_decision_policy().shadow_scoring_experiment
    assert experiment is not None
    setup = evaluate_strategy_setup(
        _snapshot(
            "TRENDING_UP",
            _timeframe(trend="down", adx=32, distance=0.4),
            _timeframe(close=101, previous_close=100.5, trend="up"),
            _timeframe(trend="up", adx=30),
        ),
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
        shadow_scoring_experiment=experiment.to_dict(),
    )

    experiment_score = setup["experimental_scores"]["continuous_conflict_v2"]
    penalty = next(
        item
        for item in experiment_score["conflict_penalties"]
        if item["conflict_id"] == "momentum_one_hour_trend_mismatch"
    )

    assert penalty["severity"] == 1.0
    assert penalty["penalty"] == 12.0


def test_continuous_shadow_score_does_not_change_active_v1_route() -> None:
    experiment = load_decision_policy().shadow_scoring_experiment
    assert experiment is not None
    snapshot = _snapshot(
        "TRENDING_UP",
        _timeframe(trend="up", adx=24.5, distance=0.6),
        _timeframe(close=101, previous_close=100.5, trend="up"),
        _timeframe(trend="up", adx=30),
    )

    active_only = evaluate_strategy_setup(
        snapshot,
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
    )
    with_shadow = evaluate_strategy_setup(
        snapshot,
        "momentum",
        spread_bps=2.0,
        volume_usd_24h=500_000_000,
        shadow_scoring_experiment=experiment.to_dict(),
    )

    for key in ("score", "confidence", "decision_zone", "eligible", "conflicts"):
        assert with_shadow[key] == active_only[key]
    assert "experimental_scores" not in active_only
    assert with_shadow["experimental_scores"]["continuous_conflict_v2"][
        "active_for_routing"
    ] is False


def test_feature_computation_uses_stable_positive_windows() -> None:
    candles = [
        Candle(
            timestamp_ms=index * 3_600_000,
            open=100 + index * 0.1,
            high=101 + index * 0.1,
            low=99 + index * 0.1,
            close=100.2 + index * 0.1 + (0.2 if index % 3 == 0 else 0),
            volume=1_000 + index,
        )
        for index in range(220)
    ]

    features = compute_timeframe_features(candles)

    assert features["atr14"] > 0
    assert 0 <= features["rsi14"] <= 100
    assert features["donchian20_high"] > features["donchian20_low"]
