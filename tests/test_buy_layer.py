"""The buy rule's momentum and the layer on top of it (2026-09-28).

Tom: *"tạo layer nữa dựa vào phân tích: gợi ý nên mua gì, accept range, expect
lên bao nhiêu trong các chu kỳ 4 tuần 8 tuần"*. What is pinned here:

  * the momentum production computes IS the one the study measured (same
    lookback, same skip, same volatility window) -- a second definition would
    let the product drift from the number that justified it (§22.11);
  * the accept range and the 4/8-week bands are the measured tables applied as
    documented, including the market-state switch between tables;
  * a snapshot written before the rule existed is refused, not served as an
    empty buy list.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from services import buy_layer as bl


def _closes(n=300, seed=4, drift=0.001):
    rng = np.random.default_rng(seed)
    return list(20 * np.cumprod(1 + rng.normal(drift, 0.02, n)))


def test_momentum_is_the_studied_definition():
    """(C[t-5]/C[t-126] - 1) / std(126 daily returns ending at t), ddof=1 --
    exactly `ramom126` in docs/reviews/strategy_study_2026-09-28/signals.py."""
    c = pd.Series(_closes())
    want_mom = c.shift(5).iloc[-1] / c.shift(126).iloc[-1] - 1
    want_vol = c.pct_change().rolling(126).std().iloc[-1]
    score, mom, vol = bl.risk_adjusted_momentum(c.tolist())
    assert mom == pytest.approx(want_mom)
    assert vol == pytest.approx(want_vol)
    assert score == pytest.approx(want_mom / want_vol)


def test_momentum_needs_six_months_and_says_so():
    assert bl.risk_adjusted_momentum(_closes(126)) == (None, None, None)
    assert bl.risk_adjusted_momentum(_closes(127))[0] is not None


def test_the_latest_week_does_not_move_momentum():
    """The skip is the point: a 1-5 day spike mean-reverts, it is not trend."""
    c = _closes()
    spiked = c[:-3] + [x * 1.2 for x in c[-3:]]
    assert bl.risk_adjusted_momentum(spiked)[1] == pytest.approx(bl.risk_adjusted_momentum(c)[1])


def test_daily_vol_is_the_63_session_std():
    c = pd.Series(_closes())
    assert bl.daily_vol(c.tolist(), 63) == pytest.approx(c.pct_change().rolling(63).std().iloc[-1])
    assert bl.daily_vol(_closes(63), 63) is None


def test_the_accept_range_is_the_measured_premium_and_two_days_of_noise():
    lo, hi = bl.accept_range(50.0, 0.02)
    assert hi == pytest.approx(50.5), "1% above the signal close, where the edge is gone"
    assert lo == pytest.approx(48.0), "2 x daily vol below"
    assert bl.accept_range(50.0, None) == (None, 50.5)
    assert bl.accept_range(0.0, 0.02) == (None, None)


@pytest.mark.parametrize("h", [20, 40])
def test_the_outlook_scales_with_the_names_own_volatility(h):
    calm = bl.outlook(0.01, True, h)
    wild = bl.outlook(0.03, True, h)
    z = bl.Z[(h, True)]
    s = 0.01 * math.sqrt(h)
    assert calm["p25"] == pytest.approx(z["q25"] * s - bl.ROUND_TRIP)
    assert calm["p75"] == pytest.approx(z["q75"] * s - bl.ROUND_TRIP)
    assert calm["p10"] < calm["p25"] < calm["median"] < calm["p75"] < calm["p90"]
    assert (wild["p75"] - wild["p25"]) == pytest.approx(3 * (calm["p75"] - calm["p25"]))


def test_the_market_state_picks_the_table():
    up, down, unknown = (bl.outlook(0.02, s, 40) for s in (True, False, None))
    assert up["win"] == bl.Z[(40, True)]["win"]
    assert down["win"] == bl.Z[(40, False)]["win"]
    assert unknown["win"] == bl.Z[(40, None)]["win"], "unknown -> the pooled table"
    assert bl.outlook(None, True, 20) is None and bl.outlook(0.02, True, 30) is None


def test_the_edge_is_weaker_below_the_200_day_average():
    """The one market-state fact the study supports (no switch: see RECORD)."""
    for h in (20, 40):
        assert bl.EDGE[(h, False)] < bl.EDGE[(h, None)] < bl.EDGE[(h, True)]


def test_market_state_is_vnindex_against_its_200_session_average():
    rising = list(np.linspace(1000, 1800, 260))
    st = bl.market_state(rising)
    assert st["up"] is True and st["sma200"] == pytest.approx(np.mean(rising[-200:]))
    assert st["gap"] == pytest.approx(rising[-1] / st["sma200"] - 1)
    assert bl.market_state(rising[::-1])["up"] is False
    assert bl.market_state(rising[:150])["up"] is None


def test_annotate_is_what_the_surfaces_print():
    a = bl.annotate(40.0, 0.025, False)
    assert set(a) == {"accept_lo", "accept_hi", "outlook_4w", "outlook_8w"}
    assert a["outlook_8w"] == bl.outlook(0.025, False, 40)


# --------------------------------------------------------------- the service

def test_a_snapshot_from_before_the_rule_is_refused(tmp_path, monkeypatch):
    """Schema 1 rows have no momentum: served, the buy list would be empty
    until the next rebuild. Refused, the next get_snapshot() rebuilds."""
    from datetime import date, datetime

    import services.picks_universe_service as mod
    row = mod.TickerRow(symbol="VIC", sector_code="REAL", close=231.9)
    fr = mod.FreshnessReport(as_of=date(2026, 9, 28), built_at=datetime(2026, 9, 28, 17))
    snap = mod.UniverseSnapshot(as_of=date(2026, 9, 28), built_at=fr.built_at,
                                tickers={"VIC": row}, by_sector={"REAL": [row]},
                                freshness=fr, is_valid=True)
    monkeypatch.setattr(mod, "_latest_signal_date", lambda: date(2026, 9, 28))
    path = tmp_path / "picks_universe.json"
    monkeypatch.setattr(mod, "SNAPSHOT_PATH", path)

    blob = mod._snapshot_to_json(snap)
    path.write_text(json.dumps(blob, default=str), encoding="utf-8")
    assert mod.PicksUniverseService()._load_from_disk() is not None, "control: loads"
    path.write_text(json.dumps({**blob, "schema": 1}, default=str), encoding="utf-8")
    assert mod.PicksUniverseService()._load_from_disk() is None


def test_the_market_state_survives_a_vnstock_quota_exit(monkeypatch):
    """vnai ends the process with sys.exit() at 20 req/min (it killed the
    2026-09-28 report). The buy layer must degrade to "unknown", not die."""
    import services.picks_universe_service as mod

    def quota(*a, **k):
        raise SystemExit("Rate limit exceeded. Process terminated.")

    monkeypatch.setattr("services.macro_service.fetch_vnindex_daily", quota)
    monkeypatch.setattr("utils.vnstock_gate.BACKOFF", ())
    assert mod._market_state() == {"up": None}


def test_build_row_carries_the_momentum_of_its_raw_closes():
    from services.picks_universe_service import _build_ticker_row
    c = _closes(280, seed=9)
    df = pd.DataFrame({"time": pd.bdate_range("2025-08-01", periods=280),
                       "open": c, "high": [x * 1.01 for x in c], "low": [x * 0.99 for x in c],
                       "close": c, "volume": 1e6})
    row = _build_ticker_row("AAA", "BANK", df, 10.0, 1e10)
    score, mom, _ = bl.risk_adjusted_momentum(c)
    assert row.momentum == pytest.approx(score, abs=1e-4)
    assert row.mom_6m == pytest.approx(mom * 100, abs=0.01)
    assert row.vol_63d == pytest.approx(bl.daily_vol(c, 63), abs=1e-5)


# ============ buying a few names on your own days (2026-09-29) ================
# Tom: "khuyến nghị mã nào nên mua hằng ngày (có các priority)". The list's SET
# stays the momentum top N; the priority only orders it for a partial buyer.

def test_momentum_history_ends_with_todays_score():
    c = _closes()
    h = bl.momentum_history(c)
    assert len(h) == bl.MOM_HISTORY == 11
    assert h[-1] == pytest.approx(bl.risk_adjusted_momentum(c)[0], abs=1e-4)
    assert h[0] == pytest.approx(bl.risk_adjusted_momentum(c[:-10])[0], abs=1e-4)


def test_a_short_history_leaves_the_early_days_unknown():
    h = bl.momentum_history(_closes(n=130))
    assert h[:6] == [None] * 6 and all(x is not None for x in h[-4:])


def _hist(*vals):
    return list(vals)


def test_top_runs_count_consecutive_days_in_the_top_k_up_to_today():
    # k = 2. A is top every day; B only the last two; C was top, then fell out.
    H = {"A": _hist(9, 9, 9, 9), "B": _hist(1, 1, 8, 8), "C": _hist(8, 8, 1, 1),
         "D": _hist(2, 2, 2, 2)}
    runs = bl.top_runs(H, k=2)
    assert runs == {"A": 4, "B": 2, "C": 0, "D": 0}


def test_a_row_without_history_is_unknown_not_new():
    runs = bl.top_runs({"A": _hist(9, 9), "OLD": []}, k=2)
    assert runs["OLD"] is None and bl.priority(runs["OLD"]) is None
    assert runs["A"] == 2


def test_priority_a_needs_a_run_longer_than_ten_sessions():
    assert bl.priority(11) == "A" and bl.priority(10) == "B" and bl.priority(0) == "B"


def test_prioritise_orders_a_before_b_and_keeps_rank_inside_each():
    picks = [{"symbol": "X", "rank": 1, "priority": "B"},
             {"symbol": "Y", "rank": 2, "priority": "A"},
             {"symbol": "Z", "rank": 3, "priority": None},
             {"symbol": "W", "rank": 4, "priority": "A"}]
    assert [p["symbol"] for p in bl.prioritise(picks)] == ["Y", "W", "X", "Z"]
    # without any priority (an old snapshot) the order is the rank order
    plain = [{"symbol": s, "rank": i, "priority": None} for i, s in enumerate("PQR", 1)]
    assert [p["symbol"] for p in bl.prioritise(plain)] == ["P", "Q", "R"]


def test_an_outside_name_is_placed_among_the_ranked_scores():
    scores = [5.0, 4.0, 3.0, 2.0]
    assert bl.equivalent_rank(3.5, scores) == 3
    assert bl.equivalent_rank(9.0, scores) == 1
    assert bl.equivalent_rank(None, scores) is None


def test_the_sell_sentence_quotes_the_measured_alternatives():
    s = bl.sell_rule_sentence()
    e = bl.EXIT_STUDY
    for key in ("take_profit_20", "hard_cap_40", "cut_loss_10"):
        assert f"{e[key] * 100:.0f}%" in s
    assert "không quyết định bán" in s and "**" not in s, "plain text: the email reuses it"


def test_the_priority_sentence_says_how_small_the_effect_is():
    s = bl.priority_sentence()
    assert "2025 ngược lại" in s and "**" not in s
