"""Build normalized market context for LLM-governed decisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

try:
    from .confluence_signal import classify_candidate_direction
except ImportError:  # pragma: no cover - direct script/test import fallback
    from confluence_signal import classify_candidate_direction  # type: ignore
from schemas.models import DataQuality, MarketDossier


class MarketDossierBuildError(RuntimeError):
    """Raised when core market context is insufficient for a safe decision."""


def build_market_dossier(
    *,
    symbol: str,
    current_price: float | int | str | None,
    confluence: dict[str, Any] | float | int,
    regime: dict[str, Any] | str | None,
    market: str = "crypto",
    timeframe: str = "1h",
    min_confluence: float = 2.0,
    data_source: str = "unknown",
    data_age_s: float | int | None = None,
    data_timestamp_utc: str | None = None,
    max_data_age_s: float = 60.0,
    spread_state: str | None = None,
    funding_state: str | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    recent_trades: list[dict[str, Any]] | None = None,
    portfolio_exposure: dict[str, Any] | None = None,
    feature_snapshot: dict[str, Any] | None = None,
    regime_evidence: dict[str, Any] | None = None,
    setup_quality: dict[str, Any] | None = None,
    open_positions_reader: Callable[[], list[dict[str, Any]]] | None = None,
    recent_trades_reader: Callable[[], list[dict[str, Any]]] | None = None,
) -> MarketDossier:
    """Return a JSON-serializable dossier or raise on unsafe core data."""
    price = _positive_number(current_price, "current_price")
    score = _confluence_score(confluence)
    regime_name = _regime_name(regime)
    age_s = _data_age_seconds(data_age_s, data_timestamp_utc)
    warnings: list[str] = []

    if open_positions is None and open_positions_reader is not None:
        try:
            open_positions = open_positions_reader()
        except Exception as exc:  # noqa: BLE001
            raise MarketDossierBuildError("journal positions could not be read") from exc

    if open_positions is None:
        open_positions = []
    if not isinstance(open_positions, list):
        raise MarketDossierBuildError("open_positions must be a list")
    if recent_trades is None and recent_trades_reader is not None:
        try:
            recent_trades = recent_trades_reader()
        except Exception as exc:  # noqa: BLE001
            raise MarketDossierBuildError("journal recent trades could not be read") from exc
    if recent_trades is None:
        recent_trades = []
    if not isinstance(recent_trades, list):
        raise MarketDossierBuildError("recent_trades must be a list")

    if age_s > max_data_age_s:
        warnings.append("stale_market_data")
    if data_source == "unknown":
        warnings.append("unknown_data_source")

    exposure = dict(portfolio_exposure or {})
    exposure.setdefault("warnings", [])
    if not isinstance(exposure["warnings"], list):
        exposure["warnings"] = [str(exposure["warnings"])]
    exposure["warnings"].extend(warnings)

    data_quality = DataQuality.C if warnings else DataQuality.A
    candidate_direction = classify_candidate_direction(score, min_confluence)

    return MarketDossier(
        symbol=_non_empty_string(symbol, "symbol"),
        market=_non_empty_string(market, "market"),
        timeframe=_non_empty_string(timeframe, "timeframe"),
        current_price=price,
        confluence_score=score,
        candidate_direction=candidate_direction,
        regime=regime_name,
        trend_state=_trend_state(regime_name),
        volatility_state=_volatility_state(regime),
        data_source=_non_empty_string(data_source, "data_source"),
        data_age_s=age_s,
        data_quality=data_quality,
        spread_state=spread_state,
        funding_state=funding_state,
        open_positions=open_positions,
        recent_trades=recent_trades[-3:],
        portfolio_exposure=exposure,
        data_timestamp_utc=data_timestamp_utc,
        feature_snapshot=dict(feature_snapshot or {}),
        regime_evidence=dict(regime_evidence or {}),
        setup_quality=dict(setup_quality or {}),
    )


def dossier_hash(dossier: MarketDossier | dict[str, Any]) -> str:
    """Return a stable sha256 hash for journal snapshot references."""
    payload = dossier.to_dict() if isinstance(dossier, MarketDossier) else dict(dossier)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _positive_number(value: float | int | str | None, label: str) -> float:
    if value is None:
        raise MarketDossierBuildError(f"{label} is required")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDossierBuildError(f"{label} must be numeric") from exc
    if parsed <= 0:
        raise MarketDossierBuildError(f"{label} must be > 0")
    return parsed


def _confluence_score(confluence: dict[str, Any] | float | int) -> float:
    if isinstance(confluence, dict):
        for key in ("total_score", "score", "confluence_score"):
            if key in confluence:
                return _number(confluence[key], "confluence_score")
        raise MarketDossierBuildError("confluence score is required")
    return _number(confluence, "confluence_score")


def _regime_name(regime: dict[str, Any] | str | None) -> str:
    if isinstance(regime, str):
        return _non_empty_string(regime, "regime")
    if isinstance(regime, dict):
        for key in ("name", "regime", "regime_name"):
            value = regime.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise MarketDossierBuildError("regime is required")


def _data_age_seconds(
    data_age_s: float | int | None,
    data_timestamp_utc: str | None,
) -> float:
    if data_age_s is not None:
        return max(0.0, _number(data_age_s, "data_age_s"))
    if not data_timestamp_utc:
        return 0.0
    try:
        parsed = datetime.fromisoformat(data_timestamp_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketDossierBuildError("data_timestamp_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def _trend_state(regime_name: str) -> str:
    normalized = regime_name.upper()
    if normalized == "TRENDING_UP":
        return "up"
    if normalized == "TRENDING_DOWN":
        return "down"
    if normalized == "RANGING":
        return "range"
    if normalized == "HIGH_VOLATILITY":
        return "volatile"
    return "mixed"


def _volatility_state(regime: dict[str, Any] | str | None) -> str:
    if isinstance(regime, dict):
        value = regime.get("volatility_state") or regime.get("volatility")
        if isinstance(value, str) and value.strip():
            return value.strip()
    regime_name = _regime_name(regime)
    if regime_name.upper() == "HIGH_VOLATILITY":
        return "high"
    return "normal"


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MarketDossierBuildError(f"{label} must be numeric")
    return float(value)


def _non_empty_string(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketDossierBuildError(f"{label} must be a non-empty string")
    return value.strip()
