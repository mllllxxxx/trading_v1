"""AI Berkshire research and signal-source routes for Trade_V1.

This module turns the upstream AI Berkshire idea into an operational, local
research workflow and crypto SignalCandidate source for the Web UI. It
defaults to signal-only output. When explicitly requested, eligible signals may
feed the LLM-governed demo trading pipeline only through the shared contracts,
verifier, risk compiler, execution adapter, and journal.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from berkshire_scanner import rank_signal_candidates, scan_crypto_market
from strategy_teams import build_team_dashboard, resolve_team, team_ids_from_env

try:
    from auto.equity import runtime_equity
    from auto.signal_pipeline import run_signal_to_demo_execution
except Exception:  # pragma: no cover - package topology fallback
    from equity import runtime_equity  # type: ignore
    from signal_pipeline import run_signal_to_demo_execution  # type: ignore

LaneKey = Literal["crypto", "forex"]
SkillKey = Literal[
    "investment-team",
    "investment-research",
    "investment-checklist",
    "quality-screen",
    "news-pulse",
    "thesis-tracker",
    "portfolio-review",
]

AuthDep = Callable[..., Any]

_STATE_LOCK = threading.RLock()
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9./:-]{1,24}$")
_PRICE_Q = Decimal("0.0001")
_PCT_Q = Decimal("0.01")
_SCORE_Q = Decimal("0.1")


class BerkshireResearchRequest(BaseModel):
    """Request body for creating one Berkshire-style research run."""

    lane: LaneKey
    symbol: str = Field(..., min_length=2, max_length=25)
    skill: SkillKey = "investment-team"
    catalyst: str = Field("", max_length=1000)
    thesis: str = Field("", max_length=3000)
    entry_price: str | None = Field(None, max_length=64)
    stop_loss: str | None = Field(None, max_length=64)
    target_price: str | None = Field(None, max_length=64)
    capital_usd: str | None = Field(None, max_length=64)

    @field_validator("symbol")
    @classmethod
    def _symbol_shape(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _SYMBOL_RE.fullmatch(normalized):
            raise ValueError("symbol must be 2-25 chars: A-Z, 0-9, '.', '/', ':', '-'")
        return normalized

    @field_validator("catalyst", "thesis")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


class BerkshireCryptoScanRequest(BaseModel):
    """Request body for creating one crypto signal scan."""

    symbols: list[str] | None = Field(None, max_length=50)
    limit: int = Field(50, ge=1, le=50)
    team_id: str = Field("berkshire", min_length=2, max_length=40)
    auto_promote_demo: bool = False
    max_promotions: int = Field(10, ge=1, le=10)
    equity_usd: float | None = Field(None, gt=0)

    @field_validator("symbols")
    @classmethod
    def _symbols_shape(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_symbols(value)

    @field_validator("team_id")
    @classmethod
    def _team_id_shape(cls, value: str) -> str:
        return resolve_team(value).team_id


class TradingTeamsScanRequest(BaseModel):
    """Request body for scanning one or more tournament teams."""

    symbols: list[str] | None = Field(None, max_length=50)
    limit: int = Field(50, ge=1, le=50)
    team_ids: list[str] | None = Field(None, max_length=4)
    auto_promote_demo: bool = False
    max_promotions: int = Field(10, ge=1, le=10)
    equity_usd: float | None = Field(None, gt=0)

    @field_validator("symbols")
    @classmethod
    def _symbols_shape(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_symbols(value)

    @field_validator("team_ids")
    @classmethod
    def _team_ids_shape(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [resolve_team(item).team_id for item in value]
        return list(dict.fromkeys(normalized))


def _normalize_symbols(value: list[str] | None) -> list[str] | None:
    """Normalize request symbols and reject unsafe shapes."""
    if value is None:
        return None
    normalized: list[str] = []
    for raw in value:
        symbol = str(raw).strip().upper()
        if symbol.endswith("-SWAP"):
            symbol = symbol[: -len("-SWAP")]
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError("symbols must be 2-25 chars: A-Z, 0-9, '.', '/', ':', '-'")
        if symbol not in normalized:
            normalized.append(symbol)
    return normalized


def register_berkshire_routes(app: FastAPI, require_auth: AuthDep | None = None) -> None:
    """Register AI Berkshire research endpoints on the host FastAPI app."""
    if require_auth is None:
        host = sys.modules.get("api_server") or sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover - only odd import topologies
            raise RuntimeError("register_berkshire_routes requires require_auth")
        require_auth = host.require_auth

    @app.get("/api/berkshire/state", dependencies=[Depends(require_auth)])
    async def get_berkshire_state() -> dict[str, Any]:
        """Return the persisted AI Berkshire desk state."""
        return _build_state()

    @app.post(
        "/api/berkshire/research",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_berkshire_research(payload: BerkshireResearchRequest) -> dict[str, Any]:
        """Create and persist one local Berkshire-style research run."""
        run = _create_research_run(payload)
        store = _load_store()
        runs = store.setdefault("runs", [])
        runs.insert(0, run)
        del runs[50:]
        store["updated_at"] = _now_iso()
        store["active_run_id"] = run["id"]
        _save_store(store)
        state = _build_state(store)
        return {"status": "ok", "run": run, "state": state}

    @app.post(
        "/api/berkshire/crypto/scan",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def scan_berkshire_crypto(payload: BerkshireCryptoScanRequest) -> dict[str, Any]:
        """Create and persist one crypto SignalCandidate scan."""
        team = resolve_team(payload.team_id)
        scan = scan_crypto_market(symbols=payload.symbols, limit=payload.limit, team_id=team.team_id)
        if payload.auto_promote_demo:
            scan["demo_promotions"] = _promote_scan_signals_to_demo(
                scan,
                max_promotions=payload.max_promotions,
                equity=payload.equity_usd or runtime_equity(team.team_capital_usd),
            )
        store = _load_store()
        scans = store.setdefault("crypto_scans", [])
        scans.insert(0, scan)
        del scans[20:]
        events = store.setdefault("system_events", _system_events())
        events.insert(
            0,
            {
                "time": _time_label(scan.get("created_at")),
                "label": "Crypto signal scan",
                "value": f"{scan.get('signal_count', 0)} signals, top {scan.get('top_symbol') or 'n/a'}",
                "tone": "success" if scan.get("top_signal") in {"strong_candidate", "candidate"} else "info",
            },
        )
        del events[20:]
        store["updated_at"] = _now_iso()
        _save_store(store)
        state = _build_state(store)
        return {"status": "ok", "scan": scan, "state": state}

    @app.get("/api/trading-teams/status", dependencies=[Depends(require_auth)])
    async def get_trading_teams_status() -> dict[str, Any]:
        """Return strategy-team tournament metrics from journal evidence."""
        try:
            from auto import journal as _journal  # type: ignore
            _journal.ensure_dirs()
            positions = _journal.read_positions()
            closed = _journal.read_closed_trades()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc), "teams": []}
        return {
            "status": "ok",
            "ts": _now_iso(),
            "teams": build_team_dashboard(positions, closed),
        }

    @app.post(
        "/api/trading-teams/crypto/scan",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def scan_trading_teams_crypto(payload: TradingTeamsScanRequest) -> dict[str, Any]:
        """Create crypto SignalCandidate scans for multiple strategy teams."""
        team_ids = payload.team_ids or list(team_ids_from_env())
        scans: list[dict[str, Any]] = []
        for team_id in team_ids:
            team = resolve_team(team_id)
            scan = scan_crypto_market(symbols=payload.symbols, limit=payload.limit, team_id=team.team_id)
            if payload.auto_promote_demo:
                scan["demo_promotions"] = _promote_scan_signals_to_demo(
                    scan,
                    max_promotions=payload.max_promotions,
                    equity=payload.equity_usd or runtime_equity(team.team_capital_usd),
                )
            scans.append(scan)
        return {"status": "ok", "scans": scans, "team_count": len(scans)}


def _promote_scan_signals_to_demo(
    scan: dict[str, Any],
    *,
    max_promotions: int,
    equity: float,
) -> list[dict[str, Any]]:
    """Promote eligible scan signals through the demo execution pipeline."""
    promotions: list[dict[str, Any]] = []
    candidates = rank_signal_candidates([
        dict(signal)
        for signal in scan.get("signals", [])
        if _looks_demo_promotable(signal)
    ])
    cap = min(max_promotions, _env_int("AUTO_MAX_POSITIONS", 10))
    for signal in candidates:
        executed_count = sum(1 for item in promotions if item.get("executed"))
        if executed_count >= cap:
            break
        result = run_signal_to_demo_execution(
            signal,
            equity=equity,
            autonomy_mode="paper",
        )
        promotions.append(result.to_dict())
    return promotions


def _looks_demo_promotable(signal: Any) -> bool:
    """Cheap prefilter before the full SignalCandidate validator runs."""
    if not isinstance(signal, dict):
        return False
    status_value = signal.get("status") or signal.get("signal")
    return (
        status_value in {"strong_candidate", "candidate"}
        and signal.get("direction") in {"long", "short"}
        and signal.get("action_hint") in {"OPEN_LONG", "OPEN_SHORT"}
        and not signal.get("blockers")
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _data_dir() -> Path:
    """Return the persistent Berkshire data directory."""
    return Path(os.getenv("VIBE_TRADING_HOME", "/data")) / "berkshire"


def _state_file() -> Path:
    """Return the JSON state file path."""
    return _data_dir() / "state.json"


def _now_iso() -> str:
    """Return UTC timestamp with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_store() -> dict[str, Any]:
    """Load persisted state, backing up corrupt JSON and starting clean."""
    path = _state_file()
    with _STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            store = _empty_store()
            _write_json(path, store)
            return store
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = path.with_suffix(f".corrupt.{int(time.time())}.bak")
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
            raw = _empty_store()
            raw["system_events"].insert(
                0,
                {
                    "time": _time_label(),
                    "label": "Berkshire state reset",
                    "value": f"corrupt store backed up to {backup.name}",
                    "tone": "warning",
                },
            )
            _write_json(path, raw)
        if not isinstance(raw, dict):
            raw = _empty_store()
        raw.setdefault("runs", [])
        raw.setdefault("crypto_scans", [])
        raw.setdefault("system_events", _system_events())
        raw.setdefault("active_run_id", None)
        raw.setdefault("created_at", _now_iso())
        raw.setdefault("updated_at", raw["created_at"])
        return raw


def _save_store(store: dict[str, Any]) -> None:
    """Persist state atomically."""
    with _STATE_LOCK:
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, store)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _empty_store() -> dict[str, Any]:
    now = _now_iso()
    return {
        "schema_version": "berkshire.v1",
        "created_at": now,
        "updated_at": now,
        "active_run_id": None,
        "runs": [],
        "crypto_scans": [],
        "system_events": _system_events(),
    }


def _build_state(store: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the API state payload consumed by the Berkshire screen."""
    store = store or _load_store()
    runs = [r for r in store.get("runs", []) if isinstance(r, dict)]
    scans = [s for s in store.get("crypto_scans", []) if isinstance(s, dict)]
    active_run_id = store.get("active_run_id")
    active_run = next((r for r in runs if r.get("id") == active_run_id), runs[0] if runs else None)
    return {
        "status": "ok",
        "ts": _now_iso(),
        "schema_version": store.get("schema_version", "berkshire.v1"),
        "lanes": _lanes(runs, scans),
        "pipelines": _pipelines(),
        "analyst_pods": _analyst_pods(),
        "roadmap": _roadmap(),
        "capabilities": _capabilities(),
        "requirements": _requirements(),
        "crypto_scans": scans[:10],
        "latest_crypto_scan": scans[0] if scans else None,
        "runs": runs[:20],
        "active_run": active_run,
        "audit_events": _audit_events(store, runs),
    }


def _create_research_run(payload: BerkshireResearchRequest) -> dict[str, Any]:
    """Create one deterministic four-lens research run."""
    financial = _financial_checks(payload)
    analysts = _analysts(payload, financial)
    checklist = _checklist(payload, financial)
    avg_score = _average_score(analysts)
    verdict = _verdict(payload, checklist, avg_score)
    info_grade = _info_grade(payload, financial)
    conviction = _conviction(avg_score, checklist, payload.lane)

    run_id = f"brk_{uuid.uuid4().hex[:16]}"
    created_at = _now_iso()
    report = _report_markdown(
        payload=payload,
        analysts=analysts,
        checklist=checklist,
        financial=financial,
        verdict=verdict,
        info_grade=info_grade,
        conviction=conviction,
    )
    return {
        "id": run_id,
        "created_at": created_at,
        "lane": payload.lane,
        "symbol": payload.symbol,
        "skill": payload.skill,
        "status": "complete",
        "mode": "research_only",
        "verdict": verdict,
        "info_grade": info_grade,
        "conviction": conviction,
        "summary": _summary(payload, verdict, avg_score),
        "catalyst": payload.catalyst,
        "thesis": payload.thesis,
        "analysts": analysts,
        "checklist": checklist,
        "financial_checks": financial,
        "audit": [
            {
                "time": _time_label(created_at),
                "label": "Research run created",
                "value": f"{payload.skill} on {payload.symbol}",
                "tone": "info",
            },
            {
                "time": _time_label(created_at),
                "label": "Execution guard",
                "value": "research_only, no order payload generated",
                "tone": "success",
            },
        ],
        "report_markdown": report,
    }


def _financial_checks(payload: BerkshireResearchRequest) -> dict[str, Any]:
    """Run Decimal-based price sanity checks when price fields are provided."""
    provided = [payload.entry_price, payload.stop_loss, payload.target_price]
    if not any(v not in (None, "") for v in provided):
        return {
            "status": "not_provided",
            "tone": "neutral",
            "summary": "No entry, stop, and target supplied. Risk/reward audit skipped.",
            "items": [],
        }
    if not all(v not in (None, "") for v in provided):
        return {
            "status": "incomplete",
            "tone": "warning",
            "summary": "Entry, stop, and target are all required for risk/reward audit.",
            "items": [],
        }

    entry = _parse_decimal("entry_price", payload.entry_price)
    stop = _parse_decimal("stop_loss", payload.stop_loss)
    target = _parse_decimal("target_price", payload.target_price)
    capital = _parse_decimal("capital_usd", payload.capital_usd) if payload.capital_usd else None

    if entry <= 0 or stop <= 0 or target <= 0:
        raise HTTPException(status_code=400, detail="price fields must be positive")
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0:
        raise HTTPException(status_code=400, detail="stop_loss must differ from entry_price")
    direction = "long" if target > entry and stop < entry else "short" if target < entry and stop > entry else "invalid"
    rr = (reward / risk).quantize(_PRICE_Q, rounding=ROUND_HALF_UP)
    risk_pct = ((risk / entry) * Decimal("100")).quantize(_PCT_Q, rounding=ROUND_HALF_UP)
    risk_usd = None
    if capital is not None and capital > 0:
        risk_usd = ((capital * risk_pct) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    tone = "danger" if direction == "invalid" or rr < Decimal("1") else "warning" if rr < Decimal("2") else "success"
    return {
        "status": "ok" if direction != "invalid" else "invalid",
        "tone": tone,
        "summary": f"{direction} setup, R/R {rr}, risk {risk_pct}%",
        "direction": direction,
        "entry_price": _dec(entry),
        "stop_loss": _dec(stop),
        "target_price": _dec(target),
        "risk_reward": _dec(rr),
        "risk_pct": format(risk_pct, "f"),
        "risk_usd": format(risk_usd, "f") if risk_usd is not None else None,
        "items": [
            {"label": "entry", "value": _dec(entry), "tone": "neutral"},
            {"label": "stop", "value": _dec(stop), "tone": "warning"},
            {"label": "target", "value": _dec(target), "tone": "success"},
            {"label": "risk_reward", "value": _dec(rr), "tone": tone},
        ],
    }


def _parse_decimal(label: str, raw: str | None) -> Decimal:
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a decimal string") from exc


def _dec(value: Decimal) -> str:
    return format(value.quantize(_PRICE_Q, rounding=ROUND_HALF_UP), "f")


def _analysts(payload: BerkshireResearchRequest, financial: dict[str, Any]) -> list[dict[str, Any]]:
    templates = [
        ("business_model", "Duan Yongping lens", "Business quality", "Does the trade thesis describe a durable, simple edge?"),
        ("valuation_quality", "Buffett lens", "Valuation and margin", "Is the price/risk setup attractive enough to wait for?"),
        ("inversion", "Munger lens", "Failure mode", "What can kill the thesis and how obvious is that risk?"),
        ("long_term_certainty", "Li Lu lens", "Long-term certainty", "Can this idea survive regime shifts and uncertainty?"),
    ]
    return [
        _analyst_payload(payload, financial, key, name, focus, question)
        for key, name, focus, question in templates
    ]


def _analyst_payload(
    payload: BerkshireResearchRequest,
    financial: dict[str, Any],
    key: str,
    name: str,
    focus: str,
    question: str,
) -> dict[str, Any]:
    score = Decimal("3.0")
    if len(payload.thesis) >= 120:
        score += Decimal("0.4")
    elif len(payload.thesis) >= 40:
        score += Decimal("0.2")
    if payload.catalyst:
        score += Decimal("0.2")
    if financial.get("status") == "ok":
        rr = Decimal(str(financial.get("risk_reward", "0")))
        if rr >= Decimal("2"):
            score += Decimal("0.4")
        elif rr < Decimal("1"):
            score -= Decimal("0.4")
    elif financial.get("status") == "invalid":
        score -= Decimal("0.8")
    if payload.lane == "forex":
        score -= Decimal("0.3")
    if key == "inversion" and payload.catalyst:
        score += Decimal("0.2")
    if key == "long_term_certainty" and payload.lane == "forex":
        score -= Decimal("0.2")
    score = max(Decimal("1.0"), min(Decimal("5.0"), score)).quantize(_SCORE_Q, rounding=ROUND_HALF_UP)
    stance = "support" if score >= Decimal("3.8") else "challenge" if score < Decimal("3.0") else "watch"
    return {
        "key": key,
        "name": name,
        "focus": focus,
        "question": question,
        "score": float(score),
        "stance": stance,
        "finding": _finding(payload, financial, key, stance),
        "concern": _concern(payload, financial, key),
    }


def _finding(payload: BerkshireResearchRequest, financial: dict[str, Any], key: str, stance: str) -> str:
    if key == "business_model":
        return f"{payload.symbol} has a researchable setup, but the edge must stay explicit and falsifiable."
    if key == "valuation_quality":
        return financial.get("summary", "No price audit supplied, so valuation quality stays unproven.")
    if key == "inversion":
        return "The strongest version of the bear case is tracked before any conviction is raised."
    if payload.lane == "forex":
        return "Forex thesis is useful for research, but execution certainty is blocked by missing broker/session contracts."
    return f"Stance is {stance}; thesis can be tracked but cannot override hard validator gates."


def _concern(payload: BerkshireResearchRequest, financial: dict[str, Any], key: str) -> str:
    if payload.lane == "forex":
        return "Forex lane has no live adapter, economic calendar, or spread guard yet."
    if financial.get("status") in {"not_provided", "incomplete"}:
        return "Risk/reward is not fully audited with Decimal price inputs."
    if key == "inversion":
        return "Need a concrete invalidation trigger, not only a bullish catalyst."
    return "Needs live evidence refresh before promotion from research to trading context."


def _checklist(payload: BerkshireResearchRequest, financial: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _check("Circle of competence", bool(payload.thesis), "Thesis provided", "Thesis is missing"),
        _check("Catalyst clarity", bool(payload.catalyst), "Catalyst recorded", "Catalyst not recorded"),
        _check(
            "Decimal risk audit",
            financial.get("status") == "ok",
            financial.get("summary", "Risk audit passed"),
            financial.get("summary", "Risk audit not complete"),
            warn_only=True,
        ),
        _check(
            "Execution isolation",
            True,
            "Research output cannot place orders or override validator",
            "Execution guard missing",
        ),
        _check(
            "Forex readiness",
            payload.lane != "forex",
            "Crypto lane can feed existing advisory context",
            "Forex is research-only until broker/session/spread contracts exist",
            block=payload.lane == "forex",
        ),
    ]


def _check(
    label: str,
    ok: bool,
    pass_detail: str,
    fail_detail: str,
    *,
    warn_only: bool = False,
    block: bool = False,
) -> dict[str, Any]:
    if ok:
        return {"label": label, "status": "pass", "tone": "success", "detail": pass_detail}
    status_value = "block" if block else "warn" if warn_only else "warn"
    return {"label": label, "status": status_value, "tone": "danger" if block else "warning", "detail": fail_detail}


def _average_score(analysts: list[dict[str, Any]]) -> Decimal:
    total = sum(Decimal(str(a.get("score", 0))) for a in analysts)
    return (total / Decimal(max(1, len(analysts)))).quantize(_SCORE_Q, rounding=ROUND_HALF_UP)


def _verdict(payload: BerkshireResearchRequest, checklist: list[dict[str, Any]], avg_score: Decimal) -> str:
    if any(item.get("status") == "block" for item in checklist):
        return "research_only_blocked"
    if avg_score >= Decimal("3.8") and payload.lane == "crypto":
        return "pass_research"
    if avg_score < Decimal("3.0"):
        return "reject_research"
    return "gray_zone"


def _info_grade(payload: BerkshireResearchRequest, financial: dict[str, Any]) -> str:
    richness = len(payload.thesis) + len(payload.catalyst)
    if richness >= 260 and financial.get("status") == "ok":
        return "A"
    if richness >= 90:
        return "B"
    return "C"


def _conviction(avg_score: Decimal, checklist: list[dict[str, Any]], lane: str) -> int:
    base = int((avg_score / Decimal("5.0")) * Decimal("100"))
    if any(item.get("status") == "block" for item in checklist):
        base = min(base, 45)
    if lane == "forex":
        base = min(base, 52)
    return max(10, min(90, base))


def _summary(payload: BerkshireResearchRequest, verdict: str, avg_score: Decimal) -> str:
    return (
        f"{payload.symbol} completed {payload.skill} run with {verdict}; "
        f"four-lens average score {avg_score}/5. Output is research-only."
    )


def _report_markdown(
    *,
    payload: BerkshireResearchRequest,
    analysts: list[dict[str, Any]],
    checklist: list[dict[str, Any]],
    financial: dict[str, Any],
    verdict: str,
    info_grade: str,
    conviction: int,
) -> str:
    lines = [
        f"# Berkshire Research: {payload.symbol}",
        "",
        f"- Lane: {payload.lane}",
        f"- Skill: {payload.skill}",
        f"- Verdict: {verdict}",
        f"- Info grade: {info_grade}",
        f"- Conviction: {conviction}/100",
        "- Mode: research_only",
        "",
        "## Four-lens view",
    ]
    for analyst in analysts:
        lines.append(f"- {analyst['name']} ({analyst['score']}/5): {analyst['finding']}")
    lines.extend(["", "## Checklist"])
    for item in checklist:
        lines.append(f"- {item['status'].upper()} {item['label']}: {item['detail']}")
    lines.extend(["", "## Financial rigor", financial.get("summary", "No financial check.")])
    if payload.thesis:
        lines.extend(["", "## Thesis", payload.thesis])
    if payload.catalyst:
        lines.extend(["", "## Catalyst", payload.catalyst])
    return "\n".join(lines)


def _lanes(runs: list[dict[str, Any]], scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = {
        "crypto": sum(1 for run in runs if run.get("lane") == "crypto"),
        "forex": sum(1 for run in runs if run.get("lane") == "forex"),
    }
    latest_scan = scans[0] if scans else {}
    latest_signal_count = str(latest_scan.get("signal_count", 0)) if latest_scan else "0"
    return [
        {
            "key": "crypto",
            "label": "Crypto Futures",
            "status": "live",
            "status_label": "Live lane",
            "subtitle": "OKX swap execution with confluence, validator, bracket orders, and journal telemetry.",
            "execution": "OKX USDT SWAP",
            "universe": "Top 50 market cap coins",
            "risk_policy": "Dynamic 0.5% to 5% risk, 5x to 10x leverage",
            "readiness": min(90, 82 + min(8, counts["crypto"])),
            "instruments": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "LINK-USDT", "XRP-USDT"],
            "blockers": ["Berkshire scoring remains advisory", "Cross-lane exposure ledger pending"],
            "telemetry": [
                {"label": "runtime", "value": "connected", "tone": "success"},
                {"label": "research runs", "value": str(counts["crypto"]), "tone": "info"},
                {"label": "signals", "value": latest_signal_count, "tone": "accent" if scans else "neutral"},
                {"label": "validator", "value": "hard gate", "tone": "success"},
            ],
        },
        {
            "key": "forex",
            "label": "Forex",
            "status": "foundation",
            "status_label": "Foundation lane",
            "subtitle": "Parallel research desk for FX majors, metals, macro calendar, and broker adapter planning.",
            "execution": "Research-only, broker adapter planned",
            "universe": "Majors, crosses, XAU, XAG",
            "risk_policy": "Pending spread, session, and rollover controls",
            "readiness": min(48, 34 + min(10, counts["forex"] * 2)),
            "instruments": ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "XAU/USD"],
            "blockers": ["Broker adapter missing", "Economic calendar feed missing", "FX journal schema not extended"],
            "telemetry": [
                {"label": "runtime", "value": "planned", "tone": "neutral"},
                {"label": "research runs", "value": str(counts["forex"]), "tone": "info"},
                {"label": "validator", "value": "contract needed", "tone": "warning"},
            ],
        },
    ]


def _pipelines() -> dict[str, list[dict[str, Any]]]:
    return {
        "crypto": [
            {"title": "News pulse", "owner": "Catalyst desk", "status": "operational", "tone": "success", "description": "Create catalyst-aware research runs before LLM decides."},
            {"title": "Quality screen", "owner": "Moat desk", "status": "operational", "tone": "success", "description": "Score liquidity, market structure, drawdown behavior, and regime alignment."},
            {"title": "Thesis tracker", "owner": "Portfolio desk", "status": "operational", "tone": "info", "description": "Persist thesis, invalidation level, review cadence, and exit narrative."},
            {"title": "Report audit", "owner": "Risk desk", "status": "operational", "tone": "success", "description": "Audit evidence quality before advisory context is trusted."},
        ],
        "forex": [
            {"title": "Macro calendar", "owner": "Rates desk", "status": "needed", "tone": "danger", "description": "Block or reduce risk around CPI, NFP, central bank decisions, and holiday liquidity."},
            {"title": "Session model", "owner": "Market desk", "status": "planned", "tone": "warning", "description": "Separate Asia, London, New York, overlap, rollover, and weekend gap behavior."},
            {"title": "Quality screen", "owner": "Liquidity desk", "status": "operational", "tone": "info", "description": "Use spread, ATR, trend persistence, and macro conflict as first-pass filters."},
            {"title": "Portfolio review", "owner": "Risk desk", "status": "planned", "tone": "warning", "description": "Share one exposure ledger with crypto so USD and risk-on bets do not stack blindly."},
        ],
    }


def _analyst_pods() -> list[dict[str, str]]:
    return [
        {"label": "Business quality", "value": "Moat, liquidity, durability", "detail": "Maps quality-screen thinking onto protocols, exchanges, FX liquidity, and macro durability."},
        {"label": "Market structure", "value": "Trend, range, volatility", "detail": "Feeds confluence context without bypassing existing hard validator rules."},
        {"label": "Risk governance", "value": "Sizing, invalidation, exposure", "detail": "Keeps recommendations advisory and caps impact to risk reduction until backend gates exist."},
        {"label": "Evidence audit", "value": "Source quality, stale context", "detail": "Turns report_audit and financial_rigor ideas into checks before a thesis is trusted."},
    ]


def _roadmap() -> list[dict[str, str]]:
    return [
        {"stage": "Now", "title": "Research workflow API", "state": "done", "tone": "success", "detail": "State, persistence, research creation, four-lens report, and audit are live."},
        {"stage": "Now", "title": "Signal promotion to LLM tickets", "state": "operational", "tone": "success", "detail": "Eligible SignalCandidate records can feed the LLM decision path before demo execution."},
        {"stage": "Then", "title": "Forex runtime lane", "state": "blocked", "tone": "danger", "detail": "Add broker adapter, spread guards, sessions, and journal compatibility."},
        {"stage": "Guardrail", "title": "Unified exposure ledger", "state": "required", "tone": "accent", "detail": "Crypto and Forex must share global risk, drawdown, and kill-switch policy."},
    ]


def _capabilities() -> list[dict[str, str]]:
    return [
        {"label": "State API", "value": "GET /api/berkshire/state", "tone": "success"},
        {"label": "Research run", "value": "POST /api/berkshire/research", "tone": "success"},
        {"label": "Crypto scan", "value": "POST /api/berkshire/crypto/scan", "tone": "success"},
        {"label": "Financial rigor", "value": "Decimal risk/reward audit", "tone": "success"},
        {"label": "Execution", "value": "demo pipeline gated", "tone": "success"},
    ]


def _requirements() -> list[dict[str, str]]:
    return [
        {"label": "LLM multi-agent workers", "status": "needed", "tone": "warning", "detail": "Use existing LLM/swarm layer to run four independent analyst prompts."},
        {"label": "Live evidence providers", "status": "needed", "tone": "warning", "detail": "News, filings, macro calendar, funding, spreads, and cross-source validation."},
        {"label": "Forex broker adapter", "status": "blocked", "tone": "danger", "detail": "Required before any FX execution can exist."},
        {"label": "Shared risk ledger", "status": "required", "tone": "accent", "detail": "One exposure and drawdown policy across crypto and forex."},
    ]


def _system_events() -> list[dict[str, str]]:
    return [
        {"time": _time_label(), "label": "AI Berkshire source mapped", "value": "skills plus tools, no runtime package", "tone": "info"},
        {"time": _time_label(), "label": "Signal contract active", "value": "Berkshire emits SignalCandidate records", "tone": "success"},
        {"time": _time_label(), "label": "Execution guard", "value": "research_only, no order payloads", "tone": "success"},
    ]


def _audit_events(store: dict[str, Any], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = list(store.get("system_events", []))
    for run in runs[:8]:
        events.append(
            {
                "time": _time_label(run.get("created_at")),
                "label": f"{run.get('symbol')} {run.get('skill')}",
                "value": f"{run.get('verdict')} ({run.get('conviction')}/100)",
                "tone": "success" if run.get("verdict") == "pass_research" else "warning",
            }
        )
    return events[:12]


def _time_label(iso: str | None = None) -> str:
    try:
        dt = datetime.fromisoformat((iso or _now_iso()).replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.astimezone().strftime("%H:%M")
