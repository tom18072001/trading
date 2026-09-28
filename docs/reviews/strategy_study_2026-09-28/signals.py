"""Signal families for the lab. Each returns a score frame: HIGHER = buy first.

Declared before any result was seen; the count of variants run is logged by
the runners so the multiple-testing cost can be stated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "docs" / "reviews" / "algo_review_2026-09-24"))


def _r(x):
    return x.rank(axis=1, pct=True)


def families(f: dict) -> dict[str, pd.DataFrame]:
    s = {}
    for k in ("mom21_0", "mom63_0", "mom63_5", "mom126_5", "mom126_21", "mom250_21", "mom250_5"):
        s[k] = f[k]
    s["rev5"] = -(f["close"] / f["close"].shift(5) - 1)            # short-term reversal
    s["hi126"] = f["hi126"]
    s["hi250"] = f["hi250"]
    s["ramom126"] = f["mom126_5"] / f["vol126"]
    s["ramom63"] = f["mom63_5"] / f["vol63"]
    s["trend200"] = f["close"] / f["sma200"] - 1
    s["trend50_200"] = f["sma50"] / f["sma200"] - 1
    s["obv60"] = f["obv60"]
    s["lowvol"] = -f["vol63"]
    s["vratio"] = f["vratio"]
    # composites (mean of cross-sectional percentile ranks)
    s["c_mom_hi"] = (_r(f["mom126_5"]) + _r(f["hi250"])) / 2
    s["c_multi_mom"] = (_r(f["mom63_5"]) + _r(f["mom126_5"]) + _r(f["mom250_21"])) / 3
    s["c_ramom_hi_obv"] = (_r(s["ramom126"]) + _r(f["hi250"]) + _r(f["obv60"])) / 3
    s["c_mom_lowvol"] = (_r(f["mom126_5"]) + _r(-f["vol63"])) / 2
    return s


def baseline(f_repo: dict, elig: pd.DataFrame) -> pd.DataFrame:
    """The shipped rule (2026-09-25): SMA200 gate -> rank blend of score and OBV."""
    from picks_eval import production_rank, production_score

    from services.picks_scoring import UNTRENDED_FLOOR
    sc = production_score(f_repo)
    rk = production_rank(sc, f_repo["obv_chg20"], elig)
    # tie-break exactly like _rank_key: rank_score, then score
    return rk.where(sc > UNTRENDED_FLOOR) + sc.rank(axis=1, pct=True) * 1e-6
