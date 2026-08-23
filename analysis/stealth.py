# ============================================
# analysis/stealth.py — Early Money-Flow Detection (CLAUDE.md §16)
# ============================================
# Detects "stealth accumulation" — sectors where smart money is loading
# quietly before price has moved. Implements the 5-condition gate from §16.1.
#
# Pure functions over a per-sector panel (sorted by date). No DB, no IO.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# --- Tunable thresholds (§16.1 conditions; scoring per §16.1-2026-08-23) ---
FLOW_Z_THRESHOLD = 1.0          # cond1: flow_z20 > +1.0
FOREIGN_HIT_THRESHOLD = 0.60    # cond2: ≥60% of last 20 sessions with foreign_net > 0
RETURN_BOTTOM_FRAC = float(__import__("os").environ.get("STEALTH_RETURN_BOTTOM_FRAC", "0.40"))  # cond5: price in bottom X% of 60d range
STEALTH_MIN_SESSIONS = int(__import__("os").environ.get("STEALTH_MIN_SESSIONS", "3"))  # score held ≥N sessions

# 2026-08-23: the gate stopped being a conjunction. Measured over the whole
# 13,470-row panel, all five conditions held simultaneously on 0.3% of rows and
# the longest consecutive run across 15 sectors over 3.5 years was **2
# sessions** — so `all five for ≥3` was arithmetically unreachable and
# `accumulation_age` was 0 on every row ever written. It was not that §16 had
# never been tested; it could not fire.
#
# Individual pass rates (full panel): c1 17.5% · c2 20.4% · c3 34.7% ·
# c4 52.1% · c5 47.7%. Five weakly-correlated conditions at those rates cannot
# co-occur for 3 sessions.
#
# Requiring ≥4 of 5 instead yields 23 events across 11 sectors — a live gate.
# The five conditions are deliberately unweighted: §16.1 gives no basis to rank
# them, and an invented weight vector would be a number nobody could defend.
STEALTH_MIN_CONDITIONS = int(__import__("os").environ.get("STEALTH_MIN_CONDITIONS", "4"))


@dataclass
class StealthState:
    """Per-row stealth diagnostic."""
    in_stealth: bool
    conditions_met: int
    accumulation_age: int  # days since stealth first flipped on in current run


def _rolling_z(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(5, window // 2)).mean()
    std = series.rolling(window, min_periods=max(5, window // 2)).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def _foreign_streak(foreign: pd.Series) -> pd.Series:
    """Consecutive sessions with foreign_net > 0, capped at 20."""
    pos = (foreign.fillna(0) > 0).astype(int)
    out = np.zeros(len(pos), dtype=int)
    run = 0
    for i, v in enumerate(pos.values):
        run = run + 1 if v else 0
        out[i] = min(run, 20)
    return pd.Series(out, index=foreign.index)


def _foreign_hit_20d(foreign: pd.Series) -> pd.Series:
    pos = (foreign.fillna(0) > 0).astype(float)
    return pos.rolling(20, min_periods=5).mean()


def _atr_rank_20d(atr: pd.Series) -> pd.Series:
    """0..1 rank of current atr vs 20d window (0 = quietest)."""
    return atr.rolling(20, min_periods=5).rank(pct=True)


def _return_60d_position(close: pd.Series) -> pd.Series:
    """Where does today's close sit in the 60d range? 0 = bottom, 1 = top."""
    hi = close.rolling(60, min_periods=10).max()
    lo = close.rolling(60, min_periods=10).min()
    span = (hi - lo).replace(0, np.nan)
    return (close - lo) / span


def _return_20d_z(close: pd.Series) -> pd.Series:
    ret20 = close.pct_change(20)
    return (ret20 - ret20.rolling(60, min_periods=10).mean()) / \
        ret20.rolling(60, min_periods=10).std(ddof=0).replace(0, np.nan)


def compute_leading_features(df: pd.DataFrame) -> pd.DataFrame:
    """Input columns: date, sector_code, net_dollar_flow, foreign_net,
    atr_pct, close_idx, breadth_sma20.

    Returns the same df with new columns: flow_z20, flow_z60,
    foreign_streak, foreign_hit_20d, stealth_score, flow_price_divergence,
    conditions_met (0-5), in_stealth (bool), accumulation_age.
    """
    if df.empty:
        return df
    df = df.sort_values(["sector_code", "date"]).reset_index(drop=True)
    out_parts = []
    for _code, grp in df.groupby("sector_code", sort=False):
        g = grp.copy()
        flow = g["net_dollar_flow"].astype(float)
        foreign = g["foreign_net"].astype(float)
        atr = g["atr_pct"].astype(float)
        close = g["close_idx"].astype(float)
        breadth = g["breadth_sma20"].astype(float)

        g["flow_z20"] = _rolling_z(flow, 20)
        g["flow_z60"] = _rolling_z(flow, 60)
        g["foreign_streak"] = _foreign_streak(foreign)
        g["foreign_hit_20d"] = _foreign_hit_20d(foreign)

        atr_rank = _atr_rank_20d(atr)
        breadth_rising = (breadth.diff().rolling(5, min_periods=1).mean() > 0).astype(float)
        g["stealth_score"] = (
            g["flow_z20"].fillna(0) * breadth_rising * (1.0 / (1.0 + atr_rank.fillna(1.0)))
        )

        ret20_z = _return_20d_z(close)
        g["flow_price_divergence"] = g["flow_z20"].fillna(0) - ret20_z.fillna(0)

        # --- §16.1 conditions, scored rather than AND-ed ---
        cond1 = g["flow_z20"] > FLOW_Z_THRESHOLD
        cond2 = g["foreign_hit_20d"] >= FOREIGN_HIT_THRESHOLD
        cond3 = breadth_rising.astype(bool)
        atr_median = atr.rolling(20, min_periods=5).median()
        cond4 = atr < atr_median
        cond5 = _return_60d_position(close) < RETURN_BOTTOM_FRAC

        # Data-availability fallbacks. A condition that CANNOT be evaluated is
        # dropped from both the numerator and the denominator — counting it as
        # a failure would silently raise the bar, and counting it as a pass
        # would invent evidence.
        #  - foreign_net all-zero  → cond2 unevaluable (was true until the
        #    2026-08-23 backfill; 12,616/13,470 rows are non-zero now).
        #  - STEALTH_SYNTHETIC_CLOSE=1 → cond5 unevaluable, because a synthetic
        #    close_idx is derived from net flow and would make cond5 a restated
        #    cond1.
        import os as _os
        foreign_available = foreign.abs().sum() > 0
        synthetic_close = _os.environ.get("STEALTH_SYNTHETIC_CLOSE", "0") == "1"

        conds = [cond1.fillna(False), cond3.fillna(False), cond4.fillna(False)]
        if foreign_available:
            conds.append(cond2.fillna(False))
        if not synthetic_close:
            conds.append(cond5.fillna(False))

        score = sum(c.astype(int) for c in conds)
        g["conditions_met"] = score
        # Scale the requirement to the conditions actually evaluable, so
        # dropping one does not quietly make the gate stricter.
        need = min(STEALTH_MIN_CONDITIONS, len(conds))
        qualifies = score >= need

        # Persistence: the score held for ≥STEALTH_MIN_SESSIONS sessions.
        persisted = qualifies.rolling(STEALTH_MIN_SESSIONS, min_periods=STEALTH_MIN_SESSIONS).sum() \
            == STEALTH_MIN_SESSIONS
        g["in_stealth"] = persisted.fillna(False).astype(bool)

        # Accumulation age: days since stealth flipped on in current run
        age = np.zeros(len(g), dtype=int)
        run = 0
        for i, v in enumerate(g["in_stealth"].values):
            run = run + 1 if v else 0
            age[i] = run
        g["accumulation_age"] = age

        out_parts.append(g)

    return pd.concat(out_parts, ignore_index=True)


def active_stealth_sectors(df_with_features: pd.DataFrame) -> pd.DataFrame:
    """Return the rows where each sector's LATEST date is currently in stealth."""
    if df_with_features.empty:
        return df_with_features
    latest = (
        df_with_features.sort_values(["sector_code", "date"])
        .groupby("sector_code").tail(1)
    )
    return latest[latest["in_stealth"]].reset_index(drop=True)
