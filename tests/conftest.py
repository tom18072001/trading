# ============================================
# tests/conftest.py — Sector Money-Flow fixtures
# ============================================

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, event

import models.rotation_ranker as _rr
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import (
    Base, Sector, SectorConstituent, SectorFlowDaily, MacroAnchor,
)
from config import PROXY_BASKETS, SECTORS


@pytest.fixture(scope="session", autouse=True)
def _models_go_to_a_tmpdir(tmp_path_factory):
    """Keep `fit()` away from the live model directory.

    `RotationRanker.fit()` writes `rotation_ranker.pkl` + `.json` to
    `config.SAVED_MODELS_DIR` unconditionally — there is no opt-out, and six
    tests call it with 2-3 synthetic features. So **running pytest replaced the
    production ranker with a test artefact**, and the next `main.py --publish`
    died with "number of features in data (19) is not the same as it was in
    training data (3)". Found 2026-08-24; `models/saved/` is gitignored, so git
    could not show the damage and nothing failed until the job ran.

    Autouse and session-scoped on purpose: an opt-in fixture only protects the
    tests that remember to ask, and the ones that forget are exactly the
    dangerous ones. Repointing the module global covers every present and
    future caller.

    `ponytail:` the real fix is `fit(save_to=...)` so production names the path
    explicitly. That is a signature change with call sites in
    `rotation_model_service`; this stops the bleeding without touching them.
    """
    _rr.SAVED_MODELS_DIR = str(tmp_path_factory.mktemp("saved_models"))
    yield


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        "sqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _pragma(dbapi, _):
        c = dbapi.cursor()
        c.execute("PRAGMA foreign_keys=ON")
        c.close()

    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    s = Session()
    yield s
    s.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def seeded_session(session):
    """Insert all 15 sectors + their proxy constituents."""
    for code, name in SECTORS.items():
        session.add(Sector(sector_code=code, name=name))
    session.flush()
    for code, syms in PROXY_BASKETS.items():
        for sym in syms:
            session.add(SectorConstituent(
                sector_code=code, symbol=sym, weight=1.0 / len(syms),
            ))
    session.flush()
    return session


@pytest.fixture
def synthetic_constituent_df():
    """A 100-bar synthetic OHLCV DataFrame."""
    base = datetime(2025, 1, 1)
    rows = []
    price = 100.0
    for i in range(100):
        price += np.sin(i / 5) * 0.5
        rows.append({
            "open": price - 0.3, "high": price + 0.5,
            "low": price - 0.5, "close": price,
            "volume": 1_000_000 + i * 1000,
        })
    df = pd.DataFrame(rows, index=pd.date_range(base, periods=100, freq="D"))
    return df


@pytest.fixture
def daily_panel(seeded_session):
    """Insert 30 days of synthetic sector_flow_daily for 3 sectors."""
    base = datetime(2025, 1, 1)
    sectors = ["BANK", "TECH", "OIL"]
    for code in sectors:
        idx = 100.0
        for i in range(30):
            dt = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            ret = (i % 5 - 2) / 100
            idx *= 1 + ret
            seeded_session.add(SectorFlowDaily(
                sector_code=code, date=dt, close_idx=idx,
                return_1d=ret, net_dollar_flow=1e6 * (i % 7 - 3),
                foreign_net=5e5 * (i % 4 - 2),
                up_down_vol_ratio=1.0 + (i % 3) * 0.1,
                breadth_sma20=0.6, breadth_sma50=0.55,
                rs_vnindex_5d=0.01, rs_vnindex_20d=0.02,
                atr_pct=0.015,
            ))
    seeded_session.flush()
    return seeded_session


@pytest.fixture
def macro_session(seeded_session):
    base = datetime(2025, 1, 1)
    price = 1200.0
    for i in range(60):
        seeded_session.add(MacroAnchor(
            time=base + timedelta(days=i),
            vnindex=price + i * 0.5,
            usdvnd=24000 + i,
            brent=80.0 + i * 0.1,
            us10y=4.2,
            gold=2300.0 + i * 0.2,
        ))
    seeded_session.flush()
    return seeded_session
