"""One buy rule for every surface — 2026-09-25.

Review 2026-09-24 §2.4 found three surfaces running three different buy rules:
the 17:30 bulletin (score >= 2.5 -> blend), Daily Insight (BUY-sector names
first, then the rest) and the 17:00 email (ranker sectors only, raw-score order,
a -12% 5-day guard, top 6). Tom then removed the 2.5 cutoff and kept the SMA200
gate ("bỏ ngay, giữ cổng SMA200"). These tests pin the result: one function,
`long_shortlist`, and every surface calls it.
"""
from __future__ import annotations

import pathlib
from datetime import date

import pytest

from services.picks_scoring import MIN_BUY_SCORE, UNTRENDED_FLOOR
from services.picks_universe_service import TickerRow, long_shortlist

REPO = pathlib.Path(__file__).resolve().parent.parent


def _row(sym, score, rank, sector="BANK", close=10.0):
    return TickerRow(symbol=sym, sector_code=sector, close=close, score=score,
                     rank_score=rank, is_valid_buy=True, stop=close * 0.9,
                     target=close * 1.2, rr=2.0, atr_pct=2.0)


def _universe():
    return [
        _row("AAA", 4.0, 0.30),                 # passes the old cutoff too
        _row("BBB", 1.0, 0.80),                 # gated, below 2.5
        _row("CCC", -0.7, 0.60),                # gated, negative
        _row("DDD", 3.0, 0.70),                 # passes the old cutoff too
        _row("EEE", UNTRENDED_FLOOR, 0.99),     # below SMA200: never
        _row("FFF", 2.6, 0.10, sector="TECH"),  # passes the old cutoff too
    ]


# ------------------------------------------------------------ the rule itself

def test_long_shortlist_is_the_sma200_gate_then_the_blend():
    out = [r.symbol for r in long_shortlist(_universe(), 10)]
    assert out == ["BBB", "DDD", "CCC", "AAA", "FFF"]
    assert "EEE" not in out, "a name below its SMA200 is never a buy"


def test_long_shortlist_excludes_what_is_already_held():
    out = [r.symbol for r in long_shortlist(_universe(), 3, exclude={"BBB"})]
    assert out == ["DDD", "CCC", "AAA"]


def test_the_retired_cutoff_is_only_a_shadow_filter():
    """`min_score` reproduces the old rule for the audit log, nothing else."""
    out = [r.symbol for r in long_shortlist(_universe(), 5, min_score=MIN_BUY_SCORE)]
    assert out == ["DDD", "AAA", "FFF"]


def test_an_invalid_geometry_is_still_not_a_buy():
    bad = _row("ZZZ", 3.0, 0.95)
    bad.is_valid_buy = False
    assert "ZZZ" not in [r.symbol for r in long_shortlist([bad, *_universe()], 10)]


# ------------------------------------------------------- the three surfaces

class _Snap:
    def __init__(self, rows):
        self.as_of = date(2026, 9, 24)
        self.tickers = {r.symbol: r for r in rows}


def test_daily_insight_uses_the_rule(monkeypatch):
    import services.picks_universe_service as mod
    rows = _universe()
    svc = mod.PicksUniverseService()
    # Sector signals must not matter: flag the WORST-ranked sector as BUY.
    monkeypatch.setattr(svc, "_sectors_with_action", lambda *a, **k: {"TECH"})
    monkeypatch.setattr(mod, "fetch_news", lambda *a, **k: [], raising=False)
    out = svc._select_top({r.symbol: r for r in rows}, {}, action="BUY", n=5,
                          as_of=date(2026, 9, 24))
    assert [p.symbol for p in out] == [r.symbol for r in long_shortlist(rows, 5)]
    assert all(p.sell_from and p.sell_by for p in out), "every BUY carries its window"


def test_the_bulletin_uses_the_rule_and_logs_the_old_one(monkeypatch):
    import services.picks_universe_service as mod
    from daily_watch import service
    from services import trading_state

    rows = _universe()
    monkeypatch.setattr(mod.PicksUniverseService, "peek", lambda self: _Snap(rows))
    monkeypatch.setattr(trading_state, "held_symbols", lambda: {"DDD"})

    picks, meta = service._shortlist(5)
    assert [p["symbol"] for p in picks] == ["BBB", "CCC", "AAA", "FFF"]
    assert [x["symbol"] for x in meta["shortlist_with_cutoff"]] == ["AAA", "FFF"]
    assert meta["qualified"] == 4
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
    assert [x["symbol"] for x in payload["shortlist_with_cutoff"]] == ["DDD", "AAA", "FFF"]
    assert "shortlist_with_cutoff" not in payload["shortlist_meta"]
    assert "_universe_closes" not in payload["shortlist_meta"]
    assert set(payload["marks"]) >= {r.symbol for r in rows}
    md = service.render(payload)
    assert "không phải khuyến nghị" in md and "T+" not in md


def test_the_email_takes_the_daily_insight_list_verbatim():
    """generate_report.py builds its buys from `snapshot.top_buys` and its watch
    list from `long_shortlist` — no ranker gate, no cutoff, no 5-day guard, no
    raw-score re-sort. Read as text: importing it pulls in the whole report."""
    src = (REPO / "generate_report.py").read_text(encoding="utf-8")
    assert "long_shortlist" in src
    assert "for p in _universe_snap.top_buys" in src
    for gone in ("MIN_BUY_SCORE", "MAX_5D_DROP_PCT", "in_secs"):
        assert gone not in src, f"{gone} is a second buy rule"


# ------------------------------------------------------------------ the audit

def _archive(day, shortlist, shadow=None, marks=None):
    snap = {"generated_at": day, "shortlist": [{"symbol": s} for s in shortlist],
            "marks": marks or {}, "book": {"positions": []}}
    if shadow is not None:
        snap["shortlist_with_cutoff"] = [{"symbol": s} for s in shadow]
    return snap


def test_a_pre_switch_archive_is_scored_as_the_old_rule():
    from daily_watch.audit import CUTOFF, RUNNING, rule_lists
    assert rule_lists(_archive("2026-09-20", ["GAS"])) == {CUTOFF: ["GAS"]}
    got = rule_lists(_archive("2026-09-26", ["BBB", "CCC"], shadow=["AAA"]))
    assert got == {RUNNING: ["BBB", "CCC"], CUTOFF: ["AAA"]}


def test_the_audit_scores_both_rules_against_the_same_base():
    from daily_watch.audit import CUTOFF, RUNNING, forward
    names = [f"S{i:02d}" for i in range(12)]
    m0 = dict.fromkeys(names, 10.0)
    m1 = dict.fromkeys(names, 10.0) | {"S00": 12.0, "S01": 9.0}
    snaps = [_archive("d0", ["S00"], shadow=["S01"], marks=m0),
             _archive("d1", [], shadow=[], marks=m1)]
    rows, pending = forward(snaps, 1)
    assert len(rows) == 1 and pending == 0
    r = rows[0]
    assert r[RUNNING] == pytest.approx(0.20)
    assert r[CUTOFF] == pytest.approx(-0.10)
    assert r["base"] == pytest.approx((0.20 - 0.10) / 12)
