"""Crypto signal scanner for the AI Berkshire advisory desk.

The scanner converts public crypto futures ticker data into shared
SignalCandidate-style records. It deliberately produces advisory context for
the LLM pipeline rather than broker-ready order payloads.
"""

from __future__ import annotations

import json
import os
import urllib.request
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from strategy_teams import StrategyTeam, resolve_team
from market_features import (
    build_market_feature_snapshot,
    evaluate_strategy_setup,
)

try:
    from auto.adaptive_hybrid import (
        DecisionPolicy,
        decision_policy_snapshot,
        load_decision_policy,
    )
except ImportError:  # pragma: no cover - direct script/test import fallback
    from adaptive_hybrid import (  # type: ignore
        DecisionPolicy,
        decision_policy_snapshot,
        load_decision_policy,
    )

try:
    from auto.universe import (
        HARDCODED_UNIVERSE,
        fetch_okx_swap_tickers as _universe_fetch_okx_swap_tickers,
        load_universe as _load_universe,
    )
except Exception:  # pragma: no cover - direct packaging fallback
    HARDCODED_UNIVERSE = []  # type: ignore[assignment]
    _universe_fetch_okx_swap_tickers = None  # type: ignore[assignment]
    _load_universe = None  # type: ignore[assignment]


TickerFetcher = Callable[[str], dict[str, Any]]
FeatureSnapshotFetcher = Callable[[str], dict[str, Any]]

_PCT_Q = Decimal("0.01")
_CONF_Q = Decimal("0.01")


class BerkshireScanError(RuntimeError):
    """Raised when a scan cannot produce a safe response."""


def scan_crypto_market(
    *,
    symbols: list[str] | None = None,
    limit: int = 50,
    tickers_fetcher: TickerFetcher | None = None,
    feature_fetcher: FeatureSnapshotFetcher | None = None,
    team_id: str | None = None,
    decision_policy: DecisionPolicy | None = None,
) -> dict[str, Any]:
    """Scan the crypto futures universe and return signal-only output.

    Public OKX ticker data is used when available. If provider data fails, the
    scan still returns blocked signals for the configured/fallback symbols so
    the UI and LLM context cannot mistake missing evidence for a green light.
    """
    team = resolve_team(team_id)
    selected_policy = decision_policy or load_decision_policy()
    normalized_symbols = _scan_symbols(symbols=symbols, limit=limit)
    provider_error: str | None = None
    tickers: list[dict[str, Any]] = []
    try:
        tickers = _fetch_okx_tickers(fetcher=tickers_fetcher)
    except Exception as exc:  # noqa: BLE001
        provider_error = f"okx_ticker_provider_failed: {exc}"

    ticker_by_symbol = {
        _spot_symbol(str(item.get("instId", ""))): item
        for item in tickers
        if isinstance(item, dict) and item.get("instId")
    }

    snapshots: dict[str, dict[str, Any]] = {}
    feature_errors: dict[str, str] = {}
    if provider_error is None:
        feature_builder = feature_fetcher or build_market_feature_snapshot
        for symbol in _feature_enrichment_symbols(
            normalized_symbols,
            ticker_by_symbol,
            team=team,
            explicit_symbols=bool(symbols),
        ):
            try:
                snapshots[symbol] = feature_builder(symbol)
            except Exception as exc:  # noqa: BLE001
                feature_errors[symbol] = f"mtf_feature_provider_failed: {exc}"

    created_at = _now_iso()
    provider_source = (
        "okx_public_tickers+okx_confirmed_candles"
        if provider_error is None
        else "provider_blocked"
    )
    signals = [
        _with_signal_contract(
            _signal_from_ticker(
                symbol,
                ticker_by_symbol.get(symbol),
                provider_error=provider_error,
                feature_snapshot=snapshots.get(symbol),
                feature_error=feature_errors.get(symbol),
                team=team,
                decision_policy=selected_policy,
            ),
            generated_at=created_at,
            provider_source=provider_source,
            team=team,
        )
        for symbol in normalized_symbols
    ]
    ranked = rank_signal_candidates(signals)
    return {
        "id": f"{team.team_id}_scan_{uuid.uuid4().hex[:16]}",
        "created_at": created_at,
        "market": "crypto",
        "mode": "signal_only",
        "source": provider_source,
        "team": team.to_dict(),
        "team_id": team.team_id,
        "team_name": team.team_name,
        "strategy_id": team.strategy_id,
        "strategy_name": team.strategy_name,
        "decision_policy": decision_policy_snapshot(selected_policy),
        "provider_error": provider_error,
        "universe_count": len(normalized_symbols),
        "signal_count": len(ranked),
        "top_symbol": ranked[0]["symbol"] if ranked else None,
        "top_signal": ranked[0]["signal"] if ranked else None,
        "signals": ranked,
        "audit": [
            {
                "time": _time_label(created_at),
                "label": f"{team.team_name} scan guard",
                "value": "SignalCandidate only, no order payload generated",
                "tone": "success",
            },
            {
                "time": _time_label(created_at),
                "label": "LLM integration",
                "value": "team signals may feed advisory prompt context only",
                "tone": "info",
            },
        ],
    }


def rank_signal_candidates(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank signals by confidence first, then score, liquidity, and symbol."""
    return sorted(signals, key=_signal_rank_key)


def _signal_rank_key(signal: dict[str, Any]) -> tuple[float, int, float, str]:
    return (
        -_float_value(signal.get("confidence")),
        -int(_float_value(signal.get("score"))),
        -_float_value(signal.get("volume_usd_24h") or (signal.get("evidence") or {}).get("volume_usd_24h")),
        str(signal.get("symbol", "")),
    )


def _with_signal_contract(
    signal: dict[str, Any],
    *,
    generated_at: str,
    provider_source: str,
    team: StrategyTeam,
) -> dict[str, Any]:
    """Attach the shared SignalCandidate fields while preserving UI aliases."""
    llm_context = signal.get("llm_context", {})
    action_hint = _action_hint(signal)
    status_value = str(signal.get("signal", "blocked"))
    reasons = list(signal.get("why", []))
    skill_profile = team.skill_profile()
    evidence = {
        "provider_source": provider_source,
        "team_id": team.team_id,
        "team_name": team.team_name,
        "strategy_id": team.strategy_id,
        "strategy_name": team.strategy_name,
        "skill_profile": skill_profile,
        "last_price": signal.get("last_price"),
        "change_pct_24h": signal.get("change_pct_24h"),
        "range_pct_24h": signal.get("range_pct_24h"),
        "volume_usd_24h": signal.get("volume_usd_24h"),
        "spread_bps": signal.get("spread_bps"),
        "data_timestamp_utc": signal.get("data_timestamp_utc"),
        "data_age_s": signal.get("data_age_s"),
        "regime": signal.get("regime"),
        "regime_evidence": signal.get("regime_evidence", {}),
        "confluence_score": signal.get("confluence_score"),
        "feature_snapshot": signal.get("feature_snapshot", {}),
        "setup_quality": signal.get("setup_quality", {}),
        "rule_score": signal.get("rule_score", signal.get("score")),
        "score_components": signal.get("score_components", {}),
        "experimental_scores": signal.get("experimental_scores", {}),
        "conflicts": signal.get("conflicts", []),
        "hard_blockers": signal.get("hard_blockers", signal.get("blockers", [])),
        "decision_zone": signal.get("decision_zone"),
        "confidence_calibrated": signal.get("confidence_calibrated", False),
    }
    llm_context = {
        **dict(llm_context),
        "skill_profile": skill_profile,
        "preferred_playbook_ids": list(team.preferred_playbook_ids),
        "required_soft_policy_ids": list(team.required_soft_policy_ids),
        "entry_style": team.entry_style,
        "avoid_conditions": list(team.avoid_conditions),
        "llm_guidance": team.llm_guidance,
        "risk_personality": team.risk_personality,
    }
    signal.update(
        {
            "signal_id": f"sig_{uuid.uuid4().hex[:16]}",
            "generated_at": generated_at,
            "source": team.scanner_source,
            "timeframe": "15m_1h_4h",
            "status": status_value,
            "action_hint": action_hint,
            "llm_context": llm_context,
            "promotion_gate": str(llm_context.get("ticket_gate", "research_only_or_request_more_data")),
            "reasons": reasons,
            "evidence": evidence,
            **team.signal_metadata(),
        }
    )
    return signal


def _action_hint(signal: dict[str, Any]) -> str:
    """Return a schema-safe TradeAction hint for a signal."""
    llm_context = signal.get("llm_context", {})
    candidate_action = str(llm_context.get("candidate_action", ""))
    if candidate_action in {"OPEN_LONG", "OPEN_SHORT"}:
        return candidate_action
    blockers = [str(item) for item in signal.get("blockers", [])]
    if any("missing" in item or "provider" in item or "unavailable" in item for item in blockers):
        return "REQUEST_MORE_DATA"
    return "HOLD"


def _scan_symbols(*, symbols: list[str] | None, limit: int) -> list[str]:
    capped = max(1, min(int(limit or 10), 50))
    if symbols:
        values = [_spot_symbol(item) for item in symbols if str(item).strip()]
    else:
        values = _universe_symbols(capped)
        if not values:
            values = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", "LINK-USDT"][:capped]
    seen: set[str] = set()
    out: list[str] = []
    for symbol in values:
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
        if len(out) >= capped:
            break
    if not out:
        raise BerkshireScanError("crypto scan requires at least one symbol")
    return out


def _universe_symbols(limit: int) -> list[str]:
    """Return top symbols from the shared universe loader with fallback."""
    if _load_universe is not None:
        try:
            snap = _load_universe(top_n=limit)
            return [
                _spot_symbol(getattr(meta, "spot_symbol", "") or getattr(meta, "swap_symbol", ""))
                for meta in snap.symbols[:limit]
            ]
        except Exception:
            pass
    return [
        _spot_symbol(getattr(meta, "spot_symbol", "") or getattr(meta, "swap_symbol", ""))
        for meta in HARDCODED_UNIVERSE[:limit]
    ]


def _fetch_okx_tickers(*, fetcher: TickerFetcher | None) -> list[dict[str, Any]]:
    """Fetch public OKX swap tickers with an import-free fallback."""
    if _universe_fetch_okx_swap_tickers is not None:
        try:
            return _universe_fetch_okx_swap_tickers(fetcher=fetcher)
        except Exception:
            if fetcher is not None:
                raise
    url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
    if fetcher is not None:
        payload = fetcher(url)
        return _usdt_swap_tickers(list(payload.get("data", [])))
    req = urllib.request.Request(url, headers={"User-Agent": "trade-v1/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") != "0":
        raise BerkshireScanError(f"OKX API error: {payload}")
    return _usdt_swap_tickers(list(payload.get("data", [])))


def _usdt_swap_tickers(tickers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only USDT-margined perpetual tickers."""
    return [
        item for item in tickers
        if isinstance(item, dict) and str(item.get("instId", "")).endswith("-USDT-SWAP")
    ]


def _signal_from_ticker(
    symbol: str,
    ticker: dict[str, Any] | None,
    *,
    provider_error: str | None,
    feature_snapshot: dict[str, Any] | None,
    feature_error: str | None,
    team: StrategyTeam,
    decision_policy: DecisionPolicy,
) -> dict[str, Any]:
    if provider_error is not None or ticker is None:
        blockers = [provider_error or "ticker_missing"]
        return _blocked_signal(symbol, blockers, team=team)

    try:
        last = _positive_decimal(ticker.get("last"), "last")
        open_24h = _positive_decimal(ticker.get("open24h"), "open24h")
        high_24h = _positive_decimal(ticker.get("high24h"), "high24h")
        low_24h = _positive_decimal(ticker.get("low24h"), "low24h")
        volume_usd = _quote_volume_usd(ticker, last)
        bid = _decimal_or_none(ticker.get("bidPx"))
        ask = _decimal_or_none(ticker.get("askPx"))
    except BerkshireScanError as exc:
        return _blocked_signal(symbol, [str(exc)], team=team)

    if feature_snapshot is None:
        return _blocked_signal(
            symbol,
            [feature_error or "mtf_feature_snapshot_unavailable"],
            team=team,
            ticker=ticker,
        )

    change_pct = ((last - open_24h) / open_24h * Decimal("100")).quantize(_PCT_Q, rounding=ROUND_HALF_UP)
    range_pct = ((high_24h - low_24h) / last * Decimal("100")).quantize(_PCT_Q, rounding=ROUND_HALF_UP)
    spread_bps = _spread_bps(last, bid, ask)
    setup = evaluate_strategy_setup(
        feature_snapshot,
        team.team_id,
        spread_bps=float(spread_bps) if spread_bps is not None else None,
        volume_usd_24h=float(volume_usd),
        strong_min_score=decision_policy.strong_min_score,
        gray_min_score=decision_policy.gray_min_score,
        shadow_scoring_experiment=(
            decision_policy.shadow_scoring_experiment.to_dict()
            if decision_policy.shadow_scoring_experiment is not None
            else None
        ),
    )
    direction = str(setup["direction"])
    blockers = list(setup["blockers"])
    score = int(setup["score"])
    decision_zone = str(setup["decision_zone"])
    signal = _signal_label(decision_zone, score, blockers, direction)
    levels = _feature_levels(setup.get("levels", {}))
    confidence = Decimal(str(setup["confidence"])).quantize(_CONF_Q, rounding=ROUND_HALF_UP)
    confidence_components = _feature_confidence_components(
        confidence=float(confidence),
        spread_bps=spread_bps,
        volume_usd=volume_usd,
        setup_quality=setup.get("setup_quality", {}),
    )
    reasons = list(setup["reasons"])
    reasons.append(f"{team.team_name} uses confirmed 15m/1H/4H OKX candle evidence.")
    eligible = decision_zone in {"strong", "gray"} and direction in {"long", "short"} and not blockers

    return {
        "symbol": symbol,
        "market": "crypto",
        "direction": direction,
        "signal": signal,
        "score": score,
        "grade": _grade(score),
        "confidence": float(confidence),
        "confidence_components": confidence_components,
        "rule_score": score,
        "score_components": setup.get("score_components", {}),
        "experimental_scores": setup.get("experimental_scores", {}),
        "conflicts": setup.get("conflicts", []),
        "hard_blockers": setup.get("hard_blockers", blockers),
        "decision_zone": decision_zone,
        "confidence_calibrated": setup.get("confidence_calibrated", False),
        "mode": "signal_only",
        "time_horizon": "swing_2d_7d",
        "last_price": _dec(last),
        "change_pct_24h": format(change_pct, "f"),
        "range_pct_24h": format(range_pct, "f"),
        "volume_usd_24h": _dec(volume_usd),
        "spread_bps": format(spread_bps, "f") if spread_bps is not None else None,
        "data_timestamp_utc": feature_snapshot.get("data_timestamp_utc"),
        "data_age_s": feature_snapshot.get("data_age_s"),
        "regime": feature_snapshot.get("regime"),
        "regime_evidence": feature_snapshot.get("regime_evidence", {}),
        "confluence_score": setup.get("setup_confluence_score"),
        "feature_snapshot": feature_snapshot.get("features", {}),
        "setup_quality": setup.get("setup_quality", {}),
        "entry_zone": levels["entry_zone"],
        "invalidation": levels["invalidation"],
        "target_zone": levels["target_zone"],
        "risk_reward": levels["risk_reward"],
        "why": reasons,
        "blockers": blockers,
        "llm_context": {
            "role": "advisory_signal_context",
            "candidate_action": _candidate_action(direction, eligible),
            "ticket_gate": "eligible_for_draft_ticket" if eligible else "research_only_or_request_more_data",
            "instruction": (
                f"Use this {team.team_name} team signal as advisory evidence only. "
                "It is not an order and cannot bypass verifier or risk compiler."
            ),
            "strategy_id": team.strategy_id,
            "strategy_name": team.strategy_name,
            "preferred_playbook_ids": list(team.preferred_playbook_ids),
            "required_soft_policy_ids": list(team.required_soft_policy_ids),
            "entry_style": team.entry_style,
            "avoid_conditions": list(team.avoid_conditions),
            "llm_guidance": team.llm_guidance,
            "risk_personality": team.risk_personality,
            "prompt_context": _prompt_context(
                symbol,
                direction,
                signal,
                score,
                confidence,
                reasons,
                blockers,
                team,
            ),
        },
        **team.signal_metadata(),
    }


def _blocked_signal(
    symbol: str,
    blockers: list[str],
    *,
    team: StrategyTeam,
    ticker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    last = _decimal_or_none((ticker or {}).get("last"))
    return {
        "symbol": symbol,
        "market": "crypto",
        "direction": "neutral",
        "signal": "blocked",
        "score": 0,
        "grade": "D",
        "confidence": 0.0,
        "confidence_components": {
            "momentum": 0.0,
            "liquidity": 0.0,
            "spread": 0.0,
            "range": 0.0,
            "evidence": 0.0,
            "final": 0.0,
        },
        "mode": "signal_only",
        "time_horizon": "swing_2d_7d",
        "last_price": _dec(last) if last is not None and last > 0 else None,
        "change_pct_24h": None,
        "range_pct_24h": None,
        "volume_usd_24h": None,
        "spread_bps": None,
        "entry_zone": "n/a",
        "invalidation": "n/a",
        "target_zone": "n/a",
        "risk_reward": None,
        "why": ["Provider evidence is missing, so Berkshire blocks signal promotion."],
        "blockers": [item for item in blockers if item],
        "llm_context": {
            "role": "advisory_signal_context",
            "candidate_action": "REQUEST_MORE_DATA",
            "ticket_gate": "blocked_missing_evidence",
            "instruction": "Do not trade. Request fresh market data before drafting a ticket.",
            "strategy_id": team.strategy_id,
            "strategy_name": team.strategy_name,
            "preferred_playbook_ids": list(team.preferred_playbook_ids),
            "required_soft_policy_ids": list(team.required_soft_policy_ids),
            "entry_style": team.entry_style,
            "avoid_conditions": list(team.avoid_conditions),
            "llm_guidance": team.llm_guidance,
            "risk_personality": team.risk_personality,
            "prompt_context": f"{symbol}: {team.team_name} team crypto signal is blocked because evidence is missing.",
        },
        **team.signal_metadata(),
    }


def _feature_enrichment_symbols(
    symbols: list[str],
    ticker_by_symbol: dict[str, dict[str, Any]],
    *,
    team: StrategyTeam,
    explicit_symbols: bool,
) -> list[str]:
    """Bound candle calls while enriching every explicitly requested symbol."""
    if explicit_symbols:
        return list(symbols)
    limit = max(1, min(int(os.getenv("STRATEGY_MTF_ENRICH_LIMIT", "12")), len(symbols)))

    def quote_volume(symbol: str) -> float:
        ticker = ticker_by_symbol.get(symbol, {})
        try:
            last = Decimal(str(ticker.get("last") or 0))
            if last <= 0:
                return 0.0
            return float(_quote_volume_usd(ticker, last))
        except (BerkshireScanError, InvalidOperation, TypeError, ValueError):
            return 0.0

    def rank(symbol: str) -> tuple[float, float, str]:
        ticker = ticker_by_symbol.get(symbol, {})
        try:
            last = float(ticker.get("last") or 0)
            opened = float(ticker.get("open24h") or 0)
            high = float(ticker.get("high24h") or 0)
            low = float(ticker.get("low24h") or 0)
            change = abs((last - opened) / opened) if opened > 0 else 0.0
            range_pct = (high - low) / last if last > 0 else 0.0
        except (TypeError, ValueError):
            return (0.0, 0.0, symbol)
        primary = range_pct if team.team_id == "volatility_breakout" else change
        return (-primary, -quote_volume(symbol), symbol)

    def liquidity_rank(symbol: str) -> tuple[float, str]:
        return (-quote_volume(symbol), symbol)

    anchor_count = min(limit, max(2, limit // 3))
    ordered = [
        *sorted(symbols, key=liquidity_rank)[:anchor_count],
        *sorted(symbols, key=rank),
    ]
    selected: list[str] = []
    seen: set[str] = set()
    for symbol in ordered:
        if symbol in seen:
            continue
        selected.append(symbol)
        seen.add(symbol)
        if len(selected) >= limit:
            break
    return selected


def _feature_levels(raw: dict[str, Any]) -> dict[str, str | None]:
    entry = _positive_float(raw.get("entry"))
    stop = _positive_float(raw.get("stop_loss"))
    target = _positive_float(raw.get("take_profit"))
    rr = _positive_float(raw.get("rr"))
    if None in {entry, stop, target, rr}:
        return {"entry_zone": "n/a", "invalidation": "n/a", "target_zone": "n/a", "risk_reward": None}
    return {
        "entry_zone": _price_text(entry),
        "invalidation": _price_text(stop),
        "target_zone": _price_text(target),
        "risk_reward": f"{rr:.4f}",
    }


def _feature_confidence_components(
    *,
    confidence: float,
    spread_bps: Decimal | None,
    volume_usd: Decimal,
    setup_quality: dict[str, Any],
) -> dict[str, float]:
    adx = max(0.0, min(float(setup_quality.get("one_hour_adx14", 0)) / 40.0, 1.0))
    return {
        "momentum": round(adx, 2),
        "liquidity": _liquidity_confidence(volume_usd),
        "spread": _spread_confidence(spread_bps),
        "range": round(max(0.0, min(1.0, confidence)), 2),
        "evidence": 1.0,
        "final": round(confidence, 2),
    }


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _price_text(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _score(
    *,
    change_pct: Decimal,
    range_pct: Decimal,
    spread_bps: Decimal | None,
    volume_usd: Decimal,
    blockers: list[str],
    direction: str,
    team: StrategyTeam,
) -> int:
    if blockers:
        return 35
    abs_change = abs(change_pct)
    momentum_multiplier = {
        "momentum": Decimal("3.4"),
        "mean_reversion": Decimal("2.2"),
        "volatility_breakout": Decimal("2.0"),
    }.get(team.team_id, Decimal("2.5"))
    momentum = min(Decimal("30"), abs_change * momentum_multiplier)
    liquidity = Decimal("25") if volume_usd >= Decimal("1000000000") else Decimal("18") if volume_usd >= Decimal("250000000") else Decimal("12") if volume_usd >= Decimal("50000000") else Decimal("5")
    spread = Decimal("20")
    if spread_bps is None:
        spread = Decimal("8")
    elif spread_bps > Decimal("15"):
        spread = Decimal("10")
    elif spread_bps > Decimal("5"):
        spread = Decimal("15")
    risk = Decimal("15")
    if range_pct > Decimal("20"):
        risk = Decimal("5")
    elif range_pct > Decimal("12"):
        risk = Decimal("9")
    elif range_pct > Decimal("8"):
        risk = Decimal("12")
    base = Decimal("15")
    if team.team_id == "mean_reversion":
        # Reversion likes stretched but not disorderly ranges.
        risk = Decimal("18") if Decimal("5") <= range_pct <= Decimal("18") else risk
    elif team.team_id == "volatility_breakout":
        # Breakout team is paid for expansion; range quality is an edge, not just heat.
        risk = min(Decimal("20"), max(Decimal("8"), range_pct * Decimal("1.2")))
    if direction == "neutral":
        base -= Decimal("8")
    return int(min(Decimal("100"), base + momentum + liquidity + spread + risk).to_integral_value(rounding=ROUND_HALF_UP))


def _confidence_components(
    *,
    change_pct: Decimal,
    range_pct: Decimal,
    spread_bps: Decimal | None,
    volume_usd: Decimal,
    blockers: list[str],
    direction: str,
    team: StrategyTeam,
) -> dict[str, float]:
    """Compute transparent scanner confidence components."""
    momentum_denominator = Decimal("6") if team.team_id == "momentum" else Decimal("8")
    range_component = Decimal(str(_range_confidence(range_pct)))
    if team.team_id == "volatility_breakout":
        range_component = min(Decimal("1"), range_pct / Decimal("10"))
    if team.team_id == "mean_reversion":
        range_component = Decimal("1") if Decimal("5") <= range_pct <= Decimal("18") else range_component
    if blockers:
        return {
            "momentum": _component_float(min(Decimal("1"), abs(change_pct) / momentum_denominator)),
            "liquidity": _liquidity_confidence(volume_usd),
            "spread": _spread_confidence(spread_bps),
            "range": _component_float(range_component),
            "evidence": 0.0,
            "final": 0.0,
        }
    momentum = min(Decimal("1"), abs(change_pct) / momentum_denominator)
    liquidity = Decimal(str(_liquidity_confidence(volume_usd)))
    spread = Decimal(str(_spread_confidence(spread_bps)))
    range_quality = range_component
    evidence = Decimal("1.0")
    final = (
        momentum * Decimal("0.30")
        + liquidity * Decimal("0.25")
        + spread * Decimal("0.20")
        + range_quality * Decimal("0.15")
        + evidence * Decimal("0.10")
    )
    if direction == "neutral":
        final *= Decimal("0.6")
    return {
        "momentum": _component_float(momentum),
        "liquidity": _component_float(liquidity),
        "spread": _component_float(spread),
        "range": _component_float(range_quality),
        "evidence": _component_float(evidence),
        "final": _component_float(min(Decimal("1"), final)),
    }


def _liquidity_confidence(volume_usd: Decimal) -> float:
    if volume_usd >= Decimal("1000000000"):
        return 1.0
    if volume_usd >= Decimal("250000000"):
        return 0.75
    if volume_usd >= Decimal("50000000"):
        return 0.50
    if volume_usd >= Decimal("10000000"):
        return 0.25
    return 0.05


def _spread_confidence(spread_bps: Decimal | None) -> float:
    if spread_bps is None:
        return 0.20
    if spread_bps <= Decimal("2"):
        return 1.0
    if spread_bps <= Decimal("5"):
        return 0.85
    if spread_bps <= Decimal("15"):
        return 0.65
    if spread_bps <= Decimal("35"):
        return 0.35
    return 0.10


def _range_confidence(range_pct: Decimal) -> float:
    if range_pct <= Decimal("8"):
        return 1.0
    if range_pct <= Decimal("12"):
        return 0.75
    if range_pct <= Decimal("20"):
        return 0.45
    if range_pct <= Decimal("30"):
        return 0.25
    return 0.05


def _component_float(value: Decimal) -> float:
    return float(value.quantize(_CONF_Q, rounding=ROUND_HALF_UP))


def _signal_label(
    decision_zone: str,
    score: int,
    blockers: list[str],
    direction: str,
) -> str:
    if blockers:
        return "blocked"
    if direction == "neutral":
        return "watchlist" if score >= 40 else "blocked"
    if decision_zone == "strong":
        return "strong_candidate"
    if decision_zone == "gray":
        return "candidate"
    if score >= 40:
        return "watchlist"
    return "blocked"


def _direction(change_pct: Decimal) -> str:
    if change_pct >= Decimal("1.50"):
        return "long"
    if change_pct <= Decimal("-1.50"):
        return "short"
    return "neutral"


def _direction_for_team(team: StrategyTeam, change_pct: Decimal, range_pct: Decimal) -> str:
    """Return the team-specific directional interpretation."""
    if team.team_id == "momentum":
        if change_pct >= Decimal("2.00"):
            return "long"
        if change_pct <= Decimal("-2.00"):
            return "short"
        return "neutral"
    if team.team_id == "mean_reversion":
        if change_pct <= Decimal("-3.00"):
            return "long"
        if change_pct >= Decimal("3.00"):
            return "short"
        return "neutral"
    if team.team_id == "volatility_breakout":
        if range_pct < Decimal("4.00"):
            return "neutral"
        if change_pct >= Decimal("1.00"):
            return "long"
        if change_pct <= Decimal("-1.00"):
            return "short"
        return "neutral"
    return _direction(change_pct)


def _blockers(
    *,
    spread_bps: Decimal | None,
    range_pct: Decimal,
    volume_usd: Decimal,
    team: StrategyTeam,
) -> list[str]:
    blockers: list[str] = []
    if spread_bps is None:
        blockers.append("missing_spread")
    elif spread_bps > Decimal("35"):
        blockers.append("spread_too_wide")
    if range_pct > Decimal("30"):
        blockers.append("range_too_hot")
    if volume_usd < Decimal("10000000"):
        blockers.append("liquidity_too_thin")
    if team.team_id == "volatility_breakout" and range_pct < Decimal("4"):
        blockers.append("range_expansion_missing")
    if team.team_id == "mean_reversion" and range_pct > Decimal("25"):
        blockers.append("reversion_range_disorderly")
    return blockers


def _reference_levels(last: Decimal, direction: str, range_pct: Decimal) -> dict[str, str | None]:
    if direction == "neutral":
        return {
            "entry_zone": f"{_dec(last * Decimal('0.9975'))} - {_dec(last * Decimal('1.0025'))}",
            "invalidation": "wait for directional break",
            "target_zone": "n/a",
            "risk_reward": None,
        }
    risk_pct = max(Decimal("2.0"), min(Decimal("6.0"), range_pct * Decimal("0.30")))
    risk = last * risk_pct / Decimal("100")
    reward = risk * Decimal("2")
    if direction == "long":
        invalidation = last - risk
        target = last + reward
    else:
        invalidation = last + risk
        target = last - reward
    return {
        "entry_zone": f"{_dec(last * Decimal('0.9975'))} - {_dec(last * Decimal('1.0025'))}",
        "invalidation": _dec(invalidation),
        "target_zone": _dec(target),
        "risk_reward": "2.0000",
    }


def _reasons(
    *,
    direction: str,
    change_pct: Decimal,
    volume_usd: Decimal,
    spread_bps: Decimal | None,
    range_pct: Decimal,
    team: StrategyTeam,
) -> list[str]:
    if team.team_id == "mean_reversion" and direction != "neutral":
        reasons = [f"{team.team_name} fades the stretched 24h move of {change_pct}% toward {direction}."]
    elif team.team_id == "volatility_breakout" and direction != "neutral":
        reasons = [f"{team.team_name} sees range expansion {range_pct}% with {change_pct}% directional pressure."]
    else:
        reasons = [f"24h momentum points {direction} at {change_pct}%." if direction != "neutral" else f"24h momentum is neutral at {change_pct}%."]
    reasons.append(f"{team.team_name} method: {team.method}.")
    if volume_usd >= Decimal("250000000"):
        reasons.append("Liquidity passes first Berkshire quality screen.")
    else:
        reasons.append("Liquidity is acceptable only as a watchlist signal.")
    if spread_bps is not None and spread_bps <= Decimal("15"):
        reasons.append(f"Spread is contained at {spread_bps} bps.")
    reasons.append(f"24h range is {range_pct}%, used as risk heat check.")
    return reasons


def _candidate_action(direction: str, eligible: bool) -> str:
    if not eligible:
        return "HOLD_OR_REQUEST_MORE_DATA"
    return "OPEN_LONG" if direction == "long" else "OPEN_SHORT"


def _prompt_context(
    symbol: str,
    direction: str,
    signal: str,
    score: int,
    confidence: Decimal,
    reasons: list[str],
    blockers: list[str],
    team: StrategyTeam,
) -> str:
    blocker_text = ", ".join(blockers) if blockers else "none"
    return (
        f"{team.team_name} crypto team scan for {symbol}: strategy={team.strategy_name}, "
        f"signal={signal}, direction={direction}, "
        f"score={score}, confidence={confidence}. Reasons: {'; '.join(reasons)}. "
        f"Blockers: {blocker_text}. Target risk {team.target_risk_pct_equity:.2%} "
        f"inside {team.risk_min_pct_equity:.2%}-{team.risk_max_pct_equity:.2%} demo band. "
        f"Entry style: {team.entry_style}. Avoid: {', '.join(team.avoid_conditions)}. "
        f"Guidance: {team.llm_guidance}. "
        "Treat as advisory evidence only."
    )


def _spot_symbol(raw: str) -> str:
    symbol = str(raw).strip().upper()
    if symbol.endswith("-SWAP"):
        symbol = symbol[: -len("-SWAP")]
    return symbol


def _spread_bps(last: Decimal, bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return ((ask - bid) / last * Decimal("10000")).quantize(_PCT_Q, rounding=ROUND_HALF_UP)


def _grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _positive_decimal(raw: Any, label: str) -> Decimal:
    value = _decimal(raw, label)
    if value <= 0:
        raise BerkshireScanError(f"{label}_missing_or_non_positive")
    return value


def _quote_volume_usd(ticker: dict[str, Any], last: Decimal) -> Decimal:
    """Return an approximate 24h quote volume in USDT.

    OKX SWAP tickers often omit `volCcyQuote24h`; `volCcy24h` is the base
    currency amount, so multiply by last price for a quote-volume proxy.
    """
    quote = ticker.get("volCcyQuote24h")
    if quote not in (None, ""):
        return _decimal(quote, "volCcyQuote24h")
    base_volume = _decimal(ticker.get("volCcy24h"), "volCcy24h")
    return base_volume * last


def _decimal(raw: Any, label: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError) as exc:
        raise BerkshireScanError(f"{label}_not_numeric") from exc


def _decimal_or_none(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _float_value(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _dec(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _time_label(iso: str | None = None) -> str:
    try:
        dt = datetime.fromisoformat((iso or _now_iso()).replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.astimezone().strftime("%H:%M")
