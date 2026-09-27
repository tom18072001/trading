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


def _market_now():
    """Naive market-local datetime. Lazy import keeps this module dependency-light."""
    from utils.clock import now
    return now().replace(tzinfo=None)


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
    # Weighted last-bar return of the basket (review 2026-08-22, P0-3).
    # `close_idx` is a raw weighted SUM OF PRICES, so it jumps on a stock
    # split or a constituent change and manufactures a fake return. This is
    # the split-safe quantity: the mean of each constituent's own 1-day
    # return, which no corporate action can distort. Downstream code should
    # prefer this over close_idx ratios.
    basket_return: float = 0.0


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


def _last_bar_return(df: pd.DataFrame) -> float | None:
    """close_t / close_{t-1} - 1 for the final bar, or None if undefined."""
    if len(df) < 2:
        return None
    prev = float(df.iloc[-2]["close"])
    last = float(df.iloc[-1]["close"])
    if prev <= 0 or np.isnan(prev) or np.isnan(last):
        return None
    return last / prev - 1.0


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
        weights = dict.fromkeys(syms, 1.0 / n)

    net_flow = 0.0
    up = 0.0
    down = 0.0
    breadth20_hits = 0
    breadth20_n = 0
    breadth50_hits = 0
    breadth50_n = 0
    atr_acc = 0.0
    atr_w = 0.0
    close_idx = 0.0
    ret_acc = 0.0
    ret_w = 0.0
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

        # Weighted MEAN: divide by the weights that contributed, not by a
        # count. It used to add atr*w (w = 1/n) and then divide by atr_n = n,
        # i.e. divide by n twice -- every sector ATR since the table existed
        # was 1/5 of the basket's (median 0.57% instead of ~2.7%). That fed the
        # sentinel stop (CRITICAL on 21.7% of sector-days instead of 0.7%), the
        # backtest slippage (always the 0.3% floor) and §16.15's premise.
        # Review 2026-09-24 §4.1/3.
        atr = _atr_pct(df)
        if not np.isnan(atr):
            atr_acc += atr * w
            atr_w += w

        # Weighted SUM OF RAW PRICES. Not an index: it jumps whenever the set
        # of constituents that fetched changes (STEEL +62% then -39% on
        # 2026-09-22/23 with `return_1d` +0.5% / -0.1%). `sector_flow_daily`
        # stores a CHAINED index instead (`chain_close_idx`, 2026-09-25); this
        # raw figure stays on the intraday table only.
        close_idx += float(df["close"].iloc[-1]) * w

        r = _last_bar_return(df)
        if r is not None:
            ret_acc += r * w
            ret_w += w
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
        time=last_time if last_time is not None else pd.Timestamp(_market_now()),
        net_dollar_flow=net_flow,
        up_vol=up,
        down_vol=down,
        foreign_net=foreign_net,
        foreign_buy_val=foreign_buy,
        foreign_sell_val=foreign_sell,
        foreign_intensity=foreign_intensity,
        breadth_sma20=(breadth20_hits / breadth20_n) if breadth20_n else float("nan"),
        breadth_sma50=(breadth50_hits / breadth50_n) if breadth50_n else float("nan"),
        atr_pct=(atr_acc / atr_w) if atr_w > 0 else float("nan"),
        close_idx=close_idx,
        basket_return=(ret_acc / ret_w) if ret_w > 0 else 0.0,
    )


def chain_close_idx(prev_close_idx: float | None, basket_return: float | None,
                    base: float = 100.0) -> float:
    """The sector's daily index level, chained from its split-safe return.

    `prev_close_idx` is the previous session's stored level; `basket_return` is
    today's mean constituent return (`SectorAggregate.basket_return`). A
    missing previous level starts the chain at `base`; a missing return
    carries the level flat rather than inventing a move.
    """
    prev = prev_close_idx if (prev_close_idx is not None and prev_close_idx > 0
                              and not np.isnan(prev_close_idx)) else base
    if basket_return is None or np.isnan(basket_return):
        return float(prev)
    return float(prev * (1.0 + basket_return))


def relative_strength(
    sector_close: pd.Series, vnindex_close: pd.Series, lookback: int
) -> float:
    """RS = sector return − vnindex return over `lookback` sessions."""
    if len(sector_close) <= lookback or len(vnindex_close) <= lookback:
        return float("nan")
    s_ret = sector_close.iloc[-1] / sector_close.iloc[-lookback - 1] - 1
    b_ret = vnindex_close.iloc[-1] / vnindex_close.iloc[-lookback - 1] - 1
    return float(s_ret - b_ret)
