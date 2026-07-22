"""OKX public data fetcher for backtest.

Fetches historical 1h candles from OKX public endpoint, paginating to
cover the requested lookback period. No auth required.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pandas as pd

log = logging.getLogger(__name__)

OKX_BASE = "https://www.okx.com"


def _okx_get(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    """Single OKX public GET request. No auth."""
    url = OKX_BASE + path
    if params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "trade-v1-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_candles(
    symbol: str,
    bar: str = "1H",
    days: int = 180,
    max_per_request: int = 300,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Fetch historical candles for ``symbol``.

    Returns DataFrame indexed by UTC timestamp (ts) with columns
    [open, high, low, close, volume, vol_quote, _raw]. Sorted ascending.
    """
    f = fetcher or _okx_get
    # OKX returns newest first; we paginate by `after` (older than X)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    rows: list[list[str]] = []
    cursor = end_ms
    page = 0
    while cursor > start_ms and page < 30:  # safety cap
        data = f("/api/v5/market/history-candles", {
            "instId": symbol,
            "bar": bar,
            "limit": str(max_per_request),
            "after": str(cursor),
        })
        if data.get("code") != "0":
            raise RuntimeError(f"OKX error: {data}")
        batch = data.get("data", [])
        if not batch:
            break
        rows.extend(batch)
        # Next page: oldest bar in this batch
        oldest = int(batch[-1][0])
        if oldest >= cursor:
            break
        cursor = oldest
        page += 1
        time.sleep(0.05)  # gentle on public API
    if not rows:
        raise RuntimeError(f"No candles returned for {symbol}")
    # OKX row: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
    df = pd.DataFrame(rows, columns=[
        "ts", "open", "high", "low", "close", "volume", "volCcy",
        "volCcyQuote", "confirm",
    ])
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume", "volCcyQuote"):
        df[col] = df[col].astype(float)
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    df = df.set_index("ts")
    log.info("fetched %d candles for %s (%s to %s)",
             len(df), symbol, df.index[0], df.index[-1])
    return df[["open", "high", "low", "close", "volume", "volCcyQuote"]]


def cache_path(symbol: str, bar: str, days: int) -> Path:
    """Local cache file path (per-symbol). CSV (not parquet — no extra dep)."""
    cache_dir = Path("backtest") / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("/", "_").replace("-", "_")
    return cache_dir / f"{safe}_{bar}_{days}d.csv"


def fetch_candles_cached(symbol: str, bar: str = "1H", days: int = 180,
                          force_refresh: bool = False) -> pd.DataFrame:
    """Fetch with on-disk CSV cache."""
    path = cache_path(symbol, bar, days)
    if path.exists() and not force_refresh:
        log.info("cache hit: %s", path.name)
        df = pd.read_csv(path, index_col="ts", parse_dates=["ts"])
        return df
    df = fetch_candles(symbol, bar=bar, days=days)
    df.to_csv(path)
    return df
