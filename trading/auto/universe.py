"""Universe loader for Trade_V1 futures/swap trading.

Fetches top-N USDT-margined SWAP contracts from OKX, sorted by 24h volume.
Refreshed daily at 00:00 UTC, cached to /data/universe.json.

On API failure: falls back to hardcoded list (see HARDCODED_UNIVERSE below)
so the bot never starves because of a transient network blip.

This module is intentionally side-effect-light: no I/O at import time,
functions are pure or take an injectable HTTP fetcher.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)
MAX_NOTIONAL_PCT = float(os.getenv("FUTURES_MAX_POSITION_PCT", "0.20"))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SymbolMeta:
    """Per-symbol metadata. Mirrors ``okx_futures_bracket.SymbolMeta`` so the
    scheduler can read from one source of truth. Kept in sync manually.
    """
    base: str
    swap_symbol: str
    spot_symbol: str
    leverage: int
    max_notional_pct: float
    min_confluence: int
    liq_buffer_pct: float
    min_rr: float
    contract_size: float
    min_qty: float
    maintenance_margin_rate: float


@dataclass
class UniverseSnapshot:
    """Snapshot of tradable universe at a point in time."""
    fetched_at: str                   # ISO8601 UTC
    source: str                       # "okx_api" | "fallback_hardcoded" | "cache" | "env_override"
    symbols: list[SymbolMeta] = field(default_factory=list)
    raw_count: int = 0                # how many tickers OKX returned (pre-filter)


# Hardcoded fallback — locked top 10 as of 2026-06-23. Mirrors
# ``okx_futures_bracket.DEFAULT_FUTURES_UNIVERSE``.
FALLBACK_BASES: list[str] = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "AVAX", "TRX", "LINK",
    "BCH", "DOT", "SUI", "LTC", "HBAR", "XLM", "SHIB", "UNI", "APT", "NEAR",
    "ICP", "ETC", "FIL", "ARB", "OP", "ATOM", "INJ", "AAVE", "MKR", "RENDER",
    "WLD", "PEPE", "FLOKI", "BONK", "SEI", "TIA", "LDO", "JUP", "ONDO",
    "PENDLE", "ALGO", "VET", "EOS", "SAND", "MANA", "GALA", "IMX", "STX",
    "FET", "RUNE",
]

_KNOWN_OVERRIDES: dict[str, dict[str, float | int]] = {
    "BTC": {"leverage": 10, "min_confluence": 4, "liq_buffer_pct": 0.08, "contract_size": 0.01, "min_qty": 0.01, "maintenance_margin_rate": 0.005},
    "ETH": {"leverage": 3, "min_confluence": 3, "liq_buffer_pct": 0.25, "contract_size": 0.01, "min_qty": 0.01, "maintenance_margin_rate": 0.005},
    "BNB": {"leverage": 3, "min_confluence": 3, "liq_buffer_pct": 0.25, "contract_size": 0.01, "min_qty": 0.01, "maintenance_margin_rate": 0.01},
}


def _default_meta(base: str) -> SymbolMeta:
    """Return conservative futures metadata for any OKX USDT swap base."""
    normalized = base.strip().upper()
    overrides = _KNOWN_OVERRIDES.get(normalized, {})
    return SymbolMeta(
        normalized,
        f"{normalized}-USDT-SWAP",
        f"{normalized}-USDT",
        int(overrides.get("leverage", 3)),
        MAX_NOTIONAL_PCT,
        int(overrides.get("min_confluence", 3)),
        float(overrides.get("liq_buffer_pct", 0.25)),
        1.5,
        float(overrides.get("contract_size", 1.0)),
        float(overrides.get("min_qty", 1.0)),
        float(overrides.get("maintenance_margin_rate", 0.01)),
    )


HARDCODED_UNIVERSE: list[SymbolMeta] = [_default_meta(base) for base in FALLBACK_BASES]


# Stablecoins to exclude (lowercase bases)
STABLECOIN_BASES = frozenset({
    "usdt", "usdc", "dai", "busd", "tusd", "usdd", "frax", "usdp", "gusd",
    "mim", "usdk", "usds",
})


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    """Location of the cached universe snapshot."""
    data_dir = Path(os.getenv("VIBE_TRADING_HOME", "/data"))
    return data_dir / "universe.json"


def save_snapshot(snap: UniverseSnapshot, path: Path | None = None) -> None:
    """Persist snapshot to disk. Atomic write via tmp + rename."""
    target = path or _cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": snap.fetched_at,
        "source": snap.source,
        "raw_count": snap.raw_count,
        "symbols": [asdict(s) for s in snap.symbols],
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    logger.info("universe snapshot saved: %d symbols (%s)", len(snap.symbols), snap.source)


def load_cached_snapshot(path: Path | None = None) -> UniverseSnapshot | None:
    """Load cached snapshot from disk. Returns None if file missing/corrupt."""
    target = path or _cache_path()
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        symbols = [SymbolMeta(**s) for s in payload.get("symbols", [])]
        return UniverseSnapshot(
            fetched_at=payload["fetched_at"],
            source="cache",
            symbols=symbols,
            raw_count=payload.get("raw_count", 0),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("universe cache corrupt: %s", exc)
        return None


# ---------------------------------------------------------------------------
# OKX API
# ---------------------------------------------------------------------------

def fetch_okx_swap_tickers(
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    base_url: str = "https://www.okx.com",
) -> list[dict[str, Any]]:
    """Fetch all USDT-margined SWAP tickers from OKX public endpoint.

    Injectable ``fetcher`` for testing. Default uses urllib (no extra deps).
    """
    import urllib.request
    import urllib.error

    path = "/api/v5/market/tickers?instType=SWAP"
    url = base_url + path

    if fetcher is not None:
        return fetcher(url).get("data", [])

    headers = {"User-Agent": "trade-v1/1.0"}
    if _env_flag_true("OKX_TESTNET") and _env_flag_true("OKX_SANDBOX"):
        headers["x-simulated-trading"] = "1"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") != "0":
        raise RuntimeError(f"OKX API error: {payload}")
    return payload.get("data", [])


def _ticker_to_meta(ticker: dict[str, Any]) -> SymbolMeta | None:
    """Map an OKX USDT SWAP ticker to conservative SymbolMeta."""
    inst_id = ticker.get("instId", "")
    if not inst_id.endswith("-USDT-SWAP"):
        return None
    parts = inst_id.split("-")
    if len(parts) < 3:
        return None
    base = parts[0]
    if base.lower() in STABLECOIN_BASES:
        return None
    return _default_meta(base)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def load_universe(
    top_n: int = 50,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    use_cache_if_api_fails: bool = True,
) -> UniverseSnapshot:
    """Load tradable universe, preferring live OKX API over cache over fallback.

    Order of preference (controlled by env UNIVERSE_OVERRIDE / source flags):
      1. UNIVERSE_OVERRIDE env (comma-separated swap symbols) - operator override
      2. Live OKX API (top N by 24h volume, USDT-margined, non-stablecoin)
      3. Cached snapshot from /data/universe.json (if recent enough)
      4. Hardcoded HARDCODED_UNIVERSE (last resort)
    """
    # 1. Operator override
    override = os.getenv("UNIVERSE_OVERRIDE", "").strip()
    if override:
        symbols = _parse_override(override)
        if symbols:
            return UniverseSnapshot(
                fetched_at=datetime.now(timezone.utc).isoformat(),
                source="env_override",
                symbols=symbols,
                raw_count=len(symbols),
            )

    # 2. Live API
    try:
        tickers = fetch_okx_swap_tickers(fetcher=fetcher)
        # Filter: USDT-margined, non-stablecoin.
        candidates: list[tuple[dict[str, Any], SymbolMeta]] = []
        for t in tickers:
            meta = _ticker_to_meta(t)
            if meta is None:
                continue
            candidates.append((t, meta))
        candidates.sort(key=lambda c: _ticker_quote_volume(c[0]), reverse=True)
        top = [meta for _, meta in candidates[:top_n]]
        if top:
            snap = UniverseSnapshot(
                fetched_at=datetime.now(timezone.utc).isoformat(),
                source="okx_api",
                symbols=top,
                raw_count=len(tickers),
            )
            save_snapshot(snap)
            return snap
        logger.warning("OKX API returned 0 valid symbols, falling back")
    except Exception as exc:  # noqa: BLE001
        logger.warning("OKX API fetch failed: %s", exc)

    # 3. Cache
    if use_cache_if_api_fails:
        cached = load_cached_snapshot()
        if cached is not None and cached.symbols:
            logger.info("using cached universe (%d symbols)", len(cached.symbols))
            return cached

    # 4. Hardcoded fallback
    logger.warning("using hardcoded universe fallback (%d symbols)", len(HARDCODED_UNIVERSE))
    return UniverseSnapshot(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        source="fallback_hardcoded",
        symbols=list(HARDCODED_UNIVERSE[:top_n]),
        raw_count=0,
    )


def _parse_override(value: str) -> list[SymbolMeta]:
    """Parse UNIVERSE_OVERRIDE env like 'BTC-USDT-SWAP,ETH-USDT-SWAP' into SymbolMeta list."""
    out: list[SymbolMeta] = []
    known = {s.base: s for s in HARDCODED_UNIVERSE}
    seen_bases: set[str] = set()
    for raw in value.split(","):
        token = raw.strip().upper()
        if not token:
            continue
        if not token.endswith("-USDT-SWAP"):
            # Allow bare base too
            base = token.split("-")[0] if "-" in token else token
        else:
            base = token.split("-")[0]
        if base in seen_bases:
            continue
        if base.lower() in STABLECOIN_BASES:
            logger.warning("UNIVERSE_OVERRIDE: skipping stablecoin base '%s'", base)
            continue
        out.append(known.get(base) or _default_meta(base))
        seen_bases.add(base)
    return out


def _ticker_quote_volume(ticker: dict[str, Any]) -> float:
    """Return best-effort USDT quote volume for top-universe ranking."""
    for key in ("volCcyQuote24h", "volUsd24h"):
        raw = ticker.get(key)
        if raw not in (None, ""):
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    try:
        return float(ticker.get("volCcy24h", 0) or 0) * float(ticker.get("last", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_stale(snap: UniverseSnapshot, max_age_seconds: int = 26 * 3600) -> bool:
    """True if snapshot is older than max_age_seconds (default 26h, allows for
    scheduler jitter on daily refresh).
    """
    try:
        ts = datetime.fromisoformat(snap.fetched_at)
    except (TypeError, ValueError):
        return True
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() > max_age_seconds


def swap_symbols(snap: UniverseSnapshot) -> list[str]:
    """Convenience: list swap symbols for scheduler / monitor."""
    return [s.swap_symbol for s in snap.symbols]


def spot_symbols(snap: UniverseSnapshot) -> list[str]:
    """Convenience: list spot symbols for confluence + data."""
    return [s.spot_symbol for s in snap.symbols]


def _env_flag_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Print current tradable universe")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--refresh", action="store_true",
                        help="Force live API fetch (skip cache)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.refresh and _cache_path().exists():
        _cache_path().unlink()

    snap = load_universe(top_n=args.top)

    if args.json:
        print(json.dumps({
            "fetched_at": snap.fetched_at,
            "source": snap.source,
            "raw_count": snap.raw_count,
            "symbols": [asdict(s) for s in snap.symbols],
        }, indent=2))
    else:
        print(f"Source : {snap.source}")
        print(f"Fetched: {snap.fetched_at}")
        print(f"Raw OKX tickers: {snap.raw_count}")
        print(f"Symbols ({len(snap.symbols)}):")
        for s in snap.symbols:
            print(f"  {s.base:5s} {s.swap_symbol:18s} lev={s.leverage}x "
                  f"liq_buf>={s.liq_buffer_pct:.0%} min_rr>={s.min_rr} "
                  f"contract_size={s.contract_size}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
