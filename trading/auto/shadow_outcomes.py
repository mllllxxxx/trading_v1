"""Collect and resolve broker-free adaptive shadow outcomes."""

from __future__ import annotations

import hashlib
import math
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from market_features import Candle, fetch_confirmed_candles

try:
    from . import journal
    from .adaptive_hybrid import (
        DecisionPolicy,
        build_rule_proposal,
        decision_policy_snapshot,
        load_decision_policy,
    )
except ImportError:  # pragma: no cover - direct script/test import fallback
    import journal  # type: ignore
    from adaptive_hybrid import (  # type: ignore
        DecisionPolicy,
        build_rule_proposal,
        decision_policy_snapshot,
        load_decision_policy,
    )


CandleFetcher = Callable[..., list[Candle]]
BAR_MS = 900_000
_RESOLVER_LOCK = threading.Lock()


@dataclass(frozen=True)
class ShadowOutcomeConfig:
    """Operational limits for broker-free shadow evidence."""

    enabled: bool = True
    max_hold_bars: int = 192
    fee_bps_per_leg: float = 5.0
    slippage_bps: float = 2.0
    max_symbols_per_cycle: int = 12
    max_pending: int = 2_000
    candle_limit: int = 300

    @classmethod
    def from_env(cls) -> "ShadowOutcomeConfig":
        """Load bounded operational settings from environment variables."""
        return cls(
            enabled=_env_bool("AUTO_SHADOW_EVALUATION_ENABLED", True),
            max_hold_bars=max(1, min(_env_int("AUTO_SHADOW_MAX_HOLD_BARS", 192), 288)),
            fee_bps_per_leg=max(0.0, min(_env_float("AUTO_SHADOW_FEE_BPS_PER_LEG", 5.0), 100.0)),
            slippage_bps=max(0.0, min(_env_float("AUTO_SHADOW_SLIPPAGE_BPS", 2.0), 100.0)),
            max_symbols_per_cycle=max(
                1,
                min(_env_int("AUTO_SHADOW_MAX_SYMBOLS_PER_CYCLE", 12), 50),
            ),
            max_pending=max(1, min(_env_int("AUTO_SHADOW_MAX_PENDING", 2_000), 20_000)),
            candle_limit=max(10, min(_env_int("AUTO_SHADOW_CANDLE_LIMIT", 300), 300)),
        )


def capture_shadow_candidates(
    signals: Iterable[Mapping[str, Any]],
    *,
    scan_id: str | None,
    journal_module: Any = journal,
    config: ShadowOutcomeConfig | None = None,
    now: datetime | None = None,
    decision_policy: DecisionPolicy | None = None,
) -> dict[str, Any]:
    """Persist every blocker-free directional candidate before route filters."""
    cfg = config or ShadowOutcomeConfig.from_env()
    summary = {
        "enabled": cfg.enabled,
        "captured": 0,
        "duplicates": 0,
        "ineligible": 0,
        "capacity_skipped": 0,
        "pending": 0,
        "broker_calls": 0,
    }
    read_pending = getattr(journal_module, "read_shadow_positions", None)
    add_pending = getattr(journal_module, "add_shadow_position", None)
    if not cfg.enabled or not callable(read_pending) or not callable(add_pending):
        summary["supported"] = callable(read_pending) and callable(add_pending)
        return summary

    selected_policy = decision_policy or load_decision_policy()
    summary["decision_policy"] = decision_policy_snapshot(selected_policy)
    pending = list(read_pending())
    known_ids = {str(item.get("shadow_id")) for item in pending if isinstance(item, Mapping)}
    for signal in signals:
        record = build_shadow_candidate(
            signal,
            scan_id=scan_id,
            config=cfg,
            now=now,
            decision_policy=selected_policy,
        )
        if record is None:
            summary["ineligible"] += 1
            continue
        shadow_id = str(record["shadow_id"])
        if shadow_id in known_ids:
            summary["duplicates"] += 1
            continue
        if len(known_ids) >= cfg.max_pending:
            summary["capacity_skipped"] += 1
            continue
        if bool(add_pending(record)):
            known_ids.add(shadow_id)
            summary["captured"] += 1
        else:
            summary["duplicates"] += 1
    summary["pending"] = len(known_ids)
    return summary


def build_shadow_candidate(
    signal: Mapping[str, Any],
    *,
    scan_id: str | None,
    config: ShadowOutcomeConfig,
    now: datetime | None = None,
    decision_policy: DecisionPolicy | None = None,
) -> dict[str, Any] | None:
    """Normalize one scanner signal into an idempotent pending shadow row."""
    raw = dict(signal)
    direction = str(raw.get("direction") or "").lower()
    if direction not in {"long", "short"}:
        return None
    selected_policy = decision_policy or load_decision_policy()
    proposal = build_rule_proposal(raw, policy=selected_policy)
    hard_blockers = _unique_strings(
        raw.get("hard_blockers"),
        raw.get("blockers"),
        proposal.hard_blockers,
    )
    if hard_blockers:
        return None
    levels = _price_levels(raw)
    if levels is None or not _levels_valid(direction, **levels):
        return None
    trigger_at = _first(
        _nested(raw, "evidence", "data_timestamp_utc"),
        raw.get("data_timestamp_utc"),
    )
    trigger_dt = _parse_utc(trigger_at)
    if trigger_dt is None:
        return None
    score = float(proposal.rule_score)
    if not 0 <= score <= 100:
        return None
    symbol = _canonical_symbol(str(raw.get("symbol") or raw.get("instId") or ""))
    if not symbol:
        return None
    team_id = str(raw.get("team_id") or _nested(raw, "evidence", "team_id") or "unknown")
    strategy_id = str(raw.get("strategy_id") or _nested(raw, "evidence", "strategy_id") or "unknown")
    trigger_ms = int(trigger_dt.timestamp() * 1000)
    identity = "|".join(
        [
            team_id,
            strategy_id,
            symbol,
            direction,
            str(trigger_ms),
            f"{score:.4f}",
            f"{levels['entry']:.12g}",
            f"{levels['stop_loss']:.12g}",
            f"{levels['take_profit']:.12g}",
        ]
    )
    shadow_id = f"shadow_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"
    captured_at = _iso_utc(now or datetime.now(timezone.utc))
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), Mapping) else {}
    experimental_scores = raw.get("experimental_scores")
    if not isinstance(experimental_scores, Mapping):
        experimental_scores = evidence.get("experimental_scores")
    if not isinstance(experimental_scores, Mapping):
        experimental_scores = {}
    return {
        "schema_version": "shadow_candidate.v1",
        "shadow_id": shadow_id,
        "status": "pending",
        "evaluation_source": "shadow",
        "counterfactual_eligible": True,
        "counterfactual_score_floor": 0.0,
        "captured_at": captured_at,
        "last_checked_at": None,
        "scan_id": scan_id,
        "signal_id": raw.get("signal_id"),
        "source": raw.get("source"),
        "team_id": team_id,
        "team_name": raw.get("team_name") or evidence.get("team_name"),
        "strategy_id": strategy_id,
        "strategy_name": raw.get("strategy_name") or evidence.get("strategy_name"),
        "decision_policy": decision_policy_snapshot(selected_policy),
        "symbol": symbol,
        "side": direction,
        "rule_score": round(score, 4),
        "decision_zone": proposal.decision_zone,
        "decision_lane": proposal.decision_lane,
        "score_components": dict(proposal.score_components),
        "experimental_scores": {
            str(key): dict(value)
            for key, value in experimental_scores.items()
            if isinstance(value, Mapping)
        },
        "conflicts": list(proposal.conflicts),
        "hard_blockers": [],
        "regime": raw.get("regime") or evidence.get("regime"),
        "entry": levels["entry"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "trigger_data_timestamp_utc": _iso_utc(trigger_dt),
        "trigger_timestamp_ms": trigger_ms,
        "bar": "15m",
        "bar_ms": BAR_MS,
        "max_hold_bars": config.max_hold_bars,
        "fee_bps_per_leg": config.fee_bps_per_leg,
        "slippage_bps": config.slippage_bps,
        "observed_stage": "not_promoted",
        "observed_reason": "pending_route_observation",
        "observed_executed": False,
        "observed_llm_review": None,
    }


def annotate_shadow_result(
    signal: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    journal_module: Any = journal,
    config: ShadowOutcomeConfig | None = None,
    decision_policy: DecisionPolicy | None = None,
) -> bool:
    """Attach the observed runtime route to its pending shadow record."""
    updater = getattr(journal_module, "update_shadow_position", None)
    if not callable(updater):
        return False
    cfg = config or ShadowOutcomeConfig.from_env()
    candidate = build_shadow_candidate(
        signal,
        scan_id=None,
        config=cfg,
        decision_policy=decision_policy,
    )
    if candidate is None:
        return False
    review = result.get("llm_review")
    if not isinstance(review, Mapping):
        review = None
    return bool(
        updater(
            str(candidate["shadow_id"]),
            {
                "observed_stage": result.get("stage"),
                "observed_reason": result.get("reason"),
                "observed_executed": bool(result.get("executed")),
                "observed_decision_lane": result.get("decision_lane"),
                "observed_llm_review": dict(review) if review is not None else None,
            },
        )
    )


def resolve_pending_shadow_outcomes(
    *,
    journal_module: Any = journal,
    config: ShadowOutcomeConfig | None = None,
    candle_fetcher: CandleFetcher = fetch_confirmed_candles,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve pending rows from confirmed public candles without broker calls."""
    cfg = config or ShadowOutcomeConfig.from_env()
    summary = {
        "enabled": cfg.enabled,
        "pending_before": 0,
        "symbols_checked": 0,
        "public_market_calls": 0,
        "broker_calls": 0,
        "resolved": 0,
        "still_pending": 0,
        "errors": [],
    }
    reader = getattr(journal_module, "read_shadow_positions", None)
    resolver = getattr(journal_module, "resolve_shadow_position", None)
    updater = getattr(journal_module, "update_shadow_position", None)
    if not cfg.enabled or not callable(reader) or not callable(resolver):
        summary["supported"] = callable(reader) and callable(resolver)
        return summary
    pending = [dict(item) for item in reader() if isinstance(item, Mapping)]
    summary["pending_before"] = len(pending)
    if not pending:
        return summary

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in pending:
        grouped[str(record.get("symbol") or "")].append(record)
    ordered_symbols = sorted(
        (symbol for symbol in grouped if symbol),
        key=lambda symbol: min(
            str(item.get("last_checked_at") or item.get("captured_at") or "")
            for item in grouped[symbol]
        ),
    )[: cfg.max_symbols_per_cycle]
    now_dt = now or datetime.now(timezone.utc)
    checked_at = _iso_utc(now_dt)
    for symbol in ordered_symbols:
        try:
            candles = candle_fetcher(symbol, "15m", cfg.candle_limit)
            summary["public_market_calls"] += 1
            summary["symbols_checked"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append({"symbol": symbol, "error": str(exc)})
            continue
        for record in grouped[symbol]:
            outcome = _resolve_record(record, candles, now=now_dt, candle_limit=cfg.candle_limit)
            if outcome is None:
                if callable(updater):
                    updater(str(record.get("shadow_id")), {"last_checked_at": checked_at})
                continue
            if resolver(str(record.get("shadow_id")), outcome):
                summary["resolved"] += 1
    summary["still_pending"] = max(0, len(pending) - summary["resolved"])
    return summary


def start_shadow_outcome_resolver(
    *,
    journal_module: Any = journal,
    config: ShadowOutcomeConfig | None = None,
    candle_fetcher: CandleFetcher = fetch_confirmed_candles,
) -> dict[str, Any]:
    """Start one daemon resolver without delaying the primary trading cycle."""
    cfg = config or ShadowOutcomeConfig.from_env()
    summary = {
        "enabled": cfg.enabled,
        "started": False,
        "already_running": False,
        "broker_calls": 0,
    }
    if not cfg.enabled:
        return summary
    if not _RESOLVER_LOCK.acquire(blocking=False):
        summary["already_running"] = True
        return summary

    def _worker() -> None:
        try:
            resolve_pending_shadow_outcomes(
                journal_module=journal_module,
                config=cfg,
                candle_fetcher=candle_fetcher,
            )
        finally:
            _RESOLVER_LOCK.release()

    try:
        thread = threading.Thread(
            target=_worker,
            name="shadow_outcome_resolver",
            daemon=True,
        )
        thread.start()
    except Exception:
        _RESOLVER_LOCK.release()
        raise
    summary["started"] = True
    return summary


def _resolve_record(
    record: Mapping[str, Any],
    candles: Iterable[Candle],
    *,
    now: datetime,
    candle_limit: int,
) -> dict[str, Any] | None:
    trigger_ms = _integer(record.get("trigger_timestamp_ms"))
    max_hold = _integer(record.get("max_hold_bars"))
    if trigger_ms is None or max_hold is None or max_hold <= 0:
        return _ineligible_outcome(record, now, "invalid_shadow_record", "invalid_shadow_record")
    ordered = sorted(
        (item for item in candles if isinstance(item, Candle) and item.timestamp_ms >= trigger_ms),
        key=lambda item: item.timestamp_ms,
    )
    expected_ms = trigger_ms
    holding_bars = 0
    for candle in ordered:
        if candle.timestamp_ms < expected_ms:
            continue
        if candle.timestamp_ms > expected_ms:
            return _ineligible_outcome(record, now, "history_gap", "missing_confirmed_candle")
        holding_bars += 1
        stop_hit, target_hit = _touches(record, candle)
        if stop_hit and target_hit:
            return _ineligible_outcome(
                record,
                now,
                "ambiguous_both_touched",
                "ambiguous_intrabar_sequence",
                holding_bars=holding_bars,
            )
        if stop_hit:
            return _priced_outcome(
                record,
                now,
                exit_reason="stop_loss",
                exit_price=float(record["stop_loss"]),
                holding_bars=holding_bars,
            )
        if target_hit:
            return _priced_outcome(
                record,
                now,
                exit_reason="take_profit",
                exit_price=float(record["take_profit"]),
                holding_bars=holding_bars,
            )
        if holding_bars >= max_hold:
            return _priced_outcome(
                record,
                now,
                exit_reason="timeout",
                exit_price=float(candle.close),
                holding_bars=holding_bars,
            )
        expected_ms += BAR_MS

    age_bars = max(0, int((now.timestamp() * 1000 - trigger_ms) // BAR_MS))
    if age_bars >= candle_limit:
        return _ineligible_outcome(record, now, "history_gap", "history_outside_fetch_window")
    return None


def _touches(record: Mapping[str, Any], candle: Candle) -> tuple[bool, bool]:
    side = str(record.get("side"))
    stop = float(record["stop_loss"])
    target = float(record["take_profit"])
    if side == "long":
        return candle.low <= stop, candle.high >= target
    return candle.high >= stop, candle.low <= target


def _priced_outcome(
    record: Mapping[str, Any],
    now: datetime,
    *,
    exit_reason: str,
    exit_price: float,
    holding_bars: int,
) -> dict[str, Any]:
    entry = float(record["entry"])
    stop = float(record["stop_loss"])
    side = str(record["side"])
    slip = float(record.get("slippage_bps", 0.0)) / 10_000.0
    fee_rate = float(record.get("fee_bps_per_leg", 0.0)) / 10_000.0
    filled_entry = entry * (1 + slip if side == "long" else 1 - slip)
    filled_exit = exit_price * (1 - slip if side == "long" else 1 + slip)
    gross = filled_exit - filled_entry if side == "long" else filled_entry - filled_exit
    fees = (filled_entry + filled_exit) * fee_rate
    net = gross - fees
    risk = abs(filled_entry - stop)
    r_multiple = net / risk if risk > 0 else None
    return {
        **dict(record),
        "schema_version": "shadow_outcome.v1",
        "status": "resolved",
        "resolved_at": _iso_utc(now),
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 12),
        "filled_entry_price": round(filled_entry, 12),
        "filled_exit_price": round(filled_exit, 12),
        "holding_bars": holding_bars,
        "gross_pnl_per_unit": round(gross, 12),
        "fees_per_unit": round(fees, 12),
        "net_pnl_per_unit": round(net, 12),
        "risk_per_unit": round(risk, 12),
        "r_multiple": round(r_multiple, 8) if r_multiple is not None else None,
        "counterfactual_eligible": r_multiple is not None and math.isfinite(r_multiple),
        "exclusion_reason": None,
        "last_checked_at": _iso_utc(now),
    }


def _ineligible_outcome(
    record: Mapping[str, Any],
    now: datetime,
    exit_reason: str,
    exclusion_reason: str,
    *,
    holding_bars: int = 0,
) -> dict[str, Any]:
    return {
        **dict(record),
        "schema_version": "shadow_outcome.v1",
        "status": "unresolved",
        "resolved_at": _iso_utc(now),
        "exit_reason": exit_reason,
        "exit_price": None,
        "holding_bars": holding_bars,
        "gross_pnl_per_unit": None,
        "fees_per_unit": None,
        "net_pnl_per_unit": None,
        "risk_per_unit": None,
        "r_multiple": None,
        "counterfactual_eligible": False,
        "exclusion_reason": exclusion_reason,
        "last_checked_at": _iso_utc(now),
    }


def _price_levels(signal: Mapping[str, Any]) -> dict[str, float] | None:
    entry = _number(_first(signal.get("entry_zone"), signal.get("entry")))
    stop = _number(_first(signal.get("invalidation"), signal.get("stop_loss")))
    target = _number(_first(signal.get("target_zone"), signal.get("take_profit")))
    if entry is None or stop is None or target is None:
        return None
    return {"entry": entry, "stop_loss": stop, "take_profit": target}


def _levels_valid(direction: str, *, entry: float, stop_loss: float, take_profit: float) -> bool:
    if min(entry, stop_loss, take_profit) <= 0:
        return False
    if direction == "long":
        return stop_loss < entry < take_profit
    return take_profit < entry < stop_loss


def _canonical_symbol(value: str) -> str:
    symbol = value.strip().upper().replace("/", "-").replace(":USDT", "")
    return symbol.removesuffix("-SWAP")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _nested(row: Mapping[str, Any], parent: str, key: str) -> Any:
    value = row.get(parent)
    return value.get(key) if isinstance(value, Mapping) else None


def _first(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique_strings(*values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else []
        for item in items:
            text = str(item).strip()
            if text and text not in output:
                output.append(text)
    return output


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
