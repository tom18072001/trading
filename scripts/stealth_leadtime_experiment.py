# ============================================
# scripts/stealth_leadtime_experiment.py — can §16.2's leading features buy lead time?
# ============================================
# CLAUDE.md §16.11 (2026-08-23) closes with a named next experiment:
#
#   "The conditions are the suspects, not the aggregation: c1 (flow_z20 > 1) is
#    a *contemporaneous* flow spike, so it tends to fire with the move rather
#    than ahead of it. The leading candidates in §16.2 that would actually buy
#    lead time — flow_price_divergence, foreign_streak, flow_leadtime_proxy —
#    are computed and stored but are in NO condition."
#
# This runs that experiment. It scores candidate condition sets over the FULL
# panel against the three §16.11 criteria, so a change to §16.1 can be argued
# with a number instead of a hunch.
#
# It deliberately does NOT change the shipped gate. `analysis/stealth.py` stays
# the source of truth for what runs; this is the bench you measure against it.
#
# RESULT, first run 2026-08-24 (>=4/5, N=3, full 13,470-row panel):
#
#   variant                      events sectors  breakout  lead>=10d  med lead   med RC
#   NO GATE (base rate)           13033      15      83%       23%         4    0.944
#   shipped (16.1)                   20      11      75%       20%         3    0.940
#   +divergence                      77      15      78%       10%         3    0.955
#   swap c1->divergence              38      13      74%        4%         2    0.958
#   swap c1->flow_before_price       27      11      67%       11%         3    0.959
#   swap c2->foreign_streak          16      10      88%       50%         8    0.924
#   divergence + streak              38      14      79%       17%         3    0.959
#
# THE FIRST ROW IS THE FINDING, and it was missing from the first run of this
# script. Scoring every row in the panel — i.e. no gate at all — gives 83%
# breakout, 23% at >=10d lead, median lead 4, root capture 0.944. The shipped
# §16.1 gate scores 75% / 20% / 3 / 0.940. **It is worse than not filtering.**
# Only `swap c2->foreign_streak` beats the base rate on any axis.
#
# This is why §16.11's three criteria are not sufficient on their own: they are
# absolute thresholds, so a gate can post a respectable-looking 75% breakout
# while selecting *worse-than-random* sector-days. A signal is only a signal
# relative to the base rate. The NO GATE row is now printed on every run.
#
# The doctrine's suspect was wrong. §16.11 named flow_price_divergence as the
# feature that would buy lead time; every variant containing it made lead time
# WORSE (3 -> 2-3 days, >=10d share 20% -> 4-17%) while inflating the event
# count. It fires more often, not earlier.
#
# What worked is the one §16.11 did not emphasise: replacing cond2's 20d hit
# RATE with foreign_streak >= 3 — consecutive sessions of net foreign buying.
# Median lead 3 -> 8 days, >=10d share 20% -> 50%, breakout 75% -> 88%, and it
# is the only variant that moved root capture at all (0.940 -> 0.924).
#
# This is §18.5/21's argument arriving from the other direction: a hit rate is
# satisfiable by one block trade plus 19 quiet days, and one block trade is not
# accumulation. Persistence is the part that leads.
#
# NOT SHIPPED, on purpose. n=16 over 3.5 years, and the year split shows the
# whole effect is pre-2026: 2023-25 run 50-67% at >=10d with median lead 10-14,
# while 2026's three events are 0% and median lead 3 — the same collapse the
# shipped gate shows in 2026. Tightening to streak>=8 gives 100% at >=10d on
# n=2, which is not a result. Root capture stays ~0.92 against §16.11's 0.85
# either way, so no variant here earns the "goc" claim.
#
# THE 2026 COLLAPSE IS MOSTLY THE MARKET, not the gate. Measured per year, the
# unconditional base rate falls with it: breakout 88/84/86% in 2023-25 -> 68% in
# 2026, and median forward-40d max return 7.1/5.4/7.9% -> 3.2%. Data coverage is
# not the cause (2026 rows are 99% foreign_net, 100% close_idx/atr_pct) and nor
# is right-censoring (1 of 7 events has <40 forward sessions). 2026 is simply a
# flatter tape. What is NOT explained by the tape: relative to that lower base
# rate the shipped gate still underperforms in 2026 (50% vs 68% breakout, 0% vs
# 18% at >=10d) — so it degrades faster than the market does.
#
# What would make foreign_streak shippable: re-run once 2026 has more events,
# and require it to beat the NO GATE row *within* each year, not overall.
# Until then §16.1 keeps cond2.
#
# Usage:  python -m scripts.stealth_leadtime_experiment
#         python -m scripts.stealth_leadtime_experiment --min-conditions 3
#
# ponytail: prints a table, writes nothing. If a variant wins, the follow-up is
# a §15 log entry + an edit to analysis/stealth.py — not a flag in here.

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from analysis.stealth import (
    FLOW_Z_THRESHOLD,
    FOREIGN_HIT_THRESHOLD,
    RETURN_BOTTOM_FRAC,
    STEALTH_MIN_CONDITIONS,
    STEALTH_MIN_SESSIONS,
    _return_60d_position,
    compute_leading_features,
)
from database.connection import SessionLocal
from database.models import SectorFlowDaily

# A "breakout" is §16.4's definition: forward max return over the window clears
# 2x the sector's own ATR%. Using a fixed % here would flatter quiet sectors.
BREAKOUT_WINDOW = 40
BREAKOUT_ATR_MULT = 2.0


def _load_panel() -> pd.DataFrame:
    session = SessionLocal()
    try:
        rows = session.query(SectorFlowDaily).order_by(
            SectorFlowDaily.sector_code, SectorFlowDaily.date).all()
    finally:
        session.close()
    return pd.DataFrame([{
        "sector_code": r.sector_code,
        "date": r.date,
        "net_dollar_flow": r.net_dollar_flow or 0.0,
        "foreign_net": r.foreign_net or 0.0,
        "close_idx": r.close_idx or 0.0,
        "breadth_sma20": r.breadth_sma20 or 0.0,
        "atr_pct": r.atr_pct or 0.0,
    } for r in rows])


def _conditions(g: pd.DataFrame) -> dict[str, pd.Series]:
    """Every candidate condition, keyed by name. §16.1's five plus §16.2's leaders."""
    atr = g["atr_pct"].astype(float)
    close = g["close_idx"].astype(float)
    breadth = g["breadth_sma20"].astype(float)
    breadth_rising = breadth.diff().rolling(5, min_periods=1).mean() > 0

    return {
        # --- §16.1 as shipped ---
        "c1_flow_z": g["flow_z20"] > FLOW_Z_THRESHOLD,
        "c2_foreign_hit": g["foreign_hit_20d"] >= FOREIGN_HIT_THRESHOLD,
        "c3_breadth": breadth_rising,
        "c4_atr_quiet": atr < atr.rolling(20, min_periods=5).median(),
        "c5_cheap": _return_60d_position(close) < RETURN_BOTTOM_FRAC,
        # --- §16.2 leading candidates, currently in no condition ---
        # Flow ahead of price is the literal definition of buying early; a
        # contemporaneous spike (c1) is not.
        "d1_divergence": g["flow_price_divergence"] > 1.0,
        # Persistence of the smart-money side, not just its hit rate. §18.5/21
        # argues the hit rate alone is satisfiable by one block trade.
        "d2_foreign_streak": g["foreign_streak"] >= 3,
        # Flow rising while price has NOT yet turned — the strict version of d1.
        "d3_flow_before_price": (g["flow_z20"] > 0.5) & (close.pct_change(20) <= 0),
    }


VARIANTS: dict[str, list[str]] = {
    "shipped (16.1)": ["c1_flow_z", "c2_foreign_hit", "c3_breadth", "c4_atr_quiet", "c5_cheap"],
    "+divergence": ["c1_flow_z", "c2_foreign_hit", "c3_breadth", "c4_atr_quiet", "c5_cheap",
                    "d1_divergence"],
    "swap c1->divergence": ["d1_divergence", "c2_foreign_hit", "c3_breadth", "c4_atr_quiet",
                           "c5_cheap"],
    "swap c1->flow_before_price": ["d3_flow_before_price", "c2_foreign_hit", "c3_breadth",
                                  "c4_atr_quiet", "c5_cheap"],
    "swap c2->foreign_streak": ["c1_flow_z", "d2_foreign_streak", "c3_breadth", "c4_atr_quiet",
                               "c5_cheap"],
    "divergence + streak": ["d1_divergence", "d2_foreign_streak", "c3_breadth", "c4_atr_quiet",
                            "c5_cheap"],
}


def _events(g: pd.DataFrame, keys: list[str], need: int, sessions: int) -> list[int]:
    """Row indices where a stealth run STARTS, under this condition set."""
    conds = _conditions(g)
    score = sum(conds[k].fillna(False).astype(int) for k in keys)
    qualifies = score >= min(need, len(keys))
    persisted = (qualifies.rolling(sessions, min_periods=sessions).sum() == sessions).fillna(False)
    arr = persisted.to_numpy()
    return [i for i in range(len(arr)) if arr[i] and (i == 0 or not arr[i - 1])]


def _score_event(g: pd.DataFrame, i: int) -> dict | None:
    """§16.11 metrics for one event: did it break out, how early, how cheap."""
    close = g["close_idx"].to_numpy(dtype=float)
    atr = g["atr_pct"].to_numpy(dtype=float)
    entry = close[i]
    if not np.isfinite(entry) or entry <= 0:
        return None

    fwd = close[i + 1: i + 1 + BREAKOUT_WINDOW]
    if len(fwd) < 10:
        return None                      # not enough forward data to judge
    thresh = entry * (1 + BREAKOUT_ATR_MULT * (atr[i] if np.isfinite(atr[i]) else 0.02))
    hit = np.nonzero(fwd >= thresh)[0]

    peak = float(np.nanmax(fwd))
    return {
        "broke_out": bool(len(hit)),
        # Lead time = sessions between the signal and the breakout it predicted.
        "lead_days": int(hit[0] + 1) if len(hit) else None,
        # §16.6 root capture: entry price as a fraction of the eventual peak.
        # 1.0 = you bought the top.
        "root_capture": entry / peak if peak > 0 else None,
    }


def _summarise(scored: list[dict]) -> tuple[float, float, float, float]:
    """breakout share, >=10d share, median lead, median root capture."""
    broke = [s for s in scored if s["broke_out"]]
    leads = [s["lead_days"] for s in broke]
    rcs = [s["root_capture"] for s in scored if s["root_capture"] is not None]
    return (
        len(broke) / len(scored) if scored else 0.0,
        (sum(1 for x in leads if x >= 10) / len(leads)) if leads else 0.0,
        float(np.median(leads)) if leads else 0.0,
        float(np.median(rcs)) if rcs else 0.0,
    )


def _baseline(feat: pd.DataFrame) -> list[dict]:
    """Score EVERY row, i.e. what you get with no gate at all.

    This row is the one the experiment was missing on its first run. §16.11's
    three criteria are all absolute, so a gate can clear "75% break out" while
    being *worse* than picking a sector-day at random — which is exactly what
    the shipped gate turned out to do. A signal is only a signal relative to
    the base rate.
    """
    out = []
    for _, g in feat.groupby("sector_code", sort=False):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            s = _score_event(g, i)
            if s:
                out.append(s)
    return out


def run(need: int, sessions: int) -> None:
    panel = _load_panel()
    if panel.empty:
        print("no rows in sector_flow_daily")
        return
    feat = compute_leading_features(panel)
    print(f"panel: {len(feat)} rows | {feat.sector_code.nunique()} sectors | "
          f"{feat.date.min()} -> {feat.date.max()}")
    print(f"gate: >={need} conditions held >={sessions} sessions "
          f"(breakout = +{BREAKOUT_ATR_MULT}xATR within {BREAKOUT_WINDOW}d)\n")

    hdr = (f"{'variant':<28}{'events':>7}{'sectors':>8}{'breakout':>10}"
           f"{'lead>=10d':>11}{'med lead':>10}{'med RC':>9}")
    print(hdr)
    print("-" * len(hdr))

    base = _baseline(feat)
    b_bo, b_early, b_lead, b_rc = _summarise(base)
    print(f"{'NO GATE (base rate)':<28}{len(base):>7}{feat.sector_code.nunique():>8}"
          f"{b_bo:>9.0%}{b_early:>10.0%}{b_lead:>10.0f}{b_rc:>9.3f}")
    print("-" * len(hdr))

    for name, keys in VARIANTS.items():
        scored = []
        sectors = set()
        for code, g in feat.groupby("sector_code", sort=False):
            g = g.reset_index(drop=True)
            for i in _events(g, keys, need, sessions):
                s = _score_event(g, i)
                if s:
                    scored.append(s)
                    sectors.add(code)
        if not scored:
            print(f"{name:<28}{0:>7}{0:>8}{'-':>10}{'-':>11}{'-':>10}{'-':>9}")
            continue

        bo, early, lead, rc = _summarise(scored)
        print(f"{name:<28}{len(scored):>7}{len(sectors):>8}"
              f"{bo:>9.0%}{early:>10.0%}{lead:>10.0f}{rc:>9.3f}")

    # ASCII only: Windows console is cp1252 and a section sign raises here.
    print("\n16.11 targets: breakout lead >=10d on >=60% of signals | median RC <= 0.85 "
          "| false positives <= 30%")
    print("Read every row against NO GATE, not against the targets alone: a variant "
          "that does not beat the base rate is not a signal.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-conditions", type=int, default=STEALTH_MIN_CONDITIONS)
    ap.add_argument("--min-sessions", type=int, default=STEALTH_MIN_SESSIONS)
    a = ap.parse_args()
    run(a.min_conditions, a.min_sessions)
