"""Rebuilding a session the scheduled jobs missed (2026-09-25: power cut at 11:53).

The intraday job had left a bar per sector holding the MORNING only; the 16:00
rollup never ran. `ingest_intraday_now(as_of=...)` must rebuild that session
from full-day data -- nothing after it, that day's foreign flow -- over the
partial bar, and `scripts/fill_missing_session.py` must do it only on a past
session, outside job hours, after a backup, and not at all without --apply.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.flow_aggregation import aggregate_sector
from config import PROXY_BASKETS, SECTORS
from database.models import Base, SectorFlowDaily, SectorFlowTS
from scripts import fill_missing_session as fill
from services.sector_ingest_service import SectorIngestService

DAY = "2026-09-25"
SESSIONS = pd.bdate_range("2026-05-04", "2026-09-30")     # runs PAST the day on purpose
EVENING = datetime(2026, 9, 28, 21, 30)


def _bars(sym: str) -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(sym)) % 2**32)
    c = 20 * np.cumprod(1 + rng.normal(0.0005, 0.015, len(SESSIONS)))
    idx = SESSIONS + pd.Timedelta(hours=7)                 # how the live bars are stamped
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                         "volume": 1e6}, index=idx)


BARS = {s: _bars(s) for syms in PROXY_BASKETS.values() for s in syms}
NET = {s: 1e8 * (i % 3 - 1) for i, s in enumerate(sorted(BARS))}      # that day's net flow


@pytest.fixture
def fetchers(monkeypatch):
    calls = []

    def daily(self, symbol, start, end):
        calls.append((symbol, start, end))
        return BARS[symbol].copy()                         # includes bars AFTER `end`

    def history(symbol, start, end):
        rows = [{"date": d, "buy_val": 3e8, "sell_val": 3e8 - NET[symbol], "net_val": NET[symbol]}
                for d in ("2026-09-24", DAY, "2026-09-28") if start <= d <= end]
        return pd.DataFrame(rows, columns=["date", "buy_val", "sell_val", "net_val"])

    monkeypatch.setattr(SectorIngestService, "_fetch_constituent_daily", daily)
    monkeypatch.setattr("services.foreign_flow.fetch_history", history)
    monkeypatch.setattr(SectorIngestService, "_fetch_foreign",
                        lambda self, s: pytest.fail("the live foreign path was used"))
    return calls


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "live.db"
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    for code in SECTORS:
        s.add(SectorFlowDaily(sector_code=code, date="2026-09-24", close_idx=250.0))
        # the morning bar the 11:45 run left behind
        s.add(SectorFlowTS(sector_code=code, time=datetime(2026, 9, 25, 7), net_dollar_flow=1.0,
                           close_idx=1.0, basket_return=0.5, atr_pct=9.9))
        # and the next session, already rolled up -- as on the live table, the
        # latest bar is NOT the day being filled
        s.add(SectorFlowTS(sector_code=code, time=datetime(2026, 9, 28, 7), net_dollar_flow=2.0,
                           close_idx=2.0, basket_return=0.01, atr_pct=0.02))
        s.add(SectorFlowDaily(sector_code=code, date="2026-09-28", close_idx=252.5))
    s.commit()
    s.close()
    eng.dispose()
    return path


def _session(path):
    return sessionmaker(bind=create_engine(f"sqlite:///{path}"))()


def test_as_of_rebuilds_that_session_from_full_day_data(db, fetchers):
    s = _session(db)
    n = SectorIngestService(s).ingest_intraday_now(sector_codes=["BANK"], as_of=DAY)
    assert n == 1
    assert {(st, en) for _, st, en in fetchers} == {("2026-05-28", DAY)}

    row = s.query(SectorFlowTS).filter_by(sector_code="BANK", time=datetime(2026, 9, 25, 7)).one()
    assert s.query(SectorFlowTS).filter_by(sector_code="BANK").count() == 2   # upserted, not added
    cut = {sym: BARS[sym].loc[:DAY] for sym in PROXY_BASKETS["BANK"]}
    want = aggregate_sector("BANK", cut, foreign_net_by_symbol={k: NET[k] for k in cut})
    assert row.time == datetime(2026, 9, 25, 7)
    assert row.basket_return == pytest.approx(want.basket_return)
    assert row.atr_pct == pytest.approx(want.atr_pct)
    assert row.net_dollar_flow == pytest.approx(want.net_dollar_flow)
    assert row.foreign_net == pytest.approx(sum(NET[k] for k in cut))
    s.close()


def _without_day(syms):
    """Constituent fetch where `syms` have no bar on DAY (suspended / lagging)."""
    def daily(self, symbol, start, end):
        df = BARS[symbol].copy()
        return df[df.index.strftime("%Y-%m-%d") != DAY] if symbol in syms else df
    return daily


def test_as_of_leaves_out_a_name_without_a_bar_that_day(db, fetchers, monkeypatch):
    gone = PROXY_BASKETS["BANK"][0]
    monkeypatch.setattr(SectorIngestService, "_fetch_constituent_daily", _without_day({gone}))
    s = _session(db)
    assert SectorIngestService(s).ingest_intraday_now(sector_codes=["BANK"], as_of=DAY) == 1
    row = s.query(SectorFlowTS).filter_by(sector_code="BANK", time=datetime(2026, 9, 25, 7)).one()
    cut = {sym: BARS[sym].loc[:DAY] for sym in PROXY_BASKETS["BANK"] if sym != gone}
    want = aggregate_sector("BANK", cut, foreign_net_by_symbol={k: NET[k] for k in cut})
    assert row.basket_return == pytest.approx(want.basket_return)
    assert row.foreign_net == pytest.approx(sum(NET[k] for k in cut))
    s.close()


def test_a_foreign_flow_timeout_is_asked_again(db, fetchers, monkeypatch):
    """The first 2026-09-25 fill filed HCM's foreign flow as 0 after ONE read
    timeout -- fetch_history answers a timeout with an empty frame."""
    from services import foreign_flow
    flaky = next(s for s in PROXY_BASKETS["BANK"] if NET[s] != 0)
    inner, misses = foreign_flow.fetch_history, []

    def history(symbol, start, end):
        if symbol == flaky and not misses:
            misses.append(symbol)
            return pd.DataFrame(columns=["date", "buy_val", "sell_val", "net_val"])
        return inner(symbol, start, end)

    monkeypatch.setattr("services.foreign_flow.fetch_history", history)
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = _session(db)
    SectorIngestService(s).ingest_intraday_now(sector_codes=["BANK"], as_of=DAY)
    row = s.query(SectorFlowTS).filter_by(sector_code="BANK", time=datetime(2026, 9, 25, 7)).one()
    assert misses == [flaky]
    assert row.foreign_net == pytest.approx(sum(NET[k] for k in PROXY_BASKETS["BANK"]))
    s.close()


def test_a_sector_with_no_bar_that_day_stops_before_the_rollup(db, fetchers, monkeypatch):
    """No FISH name has the day: FISH keeps its morning bar and NOTHING is rolled
    up -- rolling FISH up would file that morning bar as the day."""
    monkeypatch.setattr(SectorIngestService, "_fetch_constituent_daily",
                        _without_day(set(PROXY_BASKETS["FISH"])))
    assert fill.main(["--date", DAY, "--db", str(db), "--apply"], now=EVENING,
                     is_trading=lambda d: d.weekday() < 5) == 4
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM sector_flow_daily WHERE date = ?", (DAY,)).fetchone()[0] == 0
    ts = dict(con.execute("SELECT sector_code, basket_return FROM sector_flow_ts "
                          "WHERE time >= ? AND time < '2026-09-26'", (DAY,)).fetchall())
    con.close()
    assert ts["FISH"] == 0.5, "the morning bar is all FISH has"
    assert sum(r != 0.5 for r in ts.values()) == len(SECTORS) - 1, "the rest were rebuilt"
    assert len(list(db.parent.glob("live.db.bak-*-pre-fill"))) == 1


@pytest.mark.parametrize("lacking", ["prices", "foreign"])
def test_apply_refuses_when_a_source_lacks_the_day(db, fetchers, monkeypatch, lacking):
    if lacking == "prices":
        monkeypatch.setattr(SectorIngestService, "_fetch_constituent_daily",
                            _without_day({fill.PROBE}))
    else:
        monkeypatch.setattr("services.foreign_flow.fetch_history",
                            lambda sym, st, en: pd.DataFrame(
                                columns=["date", "buy_val", "sell_val", "net_val"]))
    before = _sha(db)
    assert fill.main(["--date", DAY, "--db", str(db), "--apply"], now=EVENING,
                     is_trading=lambda d: d.weekday() < 5) == 3
    assert _sha(db) == before
    assert not list(db.parent.glob("*.bak-*"))


def test_without_as_of_the_live_path_is_unchanged(db, monkeypatch):
    """Negative control: no `as_of`, the fetch ends today and the live foreign
    path is asked, exactly as before."""
    seen = {}

    def daily(self, symbol, start, end):
        seen["end"] = end
        return pd.DataFrame()

    monkeypatch.setattr(SectorIngestService, "_fetch_constituent_daily", daily)
    monkeypatch.setattr("services.sector_ingest_service.today_str", lambda: "2026-09-28")
    s = _session(db)
    assert SectorIngestService(s).ingest_intraday_now(sector_codes=["BANK"]) == 0
    assert seen["end"] == "2026-09-28"
    s.close()


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_the_dry_run_fetches_and_writes_nothing(db, fetchers):
    before = _sha(db)
    assert fill.main(["--date", DAY, "--db", str(db)], now=EVENING,
                     is_trading=lambda d: d.weekday() < 5) == 0
    assert _sha(db) == before and fetchers == []
    assert not list(db.parent.glob("*.bak-*"))


@pytest.mark.parametrize("day,now", [
    ("2026-09-26", EVENING),                          # a Saturday: no session
    ("2026-09-28", EVENING),                          # today: the jobs' job
    (DAY, datetime(2026, 9, 28, 16, 5)),              # during the jobs
])
def test_apply_refuses(db, fetchers, day, now):
    before = _sha(db)
    assert fill.main(["--date", day, "--db", str(db), "--apply"], now=now,
                     is_trading=lambda d: d.weekday() < 5) == 3
    assert _sha(db) == before and fetchers == []


def test_apply_fills_the_day_and_chains_from_the_session_before(db, fetchers):
    assert fill.main(["--date", DAY, "--db", str(db), "--apply"], now=EVENING,
                     is_trading=lambda d: d.weekday() < 5) == 0
    assert len(list(db.parent.glob("live.db.bak-*-pre-fill"))) == 1
    con = sqlite3.connect(db)
    rows = dict(con.execute("SELECT sector_code, close_idx FROM sector_flow_daily WHERE date = ?",
                            (DAY,)).fetchall())
    ret = dict(con.execute("SELECT sector_code, return_1d FROM sector_flow_daily WHERE date = ?",
                           (DAY,)).fetchall())
    feats = con.execute("SELECT COUNT(*) FROM sector_flow_daily WHERE date = ? AND flow_z20 IS NULL "
                        "AND foreign_hit_20d IS NULL", (DAY,)).fetchone()[0]
    con.close()
    assert set(rows) == set(SECTORS)
    for code, level in rows.items():
        assert level == pytest.approx(250.0 * (1 + ret[code])), code
        assert ret[code] != 0.5, "the morning bar's return was kept"
    assert feats == 0, "leading features were not rebuilt"
