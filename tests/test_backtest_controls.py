"""Backlog step 5 — the backtest controls the UI can now reach.

Everything here was already implemented in `services/backtest_service.py`; what
was missing was a way in (the router took no `strategy`) and a way out (the
benchmark existed only as a scalar, so the chart could not draw it). These
guards exist so neither regresses back into "modelled but unreachable".
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from database.models import MacroAnchor, SectorFlowDaily, SectorSignal
from services.backtest_service import SectorBacktestService

_BIG = ["BANK", "REAL", "STEEL", "BROK"]


def _seed(session, days=40):
    """Four big-but-flat sectors and one small one that trends.

    `flow_z20` is what separates them: FISH is tiny in VND but +2.5σ against
    its own history, which is exactly the case raw-VND ranking cannot see.
    """
    base = datetime(2026, 1, 5)
    dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    for i, d in enumerate(dates):
        for j, code in enumerate(_BIG):
            session.add(SectorFlowDaily(
                sector_code=code, date=d, close_idx=1000.0, return_1d=0.0,
                net_dollar_flow=9e11 - j * 1e10, atr_pct=0.01, flow_z20=-0.5,
            ))
        session.add(SectorFlowDaily(
            sector_code="FISH", date=d, close_idx=100.0 * (1.01 ** i),
            return_1d=0.01, net_dollar_flow=1e9, atr_pct=0.01, flow_z20=2.5,
        ))
        session.add(MacroAnchor(
            time=datetime.strptime(d, "%Y-%m-%d"), vnindex=1200.0 * (1.002 ** i)))
    session.commit()
    return dates


def _seed_signals(session, dates):
    for d in dates:
        session.add(SectorSignal(date=d, sector_code="FISH", score=1.0,
                                 rank=1, action="BUY"))
    session.commit()


# --------------------------------------------------------------------------
# The benchmark as a curve, not just a total
# --------------------------------------------------------------------------

def test_equity_curve_carries_a_benchmark_point_per_row(seeded_session):
    """One line on a chart cannot answer "did I beat the index, and when"."""
    dates = _seed(seeded_session)
    res = SectorBacktestService(seeded_session).run("bench", dates[0], dates[-1])

    assert res.benchmark_source == "vnindex"
    assert len(res.equity_curve) == len(dates)
    assert all("benchmark" in p for p in res.equity_curve)

    vals = [p["benchmark"] for p in res.equity_curve if p["benchmark"] is not None]
    assert len(vals) > len(dates) // 2, "benchmark should align on most sessions"
    # Rebased to the same capital so both lines share one axis.
    assert vals[0] == pytest.approx(res.initial_capital, rel=0.01)
    assert vals[-1] > vals[0], "a rising VNINDEX must produce a rising curve"


def test_benchmark_curve_total_agrees_with_the_scalar(seeded_session):
    """The line and the tile must not tell two different stories."""
    dates = _seed(seeded_session)
    res = SectorBacktestService(seeded_session).run("agree", dates[0], dates[-1])
    vals = [p["benchmark"] for p in res.equity_curve if p["benchmark"] is not None]
    from_curve = (vals[-1] / res.initial_capital - 1) * 100
    assert from_curve == pytest.approx(res.benchmark_return_pct, rel=0.05)


# --------------------------------------------------------------------------
# The three strategies must actually be three strategies
# --------------------------------------------------------------------------

def test_flow_z_is_not_the_same_strategy_as_flow_raw(seeded_session):
    """Found by shipping the selector: two of the three options were identical.

    `flow_z` used a *cross-sectional* z — `(v - mean) / sd` computed within the
    same day the rows were then sorted in. That is a positive affine map, and a
    positive affine map preserves order, so it produced the raw-VND permutation
    every single day. On live data both returned -25.06% over the same 330
    trades. `flow_z` now ranks on `flow_z20`, the per-sector z of a sector
    against its own history, which is what §16.2 means by flow z.
    """
    dates = _seed(seeded_session)
    svc = SectorBacktestService(seeded_session)
    z = svc.run("z", dates[0], dates[-1], strategy="flow_z")
    raw = svc.run("raw", dates[0], dates[-1], strategy="flow_raw")

    z_secs = {t["sector"] for t in z.trade_log}
    raw_secs = {t["sector"] for t in raw.trade_log}
    assert "FISH" in z_secs, "a +2.5σ sector must be reachable by flow_z"
    assert "FISH" not in raw_secs, "raw VND ranking cannot see a small sector"
    assert z.total_return_pct != raw.total_return_pct


def test_cross_sectional_z_preserves_raw_order(seeded_session):
    """The proof, pinned. If this ever fails, the note in the service is stale."""
    import pandas as pd
    g = pd.DataFrame({"sector_code": list("ABCDE"),
                      "net_dollar_flow": [9e11, 1e9, 4e11, 7e10, 2e11]})
    g["_z"] = SectorBacktestService._cross_sectional_z(g, "net_dollar_flow")
    assert (list(g.sort_values("_z", ascending=False)["sector_code"])
            == list(g.sort_values("net_dollar_flow", ascending=False)["sector_code"]))


# --------------------------------------------------------------------------
# Per-run cost overrides (§18.2/7,10)
# --------------------------------------------------------------------------

def test_cost_overrides_reach_the_simulation(seeded_session):
    dates = _seed(seeded_session)
    _seed_signals(seeded_session, dates)
    svc = SectorBacktestService(seeded_session)

    cheap = svc.run("cheap", dates[0], dates[-1], fee_bps=0, sell_tax_bps=0)
    dear = svc.run("dear", dates[0], dates[-1], fee_bps=200, sell_tax_bps=200)

    assert cheap.fee_bps == 0 and dear.fee_bps == 200
    assert dear.total_cost_pct > cheap.total_cost_pct
    assert dear.final_capital < cheap.final_capital, \
        "a 2% round-trip must cost more than a free one"


def test_defaults_are_used_when_no_override_is_given(seeded_session):
    from config import BACKTEST_FEE_BPS, BACKTEST_HOLD_SESSIONS, BACKTEST_SELL_TAX_BPS
    dates = _seed(seeded_session)
    res = SectorBacktestService(seeded_session).run("def", dates[0], dates[-1])
    assert res.fee_bps == BACKTEST_FEE_BPS
    assert res.sell_tax_bps == BACKTEST_SELL_TAX_BPS
    assert res.hold_sessions == BACKTEST_HOLD_SESSIONS


def test_negative_costs_are_clamped_not_credited(seeded_session):
    """A negative fee would pay the trader to trade. Clamp, never credit."""
    dates = _seed(seeded_session)
    _seed_signals(seeded_session, dates)
    res = SectorBacktestService(seeded_session).run(
        "neg", dates[0], dates[-1], fee_bps=-50, sell_tax_bps=-50)
    assert res.fee_bps == 0 and res.sell_tax_bps == 0
    assert res.total_cost_pct >= 0


# --------------------------------------------------------------------------
# 4 and 8 weeks only; t+1; carry the last signal (2026-09-25)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("hold", [20, 40])
def test_the_book_is_recut_only_on_the_hold_calendar(seeded_session, hold):
    """Rebalancing every session was §23.5's 844 trades/year. Now the book is
    re-cut on session 1 and every `hold` sessions after it, nowhere else."""
    dates = _seed(seeded_session, days=90)
    res = SectorBacktestService(seeded_session).run(
        "cal", dates[0], dates[-1], strategy="flow_z", hold_sessions=hold)
    assert res.hold_sessions == hold
    allowed = {dates[t] for t in range(1, len(dates), hold)}
    traded = {t["date"] for t in res.trade_log}
    assert traded and traded <= allowed
    assert res.rebalance_count == len(allowed)


@pytest.mark.parametrize("bad", [2, 3, 5, 10, 60])
def test_a_t_plus_horizon_is_refused(seeded_session, bad):
    """Tom, 2026-09-25: "chỉ sử dụng 4 tuần và 8 tuần". A 3-session backtest is
    not a smaller version of the product, it is a different product."""
    dates = _seed(seeded_session)
    with pytest.raises(ValueError, match="hold_sessions"):
        SectorBacktestService(seeded_session).run(
            "bad", dates[0], dates[-1], hold_sessions=bad)


def test_a_signal_is_traded_the_session_after_it_is_published(seeded_session):
    """Signals go out at 17:00, after the close they were computed from, so the
    first fill can only be the NEXT session's close (review 2026-09-24 §4.1/6)."""
    dates = _seed(seeded_session)
    _seed_signals(seeded_session, dates[:1])
    res = SectorBacktestService(seeded_session).run("t1", dates[0], dates[-1])
    buys = [t for t in res.trade_log if t["side"] == "BUY"]
    assert buys and buys[0]["date"] == dates[1]
    assert all(t["date"] != dates[0] for t in res.trade_log)


def test_a_session_without_a_new_signal_keeps_the_last_one(seeded_session):
    """The old engine read "no row today" as "sell everything" and did, on 66 of
    114 sessions. One signal on day 0 must hold FISH to the end."""
    dates = _seed(seeded_session, days=60)
    _seed_signals(seeded_session, dates[:1])
    res = SectorBacktestService(seeded_session).run(
        "carry", dates[0], dates[-1], hold_sessions=20)
    sells = [t for t in res.trade_log if t["side"] == "SELL"]
    assert not sells, f"sold on a day with no new signal: {sells}"
    assert res.final_capital > res.initial_capital   # FISH trends +1%/session


def test_garbage_vnindex_rows_do_not_become_the_benchmark(seeded_session, monkeypatch):
    """613 rows of vnindex ~ 1.82 printed a "+97,432%" benchmark. A series that
    is mostly garbage must fall back to the flagged sector mean."""
    import services.backtest_service as bs
    monkeypatch.setattr(bs, "_panel_vnindex", lambda: None)
    dates = _seed(seeded_session)
    for row in seeded_session.query(MacroAnchor).all():
        row.vnindex = 1.82
    seeded_session.commit()
    res = SectorBacktestService(seeded_session).run("junk", dates[0], dates[-1])
    assert res.benchmark_source == "sector_mean"
    assert abs(res.benchmark_return_pct) < 100


def test_the_price_panel_index_is_used_before_the_sector_mean(seeded_session, monkeypatch):
    """`macro_anchors` has no VNINDEX before 2026-04-09 (23.5). The price panel's
    ^VNINDEX is the same index; falling to the sector mean first was a choice."""
    import pandas as pd

    import services.backtest_service as bs
    dates = _seed(seeded_session)
    seeded_session.query(MacroAnchor).delete()
    seeded_session.commit()
    monkeypatch.setattr(bs, "_panel_vnindex", lambda: pd.Series(
        [1000.0 * 1.001 ** i for i in range(len(dates))], index=dates))
    res = SectorBacktestService(seeded_session).run("panel", dates[0], dates[-1])
    assert (res.benchmark_source, res.benchmark_origin) == ("vnindex", "price_panel")
    assert res.benchmark_return_pct == pytest.approx((1.001 ** (len(dates) - 1) - 1) * 100,
                                                     rel=1e-6)


# --------------------------------------------------------------------------
# The router — the part that was actually missing
# --------------------------------------------------------------------------

@pytest.fixture
def client(seeded_session):
    from api.main import app
    from database.connection import get_session_dependency
    app.dependency_overrides[get_session_dependency] = lambda: seeded_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_router_forwards_the_strategy(client, seeded_session):
    dates = _seed(seeded_session)
    r = client.post("/api/sectors/backtest", json={
        "name": "raw", "start_date": dates[0], "end_date": dates[-1],
        "strategy": "flow_raw",
    })
    assert r.status_code == 200
    assert r.json()["strategy_source"] == "flow_raw"


def test_router_forwards_cost_overrides(client, seeded_session):
    dates = _seed(seeded_session)
    r = client.post("/api/sectors/backtest", json={
        "name": "fees", "start_date": dates[0], "end_date": dates[-1],
        "fee_bps": 42, "sell_tax_bps": 7, "hold_sessions": 40,
    })
    body = r.json()
    assert (body["fee_bps"], body["sell_tax_bps"], body["hold_sessions"]) == (42, 7, 40)


def test_router_rejects_a_t_plus_hold(client, seeded_session):
    dates = _seed(seeded_session)
    r = client.post("/api/sectors/backtest", json={
        "name": "t3", "start_date": dates[0], "end_date": dates[-1],
        "hold_sessions": 3,
    })
    assert r.status_code == 422


def test_router_rejects_an_unknown_strategy(client, seeded_session):
    """Unvalidated, a typo fell through to flow_raw — the one nobody wants."""
    dates = _seed(seeded_session)
    r = client.post("/api/sectors/backtest", json={
        "name": "typo", "start_date": dates[0], "end_date": dates[-1],
        "strategy": "flowz",
    })
    assert r.status_code == 422


def test_router_default_is_still_signals(client, seeded_session):
    dates = _seed(seeded_session)
    _seed_signals(seeded_session, dates)
    r = client.post("/api/sectors/backtest", json={
        "name": "d", "start_date": dates[0], "end_date": dates[-1],
    })
    assert r.json()["strategy_source"] == "signals"


def test_trade_log_rows_have_the_shape_the_client_types(client, seeded_session):
    """The TS type claimed a `ret` field that has never existed."""
    dates = _seed(seeded_session)
    _seed_signals(seeded_session, dates)
    r = client.post("/api/sectors/backtest", json={
        "name": "log", "start_date": dates[0], "end_date": dates[-1],
    })
    log = r.json()["trade_log"]
    assert log, "expected trades"
    for t in log:
        assert set(t) >= {"date", "sector", "side", "cost"}
        assert t["side"] in ("BUY", "SELL")
        assert ("alloc" in t) == (t["side"] == "BUY")
        assert ("proceeds" in t) == (t["side"] == "SELL")
        assert "ret" not in t
