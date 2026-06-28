"""Backtest engine — single-symbol and combined multi-symbol.

Strategy (simplified single-TF for speed):
  * Signal: EMA20 > EMA50 (trend) AND close > EMA20 (momentum) → long
            EMA20 < EMA50 AND close < EMA20 → short
            Otherwise → no trade
  * SL: max(1.5%, 1.5x ATR%) of entry
  * TP: 2x SL (1:2 R:R baseline)
  * Min score: ±1 (trend AND momentum agree)
  * Capital: configurable, default 500 USDT
  * Risk per trade: 1% of capital
  * Max concurrent positions (combined): 3
  * Fees: 0.05% per side (OKX futures maker-tier; taker ~0.05%)
  * Funding: ignored for first pass (BTC ~10% APR = ~0.04% per day = ~0.1% per decision bar)

Brackets are simulated: for each open position, every subsequent bar
checks if low/high breached SL or TP. First to be hit closes the trade.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    side: str                  # "long" | "short"
    entry_ts: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float                # in base units
    exit_ts: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""     # "tp" | "sl" | "end_of_data"
    pnl_gross: float = 0.0
    pnl_net: float = 0.0      # after fees
    bars_held: int = 0


@dataclass
class SymbolResult:
    symbol: str
    trades: list[Trade] = field(default_factory=list)
    n_signals: int = 0
    n_filtered: int = 0        # score=0
    final_equity: float = 0.0
    peak_equity: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    avg_pnl: float = 0.0
    avg_pnl_winner: float = 0.0
    avg_pnl_loser: float = 0.0


# ---------------------------------------------------------------------------
# Indicator helpers (mirrors confluence.py logic, single-TF for speed)
# ---------------------------------------------------------------------------

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR(period) using high/low/close. NaN for first ``period`` bars."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def compute_signal(df: pd.DataFrame, i: int) -> int:
    """Return signal at bar ``i``: +1 long, -1 short, 0 no-trade.

    Uses lookback windows: 200 for EMA200, 50 for EMA50, 20 for EMA20.
    Returns 0 if any lookback is unavailable.
    """
    if i < 200:
        return 0
    close = df["close"].iloc[: i + 1]
    ema20 = _ema(close, 20).iloc[-1]
    ema50 = _ema(close, 50).iloc[-1]
    ema200 = _ema(close, 200).iloc[-1]
    last_close = float(close.iloc[-1])
    trend = "UP" if ema50 > ema200 else "DOWN"
    momentum = "UP" if last_close > ema20 else "DOWN"
    if trend == "UP" and momentum == "UP":
        return 1
    if trend == "DOWN" and momentum == "DOWN":
        return -1
    return 0


# ---------------------------------------------------------------------------
# Backtest: single symbol
# ---------------------------------------------------------------------------

def backtest_symbol(
    df: pd.DataFrame,
    symbol: str,
    starting_capital: float = 500.0,
    risk_pct: float = 0.01,
    sl_atr_mult: float = 1.5,
    sl_min_pct: float = 1.5,
    tp_rr: float = 2.0,
    fee_pct: float = 0.0005,        # 0.05% per side
    decision_every_n_bars: int = 6,  # 1h bar × 6 = every 6h
    max_bars_in_trade: int = 200,   # safety: force-close after N bars
) -> SymbolResult:
    """Run backtest on a single symbol's OHLCV.

    ``df`` must have columns: open, high, low, close (and ideally volume).
    Returns SymbolResult with all trades + aggregate metrics.
    """
    result = SymbolResult(symbol=symbol, final_equity=starting_capital,
                          peak_equity=starting_capital)
    equity = starting_capital
    open_trades: list[Trade] = []
    # Pre-compute ATR for SL width
    atr = _atr(df, 14)

    n = len(df)
    for i in range(n):
        # 1. Update exits for open trades
        for t in open_trades:
            high = float(df["high"].iloc[i])
            low = float(df["low"].iloc[i])
            t.bars_held += 1
            # For long: SL hit if low <= SL, TP hit if high >= TP
            # For short: SL hit if high >= SL, TP hit if low <= TP
            if t.side == "long":
                sl_hit = low <= t.stop_loss
                tp_hit = high >= t.take_profit
            else:
                sl_hit = high >= t.stop_loss
                tp_hit = low <= t.take_profit
            # Conservative: if both hit, assume SL first (worst case)
            if sl_hit and tp_hit:
                # Use close to determine which was "first" in practice is hard;
                # we conservatively treat as SL hit when both touch in same bar
                t.exit_price = t.stop_loss
                t.exit_reason = "sl"
                t.exit_ts = df.index[i]
            elif tp_hit:
                t.exit_price = t.take_profit
                t.exit_reason = "tp"
                t.exit_ts = df.index[i]
            elif sl_hit:
                t.exit_price = t.stop_loss
                t.exit_reason = "sl"
                t.exit_ts = df.index[i]
            elif t.bars_held >= max_bars_in_trade:
                t.exit_price = float(df["close"].iloc[i])
                t.exit_reason = "timeout"
                t.exit_ts = df.index[i]

        # 2. Close any finished trades
        still_open = []
        for t in open_trades:
            if t.exit_reason:
                if t.side == "long":
                    t.pnl_gross = (t.exit_price - t.entry_price) * t.qty
                else:
                    t.pnl_gross = (t.entry_price - t.exit_price) * t.qty
                notional_entry = t.entry_price * t.qty
                notional_exit = t.exit_price * t.qty
                fees = (notional_entry + notional_exit) * fee_pct
                t.pnl_net = t.pnl_gross - fees
                equity += t.pnl_net
                if equity > result.peak_equity:
                    result.peak_equity = equity
                dd = result.peak_equity - equity
                if dd > result.max_drawdown_usd:
                    result.max_drawdown_usd = dd
                result.trades.append(t)
            else:
                still_open.append(t)
        open_trades = still_open

        # 3. Decision point: every N bars
        if i % decision_every_n_bars != 0:
            continue
        if not open_trades and i < 200:
            continue  # not enough data for signal

        # 4. Compute signal
        sig = compute_signal(df, i)
        if sig == 0:
            result.n_filtered += 1
            continue
        result.n_signals += 1

        # 5. Build bracket
        entry = float(df["close"].iloc[i])
        atr_val = float(atr.iloc[i]) if not math.isnan(atr.iloc[i]) else 0
        atr_pct = atr_val / entry * 100 if entry > 0 else 0
        stop_pct = max(sl_min_pct, atr_pct * sl_atr_mult)
        reward_pct = stop_pct * tp_rr

        if sig > 0:
            side = "long"
            sl = entry * (1 - stop_pct / 100)
            tp = entry * (1 + reward_pct / 100)
        else:
            side = "short"
            sl = entry * (1 + stop_pct / 100)
            tp = entry * (1 - reward_pct / 100)

        # Position size by risk
        risk_usd = equity * risk_pct
        stop_distance = abs(entry - sl)
        if stop_distance <= 0:
            continue
        qty = risk_usd / stop_distance
        # Cap by 30% notional
        max_notional = equity * 0.30
        if qty * entry > max_notional:
            qty = max_notional / entry

        trade = Trade(
            symbol=symbol, side=side,
            entry_ts=df.index[i], entry_price=entry,
            stop_loss=sl, take_profit=tp, qty=qty,
        )
        open_trades.append(trade)

    # Force-close any remaining positions at last close
    if open_trades and n > 0:
        last_close = float(df["close"].iloc[-1])
        last_ts = df.index[-1]
        for t in open_trades:
            t.exit_price = last_close
            t.exit_reason = "end_of_data"
            t.exit_ts = last_ts
            if t.side == "long":
                t.pnl_gross = (last_close - t.entry_price) * t.qty
            else:
                t.pnl_gross = (t.entry_price - last_close) * t.qty
            notional_entry = t.entry_price * t.qty
            notional_exit = last_close * t.qty
            fees = (notional_entry + notional_exit) * fee_pct
            t.pnl_net = t.pnl_gross - fees
            equity += t.pnl_net
            result.trades.append(t)

    result.final_equity = equity
    if result.peak_equity > 0:
        result.max_drawdown_pct = result.max_drawdown_usd / result.peak_equity
    # Compute aggregate metrics
    if result.trades:
        pnls = [t.pnl_net for t in result.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        result.win_rate = len(wins) / len(pnls)
        result.avg_pnl = float(np.mean(pnls))
        if wins:
            result.avg_pnl_winner = float(np.mean(wins))
        if losses:
            result.avg_pnl_loser = float(np.mean(losses))
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        if gross_loss > 0:
            result.profit_factor = gross_profit / gross_loss
        # Per-trade Sharpe (annualized assuming ~365 trades/yr)
        if len(pnls) > 1:
            mean_p = float(np.mean(pnls))
            std_p = float(np.std(pnls, ddof=1))
            if std_p > 0:
                result.sharpe = (mean_p / std_p) * math.sqrt(len(pnls))
                # Downside-only std for Sortino
                neg = [p for p in pnls if p < 0]
                if neg:
                    dstd = float(np.std(neg, ddof=1))
                    if dstd > 0:
                        result.sortino = (mean_p / dstd) * math.sqrt(len(pnls))
    return result


# ---------------------------------------------------------------------------
# Backtest: combined multi-symbol
# ---------------------------------------------------------------------------

@dataclass
class CombinedResult:
    starting_capital: float
    final_equity: float
    total_pnl: float
    total_return_pct: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    win_rate: float
    profit_factor: float
    n_trades: int
    n_signals_total: int
    n_filtered_total: int
    per_symbol: dict[str, SymbolResult] = field(default_factory=dict)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)


def backtest_combined(
    data: dict[str, pd.DataFrame],
    starting_capital: float = 500.0,
    risk_pct: float = 0.01,
    max_concurrent: int = 3,
    **kwargs: Any,
) -> CombinedResult:
    """Run combined backtest across multiple symbols with shared equity.

    Each bar:
      1. Update exits for all open positions
      2. Collect new signals from each symbol
      3. Rank by |score| (here all ±1; could add signal strength)
      4. Open top-N candidates (N = remaining slots)
      5. Each position sized by per-trade risk on shared equity
    """
    symbols = list(data.keys())
    # Pre-compute indicators per symbol
    indicators = {s: {"atr": _atr(df, 14)} for s, df in data.items()}
    # Common index (union of timestamps, sorted)
    all_idx = sorted(set().union(*[df.index for df in data.values()]))
    all_idx_set = set(all_idx)

    # Equity tracking
    equity = starting_capital
    peak_equity = starting_capital
    max_dd = 0.0
    equity_curve: list[tuple[pd.Timestamp, float]] = []
    per_symbol: dict[str, SymbolResult] = {s: SymbolResult(symbol=s,
                                          final_equity=0.0,
                                          peak_equity=0.0) for s in symbols}
    all_trades: list[Trade] = []
    n_signals_total = 0
    n_filtered_total = 0
    open_trades: list[Trade] = []

    # Map ts -> {symbol: row index in that df} for fast lookup
    ts_to_idx: dict[pd.Timestamp, dict[str, int]] = defaultdict(dict)
    for sym, df in data.items():
        for i, ts in enumerate(df.index):
            ts_to_idx[ts][sym] = i

    fee_pct = kwargs.get("fee_pct", 0.0005)
    decision_every_n_bars = kwargs.get("decision_every_n_bars", 6)
    sl_atr_mult = kwargs.get("sl_atr_mult", 1.5)
    sl_min_pct = kwargs.get("sl_min_pct", 1.5)
    tp_rr = kwargs.get("tp_rr", 2.0)
    max_bars_in_trade = kwargs.get("max_bars_in_trade", 200)

    for ts in all_idx:
        # 1. Update exits
        for t in open_trades:
            sym = t.symbol
            if sym not in ts_to_idx.get(ts, {}):
                continue
            i = ts_to_idx[ts][sym]
            high = float(data[sym]["high"].iloc[i])
            low = float(data[sym]["low"].iloc[i])
            t.bars_held += 1
            if t.side == "long":
                sl_hit = low <= t.stop_loss
                tp_hit = high >= t.take_profit
            else:
                sl_hit = high >= t.stop_loss
                tp_hit = low <= t.take_profit
            if sl_hit and tp_hit:
                t.exit_price = t.stop_loss
                t.exit_reason = "sl"
            elif tp_hit:
                t.exit_price = t.take_profit
                t.exit_reason = "tp"
            elif sl_hit:
                t.exit_price = t.stop_loss
                t.exit_reason = "sl"
            elif t.bars_held >= max_bars_in_trade:
                t.exit_price = float(data[sym]["close"].iloc[i])
                t.exit_reason = "timeout"
            if t.exit_reason:
                t.exit_ts = ts

        # 2. Close finished trades
        still_open = []
        for t in open_trades:
            if t.exit_reason:
                if t.side == "long":
                    t.pnl_gross = (t.exit_price - t.entry_price) * t.qty
                else:
                    t.pnl_gross = (t.entry_price - t.exit_price) * t.qty
                notional_entry = t.entry_price * t.qty
                notional_exit = t.exit_price * t.qty
                fees = (notional_entry + notional_exit) * fee_pct
                t.pnl_net = t.pnl_gross - fees
                equity += t.pnl_net
                peak_equity = max(peak_equity, equity)
                dd = peak_equity - equity
                max_dd = max(max_dd, dd)
                all_trades.append(t)
                per_symbol[t.symbol].trades.append(t)
            else:
                still_open.append(t)
        open_trades = still_open
        equity_curve.append((ts, equity))

        # 3. New entries: gather signals from each symbol at this ts
        if len(open_trades) >= max_concurrent:
            continue
        slots = max_concurrent - len(open_trades)
        candidates: list[tuple[pd.Timestamp, Trade]] = []
        for sym in symbols:
            if sym not in ts_to_idx.get(ts, {}):
                continue
            i = ts_to_idx[ts][sym]
            if i < 200:
                continue
            sig = compute_signal(data[sym], i)
            if sig == 0:
                per_symbol[sym].n_filtered += 1
                n_filtered_total += 1
                continue
            per_symbol[sym].n_signals += 1
            n_signals_total += 1

            entry = float(data[sym]["close"].iloc[i])
            atr_val = float(indicators[sym]["atr"].iloc[i]) if not math.isnan(indicators[sym]["atr"].iloc[i]) else 0
            atr_pct = atr_val / entry * 100 if entry > 0 else 0
            stop_pct = max(sl_min_pct, atr_pct * sl_atr_mult)
            reward_pct = stop_pct * tp_rr
            if sig > 0:
                side = "long"
                sl = entry * (1 - stop_pct / 100)
                tp = entry * (1 + reward_pct / 100)
            else:
                side = "short"
                sl = entry * (1 + stop_pct / 100)
                tp = entry * (1 - reward_pct / 100)
            risk_usd = equity * risk_pct
            stop_distance = abs(entry - sl)
            if stop_distance <= 0:
                continue
            qty = risk_usd / stop_distance
            max_notional = equity * 0.30
            if qty * entry > max_notional:
                qty = max_notional / entry
            trade = Trade(
                symbol=sym, side=side,
                entry_ts=ts, entry_price=entry,
                stop_loss=sl, take_profit=tp, qty=qty,
            )
            candidates.append((ts, trade))
        # Open first N (FIFO; could rank by signal strength)
        for _, t in candidates[:slots]:
            open_trades.append(t)

    # Force-close any remaining open trades at last close
    if open_trades:
        for sym in symbols:
            df = data[sym]
            last_close = float(df["close"].iloc[-1])
            last_ts = df.index[-1]
            for t in open_trades:
                if t.symbol != sym:
                    continue
                t.exit_price = last_close
                t.exit_reason = "end_of_data"
                t.exit_ts = last_ts
                if t.side == "long":
                    t.pnl_gross = (last_close - t.entry_price) * t.qty
                else:
                    t.pnl_gross = (t.entry_price - last_close) * t.qty
                notional_entry = t.entry_price * t.qty
                notional_exit = last_close * t.qty
                fees = (notional_entry + notional_exit) * fee_pct
                t.pnl_net = t.pnl_gross - fees
                equity += t.pnl_net
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, peak_equity - equity)
                all_trades.append(t)
                per_symbol[sym].trades.append(t)
        open_trades = []

    # Compute combined metrics
    pnls = [t.pnl_net for t in all_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (sum(wins) if wins else 0.0)
    sharpe = sortino = 0.0
    if len(pnls) > 1:
        mean_p = float(np.mean(pnls))
        std_p = float(np.std(pnls, ddof=1))
        if std_p > 0:
            sharpe = (mean_p / std_p) * math.sqrt(len(pnls))
        neg = [p for p in pnls if p < 0]
        if neg:
            dstd = float(np.std(neg, ddof=1))
            if dstd > 0:
                sortino = (mean_p / dstd) * math.sqrt(len(pnls))

    for sym, r in per_symbol.items():
        r.final_equity = starting_capital + sum(t.pnl_net for t in r.trades)
        if r.trades:
            r.peak_equity = starting_capital + max(
                (sum(t.pnl_net for t in r.trades[: i + 1]) for i in range(len(r.trades))),
                default=0.0,
            )
            sp = [t.pnl_net for t in r.trades]
            sw = [p for p in sp if p > 0]
            sl_ = [p for p in sp if p < 0]
            r.win_rate = len(sw) / len(sp) if sp else 0
            r.avg_pnl = float(np.mean(sp)) if sp else 0
            r.avg_pnl_winner = float(np.mean(sw)) if sw else 0
            r.avg_pnl_loser = float(np.mean(sl_)) if sl_ else 0
            gp = sum(sw) if sw else 0
            gl = abs(sum(sl_)) if sl_ else 0
            if gl > 0:
                r.profit_factor = gp / gl
            r.max_drawdown_usd = max(
                (starting_capital + sum(t.pnl_net for t in r.trades[: i + 1])
                 for i in range(len(r.trades))),
                default=starting_capital,
            ) - (starting_capital + min(
                (sum(t.pnl_net for t in r.trades[: i + 1]) for i in range(len(r.trades))),
                default=0.0,
            ))
            # Per-symbol Sharpe (annualized; N trades per year assumption)
            if len(sp) > 1:
                mean_p = float(np.mean(sp))
                std_p = float(np.std(sp, ddof=1))
                if std_p > 0:
                    r.sharpe = (mean_p / std_p) * math.sqrt(len(sp))
                neg = [p for p in sp if p < 0]
                if neg:
                    dstd = float(np.std(neg, ddof=1))
                    if dstd > 0:
                        r.sortino = (mean_p / dstd) * math.sqrt(len(sp))

    return CombinedResult(
        starting_capital=starting_capital,
        final_equity=equity,
        total_pnl=equity - starting_capital,
        total_return_pct=(equity - starting_capital) / starting_capital * 100,
        max_drawdown_usd=max_dd,
        max_drawdown_pct=max_dd / peak_equity if peak_equity > 0 else 0,
        sharpe=sharpe,
        sortino=sortino,
        win_rate=win_rate,
        profit_factor=profit_factor,
        n_trades=len(all_trades),
        n_signals_total=n_signals_total,
        n_filtered_total=n_filtered_total,
        per_symbol=per_symbol,
        equity_curve=equity_curve,
    )
