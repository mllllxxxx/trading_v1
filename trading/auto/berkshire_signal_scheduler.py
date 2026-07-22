"""Scheduled Berkshire crypto scans feeding the demo execution pipeline."""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from . import journal
    from . import equity as _equity
    from .adaptive_hybrid import (
        DecisionPolicy,
        build_rule_proposal,
        decision_policy_snapshot,
        load_effective_decision_policy as load_decision_policy,
    )
    from .adaptive_policy_controller import run_adaptive_policy_controller
    from .shadow_score_review_controller import run_shadow_score_review_controller
    from .shadow_score_canary import (
        CanaryRoutingDecision,
        apply_canary_signal,
        canary_decision_policy,
        evaluate_canary_signal,
        run_shadow_score_canary_controller,
    )
    from .shadow_outcomes import (
        ShadowOutcomeConfig,
        annotate_shadow_result,
        capture_shadow_candidates,
        start_shadow_outcome_resolver,
    )
    from .signal_pipeline import run_signal_to_demo_execution
except ImportError:  # pragma: no cover - direct script/test import fallback
    import journal  # type: ignore
    import equity as _equity  # type: ignore
    from adaptive_hybrid import (  # type: ignore
        DecisionPolicy,
        build_rule_proposal,
        decision_policy_snapshot,
        load_effective_decision_policy as load_decision_policy,
    )
    from adaptive_policy_controller import run_adaptive_policy_controller  # type: ignore
    from shadow_score_review_controller import (  # type: ignore
        run_shadow_score_review_controller,
    )
    from shadow_score_canary import (  # type: ignore
        CanaryRoutingDecision,
        apply_canary_signal,
        canary_decision_policy,
        evaluate_canary_signal,
        run_shadow_score_canary_controller,
    )
    from shadow_outcomes import (  # type: ignore
        ShadowOutcomeConfig,
        annotate_shadow_result,
        capture_shadow_candidates,
        start_shadow_outcome_resolver,
    )
    from signal_pipeline import run_signal_to_demo_execution  # type: ignore

try:
    from berkshire_scanner import rank_signal_candidates, scan_crypto_market
except ImportError:  # pragma: no cover - package topology fallback
    from ..berkshire_scanner import rank_signal_candidates, scan_crypto_market  # type: ignore

from strategy_teams import infer_team_id, resolve_team, team_ids_from_env


ScanFn = Callable[..., dict[str, Any]]
PromotionFn = Callable[..., Any]
PolicyControllerFn = Callable[..., dict[str, Any]]
ReviewControllerFn = Callable[..., dict[str, Any]]
CanaryControllerFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class BerkshireSignalSchedulerConfig:
    """Runtime config for scheduled Berkshire signal promotion."""

    enabled: bool
    interval_s: int
    symbols: list[str] | None
    limit: int
    max_promotions: int
    equity_usd: float
    max_llm_attempts_per_cycle: int = 3
    llm_min_confidence: float = 0.72
    llm_min_score: float = 70.0
    llm_symbol_cooldown_minutes: int = 240
    llm_hold_cooldown_minutes: int = 60
    llm_error_cooldown_minutes: int = 15
    llm_cache_ttl_s: int = 21_600
    team_ids: tuple[str, ...] = ("berkshire",)
    shadow_evaluation_enabled: bool = True

    @classmethod
    def from_env(cls) -> "BerkshireSignalSchedulerConfig":
        return cls(
            enabled=_env_bool("BERKSHIRE_SIGNAL_SCHEDULER_ENABLED", False),
            interval_s=max(30, _env_int("BERKSHIRE_SIGNAL_INTERVAL_S", 900)),
            symbols=_symbols_from_env(),
            limit=max(1, min(_env_int("BERKSHIRE_SIGNAL_LIMIT", 50), 50)),
            max_promotions=max(1, min(_env_int("BERKSHIRE_SIGNAL_MAX_PROMOTIONS", 10), 10)),
            equity_usd=_equity.runtime_equity(
                _env_float("BERKSHIRE_SIGNAL_EQUITY_USD", _env_float("AUTO_CAPITAL", 10_000.0))
            ),
            max_llm_attempts_per_cycle=max(
                0,
                min(_env_int("BERKSHIRE_SIGNAL_MAX_LLM_ATTEMPTS_PER_CYCLE", 3), 10),
            ),
            llm_min_confidence=max(0.0, min(_env_float("BERKSHIRE_LLM_MIN_CONFIDENCE", 0.72), 1.0)),
            llm_min_score=max(0.0, _env_float("BERKSHIRE_LLM_MIN_SCORE", 70.0)),
            llm_symbol_cooldown_minutes=max(
                0,
                _env_int("BERKSHIRE_LLM_SYMBOL_COOLDOWN_MINUTES", 240),
            ),
            llm_hold_cooldown_minutes=max(
                0,
                _env_int("BERKSHIRE_LLM_HOLD_COOLDOWN_MINUTES", 60),
            ),
            llm_error_cooldown_minutes=max(
                0,
                _env_int("BERKSHIRE_LLM_ERROR_COOLDOWN_MINUTES", 15),
            ),
            llm_cache_ttl_s=max(0, _env_int("BERKSHIRE_LLM_CACHE_TTL_S", 21_600)),
            team_ids=team_ids_from_env(),
            shadow_evaluation_enabled=_env_bool("AUTO_SHADOW_EVALUATION_ENABLED", True),
        )


def run_once(
    *,
    config: BerkshireSignalSchedulerConfig | None = None,
    scan_fn: ScanFn = scan_crypto_market,
    promotion_fn: PromotionFn = run_signal_to_demo_execution,
    journal_module: Any = journal,
    policy_controller_fn: PolicyControllerFn = run_adaptive_policy_controller,
    review_controller_fn: ReviewControllerFn = run_shadow_score_review_controller,
    canary_controller_fn: CanaryControllerFn = run_shadow_score_canary_controller,
) -> dict[str, Any]:
    """Run one scheduled scan and promote eligible signals."""
    cfg = config or BerkshireSignalSchedulerConfig.from_env()
    shadow_config = ShadowOutcomeConfig.from_env()
    if not cfg.shadow_evaluation_enabled:
        shadow_config = replace(shadow_config, enabled=False)
    shadow_resolution = start_shadow_outcome_resolver(
        journal_module=journal_module,
        config=shadow_config,
    )
    try:
        policy_controller = policy_controller_fn(journal_module=journal_module)
    except Exception as exc:  # noqa: BLE001
        policy_controller = {
            "action": "error",
            "reason": "controller_callback_failed",
            "error": str(exc),
        }
        journal_module.append_decision(
            "adaptive_policy_controller_error",
            policy_controller,
        )
    if cfg.shadow_evaluation_enabled:
        try:
            review_controller = review_controller_fn(journal_module=journal_module)
        except Exception as exc:  # noqa: BLE001
            review_controller = {
                "action": "error",
                "reason": "review_controller_callback_failed",
                "error": str(exc),
            }
            journal_module.append_decision(
                "shadow_score_review_controller_error",
                review_controller,
            )
    else:
        review_controller = {
            "action": "skipped",
            "reason": "shadow_evaluation_disabled",
        }
    try:
        canary_controller = canary_controller_fn(journal_module=journal_module)
    except Exception as exc:  # noqa: BLE001
        canary_controller = {
            "status": "error",
            "routing_enabled": False,
            "reason": "canary_controller_callback_failed",
            "error": str(exc),
        }
        journal_module.append_decision("shadow_score_canary_error", canary_controller)
    block_reason_fn = getattr(journal_module, "trading_block_reason", None)
    block_reason_raw = block_reason_fn() if callable(block_reason_fn) else ""
    block_reason = block_reason_raw if isinstance(block_reason_raw, str) else ""
    killed_fn = getattr(journal_module, "is_killed", lambda: False)
    if not block_reason and killed_fn() is True:
        block_reason = "kill_switch_active"
    if block_reason:
        payload = {
            "reason": block_reason,
            "source": "berkshire_signal_scheduler",
            "shadow_resolution": shadow_resolution,
            "adaptive_policy_controller": policy_controller,
            "shadow_score_review_controller": review_controller,
            "shadow_score_canary": canary_controller,
        }
        journal_module.append_decision("berkshire_signal_scheduler_skip", payload)
        return {"status": "skipped", **payload}

    cycle_policy = load_decision_policy()
    adaptive = _adaptive_policy_enabled()
    cycle_policy_snapshot = decision_policy_snapshot(cycle_policy)
    team_execution_order = _rotated_team_ids(cfg.team_ids, cfg.interval_s)
    canary_cycle_state = {
        "slot_available": not _has_open_canary_position(
            journal_module,
            approval_id=str(canary_controller.get("approval_id") or ""),
        )
    }
    team_results = [
        _run_team_once(
            cfg=cfg,
            team_id=team_id,
            scan_fn=scan_fn,
            promotion_fn=promotion_fn,
            journal_module=journal_module,
            shadow_config=shadow_config,
            cycle_policy=cycle_policy,
            adaptive=adaptive,
            canary_state=canary_controller,
            canary_cycle_state=canary_cycle_state,
        )
        for team_id in team_execution_order
    ]
    if len(team_results) == 1:
        result = team_results[0]
        result["shadow_resolution"] = shadow_resolution
        result["adaptive_policy_controller"] = policy_controller
        result["shadow_score_review_controller"] = review_controller
        result["shadow_score_canary"] = canary_controller
        result["summary"]["shadow_resolution"] = shadow_resolution
        result["summary"]["adaptive_policy_controller"] = policy_controller
        result["summary"]["shadow_score_review_controller"] = review_controller
        result["summary"]["shadow_score_canary"] = canary_controller
        journal_module.append_decision("berkshire_signal_scheduler_cycle", result["summary"])
        return result

    promotions = [
        item
        for result in team_results
        for item in result.get("promotions", [])
    ]
    payload = {
        "team_ids": list(cfg.team_ids),
        "team_execution_order": list(team_execution_order),
        "teams": [result["summary"] for result in team_results],
        "signal_count": sum(int(result["summary"].get("signal_count", 0)) for result in team_results),
        "eligible_candidates": sum(int(result["summary"].get("eligible_candidates", 0)) for result in team_results),
        "llm_attempts": sum(int(result["summary"].get("llm_attempts", 0)) for result in team_results),
        "promotions": len(promotions),
        "executed": sum(1 for item in promotions if item.get("executed")),
        "adapter": os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper"),
        "decision_policy": cycle_policy_snapshot,
        "adaptive_routing_enabled": adaptive,
        "shadow_resolution": shadow_resolution,
        "adaptive_policy_controller": policy_controller,
        "shadow_score_review_controller": review_controller,
        "shadow_score_canary": canary_controller,
    }
    journal_module.append_decision("berkshire_signal_scheduler_cycle", payload)
    return {
        "status": "ok",
        "team_results": team_results,
        "scan": team_results[0].get("scan") if team_results else None,
        "promotions": promotions,
        "summary": payload,
    }


def _run_team_once(
    *,
    cfg: BerkshireSignalSchedulerConfig,
    team_id: str,
    scan_fn: ScanFn,
    promotion_fn: PromotionFn,
    journal_module: Any,
    shadow_config: ShadowOutcomeConfig,
    cycle_policy: DecisionPolicy,
    adaptive: bool,
    canary_state: Mapping[str, Any] | None = None,
    canary_cycle_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Run one team scan and promote eligible signals."""
    canary_state = canary_state or {"routing_enabled": False}
    canary_cycle_state = canary_cycle_state or {"slot_available": False}
    team = resolve_team(team_id)
    scan = _scan_for_team(
        scan_fn,
        cfg,
        team.team_id,
        decision_policy=cycle_policy,
    )
    shadow_capture = capture_shadow_candidates(
        scan.get("signals", []),
        scan_id=str(scan.get("id") or "") or None,
        journal_module=journal_module,
        config=shadow_config,
        decision_policy=cycle_policy,
    )
    portfolio = _portfolio_slots(journal_module, team_id=team.team_id)
    promotion_cap = max(0, min(cfg.max_promotions, portfolio["remaining_slots"]))
    candidates = (
        _rank_canary_candidates(scan.get("signals", []))
        if canary_state.get("routing_enabled") is True
        else _rank_promotable_signals(scan.get("signals", []))
    )
    candidate_routes = _prepare_canary_candidate_routes(
        candidates,
        policy=cycle_policy,
        canary_state=canary_state,
        canary_slot_available=canary_cycle_state["slot_available"],
    )
    open_symbols = _open_symbols(journal_module, team_id=team.team_id)
    cache = _load_llm_signal_cache(journal_module)
    now_ts = time.time()
    llm_attempts = 0
    llm_prefilter_skipped = 0
    duplicate_symbol_skipped = 0
    cooldown_skipped = 0
    cache_skipped = 0
    budget_skipped = 0
    route_rejected = 0
    promotions: list[dict[str, Any]] = []
    default_decision_policy = cycle_policy if adaptive else None
    canary_selected = 0
    canary_vetoed = 0
    for original_signal, prepared_canary_decision in candidate_routes:
        executed_count = sum(1 for item in promotions if item.get("executed"))
        if executed_count >= promotion_cap:
            break
        signal = original_signal
        decision_policy = default_decision_policy
        canary_decision = prepared_canary_decision or evaluate_canary_signal(
            signal,
            policy=cycle_policy,
            canary_state=canary_state,
            canary_slot_available=canary_cycle_state["slot_available"],
        )
        if canary_decision.selected and not canary_cycle_state["slot_available"]:
            canary_decision = evaluate_canary_signal(
                signal,
                policy=cycle_policy,
                canary_state=canary_state,
                canary_slot_available=False,
            )
        if canary_decision.selected:
            canary_selected += 1
            _record_canary_route_selection(
                journal_module,
                signal=signal,
                decision=canary_decision,
            )
            if canary_decision.v2_zone == "reject":
                canary_vetoed += 1
                result_dict = _skip_result(signal, "canary_route", "v2_rule_reject")
                result_dict["routing_experiment"] = canary_decision.routing_experiment
                _record_canary_veto(
                    journal_module,
                    signal=signal,
                    decision=canary_decision,
                )
                promotions.append(result_dict)
                annotate_shadow_result(
                    signal,
                    result_dict,
                    journal_module=journal_module,
                    config=shadow_config,
                    decision_policy=cycle_policy,
                )
                continue
            signal = apply_canary_signal(signal, canary_decision)
            decision_policy = canary_decision_policy(cycle_policy, canary_state)
        if not _looks_demo_promotable(signal):
            continue
        proposal = (
            build_rule_proposal(signal, policy=decision_policy)
            if decision_policy is not None
            else None
        )
        decision_zone = proposal.decision_zone if proposal is not None else "legacy"
        requires_llm = decision_zone == "gray" if adaptive else True
        if adaptive and decision_zone == "reject":
            route_rejected += 1
            result_dict = _skip_result(signal, "adaptive_route", "adaptive_rule_reject")
            promotions.append(result_dict)
            annotate_shadow_result(
                signal,
                result_dict,
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            continue
        if requires_llm and llm_attempts >= cfg.max_llm_attempts_per_cycle:
            break
        if not adaptive:
            threshold_ok, _threshold_reason = _passes_llm_thresholds(signal, cfg)
            if not threshold_ok:
                llm_prefilter_skipped += 1
                continue
        symbol = _signal_symbol(signal)
        if symbol and symbol in open_symbols:
            duplicate_symbol_skipped += 1
            annotate_shadow_result(
                signal,
                _skip_result(signal, "pre_execution_guard", "symbol_already_open_for_team"),
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            continue
        cooldown_active, cooldown_reason = _symbol_cooldown_active(
            cache,
            signal,
            cfg=cfg,
            now_ts=now_ts,
        )
        if cooldown_active:
            cooldown_skipped += 1
            result_dict = _skip_result(signal, "llm_symbol_cooldown", cooldown_reason)
            promotions.append(result_dict)
            annotate_shadow_result(
                signal,
                result_dict,
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            continue
        cached, cache_reason = _fingerprint_cache_active(
            cache,
            signal,
            cfg=cfg,
            now_ts=now_ts,
        )
        if cached:
            cache_skipped += 1
            result_dict = _skip_result(signal, "llm_fingerprint_cache", cache_reason)
            promotions.append(result_dict)
            annotate_shadow_result(
                signal,
                result_dict,
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            continue
        budget_status_fn = getattr(journal_module, "check_llm_budget", None)
        if requires_llm and callable(budget_status_fn):
            budget_source = f"{team.team_id}_signal"
            budget_status = budget_status_fn(source=budget_source)
            if not bool(budget_status.get("allowed", True)):
                budget_skipped += 1
                reason = str(budget_status.get("reason") or "llm_budget_cap")
                record_budget_skip = getattr(journal_module, "record_llm_budget_skip", None)
                if callable(record_budget_skip):
                    record_budget_skip(
                        source=budget_source,
                        reason=reason,
                        status=budget_status,
                    )
                result_dict = _skip_result(signal, "llm_budget", reason)
                promotions.append(result_dict)
                annotate_shadow_result(
                    signal,
                    result_dict,
                    journal_module=journal_module,
                    config=shadow_config,
                    decision_policy=cycle_policy,
                )
                break
        if requires_llm:
            llm_attempts += 1
        try:
            promotion_kwargs: dict[str, Any] = {
                "equity": cfg.equity_usd,
                "autonomy_mode": "paper",
            }
            if decision_policy is not None and _accepts_decision_policy(promotion_fn):
                promotion_kwargs["decision_policy"] = decision_policy
            result = promotion_fn(signal, **promotion_kwargs)
            result_dict = _result_to_dict(result)
            if canary_decision.selected:
                result_dict["routing_experiment"] = canary_decision.routing_experiment
                if result_dict.get("executed"):
                    canary_cycle_state["slot_available"] = False
            promotions.append(result_dict)
            annotate_shadow_result(
                signal,
                result_dict,
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            _remember_llm_attempt(cache, signal, result_dict, now_ts=now_ts, cfg=cfg)
            _write_llm_signal_cache(journal_module, cache)
        except Exception as exc:  # noqa: BLE001
            result_dict = {
                "signal_id": signal.get("signal_id") if isinstance(signal, Mapping) else None,
                "promoted": False,
                "executed": False,
                "stage": "scheduler_promotion",
                "reason": f"promotion_failed: {exc}",
            }
            if canary_decision.selected:
                result_dict["routing_experiment"] = canary_decision.routing_experiment
            promotions.append(result_dict)
            annotate_shadow_result(
                signal,
                result_dict,
                journal_module=journal_module,
                config=shadow_config,
                decision_policy=cycle_policy,
            )
            _remember_llm_attempt(cache, signal, result_dict, now_ts=now_ts, cfg=cfg)
            _write_llm_signal_cache(journal_module, cache)

    payload = {
        "team_id": team.team_id,
        "team_name": team.team_name,
        "strategy_id": team.strategy_id,
        "strategy_name": team.strategy_name,
        **_team_skill_profile_payload(team),
        "scan_id": scan.get("id"),
        "symbol_count": int(scan.get("universe_count", 0) or len(cfg.symbols or [])),
        "signal_count": int(scan.get("signal_count", 0) or 0),
        "top_symbol": scan.get("top_symbol"),
        "top_signal": scan.get("top_signal"),
        "eligible_candidates": len(candidates),
        "selected_candidates": promotion_cap,
        "max_open_positions": portfolio["max_open_positions"],
        "open_positions": portfolio["open_positions"],
        "remaining_slots": portfolio["remaining_slots"],
        "llm_attempts": llm_attempts,
        "llm_attempt_cap": cfg.max_llm_attempts_per_cycle,
        "llm_min_confidence": cfg.llm_min_confidence,
        "llm_min_score": cfg.llm_min_score,
        "llm_prefilter_skipped": llm_prefilter_skipped,
        "duplicate_symbol_skipped": duplicate_symbol_skipped,
        "cooldown_skipped": cooldown_skipped,
        "cache_skipped": cache_skipped,
        "budget_skipped": budget_skipped,
        "adaptive_route_rejected": route_rejected,
        "canary_selected": canary_selected,
        "canary_vetoed": canary_vetoed,
        "shadow_score_canary": dict(canary_state),
        "stage_counts": _count_values(promotions, "stage"),
        "reason_counts": _count_values(promotions, "reason"),
        "promotions": len(promotions),
        "executed": sum(1 for item in promotions if item.get("executed")),
        "adapter": os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper"),
        "decision_policy": decision_policy_snapshot(cycle_policy),
        "adaptive_routing_enabled": adaptive,
        "promotion_results": promotions,
        "shadow_capture": shadow_capture,
    }
    return {"status": "ok", "scan": scan, "promotions": promotions, "summary": payload}


def _team_skill_profile_payload(team: Any) -> dict[str, Any]:
    """Return advisory strategy profile fields for scheduler journaling."""
    return {
        "preferred_playbook_ids": list(getattr(team, "preferred_playbook_ids", ())),
        "required_soft_policy_ids": list(getattr(team, "required_soft_policy_ids", ())),
        "entry_style": getattr(team, "entry_style", None),
        "avoid_conditions": list(getattr(team, "avoid_conditions", ())),
        "llm_guidance": getattr(team, "llm_guidance", None),
        "risk_personality": getattr(team, "risk_personality", None),
    }


def _rotated_team_ids(team_ids: tuple[str, ...], interval_s: int) -> tuple[str, ...]:
    """Rotate first-pick priority across scheduler intervals."""
    if len(team_ids) < 2:
        return team_ids
    cycle = int(time.time() // max(1, interval_s))
    offset = cycle % len(team_ids)
    return team_ids[offset:] + team_ids[:offset]


def main_loop() -> None:
    """Run scheduled Berkshire scans until the process exits or kill switch trips."""
    cfg = BerkshireSignalSchedulerConfig.from_env()
    if not cfg.enabled:
        journal.append_decision(
            "berkshire_signal_scheduler_disabled",
            {"enabled": False, "interval_s": cfg.interval_s},
        )
        return
    journal.append_decision(
        "berkshire_signal_scheduler_start",
        {
            "enabled": True,
            "interval_s": cfg.interval_s,
            "symbols": cfg.symbols,
            "team_ids": list(cfg.team_ids),
            "limit": cfg.limit,
            "max_promotions": cfg.max_promotions,
            "max_llm_attempts_per_cycle": cfg.max_llm_attempts_per_cycle,
            "llm_min_confidence": cfg.llm_min_confidence,
            "llm_min_score": cfg.llm_min_score,
            "llm_symbol_cooldown_minutes": cfg.llm_symbol_cooldown_minutes,
            "llm_cache_ttl_s": cfg.llm_cache_ttl_s,
            "max_open_positions": _env_int("AUTO_MAX_POSITIONS", 10),
            "adapter": os.getenv("SIGNAL_EXECUTION_ADAPTER", "paper"),
        },
    )
    while True:
        try:
            run_once(config=BerkshireSignalSchedulerConfig.from_env())
        except Exception as exc:  # noqa: BLE001
            journal.append_decision(
                "berkshire_signal_scheduler_error",
                {"error": str(exc)},
            )
        time.sleep(BerkshireSignalSchedulerConfig.from_env().interval_s)


def start_in_thread() -> threading.Thread | None:
    """Start the scheduler thread when enabled."""
    cfg = BerkshireSignalSchedulerConfig.from_env()
    if not cfg.enabled:
        return None
    thread = threading.Thread(target=main_loop, name="berkshire_signal_scheduler", daemon=True)
    thread.start()
    return thread


def _looks_demo_promotable(signal: Any) -> bool:
    if not isinstance(signal, Mapping):
        return False
    status_value = signal.get("status") or signal.get("signal")
    return (
        status_value in {"strong_candidate", "candidate"}
        and signal.get("direction") in {"long", "short"}
        and signal.get("action_hint") in {"OPEN_LONG", "OPEN_SHORT"}
        and not signal.get("blockers")
    )


def _rank_promotable_signals(signals: Any) -> list[dict[str, Any]]:
    if not isinstance(signals, list):
        return []
    candidates = [dict(item) for item in signals if _looks_demo_promotable(item)]
    return rank_signal_candidates(candidates)


def _rank_canary_candidates(signals: Any) -> list[dict[str, Any]]:
    """Include blocker-free directional watchlist rows for V2 disagreements."""
    if not isinstance(signals, list):
        return []
    candidates = [
        dict(item)
        for item in signals
        if isinstance(item, Mapping)
        and item.get("direction") in {"long", "short"}
        and item.get("action_hint") in {"OPEN_LONG", "OPEN_SHORT"}
        and not item.get("blockers")
        and not item.get("hard_blockers")
    ]
    return rank_signal_candidates(candidates)


def _prepare_canary_candidate_routes(
    candidates: list[dict[str, Any]],
    *,
    policy: DecisionPolicy,
    canary_state: Mapping[str, Any],
    canary_slot_available: bool,
) -> list[tuple[dict[str, Any], CanaryRoutingDecision | None]]:
    """Prioritize selected V2 promotions without reordering normal V1 rows."""
    if canary_state.get("routing_enabled") is not True:
        return [(signal, None) for signal in candidates]
    routed = [
        (
            signal,
            evaluate_canary_signal(
                signal,
                policy=policy,
                canary_state=canary_state,
                canary_slot_available=canary_slot_available,
            ),
        )
        for signal in candidates
    ]
    selected_promotions = sorted(
        (
            item
            for item in routed
            if item[1].selected and item[1].v2_zone in {"gray", "strong"}
        ),
        key=lambda item: float(item[1].v2_score or 0.0),
        reverse=True,
    )
    selected_ids = {id(item[0]) for item in selected_promotions}
    return selected_promotions + [item for item in routed if id(item[0]) not in selected_ids]


def _record_canary_route_selection(
    journal_module: Any,
    *,
    signal: Mapping[str, Any],
    decision: CanaryRoutingDecision,
) -> None:
    """Journal selection before downstream guards can stop the attempt."""
    append = getattr(journal_module, "append_decision", None)
    if callable(append):
        append(
            "shadow_score_canary_route_selected",
            {
                "signal_id": signal.get("signal_id"),
                "symbol": signal.get("symbol"),
                "direction": signal.get("direction"),
                "routing_experiment": decision.routing_experiment,
            },
        )


def _record_canary_veto(
    journal_module: Any,
    *,
    signal: Mapping[str, Any],
    decision: CanaryRoutingDecision,
) -> None:
    """Journal an explicit no-order result for a selected V2 reject."""
    append = getattr(journal_module, "append_decision", None)
    if callable(append):
        append(
            "shadow_score_canary_route_veto",
            {
                "signal_id": signal.get("signal_id"),
                "symbol": signal.get("symbol"),
                "direction": signal.get("direction"),
                "reason": "v2_rule_reject",
                "executed": False,
                "routing_experiment": decision.routing_experiment,
            },
        )


def _has_open_canary_position(journal_module: Any, *, approval_id: str) -> bool:
    """Enforce one globally attributable canary position across strategy teams."""
    if not approval_id:
        return False
    try:
        positions = journal_module.read_positions()
    except Exception:
        return True
    return any(
        isinstance(position, Mapping)
        and isinstance(position.get("routing_experiment"), Mapping)
        and bool(position["routing_experiment"].get("approval_id"))
        for position in positions
    )


def _scan_for_team(
    scan_fn: ScanFn,
    cfg: BerkshireSignalSchedulerConfig,
    team_id: str,
    *,
    decision_policy: DecisionPolicy,
) -> dict[str, Any]:
    """Inject team and policy only when the scan callback supports them."""
    kwargs: dict[str, Any] = {"symbols": cfg.symbols, "limit": cfg.limit}
    if team_id != "berkshire":
        kwargs["team_id"] = team_id
    if _accepts_decision_policy(scan_fn):
        kwargs["decision_policy"] = decision_policy
    return scan_fn(**kwargs)


def _portfolio_slots(journal_module: Any, *, team_id: str | None = None) -> dict[str, int]:
    max_open = (
        _env_int("STRATEGY_TEAM_MAX_OPEN_POSITIONS", 1)
        if team_id
        else _env_int("AUTO_MAX_POSITIONS", 10)
    )
    try:
        positions = list(journal_module.read_positions())
    except Exception:
        positions = []
        open_positions = max_open
    else:
        if team_id:
            open_positions = sum(1 for position in positions if infer_team_id(position) == team_id)
        else:
            open_positions = len(positions)
    return {
        "max_open_positions": max_open,
        "open_positions": open_positions,
        "remaining_slots": max(0, max_open - open_positions),
    }


def _open_symbols(journal_module: Any, *, team_id: str | None = None) -> set[str]:
    try:
        positions = list(journal_module.read_positions())
    except Exception:
        return set()
    symbols: set[str] = set()
    for position in positions:
        if not isinstance(position, Mapping):
            continue
        if team_id and infer_team_id(position) != team_id:
            continue
        for key in ("symbol", "instId", "ccxt_symbol"):
            raw = position.get(key)
            if isinstance(raw, str) and raw.strip():
                symbols.add(_canonical_symbol(raw))
    return symbols


def _result_to_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, Mapping):
        return dict(result)
    raise TypeError(f"promotion result is not serializable: {type(result).__name__}")


def _accepts_decision_policy(callable_fn: Callable[..., Any]) -> bool:
    """Preserve injected callbacks that predate policy snapshots."""
    try:
        parameters = inspect.signature(callable_fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "decision_policy"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _skip_result(signal: Mapping[str, Any], stage: str, reason: str) -> dict[str, Any]:
    return {
        "signal_id": signal.get("signal_id"),
        "promoted": False,
        "executed": False,
        "stage": stage,
        "reason": reason,
        "symbol": _signal_symbol(signal),
        "team_id": infer_team_id(signal),
    }


def _passes_llm_thresholds(
    signal: Mapping[str, Any],
    cfg: BerkshireSignalSchedulerConfig,
) -> tuple[bool, str]:
    confidence = _as_float(signal.get("confidence"), 0.0)
    score = _as_float(signal.get("score"), 0.0)
    if confidence < cfg.llm_min_confidence:
        return False, "confidence_below_llm_min"
    if score < cfg.llm_min_score:
        return False, "score_below_llm_min"
    return True, ""


def _adaptive_policy_enabled() -> bool:
    """Return whether scheduler routing uses canonical adaptive zones."""
    return os.getenv("AUTO_DECISION_POLICY", "adaptive_hybrid_v1").strip().lower() == "adaptive_hybrid_v1"


def _signal_symbol(signal: Mapping[str, Any]) -> str:
    raw = signal.get("symbol") or signal.get("instId") or signal.get("ccxt_symbol")
    return _canonical_symbol(str(raw or ""))


def _canonical_symbol(symbol: str) -> str:
    value = symbol.strip().upper().replace("/", "-").replace(":USDT", "")
    if value.endswith("-SWAP"):
        value = value[:-5]
    return value


def _signal_fingerprint(signal: Mapping[str, Any]) -> str:
    evidence = signal.get("evidence")
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    price = _as_float(
        signal.get("current_price")
        or signal.get("last_price")
        or evidence_map.get("last_price")
        or evidence_map.get("price"),
        0.0,
    )
    confidence = _as_float(signal.get("confidence"), 0.0)
    feature_snapshot = evidence_map.get("feature_snapshot")
    feature_map = feature_snapshot if isinstance(feature_snapshot, Mapping) else {}
    one_hour = feature_map.get("1H")
    one_hour_map = one_hour if isinstance(one_hour, Mapping) else {}
    atr = _as_float(one_hour_map.get("atr14"), 0.0)
    price_band = (
        str(round(price / (0.5 * atr)))
        if price > 0 and atr > 0
        else "na" if price <= 0 else str(round(_safe_log(price) / 0.005))
    )
    confidence_band = str(int(confidence * 20))
    regime = str(signal.get("regime") or evidence_map.get("regime") or "unknown").lower()
    playbooks = signal.get("preferred_playbook_ids") or evidence_map.get("preferred_playbook_ids") or []
    playbook = str(playbooks[0]) if isinstance(playbooks, list) and playbooks else "none"
    return "|".join(
        [
            _signal_symbol(signal),
            infer_team_id(signal),
            str(signal.get("direction") or "unknown").lower(),
            str(signal.get("status") or signal.get("signal") or "unknown").lower(),
            regime,
            playbook,
            confidence_band,
            price_band,
        ]
    )


def _safe_log(value: float) -> float:
    import math

    try:
        return math.log(max(value, 1e-12))
    except ValueError:
        return 0.0


def _cache_file(journal_module: Any) -> Path | None:
    root = getattr(journal_module, "JOURNAL_DIR", None)
    if isinstance(root, Path):
        return root / "berkshire_llm_cache.json"
    return None


def _load_llm_signal_cache(journal_module: Any) -> dict[str, Any]:
    path = _cache_file(journal_module)
    if path is None or not path.exists():
        return {"symbols": {}, "fingerprints": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"symbols": {}, "fingerprints": {}}
    if not isinstance(payload, dict):
        return {"symbols": {}, "fingerprints": {}}
    payload.setdefault("symbols", {})
    payload.setdefault("fingerprints", {})
    return payload


def _write_llm_signal_cache(journal_module: Any, cache: dict[str, Any]) -> None:
    path = _cache_file(journal_module)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        return


def _symbol_cooldown_active(
    cache: dict[str, Any],
    signal: Mapping[str, Any],
    *,
    cfg: BerkshireSignalSchedulerConfig,
    now_ts: float,
) -> tuple[bool, str]:
    if cfg.llm_symbol_cooldown_minutes <= 0:
        return False, ""
    symbols = cache.get("symbols", {})
    if not isinstance(symbols, Mapping):
        return False, ""
    entry = symbols.get(_team_symbol_key(signal))
    if not isinstance(entry, Mapping):
        return False, ""
    age_s = now_ts - _as_float(entry.get("last_ts"), 0.0)
    cooldown_s = _effective_entry_cooldown(
        entry,
        cfg=cfg,
        default_s=float(cfg.llm_symbol_cooldown_minutes * 60),
    )
    if age_s < cooldown_s:
        remaining = int(max(0, cooldown_s - age_s))
        return True, f"symbol_cooldown_active:{remaining}s"
    return False, ""


def _fingerprint_cache_active(
    cache: dict[str, Any],
    signal: Mapping[str, Any],
    *,
    cfg: BerkshireSignalSchedulerConfig,
    now_ts: float,
) -> tuple[bool, str]:
    if cfg.llm_cache_ttl_s <= 0:
        return False, ""
    fingerprints = cache.get("fingerprints", {})
    if not isinstance(fingerprints, Mapping):
        return False, ""
    entry = fingerprints.get(_signal_fingerprint(signal))
    if not isinstance(entry, Mapping):
        return False, ""
    age_s = now_ts - _as_float(entry.get("last_ts"), 0.0)
    outcome_ttl = _effective_entry_cooldown(
        entry,
        cfg=cfg,
        default_s=float(cfg.llm_cache_ttl_s),
    )
    ttl_s = min(float(cfg.llm_cache_ttl_s), outcome_ttl)
    if age_s < ttl_s:
        return True, f"fingerprint_cache_hit:{int(max(0, ttl_s - age_s))}s"
    return False, ""


def _remember_llm_attempt(
    cache: dict[str, Any],
    signal: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    now_ts: float,
    cfg: BerkshireSignalSchedulerConfig | None = None,
) -> None:
    symbol = _signal_symbol(signal)
    symbol_key = _team_symbol_key(signal)
    fingerprint = _signal_fingerprint(signal)
    outcome_class, cooldown_s = _attempt_cooldown(result, cache_config=cfg)
    entry = {
        "last_ts": now_ts,
        "signal_id": signal.get("signal_id"),
        "fingerprint": fingerprint,
        "stage": result.get("stage"),
        "reason": result.get("reason"),
        "executed": bool(result.get("executed")),
        "outcome_class": outcome_class,
        "cooldown_s": cooldown_s,
    }
    symbols = cache.setdefault("symbols", {})
    fingerprints = cache.setdefault("fingerprints", {})
    if isinstance(symbols, dict) and symbol:
        symbols[symbol_key] = entry
    if isinstance(fingerprints, dict):
        fingerprints[fingerprint] = entry


def _attempt_cooldown(
    result: Mapping[str, Any],
    *,
    cache_config: BerkshireSignalSchedulerConfig | None,
) -> tuple[str, int]:
    """Classify an attempt so transient failures do not block a symbol for hours."""
    cfg = cache_config
    executed_minutes = cfg.llm_symbol_cooldown_minutes if cfg else 240
    hold_minutes = cfg.llm_hold_cooldown_minutes if cfg else 60
    error_minutes = cfg.llm_error_cooldown_minutes if cfg else 15
    if bool(result.get("executed")):
        return "executed", executed_minutes * 60
    stage = str(result.get("stage") or "").lower()
    reason = str(result.get("reason") or "").lower()
    transient_tokens = (
        "json",
        "schema",
        "validation failed",
        "entry_plan",
        "risk_plan",
        "order_type",
        "provider",
        "stale",
        "timeout",
        "budget exhausted",
        "budget gate unavailable",
        "budget cap",
        "call cap",
        "execution_failed",
        "metadata unavailable",
        "market_dossier_failed",
        "promotion_failed",
        "empty ticket",
        "empty tradedecisionticket",
        "no valid",
    )
    if any(token in f"{stage} {reason}" for token in transient_tokens):
        return "transient_error", error_minutes * 60
    if "hold" in stage or "hold" in reason or "request_more_data" in reason:
        return "hold", hold_minutes * 60
    return "setup_rejected", hold_minutes * 60


def _effective_entry_cooldown(
    entry: Mapping[str, Any],
    *,
    cfg: BerkshireSignalSchedulerConfig,
    default_s: float,
) -> float:
    """Apply current transient classification to cache entries written by older code."""

    stored_s = _as_float(entry.get("cooldown_s"), default_s)
    outcome_class, classified_s = _attempt_cooldown(entry, cache_config=cfg)
    if outcome_class == "transient_error":
        return min(stored_s, float(classified_s))
    return stored_s


def _count_values(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _team_symbol_key(signal: Mapping[str, Any]) -> str:
    """Return cache key that isolates each team's symbol attempts."""
    team_id = infer_team_id(signal)
    return f"{team_id}:{_signal_symbol(signal)}"


def _symbols_from_env() -> list[str] | None:
    raw = os.getenv("BERKSHIRE_SIGNAL_SYMBOLS") or ""
    values = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return values or None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


if __name__ == "__main__":
    main_loop()
