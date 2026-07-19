"""Phase 15 — Interval resampler for sector flow.

Implements the cross-cutting contract in specs/REDESIGN_PHASE15.md §4:
  "Every time-series view exposes a toggle 1D / 1W / 2W / 1M / 1Q. The
   backend resamples; the frontend never re-aggregates client-side."

Inputs: the daily rows from sector_flow_daily.
Output: a DataFrame bucketed by the requested interval, with aggregation
rules appropriate for each metric family (sum for flows, mean for
z-scores / rates, last for index price, max/min for range).
"""
from __future__ import annotations

import pandas as pd

# Pandas resample rule per interval string. "2W" uses 2-week periods
# anchored on Monday.
_RULE = {
    "1d": "D",
    "1w": "W-FRI",
    "2w": "2W-FRI",
    "1m": "M",
    "1q": "Q",
}

# How each column should collapse within a bucket.
_AGG = {
    # flow / volume are additive
    "net_dollar_flow": "sum",
    "foreign_net": "sum",
    "foreign_buy_val": "sum",
    "foreign_sell_val": "sum",
    # price-level series: keep last
    "close_idx": "last",
    "open_idx": "first",
    "high_idx": "max",
    "low_idx": "min",
    # rates / z-scores / breadth: mean
    "flow_z20": "mean",
    "flow_z60": "mean",
    "stealth_score": "mean",
    "breadth_sma20": "mean",
    "breadth_sma50": "mean",
    "atr_pct": "mean",
    "rs_vnindex_5d": "mean",
    "rs_vnindex_20d": "mean",
    "rs_vnindex_60d": "mean",
    "foreign_hit_20d": "mean",
    "foreign_intensity": "mean",
    "up_down_vol_ratio": "mean",
    # counters: last value in bucket is the current state
    "foreign_streak": "last",
    "accumulation_age": "last",
    "return_1d": "sum",  # approximate compound via sum of log-ish; fine for display
}


def normalize_interval(s: str | None) -> str:
    if not s:
        return "1d"
    k = s.lower().strip()
    if k not in _RULE:
        raise ValueError(f"Unknown interval '{s}'. Expected one of {list(_RULE)}")
    return k


def resample(df: pd.DataFrame, interval: str, date_col: str = "date") -> pd.DataFrame:
    """Resample a per-sector daily flow frame onto the requested interval.

    The input frame must have a `sector_code` column and a `date` (YYYY-MM-DD
    string or datetime) column. Grouping is per sector so buckets never mix
    across sectors. Returns a long-format frame with the same columns the
    caller passed in (any column not in _AGG is dropped).
    """
    if df.empty:
        return df

    interval = normalize_interval(interval)
    rule = _RULE[interval]

    d = df.copy()
    d[date_col] = pd.to_datetime(d[date_col])
    # Only aggregate columns we understand; keep sector_code for groupby.
    known = {k: v for k, v in _AGG.items() if k in d.columns}
    if not known:
        return d  # nothing to resample

    pieces = []
    for sector, grp in d.groupby("sector_code", sort=False):
        g = grp.set_index(date_col).sort_index()
        r = g[list(known)].resample(rule).agg(known)
        r = r.dropna(how="all")
        r["sector_code"] = sector
        r = r.reset_index().rename(columns={date_col: "date"})
        pieces.append(r)

    if not pieces:
        return pd.DataFrame(columns=list(df.columns))

    out = pd.concat(pieces, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    # put sector_code / date first for readability
    cols = ["sector_code", "date"] + [c for c in out.columns if c not in ("sector_code", "date")]
    return out[cols]
