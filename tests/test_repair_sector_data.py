"""`scripts/repair_sector_data.py` -- the one-off that rewrites stored sector history.

It writes to Tom's live database, so it is held to more than "it ran": the
values it writes are checked against the LIVE aggregator
(`analysis.flow_aggregation.aggregate_sector`) on the same prices, the dry run
must leave the file byte-identical, the backup must be the database as it was,
and the guards must refuse the two cases that would do damage.
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
from config import PROXY_BASKETS
from database.models import Base, MacroAnchor, SectorFlowDaily
from scripts import repair_sector_data as rep
from scripts.build_price_panel import SCHEMA

BANK = PROXY_BASKETS["BANK"]
SESSIONS = pd.bdate_range("2026-06-01", periods=50)
STORED = [d.strftime("%Y-%m-%d") for d in SESSIONS[-30:]]
EVENING = datetime(2026, 9, 25, 19, 0)


def _prices(jump: bool = False) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(21)
    out = {}
    for i, sym in enumerate(BANK):
        c = 20 * (1 + i) * np.cumprod(1 + rng.normal(0.001, 0.02, len(SESSIONS)))
        if jump and sym == BANK[0]:
            c[40:] *= 1.40                    # a basis jump: +40% in a day
        df = pd.DataFrame({"open": c, "high": c * 1.02, "low": c * 0.98, "close": c,
                           "volume": 1e6}, index=SESSIONS)
        out[sym] = df
    return out


@pytest.fixture
def dbs(tmp_path):
    def make(jump=False, panel_sessions=len(SESSIONS)):
        db, panel = tmp_path / "live.db", tmp_path / "panel.db"
        eng = create_engine(f"sqlite:///{db}")
        Base.metadata.create_all(eng)
        s = sessionmaker(bind=eng)()
        for h, v in enumerate((1650.0, 1.82, 1.83, None, 6000.0)):
            s.add(MacroAnchor(time=datetime(2026, 9, 1, 9 + h), vnindex=v))
        for k, d in enumerate(STORED):
            s.add(SectorFlowDaily(
                sector_code="BANK", date=d, net_dollar_flow=1e9 * np.sin(k),
                foreign_net=1e8 * np.cos(k), breadth_sma20=0.6,
                atr_pct=0.004,                                  # the old 1/5 value
                close_idx=300.0 * (1.6 if k == 20 else 1.0),    # a raw-sum jump
                return_1d=None if k % 3 == 0 else 0.001))
        s.commit()
        s.close()
        eng.dispose()
        con = sqlite3.connect(panel)
        con.executescript(SCHEMA)
        px = _prices(jump)
        con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", [
            (sym, d.strftime("%Y-%m-%d"), r.open, r.high, r.low, r.close, r.volume)
            for sym, df in px.items() for d, r in df.iloc[:panel_sessions].iterrows()])
        con.commit()
        con.close()
        return db, panel, px
    return make


def _run(db, panel, *extra, now=EVENING, trading_day=True):
    return rep.main(["--db", str(db), "--panel", str(panel), *extra],
                    now=now, trading_day=trading_day)


def _rows(db):
    con = sqlite3.connect(db)
    df = pd.read_sql("SELECT date, atr_pct, return_1d, close_idx, flow_z20 FROM sector_flow_daily "
                     "WHERE sector_code='BANK' ORDER BY date", con).set_index("date")
    macro = [r[0] for r in con.execute("SELECT vnindex FROM macro_anchors ORDER BY rowid")]
    con.close()
    return df, macro


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------- safety

def test_the_dry_run_leaves_the_database_byte_identical(dbs):
    db, panel, _ = dbs()
    before = _sha(db)
    assert _run(db, panel) == 0
    assert _sha(db) == before
    assert not list(db.parent.glob("*.bak-*"))


def test_apply_refuses_while_the_jobs_write(dbs):
    db, panel, _ = dbs()
    before = _sha(db)
    assert _run(db, panel, "--apply", now=datetime(2026, 9, 25, 16, 10)) == 3
    assert _sha(db) == before
    # the same hour on a weekend is fine (negative control)
    assert _run(db, panel, "--apply", now=datetime(2026, 9, 26, 16, 10), trading_day=False) == 0


def test_apply_refuses_a_panel_that_ends_before_the_table(dbs):
    """Rows after the panel would keep the old ATR -- a 5x step in the series."""
    db, panel, _ = dbs(panel_sessions=45)
    before = _sha(db)
    assert _run(db, panel, "--apply") == 3
    assert _sha(db) == before


def test_the_backup_is_the_database_as_it_was(dbs):
    db, panel, _ = dbs()
    con = sqlite3.connect(db)
    snapshot = con.execute("SELECT * FROM sector_flow_daily ORDER BY id").fetchall()
    con.close()
    assert _run(db, panel, "--apply") == 0
    (bak,) = db.parent.glob("live.db.bak-*-pre-repair")
    con = sqlite3.connect(bak)
    assert con.execute("SELECT * FROM sector_flow_daily ORDER BY id").fetchall() == snapshot
    con.close()


def test_a_second_apply_changes_nothing(dbs):
    db, panel, _ = dbs()
    assert _run(db, panel, "--apply") == 0
    first, _ = _rows(db)
    assert _run(db, panel, "--apply") == 0
    second, _ = _rows(db)
    pd.testing.assert_frame_equal(first, second)


# ------------------------------------------------------------ what it writes

def test_values_match_the_live_aggregator(dbs):
    """ATR and return must be what `aggregate_sector` -- the code the 16:00 job
    runs -- computes from the same prices on that day."""
    db, panel, px = dbs()
    assert _run(db, panel, "--apply") == 0
    got, _ = _rows(db)
    for d in STORED:
        live = aggregate_sector("BANK", {s: df.loc[:d] for s, df in px.items()})
        assert got.loc[d, "atr_pct"] == pytest.approx(live.atr_pct, rel=1e-9), d
        assert got.loc[d, "return_1d"] == pytest.approx(live.basket_return, rel=1e-9, abs=1e-12), d


def test_close_idx_is_chained_from_the_returns(dbs):
    db, panel, _ = dbs()
    assert _run(db, panel, "--apply") == 0
    got, _ = _rows(db)
    assert got["close_idx"].iloc[0] == rep.BASE_LEVEL
    step = got["close_idx"] / got["close_idx"].shift(1) - 1
    np.testing.assert_allclose(step.iloc[1:], got["return_1d"].iloc[1:], rtol=1e-9)
    assert step.abs().max() < 0.16, "the raw-sum jump is gone"


def test_implausible_vnindex_values_are_nulled_and_nothing_else(dbs):
    db, panel, _ = dbs()
    assert _run(db, panel, "--apply") == 0
    _, macro = _rows(db)
    assert macro == [1650.0, None, None, None, None]


def test_a_basis_jump_is_left_out_of_the_return_and_the_atr(dbs):
    db, panel, px = dbs(jump=True)
    assert _run(db, panel, "--apply") == 0
    got, _ = _rows(db)
    day = SESSIONS[40].strftime("%Y-%m-%d")
    others = {s: df.loc[:day] for s, df in px.items() if s != BANK[0]}
    assert got.loc[day, "return_1d"] == pytest.approx(
        aggregate_sector("BANK", others).basket_return, rel=1e-9)
    later = SESSIONS[45].strftime("%Y-%m-%d")                 # jump inside the ATR window
    assert got.loc[later, "atr_pct"] == pytest.approx(
        aggregate_sector("BANK", {s: df.loc[:later] for s, df in px.items() if s != BANK[0]}).atr_pct,
        rel=1e-9)


def test_the_leading_features_are_rebuilt(dbs):
    db, panel, _ = dbs()
    assert _run(db, panel, "--apply") == 0
    got, _ = _rows(db)
    assert got["flow_z20"].iloc[-1] is not None and not np.isnan(got["flow_z20"].iloc[-1])


def test_a_session_missing_from_the_table_still_moves_the_level(dbs):
    """The chain runs on the panel's calendar: drop a stored row and the next
    level must still include that session's return."""
    db, panel, px = dbs()
    gone = STORED[10]
    con = sqlite3.connect(db)
    con.execute("DELETE FROM sector_flow_daily WHERE date = ?", (gone,))
    con.commit()
    con.close()
    assert _run(db, panel, "--apply") == 0
    got, _ = _rows(db)
    prev, nxt = STORED[9], STORED[11]
    r_gone = aggregate_sector("BANK", {s: df.loc[:gone] for s, df in px.items()}).basket_return
    r_next = got.loc[nxt, "return_1d"]
    assert got.loc[nxt, "close_idx"] == pytest.approx(
        got.loc[prev, "close_idx"] * (1 + r_gone) * (1 + r_next), rel=1e-9)
