"""One buy rule for every surface.

2026-09-25: review 2026-09-24 §2.4 found three surfaces running three different
buy rules; they were unified on one function, `long_shortlist` (SMA200 gate ->
blend). 2026-09-28: that function's rule became risk-adjusted 6-month momentum
(docs/reviews/STRATEGY_STUDY_2026-09-28.md) -- the old rule survives only as
`legacy_shortlist`, the audit shadow. These tests pin both: one function, every
surface calls it, and the shadow is logged, never recommended.
"""
from __future__ import annotations

import pathlib
from datetime import date

import pytest

from services.picks_scoring import MIN_BUY_SCORE, UNTRENDED_FLOOR
from services.picks_universe_service import TickerRow, legacy_shortlist, long_shortlist

REPO = pathlib.Path(__file__).resolve().parent.parent


def _row(sym, score, rank, momentum, sector="BANK", close=10.0, valid=True):
    return TickerRow(symbol=sym, sector_code=sector, close=close, score=score,
                     rank_score=rank, is_valid_buy=valid, stop=close * 0.9,
                     target=close * 1.2, rr=2.0, atr_pct=2.0, momentum=momentum,
                     mom_6m=momentum * 2 if momentum is not None else None, vol_63d=0.02)


def _universe():
    return [
        #    sym    score  blend  momentum
        _row("AAA", 4.0, 0.30, 1.0),
        _row("BBB", 1.0, 0.80, 9.0),
        _row("CCC", -0.7, 0.60, 5.0),
        _row("DDD", 3.0, 0.70, None),               # < 6 months of prices: not ranked
        _row("EEE", UNTRENDED_FLOOR, 0.99, 7.0),    # below SMA200: the old rule's never
        _row("FFF", 2.6, 0.10, 5.0, sector="TECH"),  # ties CCC on momentum
    ]


# ------------------------------------------------------------ the rule itself

def test_long_shortlist_is_the_momentum_order():
    out = [r.symbol for r in long_shortlist(_universe(), 10)]
    assert out == ["BBB", "EEE", "CCC", "FFF", "AAA"], "momentum, then symbol on a tie"
    assert "DDD" not in out, "a name without 6 months of prices is not ranked"


def test_the_sma200_gate_and_the_geometry_are_no_longer_gates():
    """Momentum already selects uptrends; the gated variant measured worse, and
    the SWING stop/target geometry was never part of the momentum study."""
    rows = _universe()
    rows[4].is_valid_buy = False
    assert "EEE" in [r.symbol for r in long_shortlist(rows, 10)]


def test_long_shortlist_excludes_what_is_already_held():
    out = [r.symbol for r in long_shortlist(_universe(), 3, exclude={"BBB"})]
    assert out == ["EEE", "CCC", "FFF"]


def test_the_default_list_is_the_book_size():
    from services.buy_layer import BUY_TOP_K
    rows = [_row(f"S{i:02d}", 0.0, 0.5, float(i)) for i in range(20)]
    assert len(long_shortlist(rows)) == BUY_TOP_K == 8


def test_the_previous_rule_is_only_a_shadow():
    """`legacy_shortlist` reproduces the 2026-09-25 rule for the audit log."""
    out = [r.symbol for r in legacy_shortlist(_universe(), 10)]
    assert out == ["BBB", "DDD", "CCC", "AAA", "FFF"]
    assert "EEE" not in out, "the old rule never bought below the SMA200"
    cut = [r.symbol for r in legacy_shortlist(_universe(), 5, min_score=MIN_BUY_SCORE)]
    assert cut == ["DDD", "AAA", "FFF"]


# ------------------------------------------------------- the three surfaces

class _Snap:
    def __init__(self, rows, market=None):
        self.as_of = date(2026, 9, 24)
        self.tickers = {r.symbol: r for r in rows}
        self.market = market or {}


def test_daily_insight_uses_the_rule_and_carries_the_layer(monkeypatch):
    import services.picks_universe_service as mod
    rows = _universe()
    svc = mod.PicksUniverseService()
    # Sector signals must not matter: flag the WORST-ranked sector as BUY.
    monkeypatch.setattr(svc, "_sectors_with_action", lambda *a, **k: {"TECH"})
    monkeypatch.setattr("services.picks_news.fetch_news", lambda *a, **k: [])
    out = svc._select_top({r.symbol: r for r in rows}, {}, action="BUY", n=5,
                          as_of=date(2026, 9, 24), market={"up": True})
    assert [p.symbol for p in out] == [r.symbol for r in long_shortlist(rows, 5)]
    assert [p.rank for p in out] == [1, 2, 3, 4, 5]
    assert all(p.sell_from and p.sell_by for p in out), "every BUY carries its review dates"
    top = out[0]
    assert top.accept_hi == pytest.approx(10.0 * 1.01)
    assert top.accept_lo == pytest.approx(10.0 * (1 - 2 * 0.02))
    assert top.outlook_4w["p25"] < top.outlook_4w["median"] < top.outlook_4w["p75"]
    assert "Vùng mua" in top.thesis and "top 16" in top.thesis


def test_the_bulletin_uses_the_rule_and_logs_the_old_one(monkeypatch):
    import services.picks_universe_service as mod
    from daily_watch import service
    from services import trading_state

    rows = _universe()
    monkeypatch.setattr(mod.PicksUniverseService, "peek",
                        lambda self: _Snap(rows, {"up": False, "vnindex": 1780.7,
                                                  "sma200": 1795.4, "gap": -0.0082}))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"BBB"})

    picks, meta = service._shortlist(5)
    assert [p["symbol"] for p in picks] == ["EEE", "CCC", "FFF", "AAA"]
    assert [x["symbol"] for x in meta["shortlist_previous_rule"]] == ["DDD", "CCC", "AAA", "FFF"]
    assert meta["qualified"] == 4
    # the held name keeps its rank on the WHOLE universe -- the sell rule reads it
    assert meta["ranks"]["BBB"] == 1 and meta["ranked_count"] == 5
    assert picks[0]["rank"] == 2
    assert picks[0]["accept_hi"] == pytest.approx(10.1)
    assert picks[0]["outlook_8w"]["win"] == pytest.approx(0.511), "the below-SMA200 table"
    # Every universe close is archived, so the log can score a base rate.
    assert set(meta["_universe_closes"]) == {r.symbol for r in rows}


def test_the_bulletin_payload_archives_the_shadow_list_at_top_level(monkeypatch):
    import services.picks_universe_service as mod
    from daily_watch import positions, service
    from services import trading_state

    rows = _universe()
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: set())
    monkeypatch.setattr(positions, "mark_book", lambda: {
        "as_of": "2026-09-24", "positions": [], "priced": 0, "count": 0,
        "total_pnl_pct": None})
    payload = service.build(top_n=5)
    assert [x["symbol"] for x in payload["shortlist_previous_rule"]] == [
        "BBB", "DDD", "CCC", "AAA", "FFF"]
    assert "shortlist_previous_rule" not in payload["shortlist_meta"]
    assert "_universe_closes" not in payload["shortlist_meta"]
    assert set(payload["marks"]) >= {r.symbol for r in rows}
    md = service.render(payload)
    assert "không phải khuyến nghị" in md and "T+" not in md
    assert "Vùng mua" in md and "8 tuần" in md and "chưa lấy được VNINDEX" in md


def test_the_email_takes_the_daily_insight_list_verbatim():
    """generate_report.py builds its buys from `snapshot.top_buys` and its watch
    list from `long_shortlist` — no ranker gate, no cutoff, no 5-day guard, no
    raw-score re-sort. Read as text: importing it pulls in the whole report."""
    src = (REPO / "generate_report.py").read_text(encoding="utf-8")
    assert "long_shortlist" in src
    assert "for p in _universe_snap.top_buys" in src
    for gone in ("MIN_BUY_SCORE", "MAX_5D_DROP_PCT", "in_secs"):
        assert gone not in src, f"{gone} is a second buy rule"
    # 2026-09-28: the AVOID merge drops anything on the buy list
    assert 'if p["symbol"] not in buys]' in src


# ------------------------------------------------------------------ the audit

def _archive(day, shortlist, shadow=None, marks=None, key="shortlist_with_cutoff"):
    snap = {"generated_at": day, "shortlist": [{"symbol": s} for s in shortlist],
            "marks": marks or {}, "book": {"positions": []}}
    if shadow is not None:
        snap[key] = [{"symbol": s} for s in shadow]
    return snap


def test_each_archive_is_scored_as_the_rules_it_ran():
    from daily_watch.audit import CUTOFF, MOMENTUM, RUNNING, rule_lists
    assert rule_lists(_archive("2026-09-20", ["GAS"])) == {CUTOFF: ["GAS"]}
    got = rule_lists(_archive("2026-09-26", ["BBB", "CCC"], shadow=["AAA"]))
    assert got == {RUNNING: ["BBB", "CCC"], CUTOFF: ["AAA"]}
    got = rule_lists(_archive("2026-09-29", ["VIC"], shadow=["NTP"],
                              key="shortlist_previous_rule"))
    assert got == {MOMENTUM: ["VIC"], RUNNING: ["NTP"]}


def test_the_audit_scores_the_rules_against_the_same_base():
    from daily_watch.audit import MOMENTUM, RUNNING, forward
    names = [f"S{i:02d}" for i in range(12)]
    m0 = dict.fromkeys(names, 10.0)
    m1 = dict.fromkeys(names, 10.0) | {"S00": 12.0, "S01": 9.0}
    snaps = [_archive("d0", ["S00"], shadow=["S01"], marks=m0, key="shortlist_previous_rule"),
             _archive("d1", [], shadow=[], marks=m1, key="shortlist_previous_rule")]
    rows, pending = forward(snaps, 1)
    assert len(rows) == 1 and pending == 0
    r = rows[0]
    assert r[MOMENTUM] == pytest.approx(0.20)
    assert r[RUNNING] == pytest.approx(-0.10)
    assert r["base"] == pytest.approx((0.20 - 0.10) / 12)


def test_the_bulletin_sizes_the_buy_to_the_free_slots(monkeypatch):
    """The rule holds 8 names. A held name still in the top 16 keeps its slot,
    so the bulletin says how many to ADD -- not "buy the whole list" -- and
    prints each holding's rank, which is what the sell rule reads."""
    import services.picks_universe_service as mod
    from daily_watch import positions, service
    from services import trading_state

    rows = _universe() + [_row(f"X{i:02d}", 0.0, 0.5, -float(i)) for i in range(20)]
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"BBB", "X19"})
    monkeypatch.setattr(positions, "mark_book", lambda: {
        "as_of": "2026-09-24", "priced": 2, "count": 2, "total_pnl_pct": None,
        "positions": [{"symbol": "BBB", "sell_range": {}}, {"symbol": "X19", "sell_range": {}}]})
    payload = service.build(top_n=8)
    md = service.render(payload)
    assert "mua thêm **tối đa 7 mã**" in md, "BBB (rank 1) keeps its slot; X19 does not"
    # 2026-09-29: one verdict per holding. Neither has a buy date, so today's
    # rank decides: BBB stays, X19 (outside the top 16) is a sale -- and it is
    # the one alert at the top of the bulletin.
    assert "| 1/25 | GIỮ |" in md
    assert "| 25/25 | **BÁN** ATO phiên tới |" in md
    assert [a["symbol"] for a in payload["alerts"]] == ["X19"]
    assert "### 🔴 X19 — BÁN ATO phiên tới" in md


# ------------------------------- 2026-09-29: Tom buys a few, on his own days

def _steady_and_new():
    """12 names. Today's order is S00 > S01 > ... > S11. S00 jumped into the
    top 8 two sessions ago; S01..S07 have been there all 11 sessions."""
    rows = []
    for i in range(12):
        today_score = 20.0 - i
        hist = [today_score] * 11
        if i == 0:
            hist = [1.0] * 9 + [today_score] * 2          # new: 2 sessions in the top 8
        r = _row(f"S{i:02d}", 0.0, 0.5, today_score)
        r.momentum_hist = hist
        rows.append(r)
    return rows


def test_the_bulletin_lists_steady_names_first(monkeypatch):
    import services.picks_universe_service as mod
    from daily_watch import service
    from services import trading_state

    rows = _steady_and_new()
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: set())
    picks, _meta = service._shortlist(8)
    assert {p["symbol"] for p in picks} == {f"S{i:02d}" for i in range(8)}, "the set is the rule's"
    assert picks[0]["symbol"] == "S01" and picks[0]["priority"] == "A"
    assert picks[-1]["symbol"] == "S00" and picks[-1]["priority"] == "B"
    assert picks[-1]["rank"] == 1 and picks[-1]["top8_run"] == 2


def test_daily_insight_orders_its_buys_the_same_way(monkeypatch):
    import services.picks_universe_service as mod
    rows = _steady_and_new()
    svc = mod.PicksUniverseService()
    monkeypatch.setattr("services.picks_news.fetch_news", lambda *a, **k: [])
    out = svc._select_top({r.symbol: r for r in rows}, {}, action="BUY", n=8,
                          as_of=date(2026, 9, 29), market={"up": True})
    assert [p.symbol for p in out][:2] == ["S01", "S02"] and out[-1].symbol == "S00"
    assert out[-1].rank == 1 and out[-1].priority == "B" and out[0].priority == "A"


def test_a_holding_outside_the_basket_gets_an_equivalent_rank(monkeypatch):
    import services.picks_universe_service as mod
    from daily_watch import holdings, positions, service
    from services import trading_state

    rows = _universe()
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"OUT"})
    monkeypatch.setattr(holdings, "load", lambda: {"rows": {"OUT": {"close": 9.0,
                                                                    "momentum": 6.0}}})
    monkeypatch.setattr(positions, "mark_book", lambda: {
        "as_of": "2026-09-29", "priced": 1, "count": 1, "total_pnl_pct": None,
        "positions": [{"symbol": "OUT", "entry_price": 12.0, "last": 9.0, "pnl_pct": -25.0,
                       "sell_range": {}}]})
    payload = service.build(top_n=5)
    # scores 9, 7, 5, 5, 1 -> 6.0 sits third
    assert payload["shortlist_meta"]["held_ranks"]["OUT"] == {"rank": 3, "equivalent": True}
    p = payload["book"]["positions"][0]
    assert p["verdict"]["verdict"] == "GIỮ" and "tương đương" in p["verdict"]["why"]
    assert "*tương đương*" in service.render(payload)


def test_a_missed_review_is_read_back_from_the_archive(monkeypatch, tmp_path):
    import json

    import services.picks_universe_service as mod
    from daily_watch import positions, sell_range, service
    from services import trading_state
    from utils.clock import previous_trading_day, today

    rows = _universe() + [_row(f"X{i:02d}", 0.0, 0.5, -float(i)) for i in range(20)]
    d = today()
    for _ in range(22):
        d = previous_trading_day(d)
    sr = sell_range.advise({"opened_at": d.isoformat()}, [], 2.0, 10.0)
    assert sr["last_decision"], "22 sessions in: the session-19 decision is behind us"
    monkeypatch.setattr(service, "ARCHIVE_DIR", tmp_path)
    (tmp_path / f"{sr['last_decision']}.json").write_text(json.dumps(
        {"shortlist_meta": {"ranks": {"X15": 21}}}), encoding="utf-8")
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"X15"})
    monkeypatch.setattr(positions, "mark_book", lambda: {
        "as_of": "2026-09-29", "priced": 1, "count": 1, "total_pnl_pct": None,
        "positions": [{"symbol": "X15", "entry_price": 10.0, "last": 10.0, "pnl_pct": 0.0,
                       "sell_range": sr}]})
    v = service.build(top_n=5)["book"]["positions"][0]["verdict"]
    assert v["verdict"] == "BÁN" and sr["last_decision"] in v["why"]


def test_a_weak_name_before_its_review_still_takes_a_slot(monkeypatch):
    """V0 frees a slot only at a review: X19 (rank 25) bought 5 sessions ago is
    GIỮ until session 20, so the book has two names kept and six slots free."""
    import services.picks_universe_service as mod
    from daily_watch import positions, sell_range, service
    from services import trading_state
    from utils.clock import previous_trading_day, today

    d = today()
    for _ in range(5):
        d = previous_trading_day(d)
    rows = _universe() + [_row(f"X{i:02d}", 0.0, 0.5, -float(i)) for i in range(20)]
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"BBB", "X19"})
    monkeypatch.setattr(positions, "mark_book", lambda: {
        "as_of": "2026-09-24", "priced": 2, "count": 2, "total_pnl_pct": None,
        "positions": [{"symbol": "BBB", "sell_range": {}},
                      {"symbol": "X19", "sell_range": sell_range.advise(
                          {"opened_at": d.isoformat()}, [], 2.0, 10.0)}]})
    payload = service.build(top_n=8)
    assert [p["verdict"]["verdict"] for p in payload["book"]["positions"]] == ["GIỮ", "GIỮ"]
    assert payload["alerts"] == []
    assert "mua thêm **tối đa 6 mã**" in service.render(payload)
