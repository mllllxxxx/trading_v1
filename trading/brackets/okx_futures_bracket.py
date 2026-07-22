#!/usr/bin/env python3
"""Bracket order placement for OKX USDT-margined FUTURES (SWAP).

Differences from spot (``okx_bracket.py``):
  * Symbol format: ``BTC-USDT-SWAP`` (OKX perpetual swap) instead of ``BTC-USDT``
  * Margin mode: ``tdMode=isolated`` (per-position margin, no cross contagion)
  * Single algo order carries both ``slTriggerPx`` + ``tpTriggerPx`` (native OCO)
  * Position size is in CONTRACTS; OKX minimum = contract_size (e.g. 0.01 BTC)
  * Liquidation price must be computed and checked vs per-symbol buffer (H7)
  * Leverage is set per-symbol before entry (H5)
  * Funding blackout window check before placing (H8)
  * Risk/Reward threshold lowered to 1.5 (vs 2.0 spot) — account for funding cost

Environment variables (read in ``load_okx_config``):
  OKX_API_KEY, OKX_API_SECRET, OKX_PASSPHRASE, OKX_TESTNET
  FUTURES_MIN_RR (default 1.5), FUTURES_RISK_PCT (default 0.05),
  FUTURES_MAX_POSITION_PCT (default 0.60), FUTURES_MAX_MARGIN_PCT (default 0.20),
  FUTURES_MAX_LEVERAGE (default 3), FUTURES_FUNDING_BLACKOUT_MIN (default 5)

Usage:
  python okx_futures_bracket.py --symbol BTC-USDT-SWAP --side buy \\
    --entry 100000 --stop-loss 97000 --take-profit 105000 \\
    --capital 500 --leverage 10 --dry-run

Exit codes: 0 success / 1 input error / 2 risk violation / 3 placement error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Import validator for H5/H7 per-symbol checks. The tricky bit: `trading/auto/`
# is commonly on sys.path (set by the scheduler). If it is, `import auto`
# resolves to `auto.py` (a file inside that directory), which shadows the
# `auto/` package. So we must move `trading/` to position 0 BEFORE the import
# of `auto.validator` so that `auto` resolves to the package.
_HERE = Path(__file__).resolve().parent
_TRADING_DIR = _HERE.parent
_AUTO_DIR = _TRADING_DIR / "auto"
# Move trading/ to position 0 (or insert if missing) so 'auto' is the package
if str(_TRADING_DIR) in sys.path:
    sys.path.remove(str(_TRADING_DIR))
sys.path.insert(0, str(_TRADING_DIR))
# Then auto/ at position 1 so validator.py's `import skills` works
if str(_AUTO_DIR) in sys.path:
    sys.path.remove(str(_AUTO_DIR))
sys.path.insert(1, str(_AUTO_DIR))

try:
    from auto.validator import check_leverage as _check_leverage  # type: ignore
except ImportError as _exc:
    _validator_spec = importlib.util.spec_from_file_location(
        "trade_v1_auto_validator",
        _AUTO_DIR / "validator.py",
    )
    if _validator_spec is not None and _validator_spec.loader is not None:
        _validator_mod = importlib.util.module_from_spec(_validator_spec)
        _validator_spec.loader.exec_module(_validator_mod)  # type: ignore[union-attr]
        _check_leverage = _validator_mod.check_leverage  # type: ignore[attr-defined]
    else:
        import logging
        logging.getLogger(__name__).warning(
            "H5 per-symbol check unavailable: %s. Falling back to global cap only.",
            _exc,
        )
        def _check_leverage(symbol: str, leverage: int) -> tuple[bool, str]:  # type: ignore
            return True, "OK (per-symbol H5 check unavailable)"

ENV_PATH = Path.home() / ".vibe-trading" / ".env"
load_dotenv(ENV_PATH)


# ---------------------------------------------------------------------------
# Risk configuration
# ---------------------------------------------------------------------------

MIN_RR = float(os.getenv("FUTURES_MIN_RR", "1.5"))
RISK_PCT = float(os.getenv("FUTURES_RISK_PCT", "0.05"))           # 5% hard ceiling
MAX_POSITION_PCT = float(os.getenv("FUTURES_MAX_POSITION_PCT", "0.60"))  # gross notional
MAX_MARGIN_PCT = float(os.getenv("FUTURES_MAX_MARGIN_PCT", "0.20"))
DAILY_LOSS_CAP = float(os.getenv("FUTURES_DAILY_LOSS_CAP", "0.03"))      # 3%
MAX_LEVERAGE = int(os.getenv("FUTURES_MAX_LEVERAGE", "3"))
FUNDING_BLACKOUT_MIN = int(os.getenv("FUTURES_FUNDING_BLACKOUT_MIN", "5"))
DEFAULT_MAINT_MARGIN_RATE = float(os.getenv("FUTURES_MMR", "0.005"))     # 0.5%


def load_okx_config() -> dict[str, Any]:
    return {
        "api_key": os.getenv("OKX_API_KEY", "").strip(),
        "api_secret": os.getenv("OKX_API_SECRET", "").strip(),
        "passphrase": os.getenv("OKX_PASSPHRASE", "").strip(),
        "testnet": os.getenv("OKX_TESTNET", "true").lower() in ("true", "1", "yes"),
        "sandbox": os.getenv("OKX_SANDBOX", "true").lower() in ("true", "1", "yes"),
    }


# ---------------------------------------------------------------------------
# Symbol config (per-symbol overrides)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SymbolMeta:
    """Per-symbol metadata for futures bracket logic.

    Leverage and liq_buffer_pct are TIGHTLY COUPLED: at 10x leverage the
    liquidation price sits ~10% from entry (1/leverage), so requiring 30%
    buffer would block every trade. Per-symbol override is mandatory.
    """
    base: str                          # "BTC"
    swap_symbol: str                   # "BTC-USDT-SWAP"
    spot_symbol: str                   # "BTC-USDT" (for confluence / data)
    leverage: int                      # max OKX leverage to use
    max_notional_pct: float            # cap this symbol at configured % capital
    min_confluence: int                # scheduler min_confluence for this symbol
    liq_buffer_pct: float              # min distance from entry to liq (e.g. 0.10 = 10%)
    min_rr: float                      # override MIN_RR if needed
    contract_size: float               # 1 contract = X base units (BTC=0.01)
    min_qty: float                     # OKX minimum order size in contracts
    maintenance_margin_rate: float     # 0.005 BTC, 0.01 alts typical


# Hardcoded universe for futures — keep in sync with `universe.py` fallback.
# IMPORTANT: leverage & liq_buffer_pct are COUPLED. At 10x leverage the
# liquidation sits ~10% from entry (1/lev), minus MMR ~0.5% = ~9.5% distance.
# So a 10% buffer is unreachable for BTC at 10x. We use 0.08 (8%) which is
# just below max so the math is feasible, AND we accept that BTC is always
# trading close to the liquidation edge at 10x (use tighter stop-loss to
# avoid getting rekt).
DEFAULT_FUTURES_UNIVERSE: dict[str, SymbolMeta] = {
    "BTC":  SymbolMeta("BTC",  "BTC-USDT-SWAP",  "BTC-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=4, liq_buffer_pct=0.08, min_rr=1.5, contract_size=0.01, min_qty=0.01, maintenance_margin_rate=0.005),
    "ETH":  SymbolMeta("ETH",  "ETH-USDT-SWAP",  "ETH-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=0.01, min_qty=0.01, maintenance_margin_rate=0.005),
    "BNB":  SymbolMeta("BNB",  "BNB-USDT-SWAP",  "BNB-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=0.01, min_qty=0.01, maintenance_margin_rate=0.01),
    "SOL":  SymbolMeta("SOL",  "SOL-USDT-SWAP",  "SOL-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "XRP":  SymbolMeta("XRP",  "XRP-USDT-SWAP",  "XRP-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "DOGE": SymbolMeta("DOGE", "DOGE-USDT-SWAP", "DOGE-USDT", leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "ADA":  SymbolMeta("ADA",  "ADA-USDT-SWAP",  "ADA-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "AVAX": SymbolMeta("AVAX", "AVAX-USDT-SWAP", "AVAX-USDT", leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "TRX":  SymbolMeta("TRX",  "TRX-USDT-SWAP",  "TRX-USDT",  leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
    "LINK": SymbolMeta("LINK", "LINK-USDT-SWAP", "LINK-USDT", leverage=3,  max_notional_pct=MAX_POSITION_PCT, min_confluence=3, liq_buffer_pct=0.25, min_rr=1.5, contract_size=1,    min_qty=1,    maintenance_margin_rate=0.01),
}


def _default_symbol_meta(base: str) -> SymbolMeta:
    """Return conservative metadata for OKX USDT swap bases not hardcoded yet."""
    normalized = base.upper().strip()
    return SymbolMeta(
        normalized,
        f"{normalized}-USDT-SWAP",
        f"{normalized}-USDT",
        leverage=3,
        max_notional_pct=MAX_POSITION_PCT,
        min_confluence=3,
        liq_buffer_pct=0.25,
        min_rr=1.5,
        contract_size=1,
        min_qty=1,
        maintenance_margin_rate=0.01,
    )


def get_symbol_meta(symbol: str) -> SymbolMeta:
    """Look up SymbolMeta by base (e.g. 'BTC') or swap_symbol (e.g. 'BTC-USDT-SWAP')."""
    s = symbol.upper().strip()
    if "-" in s:
        base = s.split("-", 1)[0]
    else:
        base = s
    if base not in DEFAULT_FUTURES_UNIVERSE:
        return _default_symbol_meta(base)
    return DEFAULT_FUTURES_UNIVERSE[base]


# ---------------------------------------------------------------------------
# Pure math (no I/O) — easy to test
# ---------------------------------------------------------------------------

def compute_liquidation_price(
    entry: float,
    leverage: int,
    side: str,
    maintenance_margin_rate: float = DEFAULT_MAINT_MARGIN_RATE,
) -> float:
    """Estimated liquidation price for isolated-margin USDT-margined linear futures.

    Formula (simplified, OKX linear USDT perp):
        LONG : liq = entry * (1 - 1/leverage + MMR)
        SHORT: liq = entry * (1 + 1/leverage - MMR)

    For leverage=10, MMR=0.005, entry=100_000:
        LONG  : 100000 * 0.905 = 90_500   (~9.5% from entry)
        SHORT : 100000 * 1.095 = 109_500  (~9.5% from entry)
    """
    if leverage < 1:
        raise ValueError(f"leverage must be >= 1, got {leverage}")
    if entry <= 0:
        raise ValueError(f"entry must be > 0, got {entry}")
    if maintenance_margin_rate < 0 or maintenance_margin_rate >= 1:
        raise ValueError(f"maintenance_margin_rate out of range: {maintenance_margin_rate}")

    is_long = side.lower() in ("buy", "long")
    if is_long:
        return entry * (1 - 1 / leverage + maintenance_margin_rate)
    return entry * (1 + 1 / leverage - maintenance_margin_rate)


def compute_liquidation_buffer_pct(
    entry: float,
    liq_price: float,
) -> float:
    """Return distance from entry to liq as positive fraction.

    Always positive. |entry - liq| / entry. Used by H7 check.
    """
    if entry <= 0:
        raise ValueError("entry must be > 0")
    return abs(entry - liq_price) / entry


def parse_swap_symbol(symbol: str) -> tuple[str, str]:
    """'BTC-USDT-SWAP' -> ('BTC', 'USDT')."""
    parts = symbol.upper().strip().split("-")
    if len(parts) < 2:
        raise ValueError(f"Invalid swap symbol '{symbol}', expected e.g. BTC-USDT-SWAP")
    return parts[0], parts[1]


def compute_bracket_futures(
    symbol: str,
    side: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    capital: float,
    leverage: int | None = None,
    risk_pct: float | None = None,
    liq_buffer_pct: float | None = None,
    contract_size: float | None = None,
    min_qty: float | None = None,
    qty_step: float | None = None,
    maintenance_margin_rate: float | None = None,
) -> dict[str, Any]:
    """Compute all metrics for a futures bracket. No I/O.

    Returns dict suitable for downstream validator + bracket placement.
    Raises ValueError on bad input. Validation against MIN_RR, H5, H7 etc.
    is done in ``validate_futures()`` separately.
    """
    meta = get_symbol_meta(symbol)
    base, quote = parse_swap_symbol(meta.swap_symbol)

    side_lower = side.lower()
    if side_lower not in ("buy", "sell", "long", "short"):
        raise ValueError(f"side must be buy/sell/long/short, got '{side}'")
    is_long = side_lower in ("buy", "long")
    side_norm = "buy" if is_long else "sell"

    # Resolve per-symbol config with optional caller override
    lev = leverage if leverage is not None else meta.leverage
    rp = risk_pct if risk_pct is not None else RISK_PCT
    buf = liq_buffer_pct if liq_buffer_pct is not None else meta.liq_buffer_pct
    cs = contract_size if contract_size is not None else meta.contract_size
    mq = min_qty if min_qty is not None else meta.min_qty
    qs = qty_step if qty_step is not None else mq
    mmr = maintenance_margin_rate if maintenance_margin_rate is not None else meta.maintenance_margin_rate

    if lev < 1:
        raise ValueError(f"leverage must be >= 1, got {lev}")
    if lev > MAX_LEVERAGE:
        raise ValueError(f"leverage {lev} exceeds MAX_LEVERAGE {MAX_LEVERAGE}")
    if rp < 0:
        raise ValueError(f"risk_pct must be >= 0, got {rp}")
    if rp > RISK_PCT + 1e-9:
        raise ValueError(
            f"risk_pct {rp:.4f} exceeds default {RISK_PCT:.4f}. "
            "Override must shrink, not enlarge, risk."
        )
    if cs <= 0:
        raise ValueError(f"contract_size must be > 0, got {cs}")
    if mq <= 0:
        raise ValueError(f"min_qty must be > 0, got {mq}")
    if qs <= 0:
        raise ValueError(f"qty_step must be > 0, got {qs}")

    e = Decimal(str(entry))
    sl = Decimal(str(stop_loss))
    tp = Decimal(str(take_profit))
    cap = Decimal(str(capital))

    if e <= 0 or sl <= 0 or tp <= 0 or cap <= 0:
        raise ValueError("entry, stop_loss, take_profit, capital must all be > 0")

    if is_long:
        if sl >= e:
            raise ValueError("LONG: stop_loss must be BELOW entry")
        if tp <= e:
            raise ValueError("LONG: take_profit must be ABOVE entry")
        stop_distance = e - sl
        reward = tp - e
    else:
        if sl <= e:
            raise ValueError("SHORT: stop_loss must be ABOVE entry")
        if tp >= e:
            raise ValueError("SHORT: take_profit must be BELOW entry")
        stop_distance = sl - e
        reward = e - tp

    rr_ratio = float(reward / stop_distance)
    min_rr_eff = meta.min_rr  # per-symbol, may be lower than global MIN_RR

    # Position size by risk (in base units, e.g. BTC)
    risk_amount = cap * Decimal(str(rp))
    pos_by_risk = risk_amount / stop_distance  # in base units

    # Position notional at entry price
    pos_notional_by_risk = pos_by_risk * e

    # Cap by per-symbol max notional (NOT global MAX_POSITION_PCT — that's for spot)
    max_notional_pct = min(meta.max_notional_pct, MAX_MARGIN_PCT * lev)
    max_notional = cap * Decimal(str(max_notional_pct))
    scaled = False
    if pos_notional_by_risk > max_notional:
        pos_size = max_notional / e
        scaled = True
    else:
        pos_size = pos_by_risk

    # Convert to contracts
    contracts_raw = pos_size / Decimal(str(cs))
    step_dec = Decimal(str(qs))
    contracts_dec = (contracts_raw / step_dec).to_integral_value(rounding=ROUND_DOWN) * step_dec
    if contracts_dec < Decimal(str(mq)):
        # Below minimum — flag for caller
        below_min = True
    else:
        below_min = False

    contracts: int | float
    if contracts_dec == contracts_dec.to_integral_value():
        contracts = int(contracts_dec)
    else:
        contracts = float(contracts_dec)

    actual_pos_size = contracts_dec * Decimal(str(cs))
    actual_notional = actual_pos_size * e
    actual_margin_required = actual_notional / Decimal(str(lev))
    actual_risk_usd_contracts = actual_pos_size * stop_distance
    actual_risk_pct_contracts = float(actual_risk_usd_contracts / cap) * 100

    # Liquidation price
    liq_price = compute_liquidation_price(
        entry=float(e), leverage=lev, side=side_norm,
        maintenance_margin_rate=mmr,
    )
    liq_distance_pct = compute_liquidation_buffer_pct(float(e), liq_price)

    return {
        "symbol": meta.swap_symbol,
        "base": base,
        "quote": quote,
        "side": side_norm,
        "is_long": is_long,
        "pos_side": "long" if is_long else "short",
        "entry": float(e),
        "stop_loss": float(sl),
        "take_profit": float(tp),
        "stop_distance": float(stop_distance),
        "reward": float(reward),
        "rr_ratio": rr_ratio,
        "rr_ratio_str": f"1:{rr_ratio:.2f}",
        "stop_pct": float(stop_distance / e * 100),
        "tp_pct": float(reward / e * 100),
        "leverage": lev,
        "td_mode": "isolated",
        "capital": float(cap),
        "position_size_base": float(actual_pos_size),
        "contracts": contracts,
        "contract_size": cs,
        "below_min_qty": below_min,
        "min_qty": mq,
        "qty_step": qs,
        "max_notional_pct": max_notional_pct,
        "max_margin_pct": MAX_MARGIN_PCT,
        "position_notional": float(actual_notional),
        "position_pct": float(actual_notional / cap * 100),
        "margin_required": float(actual_margin_required),
        "actual_risk_usd": float(actual_risk_usd_contracts),
        "actual_risk_pct": actual_risk_pct_contracts,
        "liq_price": liq_price,
        "liq_distance_pct": liq_distance_pct,
        "liq_buffer_required": buf,
        "maintenance_margin_rate": mmr,
        "scaled": scaled,
        "min_rr": min_rr_eff,
    }


def validate_futures(proposal: dict[str, Any]) -> list[str]:
    """Validate futures proposal against H1-H8 rules.

    Returns list of violation messages. Empty = all pass.
    NOTE: H1/H2/H3/H4/H6 are checked by ``validator.validate_proposal`` upstream
    with market_context. Here we focus on futures-specific rules:
      * H5: leverage cap (per-symbol, defers to validator.check_leverage)
      * H7: liquidation distance vs buffer
      * futures-specific: R:R, position sizing
    """
    violations: list[str] = []

    if proposal["leverage"] > MAX_LEVERAGE:
        violations.append(
            f"H5 leverage: {proposal['leverage']}x > {MAX_LEVERAGE}x (max)"
        )

    # H5 per-symbol: alts capped at 3x even if global MAX_LEVERAGE is higher.
    ok5, msg5 = _check_leverage(proposal["symbol"], proposal["leverage"])
    if not ok5:
        violations.append(msg5)

    if proposal["rr_ratio"] < proposal["min_rr"]:
        violations.append(
            f"R:R = {proposal['rr_ratio_str']} < 1:{proposal['min_rr']:.1f} (minimum)"
        )

    if proposal["below_min_qty"]:
        violations.append(
            f"contracts {proposal['contracts']} < min_qty {proposal['min_qty']} "
            f"for {proposal['symbol']} — increase capital or relax risk_pct"
        )

    if proposal["position_pct"] > proposal.get("max_notional_pct", MAX_POSITION_PCT) * 100 + 1e-6:
        violations.append(
            f"position {proposal['position_pct']:.1f}% > "
            f"{proposal.get('max_notional_pct', MAX_POSITION_PCT) * 100:.0f}% (max notional)"
        )

    capital = float(proposal.get("capital", 0.0))
    max_margin_pct = float(proposal.get("max_margin_pct", MAX_MARGIN_PCT))
    if capital > 0 and proposal["margin_required"] > capital * max_margin_pct + 1e-6:
        violations.append(
            f"margin {proposal['margin_required']:.2f} > "
            f"{max_margin_pct * 100:.0f}% capital"
        )

    if proposal["liq_distance_pct"] < proposal["liq_buffer_required"]:
        violations.append(
            f"H7 liq buffer: {proposal['liq_distance_pct']:.2%} < "
            f"{proposal['liq_buffer_required']:.2%} required "
            f"(entry={proposal['entry']}, liq={proposal['liq_price']:.2f}, lev={proposal['leverage']}x)"
        )

    return violations


# ---------------------------------------------------------------------------
# Exchange helpers (lazy ccxt)
# ---------------------------------------------------------------------------

def _make_exchange(cfg: dict[str, Any]):
    """Build ccxt OKX client for SWAP (futures). Sandbox if testnet."""
    import ccxt  # type: ignore

    exchange = ccxt.okx({
        "apiKey": cfg["api_key"],
        "secret": cfg["api_secret"],
        "password": cfg["passphrase"],
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    if cfg["testnet"]:
        exchange.set_sandbox_mode(True)
    return exchange


def fetch_contract_trade_metadata(cfg: dict[str, Any], symbol: str) -> dict[str, float | str]:
    """Fetch exact-symbol contract facts from CCXT or OKX public instruments.

    OKX quantities are contracts. Dynamic top-50 symbols must use broker
    metadata here instead of the conservative `contract_size=1` fallback.
    """
    meta = get_symbol_meta(symbol)
    market = None
    try:
        exchange = _make_exchange(cfg)
        markets = exchange.load_markets()
        for candidate in markets.values():
            if not isinstance(candidate, dict):
                continue
            if candidate.get("id") == meta.swap_symbol:
                market = candidate
                break
        if market is None:
            ccxt_symbol = _ccxt_swap_symbol(meta.swap_symbol)
            candidate = markets.get(ccxt_symbol)
            if isinstance(candidate, dict):
                market = candidate
    except Exception:  # noqa: BLE001
        market = None
    if market is None:
        return _fetch_public_contract_trade_metadata(
            meta.swap_symbol,
            simulated=bool(cfg.get("testnet") or cfg.get("sandbox")),
        )

    info = market.get("info") if isinstance(market.get("info"), dict) else {}
    contract_size = _float_first(
        market.get("contractSize"),
        info.get("ctVal"),
        default=0.0,
    )
    limits = market.get("limits") if isinstance(market.get("limits"), dict) else {}
    amount_limits = limits.get("amount") if isinstance(limits.get("amount"), dict) else {}
    precision = market.get("precision") if isinstance(market.get("precision"), dict) else {}
    min_qty = _float_first(
        amount_limits.get("min"),
        info.get("minSz"),
        default=0.0,
    )
    qty_step = _float_first(
        info.get("lotSz"),
        precision.get("amount"),
        default=min_qty,
    )
    if contract_size <= 0:
        raise RuntimeError(f"OKX contract_size unavailable for {meta.swap_symbol}")
    if min_qty <= 0:
        raise RuntimeError(f"OKX min_qty unavailable for {meta.swap_symbol}")
    if qty_step <= 0:
        raise RuntimeError(f"OKX qty_step unavailable for {meta.swap_symbol}")
    return {
        "symbol": meta.swap_symbol,
        "contract_size": contract_size,
        "min_qty": min_qty,
        "qty_step": qty_step,
        "source": "okx_ccxt_markets",
    }


def _fetch_public_contract_trade_metadata(
    symbol: str,
    *,
    simulated: bool = False,
) -> dict[str, float | str]:
    """Resolve one exact OKX swap from the public instruments endpoint."""

    import requests  # type: ignore

    response = requests.get(
        "https://www.okx.com/api/v5/public/instruments",
        params={"instType": "SWAP", "instId": symbol},
        headers={"x-simulated-trading": "1"} if simulated else {},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise RuntimeError(f"OKX public instrument lookup failed for {symbol}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        rows = []
    instrument = next(
        (
            row
            for row in rows
            if isinstance(row, dict) and str(row.get("instId")) == symbol
        ),
        None,
    )
    if instrument is None:
        raise RuntimeError(f"OKX exact instrument metadata unavailable for {symbol}")
    contract_size = _float_first(instrument.get("ctVal"), default=0.0)
    min_qty = _float_first(
        instrument.get("minSz"),
        instrument.get("lotSz"),
        default=0.0,
    )
    qty_step = _float_first(instrument.get("lotSz"), default=min_qty)
    if contract_size <= 0 or min_qty <= 0 or qty_step <= 0:
        raise RuntimeError(f"OKX public contract metadata incomplete for {symbol}")
    return {
        "symbol": symbol,
        "contract_size": contract_size,
        "min_qty": min_qty,
        "qty_step": qty_step,
        "source": "okx_public_instruments",
    }


def _ccxt_swap_symbol(okx_symbol: str) -> str:
    base, quote = parse_swap_symbol(okx_symbol)
    return f"{base}/{quote}:{quote}"


def _float_first(*values: Any, default: float) -> float:
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return default


def set_leverage(
    cfg: dict[str, Any],
    symbol: str,
    leverage: int,
    pos_side: str | None,
) -> dict[str, Any]:
    """Set leverage for an exact native OKX swap instrument.

    For isolated margin, must call per posSide (long/short) on OKX v5.
    The signed endpoint accepts native ``instId`` values directly, avoiding a
    second CCXT market lookup after dynamic contract metadata is resolved.
    """
    import requests  # type: ignore

    path = "/api/v5/account/set-leverage"
    body_payload: dict[str, str] = {
        "instId": symbol,
        "lever": str(leverage),
        "mgnMode": "isolated",
    }
    if pos_side:
        body_payload["posSide"] = pos_side
    body = json.dumps(body_payload)
    headers = _signed_headers(cfg, "POST", path, body)
    if cfg.get("testnet") or cfg.get("sandbox"):
        headers["x-simulated-trading"] = "1"

    response = requests.post(
        "https://www.okx.com" + path,
        data=body,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or str(payload.get("code")) != "0" or not isinstance(rows, list) or not rows:
        message = str(payload)
        if "Leverage doesn't change" in message or (
            "leverage" in message.lower() and "same" in message.lower()
        ):
            return {
                "info": "leverage already at requested level",
                "symbol": symbol,
                "leverage": leverage,
            }
        raise RuntimeError(f"set leverage failed for {symbol}: {payload}")
    row = rows[0]
    return row if isinstance(row, dict) else {"raw": row}


def fetch_account_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return OKX account config, including position mode."""
    import requests  # type: ignore

    path = "/api/v5/account/config"
    headers = _signed_headers(cfg, "GET", path)
    if cfg.get("testnet") or cfg.get("sandbox"):
        headers["x-simulated-trading"] = "1"
    resp = requests.get("https://www.okx.com" + path, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0" or not data.get("data"):
        raise RuntimeError(f"account config fetch failed: {data}")
    row = data["data"][0]
    return row if isinstance(row, dict) else {}


def _signed_headers(
    cfg: dict[str, Any],
    method: str,
    request_path: str,
    body: str = "",
) -> dict[str, str]:
    import base64
    import hashlib
    import hmac
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    msg = ts + method.upper() + request_path + body
    sig = base64.b64encode(
        hmac.new(cfg["api_secret"].encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "Content-Type": "application/json",
        "OK-ACCESS-KEY": cfg["api_key"],
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": cfg["passphrase"],
    }


def _position_mode(cfg: dict[str, Any]) -> str:
    override = os.getenv("OKX_POSITION_MODE", "").strip().lower()
    if override in {"net", "net_mode", "long_short", "long_short_mode"}:
        return "net_mode" if override in {"net", "net_mode"} else "long_short_mode"
    try:
        raw = str(fetch_account_config(cfg).get("posMode", "")).strip().lower()
    except Exception:
        return "long_short_mode"
    return "net_mode" if raw in {"net", "net_mode"} else "long_short_mode"


def _order_pos_side(proposal_pos_side: str, position_mode: str) -> str | None:
    if position_mode == "net_mode":
        return None
    return proposal_pos_side


def fetch_funding_rate(cfg: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Return current funding rate + next funding time.

    Shape: {fundingRate: str, nextFundingTime: str (ms), fundingTime: str (ms)}
    """
    import requests  # type: ignore

    base_url = "https://www.okx.com" if not cfg["testnet"] else "https://www.okx.com"
    path = "/api/v5/public/funding-rate"
    params = {"instId": symbol}
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        # Private endpoint not needed here, but include creds for consistency
        import hmac
        import hashlib
        import base64
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        method = "GET"
        req_path = f"{path}?instId={symbol}"
        body = ""
        msg = ts + method + req_path + body
        sig = base64.b64encode(
            hmac.new(cfg["api_secret"].encode(), msg.encode(), hashlib.sha256).digest()
        ).decode()
        headers["OK-ACCESS-KEY"] = cfg["api_key"]
        headers["OK-ACCESS-SIGN"] = sig
        headers["OK-ACCESS-TIMESTAMP"] = ts
        headers["OK-ACCESS-PASSPHRASE"] = cfg["passphrase"]

    resp = requests.get(base_url + path, params=params, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0" or not data.get("data"):
        raise RuntimeError(f"funding-rate fetch failed: {data}")
    row = data["data"][0]
    return {
        "fundingRate": float(row["fundingRate"]),
        "nextFundingTime": int(row["nextFundingTime"]),
        "fundingTime": int(row.get("fundingTime", row["nextFundingTime"])),
    }


def fetch_open_interest(cfg: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Return open interest (contracts + USD notional)."""
    import requests  # type: ignore

    base_url = "https://www.okx.com"
    path = "/api/v5/public/open-interest"
    params = {"instType": "SWAP", "instId": symbol}
    resp = requests.get(base_url + path, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "0" or not data.get("data"):
        raise RuntimeError(f"open-interest fetch failed: {data}")
    row = data["data"][0]
    return {
        "oi": float(row["oi"]),
        "oiCcy": float(row["oiCcy"]),
        "ts": int(row["ts"]),
    }


def is_funding_blackout(
    symbol: str,
    now_ms: int | None = None,
    blackout_min: int = FUNDING_BLACKOUT_MIN,
) -> tuple[bool, int | None]:
    """Check if `now` is within ±blackout_min of the next funding time.

    Returns (is_blackout, next_funding_ms). If funding time cannot be fetched
    (network error), returns (False, None) — fail-open: don't block trades.
    """
    cfg = load_okx_config()
    try:
        fr = fetch_funding_rate(cfg, symbol)
    except Exception:
        return False, None
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    next_funding = fr["nextFundingTime"]
    diff_ms = next_funding - now_ms
    if -blackout_min * 60 * 1000 <= diff_ms <= blackout_min * 60 * 1000:
        return True, next_funding
    return False, next_funding


# ---------------------------------------------------------------------------
# Order placement (entry order with attached TP + SL)
# ---------------------------------------------------------------------------

def place_orders_futures(
    proposal: dict[str, Any],
    cfg: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Place a futures position with attached TP+SL protection.

    Order flow:
      1. set_leverage (idempotent)
      2. create a limit entry order with ``attachAlgoOrds`` for native TP/SL
    """
    position_mode = _position_mode(cfg)
    order_pos_side = _order_pos_side(proposal["pos_side"], position_mode)
    attached_tp_sl: list[dict[str, str]] = [
        {
            "tpTriggerPx": str(proposal["take_profit"]),
            "tpOrdPx": "-1",
            "tpTriggerPxType": "mark",
            "slTriggerPx": str(proposal["stop_loss"]),
            "slOrdPx": "-1",
            "slTriggerPxType": "mark",
        }
    ]

    if dry_run:
        algo_order = {
            "dry_run": True,
            "instId": proposal["symbol"],
            "tdMode": proposal["td_mode"],
            "side": "buy" if proposal["is_long"] else "sell",
            "ordType": "limit",
            "px": str(proposal["entry"]),
            "sz": str(proposal["contracts"]),
            "attachAlgoOrds": attached_tp_sl,
            "leverage": proposal["leverage"],
            "positionMode": position_mode,
        }
        if order_pos_side:
            algo_order["posSide"] = order_pos_side
        return {
            "algo_order": algo_order,
            "liq_price": proposal["liq_price"],
            "margin_required": proposal["margin_required"],
        }

    # 1. Set leverage first (idempotent — OKX returns current if same)
    try:
        set_leverage(cfg, proposal["symbol"], proposal["leverage"], order_pos_side)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "set_leverage",
            "error": str(exc),
        }

    # 2. Place entry order via raw API so TP/SL can be attached atomically.
    import requests  # type: ignore
    base_url = "https://www.okx.com" if not cfg["testnet"] else "https://www.okx.com"
    path = "/api/v5/trade/order"
    body_payload = {
        "instId": proposal["symbol"],
        "tdMode": proposal["td_mode"],
        "side": "buy" if proposal["is_long"] else "sell",
        "ordType": "limit",
        "px": str(proposal["entry"]),
        "sz": str(proposal["contracts"]),
        "attachAlgoOrds": attached_tp_sl,
    }
    if order_pos_side:
        body_payload["posSide"] = order_pos_side
    body = json.dumps(body_payload)

    headers = _signed_headers(cfg, "POST", path, body)
    if cfg.get("testnet") or cfg.get("sandbox"):
        headers["x-simulated-trading"] = "1"

    try:
        resp = requests.post(base_url + path, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0" or not data.get("data"):
            return {
                "ok": False,
                "stage": "place_entry",
                "error": f"OKX error: {data}",
            }
        order_row = data["data"][0]
        order_id = (
            order_row.get("ordId")
            or order_row.get("algoId")
            or order_row.get("algoClOrdId")
            or order_row.get("clOrdId")
            or ""
        )
        return {
            "ok": True,
            "order_id": order_id,
            "algo_order_id": order_id,
            "raw": order_row,
            "symbol": proposal["symbol"],
            "leverage": proposal["leverage"],
            "liq_price": proposal["liq_price"],
            "margin_required": proposal["margin_required"],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "place_entry",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_proposal_table(p: dict[str, Any]) -> None:
    side_label = "LONG" if p["is_long"] else "SHORT"
    print("=" * 70)
    print(f"FUTURES BRACKET ORDER PROPOSAL  ({p['td_mode'].upper()} margin)")
    print("=" * 70)
    print(f"Symbol        : {p['symbol']}")
    print(f"Side          : {side_label}  (posSide={p['pos_side']})")
    print(f"Leverage      : {p['leverage']}x")
    print(f"Entry         : {p['entry']}")
    print(f"Stop Loss     : {p['stop_loss']}  (-{p['stop_pct']:.2f}%)")
    print(f"Take Profit   : {p['take_profit']}  (+{p['tp_pct']:.2f}%)")
    print("-" * 70)
    rr_ok = "OK" if p["rr_ratio"] >= p["min_rr"] else "FAIL"
    print(f"R:R Ratio     : {p['rr_ratio_str']}  [{rr_ok}]")
    print(f"Contracts     : {p['contracts']}  (size={p['position_size_base']} {p['base']})")
    print(f"Notional      : ${p['position_notional']:,.2f} "
          f"({p['position_pct']:.1f}% vốn)")
    print(f"Margin req    : ${p['margin_required']:,.2f}")
    print(f"Risk          : ${p['actual_risk_usd']:,.2f} "
          f"({p['actual_risk_pct']:.3f}% vốn)")
    liq_ok = "OK" if p["liq_distance_pct"] >= p["liq_buffer_required"] else "FAIL"
    print(f"Liq Price     : {p['liq_price']:,.2f}  "
          f"(distance={p['liq_distance_pct']:.2%}, "
          f"required>={p['liq_buffer_required']:.2%}) [{liq_ok}]")
    if p["below_min_qty"]:
        print(f"[!] Position below min_qty {p['min_qty']} contracts for {p['symbol']}")
    if p["scaled"]:
        print("[!] Position was scaled DOWN to fit max notional cap")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate + place OKX futures bracket (SWAP, isolated, algo OCO)"
    )
    parser.add_argument("--symbol", required=True,
                        help="e.g. BTC-USDT-SWAP, ETH-USDT-SWAP")
    parser.add_argument("--side", required=True, choices=["buy", "sell", "long", "short"])
    parser.add_argument("--entry", type=float, required=True)
    parser.add_argument("--stop-loss", type=float, required=True)
    parser.add_argument("--take-profit", type=float, required=True)
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--leverage", type=int, default=None,
                        help="Override per-symbol leverage (default: per-symbol config)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate + show what would be placed, no API call")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip the interactive confirmation prompt")
    args = parser.parse_args()

    side_norm = "buy" if args.side in ("buy", "long") else "sell"

    try:
        proposal = compute_bracket_futures(
            args.symbol, side_norm, args.entry,
            args.stop_loss, args.take_profit, args.capital,
            leverage=args.leverage,
        )
    except ValueError as exc:
        print(json.dumps({"status": "error", "stage": "compute", "error": str(exc)},
                         indent=2))
        return 1

    violations = validate_futures(proposal)
    if violations:
        print("=" * 70)
        print("FUTURES BRACKET REJECTED")
        print("=" * 70)
        for v in violations:
            print(f"  X {v}")
        print("=" * 70)
        print("Fix the issues above and retry.")
        return 2

    _print_proposal_table(proposal)

    if args.dry_run:
        print("\n[DRY RUN] No orders will be placed.")
        cfg = load_okx_config()
        print(f"\nTestnet mode: {cfg['testnet']}")
        print(f"API key set:  {bool(cfg['api_key'])}")
        shown = place_orders_futures(proposal, cfg, dry_run=True)
        print(json.dumps(shown, indent=2))
        return 0

    cfg = load_okx_config()
    if not cfg["api_key"]:
        print("ERROR: OKX_API_KEY not set in .env")
        return 1
    if cfg["testnet"]:
        print("\n>>> Using OKX TESTNET (paper trading) <<<")
    else:
        print("\n!!! LIVE FUTURES TRADING - REAL MONEY !!!")
        print("Are you sure? Type LIVE in next 5 seconds...")
        try:
            resp = input("> ").strip()
        except EOFError:
            resp = ""
        if resp != "LIVE":
            print("Aborted.")
            return 1

    if not args.yes:
        print("\nĐặt lệnh futures? (yes/no): ", end="")
        try:
            resp = input().strip().lower()
        except EOFError:
            resp = ""
        if resp not in ("yes", "y"):
            print("Cancelled.")
            return 0

    result = place_orders_futures(proposal, cfg, dry_run=False)
    if not result.get("ok"):
        print(f"\nX Error placing futures order: {result.get('error')}")
        return 3

    print("\n[V] Futures order placed:")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
