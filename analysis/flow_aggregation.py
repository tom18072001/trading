# ============================================
# analysis/flow_aggregation.py
# ============================================
# Pure functions: take a dict of constituent OHLCV DataFrames and produce
# sector-level money-flow aggregates. NO database access here — kept pure
# so it can be unit-tested without I/O.

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


REQUIRED_COLS = ("open", "high", "low", "close", "volume")


@dataclass
class SectorAggregate:
    """One row of sector-level money flow."""
    sector_code: str
    time: pd.Timestamp
    net_dollar_flow: float
    up_vol: float
    down_vol: float
    foreign_net: float
    foreign_buy_val: float
    foreign_sell_val: float
    foreign_intensity: float
    breadth_sma20: float
    breadth_sma50: float
    atr_pct: float
    close_idx: float


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")


def _net_dollar_flow(df: pd.DataFrame) -> float:
    """Σ price·volume·sign(close - prev_close). Last bar only."""
    if len(df) < 2:
        return 0.0
    last = df.iloc[-1]
    prev_close = df.iloc[-2]["close"]
    sign = 1.0 if last["close"] > prev_close else (-1.0 if last["close"] < prev_close else 0.0)
    return float(last["close"] * last["volume"] * sign)


def _up_down_volume(df: pd.DataFrame) -> tuple[float, float]:
    if len(df) < 2:
        return 0.0, 0.0
    last = df.iloc[-1]
    prev_close = df.iloc[-2]["close"]
    if last["close"] > prev_close:
        return float(last["volume"]), 0.0
    if last["close"] < prev_close:
        return 0.0, float(last["volume"])
    return 0.0, 0.0


def _atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float("nan")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    last_close = close.iloc[-1]
    if last_close == 0 or np.isnan(last_close):
        return float("nan")
    return float(atr / last_close)


def _pct_above_sma(close: pd.Series, period: int) -> float | None:
    if len(close) < period:
        return None
    sma = close.rolling(period).mean().iloc[-1]
    return 1.0 if close.iloc[-1] > sma else 0.0


def aggregate_sector(
    sector_code: str,
    constituents: Mapping[str, pd.DataFrame],
    weights: Mapping[str, float] | None = None,
    foreign_net_by_symbol: Mapping[str, float] | None = None,
    foreign_buy_by_symbol: Mapping[str, float] | None = None,
    foreign_sell_by_symbol: Mapping[str, float] | None = None,
) -> SectorAggregate:
    """Aggregate a basket of constituent OHLCV DataFrames into one sector row.

    Each DataFrame must contain columns: open/high/low/close/volume, indexed
    by time (ascending). Optional `weights` (must sum to ~1.0); if absent
    equal-weighted. `foreign_net_by_symbol` is summed if provided.
    """
    if not constituents:
        raise ValueError(f"no constituents for sector {sector_code}")

    syms = list(constituents.keys())
    n = len(syms)
    if weights is None:
        weights = {s: 1.0 / n for s in syms}

    net_flow = 0.0
    up = 0.0
    down = 0.0
    breadth20_hits = 0
    breadth20_n = 0
    breadth50_hits = 0
    breadth50_n = 0
    atr_acc = 0.0
    atr_n = 0
    close_idx = 0.0
    last_time: pd.Timestamp | None = None

    for sym, df in constituents.items():
        _validate(df)
        if df.empty:
            continue
        w = float(weights.get(sym, 1.0 / n))

        net_flow += _net_dollar_flow(df) * w
        u, d = _up_down_volume(df)
        up += u * w
        down += d * w

        b20 = _pct_above_sma(df["close"], 20)
        if b20 is not None:
            breadth20_hits += b20
            breadth20_n += 1
        b50 = _pct_above_sma(df["close"], 50)
        if b50 is not None:
            breadth50_hits += b50
            breadth50_n += 1

        atr = _atr_pct(df)
        if not np.isnan(atr):
            atr_acc += atr * w
            atr_n += 1

        # Synthetic sector index = weighted last-close (not normalized)
        close_idx += float(df["close"].iloc[-1]) * w
        ts = df.index[-1]
        if last_time is None or ts > last_time:
            last_time = ts

    foreign_net = 0.0
    if foreign_net_by_symbol:
        for sym in syms:
            foreign_net += float(foreign_net_by_symbol.get(sym, 0.0))

    foreign_buy = 0.0
    foreign_sell = 0.0
    if foreign_buy_by_symbol:
        for sym in syms:
            foreign_buy += float(foreign_buy_by_symbol.get(sym, 0.0))
    if foreign_sell_by_symbol:
        for sym in syms:
            foreign_sell += float(foreign_sell_by_symbol.get(sym, 0.0))
    # If buy/sell not supplied but net is, derive half/half as fallback
    if foreign_buy == 0.0 and foreign_sell == 0.0 and foreign_net != 0.0:
        foreign_buy = foreign_net if foreign_net > 0 else 0.0
        foreign_sell = -foreign_net if foreign_net < 0 else 0.0

    total_turnover = (up + down) * (close_idx if close_idx else 1.0)
    foreign_intensity = (
        float(foreign_net / total_turnover) if total_turnover else float("nan")
    )

    return SectorAggregate(
        sector_code=sector_code,
        time=last_time if last_time is not None else pd.Timestamp.utcnow(),
        net_dollar_flow=net_flow,
        up_vol=up,
        down_vol=down,
        foreign_net=foreign_net,
        foreign_buy_val=foreign_buy,
        foreign_sell_val=foreign_sell,
        foreign_intensity=foreign_intensity,
        breadth_sma20=(breadth20_hits / breadth20_n) if breadth20_n else float("nan"),
        breadth_sma50=(breadth50_hits / breadth50_n) if breadth50_n else float("nan"),
        atr_pct=(atr_acc / atr_n) if atr_n else float("nan"),
        close_idx=close_idx,
    )


def relative_strength(
    sector_close: pd.Series, vnindex_close: pd.Series, lookback: int
) -> float:
    """RS = sector return − vnindex return over `lookback` sessions."""
    if len(sector_close) <= lookback or len(vnindex_close) <= lookback:
        return float("nan")
    s_ret = sector_close.iloc[-1] / sector_close.iloc[-lookback - 1] - 1
    b_ret = vnindex_close.iloc[-1] / vnindex_close.iloc[-lookback - 1] - 1
    return float(s_ret - b_ret)
