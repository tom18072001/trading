"""`scripts/build_price_panel.py` must not mix two price-adjustment bases.

Review 2026-09-24 §6: `seed_from_legacy()` ran on EVERY build with INSERT OR
IGNORE. On any date the live source had no row for (a session without a match
on an illiquid name), the legacy row — adjusted on a different basis — came
back and stayed: 145 rows in 8 symbols, SRC alternating 19.20 <-> 25.15. The
research numbers survived only because all 8 sit under the liquidity floor.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.build_price_panel import (
    SCHEMA, band_violations, fetched_symbols, seed_from_legacy, store_fetch,
)


@pytest.fixture
def panel(tmp_path):
    con = sqlite3.connect(tmp_path / "panel.db")
    con.executescript(SCHEMA)
    src = tmp_path / "legacy.db"
    s = sqlite3.connect(src)
    s.execute("CREATE TABLE _legacy_stock_prices (symbol TEXT, time TEXT, open REAL, "
              "high REAL, low REAL, close REAL, volume REAL)")
    # Legacy SRC is on the OLD basis (25.15); AAA has never been fetched.
    s.executemany("INSERT INTO _legacy_stock_prices VALUES (?,?,?,?,?,?,?)", [
        ("SRC", "2026-03-02", 25.0, 25.3, 24.9, 25.15, 100),
        ("SRC", "2026-03-03", 25.1, 25.2, 25.0, 25.15, 100),
        ("SRC", "2026-03-04", 25.1, 25.2, 25.0, 25.15, 100),
        ("AAA", "2026-03-02", 10.0, 10.1, 9.9, 10.0, 100),
    ])
    s.commit()
    s.close()
    yield con, src
    con.close()


def _closes(con, sym):
    return dict(con.execute("SELECT time, close FROM prices WHERE symbol=? ORDER BY time",
                            (sym,)).fetchall())


def test_a_fetch_replaces_every_row_in_its_span(panel):
    """The source returned 03-02 and 03-04 on the NEW basis and nothing for
    03-03 (no match that day). The legacy 03-03 row must not survive."""
    con, src = panel
    seed_from_legacy(con, src)
    store_fetch(con, "SRC", [("SRC", "2026-03-02", 19.1, 19.3, 19.0, 19.20, 5),
                             ("SRC", "2026-03-04", 19.2, 19.3, 19.1, 19.25, 5)],
                "2026-03-01", "2026-03-31")
    con.execute("INSERT INTO fetch_log VALUES ('SRC','2026-09-25',2,'ok')")
    assert _closes(con, "SRC") == {"2026-03-02": 19.20, "2026-03-04": 19.25}


def test_legacy_is_not_reseeded_over_a_fetched_symbol(panel):
    """The second half of the defect: the NEXT build seeded legacy again, and
    INSERT OR IGNORE filled exactly the dates the source had left empty."""
    con, src = panel
    store_fetch(con, "SRC", [("SRC", "2026-03-02", 19.1, 19.3, 19.0, 19.20, 5)],
                "2026-03-01", "2026-03-31")
    con.execute("INSERT INTO fetch_log VALUES ('SRC','2026-09-25',1,'ok')")
    assert fetched_symbols(con) == {"SRC"}
    seed_from_legacy(con, src)
    assert _closes(con, "SRC") == {"2026-03-02": 19.20}
    # A symbol the source has never delivered still gets the free history.
    assert _closes(con, "AAA") == {"2026-03-02": 10.0}


def test_a_basis_jump_is_flagged_and_the_index_is_not(panel):
    con, _ = panel
    con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", [
        ("SRC", "2026-03-02", 19.1, 19.3, 19.0, 19.20, 5),
        ("SRC", "2026-03-03", 25.1, 25.2, 25.0, 25.15, 5),   # +31%: two bases
        ("GAS", "2026-03-02", 60.0, 61.0, 59.0, 60.0, 5),
        ("GAS", "2026-03-03", 63.0, 64.0, 62.0, 64.2, 5),    # +7%: a normal ceiling day
        ("^VNINDEX", "2026-03-02", 1, 1, 1, 1600.0, 0),
        ("^VNINDEX", "2026-03-03", 1, 1, 1, 1900.0, 0),     # not a stock
    ])
    bad = band_violations(con)
    assert [(s, t) for s, t, _ in bad] == [("SRC", "2026-03-03")]


def test_the_index_is_kept_current_with_the_stocks(panel, monkeypatch):
    """2026-09-28: ^VNINDEX was loaded once and stopped at 09-15 while the
    stocks moved on -- every benchmark after that compared against nothing.
    Each build now refetches it over its span, delete-then-insert."""
    import pandas as pd

    from scripts import build_price_panel as bpp

    con, _ = panel
    con.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?)", [
        ("^VNINDEX", "2016-12-30", 1, 1, 1, 664.87, 0),          # outside the span: kept
        ("^VNINDEX", "2026-09-15", 1, 1, 1, 9999.0, 0),          # inside, stale: replaced
    ])
    asked = []

    def fetch(sym, start, end):
        asked.append((sym, start, end))
        return pd.DataFrame({"time": ["2026-09-15", "2026-09-28"], "open": [1805.0, 1779.0],
                             "high": [1812.0, 1785.0], "low": [1800.0, 1770.0],
                             "close": [1811.15, 1780.68], "volume": [5e8, 6e8]})

    monkeypatch.setattr(bpp, "fetch_symbol", fetch)
    assert bpp.fetch_index(con, "2017-01-01", "2026-09-28") == 2
    assert asked == [("VNINDEX", "2017-01-01", "2026-09-28")]
    assert _closes(con, "^VNINDEX") == {"2016-12-30": 664.87, "2026-09-15": 1811.15,
                                        "2026-09-28": 1780.68}
