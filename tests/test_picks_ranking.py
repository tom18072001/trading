"""The 2026-09-16 scoring rewrite: one formula, and a tie-break that is not a factor.

Two things shipped together and each can regress on its own:

  * `services.picks_scoring.score_ticker` -- a new formula, chosen by
    measurement (CLAUDE.md 26). Its own invariants live in
    `test_picks_scoring.py`; what is pinned HERE is that the measurement bench
    and the production service compute the same number, because a formula that
    exists in two files drifts and the bench would go on reporting a figure the
    product had stopped using. That is the failure 22.11 logged for the
    stealth breakout bar.

  * `_rank_key` -- the shortlist order. The tie-break used to be 20d dollar
    volume descending, which was measured to make the shortlist WORSE
    (-0.06% -> -0.15% excess over the base rate). A test that only checked
    "sorted by score" would stay green if someone put it back.

2026-09-28: the production order became risk-adjusted momentum (`_rank_key`);
the 2026-09-16/25 order lives on as `_legacy_rank_key` / `legacy_shortlist`,
the audit shadow. The score tests below pin the shadow -- it must keep
reproducing the retired rule, or the audit compares against a rule that never
ran.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.picks_scoring import UNTRENDED_FLOOR, score_ticker
from services.picks_universe_service import (
    TickerRow,
    _build_ticker_row,
    _rank_key,
    legacy_shortlist,
)
from services.picks_universe_service import _legacy_rank_key as _old_key


# ---------------------------------------------------------------- the formula

def _panel(n: int = 320, seed: int = 3) -> dict[str, pd.DataFrame]:
    """A three-name panel long enough for an SMA200 (the gate needs 200 bars).

    Every name is here to exercise one branch, and the guards below check that
    it still does:
      AAA -- uptrend, quiet: passes the gate, no ATR penalty
      ZZZ -- downtrend:      blocked by the gate
      WLD -- uptrend, wild:  passes the gate AND trips the ATR penalty

    The first draft had only AAA and ZZZ, and its daily sigma put every bar's
    ATR under WIDE_ATR_PCT -- so deleting the ATR penalty from the bench left
    all seven tests green. A fixture that never reaches a term cannot test it.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    out = {}
    # The drifts have to beat the noise over 320 bars or both names end up on
    # the same side of their SMA200 and the gate is never exercised -- which is
    # what the first draft did (sigma 0.022 against a drift of -0.0010 is a
    # coin flip, not a downtrend).
    close = pd.DataFrame({
        "AAA": 10 * np.cumprod(1 + rng.normal(0.0020, 0.012, n)),
        "ZZZ": 30 * np.cumprod(1 + rng.normal(-0.0025, 0.012, n)),
        "WLD": 20 * np.cumprod(1 + rng.normal(0.0030, 0.045, n)),
    }, index=idx)
    out["close"] = close
    out["open"] = close.shift(1).bfill()
    # The intrabar range has to be wide enough on WLD to lift ATR% past the
    # threshold; a flat +-1.2% wrapper on every name cannot.
    span = pd.Series({"AAA": 0.012, "ZZZ": 0.012, "WLD": 0.050})
    out["high"] = close * (1 + span)
    out["low"] = close * (1 - span)
    out["volume"] = pd.DataFrame(rng.uniform(1e6, 3e6, (n, len(close.columns))),
                                 index=idx, columns=close.columns)
    return out


def test_the_bench_and_the_service_agree_row_by_row():
    """The measurement and the product must be the same arithmetic.

    `scripts/ticker_alpha_bench.py` imports the coefficients rather than
    retyping them, so this checks the assembly too: same terms, same clip, same
    gate, same floor behaviour once the bench's NaN is mapped onto it.
    """
    from scripts.ticker_alpha_bench import FACTORS, build_features

    p = _panel()
    f = build_features(p)
    vec = FACTORS["P2_proposed_gated_quiet"](f)

    checked = 0
    for i in range(250, len(p["close"])):        # start where SMA200 exists
        for sym in p["close"].columns:
            scalar = score_ticker({
                "close": float(f["close"].iat[i, f["close"].columns.get_loc(sym)]),
                "rsi_2": float(f["rsi2"].iat[i, f["rsi2"].columns.get_loc(sym)]),
                "ret_1d": float(f["ret1"].iat[i, f["ret1"].columns.get_loc(sym)]) * 100,
                "atr_pct": float(f["atr_pct"].iat[i, f["atr_pct"].columns.get_loc(sym)]),
                "price_to_sma_50": float(
                    f["close"].iat[i, f["close"].columns.get_loc(sym)]
                    / f["sma50"].iat[i, f["sma50"].columns.get_loc(sym)] - 1),
                "price_to_sma_200": float(
                    f["close"].iat[i, f["close"].columns.get_loc(sym)]
                    / f["sma200"].iat[i, f["sma200"].columns.get_loc(sym)] - 1),
            })
            v = vec.iat[i, vec.columns.get_loc(sym)]
            if np.isnan(v):
                # the bench drops an ungated row; the service floors it
                assert scalar == UNTRENDED_FLOOR
            else:
                assert scalar == pytest.approx(v, abs=0.011)   # service rounds to 2dp
            checked += 1
    assert checked > 100, "the fixture stopped exercising the formula"


def test_the_fixture_actually_reaches_every_term_it_claims_to_test():
    """A guard on the guard, and it has already earned its place twice.

    Draft 1 had both names drift into uptrends, so the gate was never blocked.
    Draft 2 fixed that but kept every ATR under WIDE_ATR_PCT, so deleting the
    volatility penalty from the bench left the equivalence test green -- a test
    reporting coverage it did not have, which 19 rates as worse than no test.
    """
    from scripts.ticker_alpha_bench import FACTORS, build_features

    from services.picks_scoring import WIDE_ATR_PCT

    f = build_features(_panel())
    vec = FACTORS["P2_proposed_gated_quiet"](f).iloc[250:]
    assert vec.notna().any().any(), "no row passed the trend gate"
    assert vec.isna().any().any(), "no row was blocked by the trend gate"

    atr = f["atr_pct"].iloc[250:]
    assert (atr > WIDE_ATR_PCT).any().any(), "no row trips the ATR penalty"
    assert (atr <= WIDE_ATR_PCT).any().any(), "every row trips the ATR penalty"


# ------------------------------------------------------------- the tie-break

def _row(sym: str, score: float, dv: float) -> TickerRow:
    return TickerRow(symbol=sym, sector_code="BANK", close=10.0, score=score, dv_20d=dv)


def test_the_tie_break_is_not_dollar_volume():
    """Equal scores must NOT resolve in favour of the bigger name.

    This is the regression that matters: 20d dollar volume as the tie-break
    handed back the largest and slowest name in every score bucket, and the
    bench measured it as actively harmful rather than neutral.
    """
    big = _row("ZZZ", 3.0, dv=9e9)      # huge turnover, late in the alphabet
    small = _row("AAA", 3.0, dv=1e6)
    assert sorted([big, small], key=_old_key)[0] is small
    big.momentum = small.momentum = 4.0  # the production order: same property
    assert sorted([big, small], key=_rank_key)[0] is small


def test_best_score_still_wins_regardless_of_symbol():
    good = _row("ZZZ", 5.0, dv=1e6)
    weak = _row("AAA", 1.0, dv=9e9)
    assert sorted([good, weak], key=_old_key)[0] is good


def test_best_momentum_wins_regardless_of_symbol_and_score():
    good = _row("ZZZ", -5.0, dv=1e6)
    weak = _row("AAA", 9.0, dv=9e9)
    good.momentum, weak.momentum = 6.0, 1.0
    assert sorted([weak, good], key=_rank_key)[0] is good


def test_the_order_is_stable_across_calls():
    """A shortlist that reshuffles equal-scored names every evening trains the
    reader to ignore the order."""
    rows = [_row(s, 3.0, dv=i * 1e6) for i, s in enumerate(["DEF", "ABC", "XYZ"])]
    shuffled = rows[::-1]        # a different input order, same expected output
    first = [r.symbol for r in sorted(rows, key=_old_key)]
    second = [r.symbol for r in sorted(shuffled, key=_old_key)]
    assert first == second == ["ABC", "DEF", "XYZ"]


# ------------------------------------------------------- end-to-end row build

def test_build_row_populates_the_three_new_score_inputs():
    """`_build_ticker_row` has to actually produce rsi_2, ret_1d and
    price_to_sma_200, or the score silently falls back to the floor for every
    ticker and the whole shortlist becomes alphabetical."""
    p = _panel(n=300)
    df = pd.DataFrame({
        "time": p["close"].index,
        "open": p["open"]["AAA"].values,
        "high": p["high"]["AAA"].values,
        "low": p["low"]["AAA"].values,
        "close": p["close"]["AAA"].values,
        "volume": p["volume"]["AAA"].values,
    })
    row = _build_ticker_row("AAA", "BANK", df, foreign_room_pct=None, dv_20d=2e7)
    assert row is not None
    assert row.rsi_2 is not None and 0.0 <= row.rsi_2 <= 100.0
    assert row.ret_1d is not None
    assert row.price_to_sma_200 is not None
    assert row.score > UNTRENDED_FLOOR, "an uptrending name must clear the gate"


def test_a_short_history_cannot_fake_an_uptrend():
    """Under 200 bars there is no SMA200, so there is no confirmed uptrend.

    The lookback was widened from 110 to 400 calendar days for exactly this
    reason; if it is ever narrowed again this test says so instead of the
    system quietly scoring every name at the floor.
    """
    p = _panel(n=120)
    df = pd.DataFrame({
        "time": p["close"].index,
        "open": p["open"]["AAA"].values, "high": p["high"]["AAA"].values,
        "low": p["low"]["AAA"].values, "close": p["close"]["AAA"].values,
        "volume": p["volume"]["AAA"].values,
    })
    row = _build_ticker_row("AAA", "BANK", df, foreign_room_pct=None, dv_20d=2e7)
    assert row is not None
    assert row.price_to_sma_200 is None
    assert row.score == UNTRENDED_FLOOR


# ------------------------------------------------- the shortlist admission gate

def test_only_the_sma200_gate_decides_admission(monkeypatch):
    """2026-09-25 (Tom: "bỏ ngay, giữ cổng SMA200"): admission is the uptrend
    gate and nothing else.

    On 2026-09-16 this test pinned the opposite. The first live rebuild had
    returned VIC +3.48, VHM +1.20, NTP +0.83, HCM -0.65, SAB -0.77, the names
    below +2.5 were called padding, and MIN_BUY_SCORE kept them out. The cutoff
    was then measured for the first time (review 2026-09-24 §2.2, same ordering
    with and without it): -0.39%/trade at 20 sessions, -0.44% at 40, and the
    book fell from 7.2% to 2.7%/yr and from 11.7% to 9.3%. A gated name with a
    low score is an uptrend name that is not oversold; the blend ranks it on its
    money flow, and that ranking is what was measured.

    What must NEVER be admitted is a name whose uptrend is not confirmed.
    """
    import services.picks_universe_service as mod
    from datetime import date

    high = TickerRow(symbol="AAA", sector_code="BANK", close=10.0, score=3.48,
                     rank_score=0.50, is_valid_buy=True,
                     stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    low = TickerRow(symbol="BBB", sector_code="BANK", close=10.0, score=-0.77,
                    rank_score=0.90, is_valid_buy=True,
                    stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    floored = TickerRow(symbol="CCC", sector_code="BANK", close=10.0,
                        score=UNTRENDED_FLOOR, rank_score=0.99, is_valid_buy=True,
                        stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    tickers = {r.symbol: r for r in (high, low, floored)}

    assert mod and date  # the shadow is a pure function of the rows
    out = legacy_shortlist(tickers.values(), 5)
    assert [p.symbol for p in out] == ["BBB", "AAA"]


def test_the_buy_list_ignores_sector_signals(monkeypatch):
    """The BUY list used to put BUY/ACCUMULATE-sector names first. The ranker
    has no out-of-sample edge (review 2026-09-24 §4.2), so a sector flag must
    not move a name ahead of a better-ranked one."""
    import services.picks_universe_service as mod
    from datetime import date

    flagged = TickerRow(symbol="AAA", sector_code="BANK", close=10.0, score=5.0,
                        rank_score=0.40, is_valid_buy=True, momentum=2.0, vol_63d=0.02,
                        stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    better = TickerRow(symbol="ZZZ", sector_code="TECH", close=10.0, score=1.0,
                       rank_score=0.95, is_valid_buy=True, momentum=8.0, vol_63d=0.02,
                       stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    svc = mod.PicksUniverseService()
    monkeypatch.setattr(svc, "_sectors_with_action", lambda *a, **k: {"BANK"})
    monkeypatch.setattr("services.picks_news.fetch_news", lambda *a, **k: [])
    out = svc._select_top({r.symbol: r for r in (flagged, better)},
                          {"BANK": [flagged], "TECH": [better]},
                          action="BUY", n=5, as_of=date(2026, 9, 16))
    assert [p.symbol for p in out] == ["ZZZ", "AAA"]


def test_the_sell_list_is_not_score_gated(monkeypatch):
    """The gate is a BUY-side filter only. A SELL list exists to surface the
    weakest names, so a floor there would empty exactly the list that should be
    full — a name below its SMA200 is the most natural member of it."""
    import services.picks_universe_service as mod
    from datetime import date

    weak = TickerRow(symbol="WWW", sector_code="REAL", close=10.0,
                     score=UNTRENDED_FLOOR, is_valid_buy=True, stop=9.0)
    ok = TickerRow(symbol="OOO", sector_code="REAL", close=10.0, score=2.0,
                   is_valid_buy=True, stop=9.0)
    svc = mod.PicksUniverseService()
    monkeypatch.setattr(svc, "_sectors_with_action", lambda *a, **k: {"REAL"})
    monkeypatch.setattr(mod, "fetch_news", lambda *a, **k: [], raising=False)
    out = svc._select_top({r.symbol: r for r in (weak, ok)}, {"REAL": [weak, ok]},
                          action="SELL", n=5, as_of=date(2026, 9, 16))
    assert [p.symbol for p in out] == ["WWW", "OOO"]


# ------------------------------------------- the cross-sectional ordering pass

def test_the_ordering_uses_obv_not_just_the_score():
    """Two names with the SAME per-row score must order by money-flow trend.

    This is the whole reason a cross-sectional pass exists. Measured at exit
    +20: score alone gives +0.13% excess with non-monotone quintiles, score
    blended with OBV by rank gives +0.49%, monotone, positive in all four
    evaluable years (CLAUDE.md 26.9).
    """
    from services.picks_scoring import blended_rank_scores

    out = blended_rank_scores([3.0, 3.0], [5.0, -5.0])
    assert out[0] > out[1]


def test_a_missing_obv_ranks_mid_pack_not_last():
    """Absent data is not evidence against a name.

    Sending None to the bottom would quietly re-create the asymmetry 16.1 had
    to fix in the stealth gate, where an unevaluable condition silently raised
    the bar. A new listing with no OBV history must not be punished for it.
    """
    from services.picks_scoring import blended_rank_scores

    best, worst, unknown = blended_rank_scores([1.0, 1.0, 1.0], [9.0, -9.0, None])
    assert worst < unknown < best


def test_a_50_50_blend_can_tie_the_best_score_with_the_worst():
    """A property of the blend, pinned because it is surprising and load-bearing.

    With equal weights, the top score paired with the worst flow lands on the
    same number as the bottom score paired with the best flow -- 0.5*1.0 + 0.5*0
    either way. The first draft of this test asserted the opposite and failed,
    which is how the property was found.

    It is safe ONLY because the admission gate runs first: `long_shortlist`
    drops every name below its SMA200 (score at the floor) before this ordering
    is consulted, so the blend never ranks a name whose uptrend is unconfirmed.
    The test below pins that dependency, and the two must be read together --
    removing the gate would make this tie a live defect.
    """
    from services.picks_scoring import blended_rank_scores

    out = blended_rank_scores([6.0, 5.0, 4.0, -8.0], [-9.0, 0.0, 0.0, 9.0])
    assert out[0] == pytest.approx(out[3])


def test_flow_cannot_rescue_a_name_below_its_sma200(monkeypatch):
    """The guarantee the tie above relies on.

    Best possible money-flow trend, uptrend NOT confirmed (score at the floor):
    it must not appear. Without the gate the blend would happily rank it first.
    """
    from datetime import date

    import services.picks_universe_service as mod

    ok = TickerRow(symbol="AAA", sector_code="BANK", close=10.0,
                   score=0.5, obv_chg20=-9.0, rank_score=0.10,
                   is_valid_buy=True, stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)
    junk = TickerRow(symbol="BBB", sector_code="BANK", close=10.0,
                     score=UNTRENDED_FLOOR, obv_chg20=9.0, rank_score=0.99,
                     is_valid_buy=True, stop=9.0, target=12.0, rr=2.0, atr_pct=2.0)

    assert mod and date  # the shadow is a pure function of the rows
    out = legacy_shortlist([ok, junk], 5)
    assert [p.symbol for p in out] == ["AAA"]


def test_rank_key_prefers_rank_score_but_survives_without_it():
    """The cross-sectional pass runs once per build. A row that never went
    through it (a unit test, a degraded path) must still sort sensibly rather
    than crash or land arbitrarily."""
    hi = TickerRow(symbol="AAA", sector_code="BANK", close=10.0, score=1.0,
                   rank_score=0.9)
    lo = TickerRow(symbol="BBB", sector_code="BANK", close=10.0, score=9.0,
                   rank_score=0.1)
    assert sorted([lo, hi], key=_old_key)[0] is hi         # rank_score wins

    a = TickerRow(symbol="AAA", sector_code="BANK", close=10.0, score=1.0)
    b = TickerRow(symbol="BBB", sector_code="BANK", close=10.0, score=9.0)
    assert sorted([a, b], key=_old_key)[0] is b            # falls back to score

    # the production key: a row without momentum sorts last, it does not crash
    b.momentum = -3.0
    assert sorted([a, b], key=_rank_key)[0] is b


def test_the_bench_ordering_is_the_shipped_function():
    """The bench must CALL the production blend, not reimplement it.

    A vectorised copy in the bench would be a second implementation of the
    ordering, and the bench would go on reporting a number the product had
    stopped using -- exactly the drift 22.11 logged for the stealth breakout
    bar. Asserting on the source is crude but it is the only way to catch a
    reimplementation that happens to agree on the fixture.
    """
    import inspect

    from scripts.ticker_alpha_bench import FACTORS

    src = inspect.getsource(FACTORS["X_prop_obv"])
    assert "blended_rank_scores" in src


def test_build_row_populates_obv():
    p = _panel(n=300)
    df = pd.DataFrame({
        "time": p["close"].index,
        "open": p["open"]["AAA"].values, "high": p["high"]["AAA"].values,
        "low": p["low"]["AAA"].values, "close": p["close"]["AAA"].values,
        "volume": p["volume"]["AAA"].values,
    })
    row = _build_ticker_row("AAA", "BANK", df, foreign_room_pct=None, dv_20d=2e7)
    assert row is not None
    assert row.obv_chg20 is not None
