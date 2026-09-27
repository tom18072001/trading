"""The ruler, not the rules: what `ticker_alpha_bench.evaluate` measures against.

Review 2026-09-24 §1 found the bench overstating every gated factor two ways
at once, and it took BOTH to flip 2023: a gated factor was compared with a base
that had the same gate (so the gate's own contribution vanished), and sessions
with fewer than 30 names in the FACTOR's cross-section were dropped (109/898 of
them, the weak-market days production still trades). Its t-stats also treated
overlapping 20-session windows as independent, and "beats VNINDEX" compared an
arithmetic annualisation with a constant from another window.

These tests pin the corrected ruler on synthetic panels where the right answer
is known.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.bench import book_stats, judge, nw_t, staggered_book


def _market(n_days=260, n_names=40, seed=11):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    cols = [f"S{i:02d}" for i in range(n_names)]
    drift = np.linspace(-0.002, 0.002, n_names)          # S00 worst ... S39 best
    rets = rng.normal(drift, 0.01, (n_days, n_names))
    close = pd.DataFrame(10 * np.cumprod(1 + rets, axis=0), index=idx, columns=cols)
    p = {"close": close, "open": close.shift(1).bfill()}
    p["high"], p["low"] = close * 1.01, close * 0.99
    p["volume"] = pd.DataFrame(1e7, index=idx, columns=cols)
    f = {"dv20": pd.DataFrame(1e9, index=idx, columns=cols)}
    return p, f, drift


def _evaluate(scores, p, f, **kw):
    from scripts.ticker_alpha_bench import evaluate
    kw.setdefault("start", None)
    kw.setdefault("min_names", 30)
    return evaluate(scores, f, p, topk=kw.pop("topk", 5), min_dv=0, horizons=(20,), **kw)[20]


# --------------------------------------------------------------- the base rate

def test_a_gated_factor_is_graded_against_the_whole_market():
    """The gate IS part of the rule. Against a base with the same gate its
    contribution is zero by construction -- the old bench's defect."""
    p, f, drift = _market()
    cols = p["close"].columns
    gated = pd.DataFrame(1.0, index=p["close"].index, columns=cols).where(
        pd.DataFrame(np.tile(drift > 0, (len(p["close"]), 1)), index=p["close"].index,
                     columns=cols))
    r = _evaluate(gated, p, f, topk=len(cols))            # take EVERY gated name
    assert r["excess"] > 0.005, "the good half must beat the whole market"


def test_selecting_everything_scores_zero_excess():
    """Negative control: the whole universe against itself is exactly the base."""
    p, f, _ = _market()
    allin = pd.DataFrame(1.0, index=p["close"].index, columns=p["close"].columns)
    r = _evaluate(allin, p, f, topk=len(p["close"].columns))
    assert r["excess"] == pytest.approx(0.0, abs=1e-12)


def test_a_thin_factor_day_is_still_scored():
    """A factor with only 3 names on a day is not a reason to skip the day --
    the width floor is the MARKET's (min_names liquid names), not the factor's."""
    p, f, _ = _market()
    cols = p["close"].columns
    thin = pd.DataFrame(np.nan, index=p["close"].index, columns=cols)
    thin[list(cols[-3:])] = 1.0
    r = _evaluate(thin, p, f)
    scorable = len(p["close"]) - 21                      # fwd needs 21 more bars
    assert r["n_sessions"] == scorable and r["n_days"] == scorable


# -------------------------------------------------------------------- the t

def test_newey_west_deflates_overlapping_windows():
    """A 20-session return measured every day shares 19 days with its
    neighbour. The naive t treats those as 20 independent draws."""
    rng = np.random.default_rng(5)
    daily = rng.normal(0.0005, 0.01, 2000)
    overlapping = pd.Series(daily).rolling(20).sum().dropna().to_numpy()
    naive = overlapping.mean() / (overlapping.std(ddof=1) / np.sqrt(len(overlapping)))
    nw = nw_t(overlapping, 20)
    assert abs(nw) < abs(naive) / 2


def test_newey_west_at_lag_zero_is_the_ordinary_t():
    x = np.random.default_rng(1).normal(0.1, 1.0, 500)
    ordinary = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
    assert nw_t(x, 0) == pytest.approx(ordinary, rel=1e-9)


# ------------------------------------------------------------------ the book

def test_the_book_charges_one_round_trip_per_tranche():
    """Flat prices, one name every day: the only thing the book can lose is
    cost, 1/(h+1) of capital per day at the full round-trip rate."""
    idx = pd.bdate_range("2024-01-01", periods=100)
    px = pd.DataFrame({"A": 10.0}, index=idx)
    sel = pd.DataFrame({"A": True}, index=idx)
    r = staggered_book(sel, px, px, horizon=20, cost=0.01)
    assert r.iloc[30] == pytest.approx(-0.01 / 21)
    assert r.iloc[0] == 0.0          # nothing is bought on the signal day itself


def test_the_verdict_compares_books_on_the_same_dates():
    """"Beats VNINDEX" is the rule's book against the index on the same days,
    CAGR and Sharpe both -- not a constant from another window."""
    base = {"excess": 0.01, "excess_nw_t": 2.5, "pick_net": 0.01, "ic_nw_t": 3.0,
            "q_spread_nw_t": 3.0, "quintiles": pd.Series([0.1, 0.2, 0.3, 0.4, 0.5]),
            "by_year": pd.DataFrame({"excess": [0.01, 0.02]}, index=[2024, 2025])}
    win = judge("x", 40, {**base, "book": {"cagr": 0.20, "sharpe": 1.1},
                          "vnindex": {"cagr": 0.175, "sharpe": 0.98}})
    lose = judge("x", 40, {**base, "book": {"cagr": 0.20, "sharpe": 0.90},
                           "vnindex": {"cagr": 0.175, "sharpe": 0.98}})
    assert win.label == "VƯỢT TRẦN" and win.annualised_net == pytest.approx(0.20)
    assert lose.label == "EDGE, DƯỚI TRẦN", "higher return at a worse Sharpe is not a win"


def test_book_stats_on_a_known_series():
    idx = pd.bdate_range("2024-01-01", periods=252)
    r = pd.Series(0.0004, index=idx)
    st = book_stats(r)
    assert st["cagr"] == pytest.approx(1.0004 ** 252 - 1, rel=1e-9)
    assert st["maxdd"] == 0.0


# ------------------------------------------------ the rule the bench grades

def test_the_bench_grades_the_rule_production_ships():
    """`X_shipped_rule` must pick what `long_shortlist` picks: the production
    score with its floor over the whole liquid universe, the blend over that
    SAME universe, then the gate. `X_prop_obv` blends only gated names and is
    a different rule -- review 2026-09-24 §2.2."""
    from scripts.ticker_alpha_bench import FACTORS, _production_score, build_features
    from services.picks_scoring import UNTRENDED_FLOOR, blended_rank_scores
    from services.picks_universe_service import TickerRow, long_shortlist

    rng = np.random.default_rng(8)
    n, k = 330, 30
    idx = pd.bdate_range("2023-01-02", periods=n)
    drift = rng.uniform(-0.002, 0.003, k)
    close = pd.DataFrame(20 * np.cumprod(1 + rng.normal(drift, 0.015, (n, k)), axis=0),
                         index=idx, columns=[f"N{i:02d}" for i in range(k)])
    vol = pd.DataFrame(rng.uniform(4e5, 9e5, (n, k)), index=idx, columns=close.columns)
    p = {"close": close, "open": close.shift(1).bfill(), "high": close * 1.015,
         "low": close * 0.985, "volume": vol}
    f = build_features(p)
    bench = FACTORS["X_shipped_rule"](f)
    score = _production_score(f)

    checked = 0
    for i in range(260, n, 7):
        live = (f["dv20"].iloc[i] > 5e6) & score.iloc[i].notna()
        syms = list(live.index[live])
        if len(syms) < 10 or (score.iloc[i][syms] > UNTRENDED_FLOOR).sum() < 5:
            continue
        blend = blended_rank_scores([float(score.iloc[i][s]) for s in syms],
                                    [float(f["obv_chg20"].iloc[i][s]) for s in syms])
        rows = [TickerRow(symbol=s, sector_code="X", close=1.0,
                          score=float(score.iloc[i][s]), rank_score=round(b, 4),
                          is_valid_buy=True) for s, b in zip(syms, blend, strict=True)]
        want = [r.symbol for r in long_shortlist(rows, 5)]
        got = list(bench.iloc[i].dropna().nlargest(5).index)
        assert got == want, f"day {idx[i].date()}"
        checked += 1
    assert checked >= 5, "the fixture stopped producing gated days"


# ----------------------------------------------------------- the exit walker

def _one_trade(bars, atr_pct=2.0, max_hold=4):
    """Signal on bar 0, entry at bar 1's open; `bars` = [(open, low, close), ...]
    from bar 1 on, padded flat so the walker has room for max_hold."""
    last = bars[-1][2]
    bars = [(10.0, 10.0, 10.0)] + list(bars)
    bars += [(last, last, last)] * (max_hold + 3 - len(bars))
    idx = pd.bdate_range("2025-01-06", periods=len(bars))
    col = ["AAA"]
    frame = lambda k: pd.DataFrame([b[k] for b in bars], index=idx, columns=col)  # noqa: E731
    p = {"open": frame(0), "low": frame(1), "close": frame(2)}
    f = {"atr_pct": pd.DataFrame(atr_pct, index=idx, columns=col),
         "sma20": pd.DataFrame(0.0, index=idx, columns=col),
         "dv20": pd.DataFrame(1e9, index=idx, columns=col)}
    entries = pd.DataFrame(False, index=idx, columns=col)
    entries.iloc[0] = True
    return entries, f, p


def test_the_band_on_a_session_is_set_by_the_closes_before_it():
    """Review 2026-09-24 §3.2: the old walker raised the peak with bar k's close
    and THEN compared bar k's low with the band -- a session that dipped early
    and closed strong "touched" a band it had itself just lifted."""
    from scripts.tplus_strategy_bench import run_trail
    # entry 100; bar 1 closes 103 (armed: 103 >= 100 x 1.02); bar 2 dips to 98.5
    # and closes 110. Band on bar 2 = 103 x (1 - 2.5 x 0.02) = 97.85 -> no exit.
    # The old order put the band at 110 x 0.95 = 104.5 and sold at 104.5.
    entries, f, p = _one_trade([(100, 100, 103), (103, 98.5, 110), (110, 110, 110)])
    t = run_trail(entries, f, p, lo_atr=2.5, max_hold=4, min_dv=0, cost=0.0, arm_atr=1.0)
    assert len(t) == 1
    assert t.exit.iloc[0] == "time"
    assert t.ret.iloc[0] == pytest.approx(0.10)


def test_a_session_that_opens_through_the_band_fills_at_the_open():
    from scripts.tplus_strategy_bench import run_trail
    # peak 110 after bar 1 -> band 104.5; bar 2 OPENS at 100.
    entries, f, p = _one_trade([(100, 100, 110), (100, 99, 101)])
    t = run_trail(entries, f, p, lo_atr=2.5, max_hold=4, min_dv=0, cost=0.0, arm_atr=1.0)
    assert (t.exit.iloc[0], t.held.iloc[0]) == ("gap", 2)
    assert t.ret.iloc[0] == pytest.approx(0.0), "filled at 100, not at the 104.5 band"


def test_the_fixed_stop_walker_fills_a_gap_at_the_open_too():
    from scripts.tplus_strategy_bench import run
    # entry 100, stop 2.5 x 2% below = 95; bar 2 opens at 90.
    entries, f, p = _one_trade([(100, 99, 100), (90, 88, 91)])
    t = run(entries, f, {**p, "high": p["close"]}, target_atr=99, stop_atr=2.5,
            max_hold=4, min_dv=0, cost=0.0)
    assert t.exit.iloc[0] == "stop"
    assert t.ret.iloc[0] == pytest.approx(-0.10), "filled at the 90 open, not at 95"
