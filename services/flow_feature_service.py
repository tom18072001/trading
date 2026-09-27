# ============================================
# services/flow_feature_service.py
# ============================================
# Builds the model-ready feature frame from sector_flow_daily + macro_anchors.
# Pure read-side service: no writes. Returns a DataFrame ready for the
# rotation ranker (date, sector_code, features..., target).

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config import ROTATION_TARGET_HORIZON_DAYS
from database.models import MacroAnchor, SectorFlowDaily

FEATURE_COLS = [
    "net_dollar_flow",
    "foreign_net",
    "up_down_vol_ratio",
    "breadth_sma20",
    "breadth_sma50",
    "rs_vnindex_5d",
    "rs_vnindex_20d",
    "atr_pct",
    "flow_lag_1",
    "flow_lag_3",
    "flow_lag_5",
    "macro_vn_ret_5d",
    # --- §16.2 leading / stealth features (2026-06-18: wired into ranker) ---
    # Previously computed in analysis/stealth.py and stored on sector_flow_daily
    # but NEVER fed to the model — the ranker was blind to the early-flow edge.
    "flow_z20",
    "flow_z60",
    "foreign_streak",
    "foreign_hit_20d",
    "stealth_score",
    "flow_price_divergence",
    "accumulation_age",
]

# Leading features can be NaN for the first ~20-60 rows of each sector (rolling
# windows) or when stealth features haven't been backfilled. We 0-fill them so
# a dropna on FEATURE_COLS+target doesn't decimate the training panel. They are
# z-scores / counts centred near 0, so 0 is a neutral fill.
_LEADING_FILL_COLS = [
    "flow_z20", "flow_z60", "foreign_streak", "foreign_hit_20d",
    "stealth_score", "flow_price_divergence", "accumulation_age",
]

#: `up_down_vol_ratio` = up volume / down volume, stored NULL when down volume
#: is 0 -- an ALL-UP day (mean return_1d +1.9% on those rows vs -0.3% on the
#: rest). Training dropped those rows (18% of the panel) and prediction filled
#: them with 0, i.e. "all down" (review 2026-09-24 §4.1/9). One mapping now,
#: in `build()`, which training and prediction both call: NULL -> the cap, and
#: finite values clipped to it, so an all-up day ranks above every finite
#: reading. 1000 is above the 99.9th percentile of finite values (~1,480 is
#: p99.9 on the 2026-09-24 panel, the median is 0.55), so the clip touches
#: almost nothing a tree has split on. A day with NO volume either way (27 of
#: 16,485 intraday rows) is also NULL and gets the cap too -- accepted.
UPDOWN_RATIO_CAP = 1000.0


class FlowFeatureService:
    def __init__(self, session: Session):
        self.session = session

    def _load_daily(self) -> pd.DataFrame:
        rows = self.session.query(SectorFlowDaily).all()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([{
            "date": r.date,
            "sector_code": r.sector_code,
            "net_dollar_flow": r.net_dollar_flow,
            "foreign_net": r.foreign_net,
            "up_down_vol_ratio": r.up_down_vol_ratio,
            "breadth_sma20": r.breadth_sma20,
            "breadth_sma50": r.breadth_sma50,
            "rs_vnindex_5d": r.rs_vnindex_5d,
            "rs_vnindex_20d": r.rs_vnindex_20d,
            "atr_pct": r.atr_pct,
            "close_idx": r.close_idx,
            "return_1d": r.return_1d,
            # §16.2 leading / stealth features
            "flow_z20": r.flow_z20,
            "flow_z60": r.flow_z60,
            "foreign_streak": r.foreign_streak,
            "foreign_hit_20d": r.foreign_hit_20d,
            "stealth_score": r.stealth_score,
            "flow_price_divergence": r.flow_price_divergence,
            "accumulation_age": r.accumulation_age,
        } for r in rows])
        return df.sort_values(["sector_code", "date"]).reset_index(drop=True)

    def _load_macro(self) -> pd.DataFrame:
        rows = self.session.query(MacroAnchor).order_by(MacroAnchor.time).all()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([{
            "time": r.time, "vnindex": r.vnindex, "usdvnd": r.usdvnd,
            "brent": r.brent, "us10y": r.us10y, "gold": r.gold,
        } for r in rows])

    def _macro_vnindex_daily(self) -> pd.Series:
        """VNINDEX by date (YYYY-MM-DD): the last PLAUSIBLE hourly snapshot of
        each day. 613 rows of this column are 1.82 (review 2026-09-24 §4.1/4);
        the transition bars in and out of them made `macro_vn_ret_5d` read
        -99.9% and +87,000%. `plausible_vnindex` drops them per value."""
        from services.macro_service import plausible_vnindex

        macro = self._load_macro()
        if macro.empty or "vnindex" not in macro:
            return pd.Series(dtype=float)
        m = macro.assign(date=pd.to_datetime(macro["time"]).dt.strftime("%Y-%m-%d"))
        m = m.loc[plausible_vnindex(m["vnindex"]).index]
        return m.groupby("date")["vnindex"].last().astype(float).sort_index()

    def build(self, with_target: bool = True) -> pd.DataFrame:
        df = self._load_daily()
        if df.empty:
            return df
        df["flow_lag_1"] = df.groupby("sector_code")["net_dollar_flow"].shift(1)
        df["flow_lag_3"] = df.groupby("sector_code")["net_dollar_flow"].shift(3)
        df["flow_lag_5"] = df.groupby("sector_code")["net_dollar_flow"].shift(5)

        # All-up days are NULL in storage; see UPDOWN_RATIO_CAP.
        if "up_down_vol_ratio" in df.columns:
            df["up_down_vol_ratio"] = (
                pd.to_numeric(df["up_down_vol_ratio"], errors="coerce")
                  .clip(upper=UPDOWN_RATIO_CAP).fillna(UPDOWN_RATIO_CAP)
            )

        # Ensure §16.2 leading columns exist + are 0-filled (see _LEADING_FILL_COLS).
        for col in _LEADING_FILL_COLS:
            if col in df.columns:
                df[col] = df[col].fillna(0.0)
            else:
                df[col] = 0.0

        # --- rs_vnindex_5d / rs_vnindex_20d ------------------------------
        # Measured 2026-08-23: both columns were NULL on all 13,140 rows. They
        # have been in FEATURE_COLS since day one and nothing ever wrote them,
        # which is also what forced pandas to type them `object` and knocked
        # LightGBM into the mean-flow fallback on all 74 nightly runs.
        #
        # They are derivable from data already in the table, so they are
        # computed here rather than waiting on an ingest change -- that also
        # backfills the whole 876-day history for free.
        #
        # Benchmark preference: VNINDEX from macro_anchors when it is present
        # for the date, otherwise the equal-weighted cross-sector composite,
        # which is a legitimate "strength vs the market" reading and needs no
        # external source. `rs_benchmark` records which one was used.
        df = self._add_relative_strength(df)

        # 5 SESSIONS of VNINDEX. It was pct_change(5) over the HOURLY
        # macro_anchors rows -- a 5-hour return, then the day's last one -- and
        # on the 1.82 rows a constant, which is why it was 0 on 99.6% of rows.
        vn = self._macro_vnindex_daily()
        if len(vn) > 5:
            macro_daily = vn.pct_change(5).rename("macro_vn_ret_5d")
            df = df.merge(macro_daily, left_on="date", right_index=True, how="left")
        else:
            df["macro_vn_ret_5d"] = np.nan

        # Force every model input to a real numeric dtype.
        #
        # Found by running the live DB on 2026-08-22: rs_vnindex_5d and
        # rs_vnindex_20d are 100% NULL (nothing has ever written them), so
        # pandas types those columns as `object`. RotationModelService then
        # fillna(0.0)'s them -- which leaves an object column full of floats --
        # and LightGBM refuses it with "pandas dtypes must be int, float or
        # bool". RotationRanker caught that, fell back to _MeanFlowRanker, and
        # did so on EVERY nightly run: 74 model_runs, not one of them a real
        # ranker. The published "score" column was therefore raw net_dollar_flow
        # all along (see sector_signals: scores of 6e+07).
        #
        # One coercion is the whole difference between a ranker and
        # "sort the sectors by size".
        for col in FEATURE_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
            else:
                df[col] = 0.0

        if with_target:
            df["fwd_return"] = (
                df.groupby("sector_code")["close_idx"]
                  .shift(-ROTATION_TARGET_HORIZON_DAYS) / df["close_idx"] - 1
            )
            df["target"] = df["fwd_return"]
        return df

    def _add_relative_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill rs_vnindex_5d / rs_vnindex_20d = sector return - benchmark return."""
        close = pd.to_numeric(df.get("close_idx"), errors="coerce")
        if close is None or close.notna().sum() == 0:
            df["rs_vnindex_5d"] = np.nan
            df["rs_vnindex_20d"] = np.nan
            df["rs_benchmark"] = "none"
            return df

        df = df.copy()
        df["close_idx"] = close

        bench = None
        source = "sector_composite"
        vn = self._macro_vnindex_daily()          # plausible values only
        if not vn.empty:
            # Only trust it if it actually covers the panel.
            coverage = df["date"].isin(vn.index).mean()
            if len(vn) > 30 and coverage > 0.8:
                bench = vn
                source = "vnindex"

        if bench is None:
            # Equal-weighted composite of every sector's own index.
            bench = df.groupby("date")["close_idx"].mean().dropna()

        for lb in (5, 20):
            b_ret = (bench / bench.shift(lb) - 1.0).rename(f"_b{lb}")
            s_ret = df.groupby("sector_code")["close_idx"].pct_change(lb)
            df[f"rs_vnindex_{lb}d"] = (
                s_ret.to_numpy() - df["date"].map(b_ret).to_numpy()
            )

        df["rs_benchmark"] = source
        return df

    #: Stored columns the ranker reads directly. A column NULL for EVERY sector
    #: on a session was never computed -- `build()` would 0-fill it and the
    #: ranker would score that zero as if it were a reading.
    STORED_FEATURE_COLS = (
        "net_dollar_flow", "foreign_net", "up_down_vol_ratio", "breadth_sma20",
        "breadth_sma50", "atr_pct", *_LEADING_FILL_COLS,
    )

    def unfilled_columns_on_latest(self) -> tuple[str | None, list[str]]:
        """(latest date, stored feature columns NULL on every sector that day).

        Read from the table, before `build()` fills anything: from 2026-08-25
        the scheduled rollup left the seven §16.2 columns NULL on all 15
        sectors and the ranker scored a month of zeros (review 2026-09-24
        §4.1/1). This is the check that would have refused to.
        """
        from sqlalchemy import func
        last = self.session.query(func.max(SectorFlowDaily.date)).scalar()
        if last is None:
            return None, []
        rows = self.session.query(SectorFlowDaily).filter(SectorFlowDaily.date == last).all()
        missing = [c for c in self.STORED_FEATURE_COLS
                   if rows and all(getattr(r, c) is None for r in rows)]
        return last, missing

    def latest_features(self) -> pd.DataFrame:
        df = self.build(with_target=False)
        if df.empty:
            return df
        last_date = df["date"].max()
        return df[df["date"] == last_date].reset_index(drop=True)
