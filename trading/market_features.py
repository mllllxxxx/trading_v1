"""Confirmed OKX candle features and strategy-specific setup evaluation."""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any, Callable, Iterable, Mapping


JsonFetcher = Callable[[str], dict[str, Any]]


class MarketFeatureError(RuntimeError):
    """Raised when confirmed candle evidence cannot be built safely."""


@dataclass(frozen=True)
class Candle:
    """One confirmed OHLCV candle."""

    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


_BAR_SECONDS = {"15m": 900, "1H": 3600, "4H": 14_400}
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.RLock()


def max_confirmed_candle_age_s() -> float:
    """Return the trigger-candle freshness limit shared by scan and promotion."""
    raw = os.getenv("STRATEGY_MAX_CONFIRMED_CANDLE_AGE_S", "1080")
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 1080.0


def build_market_feature_snapshot(
    symbol: str,
    *,
    fetcher: JsonFetcher | None = None,
    now: datetime | None = None,
    cache_ttl_s: int = 60,
) -> dict[str, Any]:
    """Return an MTF snapshot from confirmed 15m, 1H, and 4H OKX candles."""
    normalized = _swap_symbol(symbol)
    cache_key = normalized
    now_dt = now or datetime.now(timezone.utc)
    now_ts = now_dt.timestamp()
    if fetcher is None and cache_ttl_s > 0:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and now_ts - cached[0] < cache_ttl_s:
                return dict(cached[1])

    series = {
        "15m": fetch_confirmed_candles(normalized, "15m", 220, fetcher=fetcher),
        "1H": fetch_confirmed_candles(normalized, "1H", 260, fetcher=fetcher),
        "4H": fetch_confirmed_candles(normalized, "4H", 260, fetcher=fetcher),
    }
    for label, candles in series.items():
        if len(candles) < 210:
            raise MarketFeatureError(f"{label}_confirmed_candles_insufficient:{len(candles)}")

    features = {label: compute_timeframe_features(candles) for label, candles in series.items()}
    regime, regime_evidence = classify_market_regime(features)
    trend_confluence = compute_trend_confluence(features)
    latest_close_ms = max(
        candles[-1].timestamp_ms + _BAR_SECONDS[label] * 1000
        for label, candles in series.items()
    )
    data_timestamp = datetime.fromtimestamp(latest_close_ms / 1000, tz=timezone.utc)
    age_s = max(0.0, (now_dt - data_timestamp).total_seconds())
    snapshot = {
        "symbol": normalized.removesuffix("-SWAP"),
        "source": "okx_confirmed_candles",
        "generated_at": now_dt.isoformat(timespec="seconds"),
        "data_timestamp_utc": data_timestamp.isoformat(timespec="seconds"),
        "data_age_s": round(age_s, 3),
        "regime": regime,
        "regime_evidence": regime_evidence,
        "trend_confluence_score": trend_confluence,
        "features": features,
    }
    if fetcher is None and cache_ttl_s > 0:
        with _CACHE_LOCK:
            _CACHE[cache_key] = (now_ts, dict(snapshot))
    return snapshot


def fetch_confirmed_candles(
    symbol: str,
    bar: str,
    limit: int,
    *,
    fetcher: JsonFetcher | None = None,
) -> list[Candle]:
    """Fetch closed candles from the OKX public market endpoint."""
    if bar not in _BAR_SECONDS:
        raise MarketFeatureError(f"unsupported_bar:{bar}")
    params = urllib.parse.urlencode(
        {"instId": _swap_symbol(symbol), "bar": bar, "limit": str(max(1, min(limit, 300)))}
    )
    url = f"https://www.okx.com/api/v5/market/candles?{params}"
    try:
        payload = (fetcher or _fetch_json)(url)
    except Exception as exc:  # noqa: BLE001
        raise MarketFeatureError(f"okx_candles_failed:{bar}:{exc}") from exc
    if str(payload.get("code", "0")) != "0":
        raise MarketFeatureError(f"okx_candles_rejected:{bar}:{payload.get('msg', '')}")
    parsed: list[Candle] = []
    for row in payload.get("data", []):
        if not isinstance(row, list) or len(row) < 6:
            continue
        if len(row) >= 9 and str(row[8]) != "1":
            continue
        try:
            candle = Candle(
                timestamp_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        except (TypeError, ValueError):
            continue
        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            continue
        parsed.append(candle)
    parsed.sort(key=lambda item: item.timestamp_ms)
    deduped = {item.timestamp_ms: item for item in parsed}
    return [deduped[key] for key in sorted(deduped)]


def compute_timeframe_features(candles: list[Candle]) -> dict[str, float | str]:
    """Compute deterministic indicators without reading future candles."""
    if len(candles) < 210:
        raise MarketFeatureError("feature_window_requires_210_candles")
    closes = [item.close for item in candles]
    highs = [item.high for item in candles]
    lows = [item.low for item in candles]
    volumes = [item.volume for item in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    atr_values = _atr_series(candles, 14)
    adx_values = _adx_series(candles, 14)
    rsi_values = _rsi_series(closes, 14)
    bb_mid, bb_upper, bb_lower, bb_width, bb_z = _bollinger_series(closes, 20)
    last = closes[-1]
    prev = closes[-2]
    atr = atr_values[-1]
    prior_high = max(highs[-21:-1])
    prior_low = min(lows[-21:-1])
    volume_window = volumes[-20:]
    vol_std = pstdev(volume_window) if len(volume_window) > 1 else 0.0
    volume_z = (volumes[-1] - fmean(volume_window)) / vol_std if vol_std > 0 else 0.0
    atr_valid = [value for value in atr_values[-100:] if value > 0]
    width_valid = [value for value in bb_width[-100:] if value > 0]
    atr_percentile = _percentile_rank(atr_valid, atr)
    width_percentile = _percentile_rank(width_valid, bb_width[-1])
    prior_width_percentile = min(
        (_percentile_rank(width_valid, value) for value in bb_width[-11:-1] if value > 0),
        default=1.0,
    )
    efficiency = _efficiency_ratio(closes[-21:])
    ema50_slope = _pct_change(ema50[-6], ema50[-1])
    trend = "up" if ema50[-1] > ema200[-1] and ema50_slope > 0 else (
        "down" if ema50[-1] < ema200[-1] and ema50_slope < 0 else "mixed"
    )
    return {
        "close": last,
        "previous_close": prev,
        "ema20": ema20[-1],
        "ema50": ema50[-1],
        "ema200": ema200[-1],
        "ema50_slope_pct_5": ema50_slope,
        "adx14": adx_values[-1],
        "atr14": atr,
        "atr_pct": atr / last * 100 if last > 0 else 0.0,
        "atr_percentile": atr_percentile,
        "rsi14": rsi_values[-1],
        "bb_mid": bb_mid[-1],
        "bb_upper": bb_upper[-1],
        "bb_lower": bb_lower[-1],
        "bb_z": bb_z[-1],
        "previous_bb_z": bb_z[-2],
        "bb_width_pct": bb_width[-1],
        "bb_width_percentile": width_percentile,
        "prior_compression_percentile": prior_width_percentile,
        "donchian20_high": prior_high,
        "donchian20_low": prior_low,
        "volume_z20": volume_z,
        "efficiency_ratio20": efficiency,
        "distance_ema20_atr": abs(last - ema20[-1]) / atr if atr > 0 else 99.0,
        "swing_high10": max(highs[-10:]),
        "swing_low10": min(lows[-10:]),
        "trend": trend,
    }


def classify_market_regime(features: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """Classify regime from independent 1H/4H trend and volatility evidence."""
    one = features["1H"]
    four = features["4H"]
    adx = float(one["adx14"])
    efficiency = float(one["efficiency_ratio20"])
    atr_percentile = float(one["atr_percentile"])
    if adx >= 25 and four["trend"] == "up" and float(four["ema50_slope_pct_5"]) > 0:
        regime = "TRENDING_UP"
    elif adx >= 25 and four["trend"] == "down" and float(four["ema50_slope_pct_5"]) < 0:
        regime = "TRENDING_DOWN"
    elif adx <= 20 and efficiency <= 0.35:
        regime = "RANGING"
    elif atr_percentile >= 0.85:
        regime = "HIGH_VOLATILITY"
    else:
        regime = "MIXED"
    return regime, {
        "one_hour_adx14": round(adx, 4),
        "one_hour_efficiency_ratio20": round(efficiency, 4),
        "one_hour_atr_percentile": round(atr_percentile, 4),
        "four_hour_trend": four["trend"],
        "four_hour_ema50_slope_pct_5": round(float(four["ema50_slope_pct_5"]), 6),
    }


def compute_trend_confluence(features: dict[str, dict[str, Any]]) -> float:
    """Return signed MTF trend evidence in the legacy -5..5 range."""
    weights = {"15m": 0.8, "1H": 1.0, "4H": 1.3}
    score = 0.0
    for label, weight in weights.items():
        trend = str(features[label]["trend"])
        score += weight if trend == "up" else -weight if trend == "down" else 0.0
    return round(score, 4)


def evaluate_strategy_setup(
    snapshot: dict[str, Any],
    team_id: str,
    *,
    spread_bps: float | None,
    volume_usd_24h: float,
    strong_min_score: float = 80.0,
    gray_min_score: float = 60.0,
    shadow_scoring_experiment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one canonical team setup from a shared MTF snapshot."""
    strong_min = float(strong_min_score)
    gray_min = float(gray_min_score)
    if not 0 <= gray_min < strong_min <= 100:
        raise ValueError("decision zone thresholds are invalid")
    features = snapshot["features"]
    one = features["1H"]
    fifteen = features["15m"]
    four = features["4H"]
    regime = str(snapshot["regime"])
    hard_blockers: list[str] = []
    reasons: list[str] = []
    if snapshot.get("data_age_s", 9999) > max_confirmed_candle_age_s():
        hard_blockers.append("stale_confirmed_candles")
    if spread_bps is None:
        hard_blockers.append("missing_spread")
    elif spread_bps > 35:
        hard_blockers.append("spread_too_wide")
    if volume_usd_24h < 10_000_000:
        hard_blockers.append("liquidity_too_thin")

    if team_id == "mean_reversion":
        setup = _mean_reversion_setup(one, fifteen, regime)
    elif team_id == "volatility_breakout":
        setup = _volatility_breakout_setup(one, fifteen, four)
    elif team_id == "momentum":
        setup = _momentum_setup(one, fifteen, four, regime)
    else:
        setup = _berkshire_setup(one, fifteen, four, regime)
    reasons.extend(setup["reasons"])
    direction = str(setup["direction"])
    conflicts = list(setup["conflicts"])
    if direction == "neutral":
        conflicts.append("strategy_setup_not_confirmed")
    hard_blockers = list(dict.fromkeys(hard_blockers))
    conflicts = list(dict.fromkeys(conflicts))
    conflict_penalty = min(48, 12 * len(conflicts))
    score = max(0, int(setup["score"]) - conflict_penalty)
    if hard_blockers or direction == "neutral":
        decision_zone = "reject"
    elif score >= strong_min:
        decision_zone = "strong"
    elif score >= gray_min:
        decision_zone = "gray"
    else:
        decision_zone = "reject"
    eligible = direction in {"long", "short"} and not hard_blockers and decision_zone != "reject"
    confidence = round(score / 100, 2)
    levels = _strategy_levels(team_id, direction, one, fifteen)
    signed_confluence = float(setup["confluence"])
    score_components = {
        "base_setup_quality": round(float(setup["score"]) / 100.0, 4),
        "strategy_alignment": round(max(0.0, 1.0 - (0.12 * len(conflicts))), 4),
        "data_safety": 0.0 if hard_blockers else 1.0,
    }
    setup_quality = dict(setup["quality"])
    setup_quality.update(
        {
            "rule_score": score,
            "score_components": score_components,
            "conflicts": conflicts,
            "hard_blockers": hard_blockers,
            "decision_zone": decision_zone,
            "confidence_calibrated": False,
        }
    )
    result = {
        "direction": direction,
        "eligible": eligible,
        "score": score,
        "confidence": confidence,
        "blockers": hard_blockers,
        "hard_blockers": hard_blockers,
        "conflicts": conflicts,
        "reasons": reasons,
        "levels": levels,
        "setup_quality": setup_quality,
        "score_components": score_components,
        "decision_zone": decision_zone,
        "confidence_calibrated": False,
        "setup_confluence_score": signed_confluence,
        "regime": regime,
    }
    if shadow_scoring_experiment is not None:
        try:
            experimental_score = _continuous_conflict_shadow_score(
                team_id=team_id,
                direction=direction,
                conflicts=conflicts,
                one=one,
                fifteen=fifteen,
                experiment=shadow_scoring_experiment,
            )
        except (KeyError, TypeError, ValueError):
            experimental_score = None
        if experimental_score is not None:
            result["experimental_scores"] = {
                str(shadow_scoring_experiment["experiment_id"]): experimental_score
            }
    return result


def _continuous_conflict_shadow_score(
    *,
    team_id: str,
    direction: str,
    conflicts: list[str],
    one: Mapping[str, Any],
    fifteen: Mapping[str, Any],
    experiment: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Calculate the observe-only continuous score without touching V1 routing."""
    if (
        str(experiment["experiment_id"]) != "continuous_conflict_v2"
        or str(experiment["mode"]) != "shadow_only"
        or str(experiment["score_version"]) != "continuous_base_and_severity_v2"
        or bool(experiment["active_for_routing"])
    ):
        return None
    max_total_penalty = float(experiment["max_total_penalty"])
    max_penalty_per_conflict = float(experiment["max_penalty_per_conflict"])
    severity_scales = experiment["severity_scales"]
    if not isinstance(severity_scales, Mapping):
        return None

    base_score = _continuous_base_score(team_id, direction, one, fifteen)
    penalty_rows: list[dict[str, Any]] = []
    for conflict_id in conflicts:
        severity, evidence = _continuous_conflict_severity(
            conflict_id,
            direction=direction,
            one=one,
            severity_scales=severity_scales,
        )
        penalty = min(max_penalty_per_conflict, severity * max_penalty_per_conflict)
        penalty_rows.append(
            {
                "conflict_id": conflict_id,
                "kind": "continuous" if evidence else "binary",
                "severity": round(severity, 6),
                "penalty": round(penalty, 6),
                **evidence,
            }
        )
    total_penalty = min(max_total_penalty, sum(row["penalty"] for row in penalty_rows))
    score = max(0.0, min(100.0, base_score - total_penalty))
    return {
        "mode": "shadow_only",
        "score_version": "continuous_base_and_severity_v2",
        "score": round(score, 4),
        "base_score": round(base_score, 4),
        "total_penalty": round(total_penalty, 4),
        "conflict_penalties": penalty_rows,
        "active_for_routing": False,
    }


def _continuous_base_score(
    team_id: str,
    direction: str,
    one: Mapping[str, Any],
    fifteen: Mapping[str, Any],
) -> float:
    adx = float(one["adx14"])
    if team_id == "momentum":
        reclaim = (
            direction == "long"
            and float(fifteen["previous_close"]) <= float(fifteen["ema20"])
            < float(fifteen["close"])
        ) or (
            direction == "short"
            and float(fifteen["previous_close"]) >= float(fifteen["ema20"])
            > float(fifteen["close"])
        )
        score = 76 + min(12.0, max(0.0, (adx - 25.0) / 3.0)) + (4 if reclaim else 0)
    elif team_id == "mean_reversion":
        bb_z = float(one["bb_z"])
        returning = (
            direction == "long"
            and float(fifteen["close"]) > float(fifteen["previous_close"])
            and abs(float(fifteen["bb_z"])) <= abs(float(fifteen["previous_bb_z"]))
        ) or (
            direction == "short"
            and float(fifteen["close"]) < float(fifteen["previous_close"])
            and abs(float(fifteen["bb_z"])) <= abs(float(fifteen["previous_bb_z"]))
        )
        score = 78 + min(12.0, max(abs(bb_z) - 1.8, 0.0) * 10.0) + (4 if returning else 0)
    elif team_id == "volatility_breakout":
        score = 78 + min(10.0, max(float(one["volume_z20"]) - 1.0, 0.0) * 4.0)
    else:
        score = 74 + min(12.0, max(0.0, adx / 5.0))
    return max(0.0, min(96.0, score))


def _continuous_conflict_severity(
    conflict_id: str,
    *,
    direction: str,
    one: Mapping[str, Any],
    severity_scales: Mapping[str, Any],
) -> tuple[float, dict[str, Any]]:
    observed: float | None = None
    boundary: float | None = None
    distance = 0.0
    if conflict_id == "momentum_adx_below_25":
        observed, boundary = float(one["adx14"]), 25.0
        distance = boundary - observed
    elif conflict_id == "momentum_late_chase_over_0_5_atr":
        observed, boundary = float(one["distance_ema20_atr"]), 0.5
        distance = observed - boundary
    elif conflict_id == "mean_reversion_adx_above_20":
        observed, boundary = float(one["adx14"]), 20.0
        distance = observed - boundary
    elif conflict_id == "breakout_prior_compression_missing":
        observed, boundary = float(one["prior_compression_percentile"]), 0.30
        distance = observed - boundary
    elif conflict_id == "breakout_volume_z_below_1":
        observed, boundary = float(one["volume_z20"]), 1.0
        distance = boundary - observed
    elif conflict_id == "breakout_retest_distance_over_0_5_atr":
        close = float(one["close"])
        level = (
            float(one["donchian20_high"])
            if direction == "long"
            else float(one["donchian20_low"])
        )
        atr = float(one["atr14"])
        observed = abs(close - level) / atr if atr > 0 else 1.5
        boundary = 0.5
        distance = observed - boundary
    if observed is None or boundary is None:
        return 1.0, {}
    scale = float(severity_scales[conflict_id])
    severity = max(0.0, min(1.0, distance / scale))
    return severity, {
        "observed": round(observed, 6),
        "boundary": boundary,
        "distance_beyond_boundary": round(max(0.0, distance), 6),
        "severity_scale": scale,
    }


def _berkshire_setup(one: dict[str, Any], fifteen: dict[str, Any], four: dict[str, Any], regime: str) -> dict[str, Any]:
    direction = str(four["trend"])
    conflicts: list[str] = []
    if direction not in {"up", "down"}:
        direction = "neutral"
        conflicts.append("four_hour_trend_missing")
    if direction != "neutral" and one["trend"] != direction:
        conflicts.append("one_hour_confirmation_missing")
    if regime in {"RANGING", "MIXED"}:
        conflicts.append("quality_directional_regime_mismatch")
    side = "long" if direction == "up" else "short" if direction == "down" else "neutral"
    score = 74 + min(12, int(float(one["adx14"]) / 5))
    return _setup_result(side, conflicts, score, [f"4H and 1H directional quality evidence: {direction}."], one, fifteen)


def _momentum_setup(one: dict[str, Any], fifteen: dict[str, Any], four: dict[str, Any], regime: str) -> dict[str, Any]:
    direction = str(four["trend"])
    conflicts: list[str] = []
    if direction not in {"up", "down"}:
        conflicts.append("momentum_four_hour_trend_missing")
    if one["trend"] != direction:
        conflicts.append("momentum_one_hour_trend_mismatch")
    if float(one["adx14"]) < 25:
        conflicts.append("momentum_adx_below_25")
    reclaim = (
        direction == "up" and float(fifteen["previous_close"]) <= float(fifteen["ema20"]) < float(fifteen["close"])
    ) or (
        direction == "down" and float(fifteen["previous_close"]) >= float(fifteen["ema20"]) > float(fifteen["close"])
    )
    pullback = float(one["distance_ema20_atr"]) <= 0.5 or reclaim
    if not pullback:
        conflicts.append("momentum_late_chase_over_0_5_atr")
    if regime not in {"TRENDING_UP", "TRENDING_DOWN"}:
        conflicts.append("momentum_regime_mismatch")
    side = "long" if direction == "up" else "short" if direction == "down" else "neutral"
    score = 76 + min(12, int((float(one["adx14"]) - 25) / 3)) + (4 if reclaim else 0)
    return _setup_result(side, conflicts, score, [f"Momentum {direction} with ADX {float(one['adx14']):.1f} and pullback/reclaim evidence."], one, fifteen)


def _mean_reversion_setup(one: dict[str, Any], fifteen: dict[str, Any], regime: str) -> dict[str, Any]:
    conflicts: list[str] = []
    if regime != "RANGING":
        conflicts.append("mean_reversion_requires_ranging_regime")
    if float(one["adx14"]) > 20:
        conflicts.append("mean_reversion_adx_above_20")
    bb_z = float(one["bb_z"])
    rsi = float(one["rsi14"])
    if bb_z <= -1.8 or rsi <= 32:
        side = "long"
    elif bb_z >= 1.8 or rsi >= 68:
        side = "short"
    else:
        side = "neutral"
        conflicts.append("mean_reversion_stretch_missing")
    returning = (
        side == "long"
        and float(fifteen["close"]) > float(fifteen["previous_close"])
        and abs(float(fifteen["bb_z"])) <= abs(float(fifteen["previous_bb_z"]))
    ) or (
        side == "short"
        and float(fifteen["close"]) < float(fifteen["previous_close"])
        and abs(float(fifteen["bb_z"])) <= abs(float(fifteen["previous_bb_z"]))
    )
    if side != "neutral" and not returning:
        conflicts.append("mean_reversion_return_to_range_missing")
    score = 78 + min(12, int(max(abs(bb_z) - 1.8, 0) * 10)) + (4 if returning else 0)
    return _setup_result(side, conflicts, score, [f"Range stretch bb_z={bb_z:.2f}, RSI={rsi:.1f}, returning={returning}."], one, fifteen)


def _volatility_breakout_setup(one: dict[str, Any], fifteen: dict[str, Any], four: dict[str, Any]) -> dict[str, Any]:
    conflicts: list[str] = []
    close = float(one["close"])
    high = float(one["donchian20_high"])
    low = float(one["donchian20_low"])
    if close > high:
        side = "long"
        level = high
    elif close < low:
        side = "short"
        level = low
    else:
        side = "neutral"
        level = close
        conflicts.append("breakout_donchian_break_missing")
    if float(one["prior_compression_percentile"]) > 0.30:
        conflicts.append("breakout_prior_compression_missing")
    if float(one["volume_z20"]) < 1.0:
        conflicts.append("breakout_volume_z_below_1")
    atr = float(one["atr14"])
    if side != "neutral" and (atr <= 0 or abs(close - level) / atr > 0.5):
        conflicts.append("breakout_retest_distance_over_0_5_atr")
    if (side == "long" and four["trend"] == "down") or (side == "short" and four["trend"] == "up"):
        conflicts.append("breakout_four_hour_opposition")
    score = 78 + min(10, int(max(float(one["volume_z20"]) - 1, 0) * 4))
    return _setup_result(side, conflicts, score, [f"Donchian breakout with volume z={float(one['volume_z20']):.2f}."], one, fifteen)


def _setup_result(
    side: str,
    conflicts: list[str],
    score: int,
    reasons: list[str],
    one: dict[str, Any],
    fifteen: dict[str, Any],
) -> dict[str, Any]:
    signed = 0.0 if side == "neutral" else (2.8 if side == "long" else -2.8)
    return {
        "direction": side,
        "conflicts": conflicts,
        "score": max(0, min(96, score)),
        "reasons": reasons,
        "confluence": signed,
        "quality": {
            "one_hour_adx14": round(float(one["adx14"]), 4),
            "one_hour_rsi14": round(float(one["rsi14"]), 4),
            "one_hour_volume_z20": round(float(one["volume_z20"]), 4),
            "fifteen_minute_distance_ema20_atr": round(float(fifteen["distance_ema20_atr"]), 4),
        },
    }


def _strategy_levels(team_id: str, direction: str, one: dict[str, Any], fifteen: dict[str, Any]) -> dict[str, float | None]:
    if direction not in {"long", "short"}:
        return {"entry": None, "stop_loss": None, "take_profit": None, "rr": None}
    entry = float(fifteen["close"])
    atr = max(float(one["atr14"]), entry * 0.002)
    if team_id == "mean_reversion":
        if direction == "long":
            stop = min(float(one["bb_lower"]), float(fifteen["swing_low10"])) - 0.25 * atr
            minimum_target = entry + 1.2 * (entry - stop)
            target = max(float(one["bb_mid"]), minimum_target)
        else:
            stop = max(float(one["bb_upper"]), float(fifteen["swing_high10"])) + 0.25 * atr
            minimum_target = entry - 1.2 * (stop - entry)
            target = min(float(one["bb_mid"]), minimum_target)
    elif team_id == "volatility_breakout":
        level = float(one["donchian20_high"] if direction == "long" else one["donchian20_low"])
        stop = level - 0.5 * atr if direction == "long" else level + 0.5 * atr
        target = entry + 2 * (entry - stop) if direction == "long" else entry - 2 * (stop - entry)
    else:
        structure = float(one["ema20"])
        if direction == "long":
            stop = min(structure, float(fifteen["swing_low10"])) - 0.5 * atr
            target = entry + 2 * (entry - stop)
        else:
            stop = max(structure, float(fifteen["swing_high10"])) + 0.5 * atr
            target = entry - 2 * (stop - entry)
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if min(entry, stop, target, risk) <= 0:
        return {"entry": None, "stop_loss": None, "take_profit": None, "rr": None}
    return {
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "rr": reward / risk,
    }


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "trade-v1-market-features/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _swap_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    return normalized if normalized.endswith("-SWAP") else f"{normalized}-SWAP"


def _ema(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1 - alpha) * output[-1])
    return output


def _wilder(values: list[float], period: int) -> list[float]:
    output: list[float] = []
    current = values[0]
    for value in values:
        current = (current * (period - 1) + value) / period
        output.append(current)
    return output


def _atr_series(candles: list[Candle], period: int) -> list[float]:
    true_ranges = [candles[0].high - candles[0].low]
    for previous, current in zip(candles, candles[1:]):
        true_ranges.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
    return _wilder(true_ranges, period)


def _adx_series(candles: list[Candle], period: int) -> list[float]:
    tr = [candles[0].high - candles[0].low]
    plus_dm = [0.0]
    minus_dm = [0.0]
    for previous, current in zip(candles, candles[1:]):
        up = current.high - previous.high
        down = previous.low - current.low
        tr.append(max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close)))
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = _wilder(tr, period)
    plus = _wilder(plus_dm, period)
    minus = _wilder(minus_dm, period)
    dx: list[float] = []
    for tr_value, plus_value, minus_value in zip(atr, plus, minus):
        plus_di = 100 * plus_value / tr_value if tr_value > 0 else 0.0
        minus_di = 100 * minus_value / tr_value if tr_value > 0 else 0.0
        total = plus_di + minus_di
        dx.append(100 * abs(plus_di - minus_di) / total if total > 0 else 0.0)
    return _wilder(dx, period)


def _rsi_series(closes: list[float], period: int) -> list[float]:
    gains = [0.0]
    losses = [0.0]
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = _wilder(gains, period)
    avg_loss = _wilder(losses, period)
    output: list[float] = []
    for gain, loss in zip(avg_gain, avg_loss):
        if loss <= 0:
            output.append(100.0 if gain > 0 else 50.0)
        else:
            output.append(100 - 100 / (1 + gain / loss))
    return output


def _bollinger_series(closes: list[float], period: int) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    mids: list[float] = []
    uppers: list[float] = []
    lowers: list[float] = []
    widths: list[float] = []
    z_scores: list[float] = []
    for index, close in enumerate(closes):
        window = closes[max(0, index - period + 1): index + 1]
        mid = fmean(window)
        std = pstdev(window) if len(window) > 1 else 0.0
        upper = mid + 2 * std
        lower = mid - 2 * std
        mids.append(mid)
        uppers.append(upper)
        lowers.append(lower)
        widths.append((upper - lower) / mid * 100 if mid > 0 else 0.0)
        z_scores.append((close - mid) / std if std > 0 else 0.0)
    return mids, uppers, lowers, widths, z_scores


def _percentile_rank(values: Iterable[float], value: float) -> float:
    items = list(values)
    if not items:
        return 0.5
    return sum(1 for item in items if item <= value) / len(items)


def _efficiency_ratio(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    travel = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
    return abs(values[-1] - values[0]) / travel if travel > 0 else 0.0


def _pct_change(previous: float, current: float) -> float:
    return (current - previous) / previous * 100 if previous else 0.0
