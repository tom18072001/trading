"""Sector layer, review 2026-09-24 §4.1 / §8 P0 -- what the scheduled jobs publish.

Each test names the finding it pins. The shortlist does not depend on any of
this; the email's sector table, Daily Insight's regime gauge, the risk
sentinel and the backtest do.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import utils.clock as clock
from database.models import MacroAnchor, ModelRun, SectorFlowDaily, SectorRegime, SectorSignal
from utils.clock import closed_today as _real_closed_today

SATURDAY = date(2026, 9, 26)


def _open_calendar_on(monkeypatch, d: date):
    """Undo conftest's pin and put the clock on `d`."""
    monkeypatch.setattr(clock, "closed_today", _real_closed_today)
    monkeypatch.setattr(clock, "today", lambda: d)


# ------------------------------------------------ §4.1/1: ranker scored zeros

def _latest_leading(session, col="flow_z20"):
    last = max(r.date for r in session.query(SectorFlowDaily).all())
    return [getattr(r, col) for r in session.query(SectorFlowDaily).filter_by(date=last)]


def test_predict_refuses_a_session_whose_leading_features_were_never_computed(daily_panel):
    """flow_z20..accumulation_age were NULL on all 15 sectors from 2026-08-25
    and `fillna(0)` turned "not computed" into "exactly average"."""
    from services.rotation_model_service import FeaturesMissingError, RotationModelService

    assert all(v is None for v in _latest_leading(daily_panel))
    with pytest.raises(FeaturesMissingError, match="flow_z20"):
        RotationModelService(daily_panel).predict_today()


def test_the_scheduled_rollup_computes_the_leading_features(daily_panel, monkeypatch):
    """The defect was the wiring: only the UI Refresh path ran the rebuild.
    This drives `main.cmd_eod_rollup` itself, with the rollup stubbed out."""
    import main
    from services.rotation_model_service import RotationModelService

    @contextmanager
    def _session():
        yield daily_panel

    class _NoRollup:
        def __init__(self, _s):
            pass

        def rollup_to_daily(self):
            return 0

    monkeypatch.setattr(main, "get_session", _session)
    monkeypatch.setattr(main, "SectorIngestService", _NoRollup)
    main.cmd_eod_rollup()

    assert all(v is not None for v in _latest_leading(daily_panel))
    assert not RotationModelService(daily_panel).predict_today().empty


def test_the_predict_job_exits_non_zero_instead_of_ranking_zeros(daily_panel, monkeypatch):
    import main

    @contextmanager
    def _session():
        yield daily_panel

    monkeypatch.setattr(main, "get_session", _session)
    with pytest.raises(SystemExit) as e:
        main.cmd_rotation_predict()
    assert e.value.code == 2


# ---------------------------------------- §4.1/8: persistence had no direction

def _flows(session, code, flows, start="2026-09-01"):
    d = date.fromisoformat(start)
    for f in flows:
        session.add(SectorFlowDaily(sector_code=code, date=d.isoformat(), net_dollar_flow=f))
        d += timedelta(days=1)
    session.flush()


def test_a_buy_needs_inflow_persistence_not_any_persistence(seeded_session):
    """24 of the 96 BUYs published had followed 3 sessions of net OUTflow."""
    from services.sector_signal_service import SectorSignalService

    _flows(seeded_session, "BANK", [-1e9, -2e9, -3e9])
    _flows(seeded_session, "TECH", [1e9, 2e9, 3e9])
    _flows(seeded_session, "OIL", [1e9, -2e9, 3e9])
    svc = SectorSignalService(seeded_session)
    assert (svc._persistence_ok("BANK", +1), svc._persistence_ok("BANK", -1)) == (False, True)
    assert (svc._persistence_ok("TECH", +1), svc._persistence_ok("TECH", -1)) == (True, False)
    assert (svc._persistence_ok("OIL", +1), svc._persistence_ok("OIL", -1)) == (False, False)


# ----------------------------------------------- §4.1/10: untraceable signals

def test_published_signals_carry_the_model_that_ranked_them(daily_panel, monkeypatch):
    """929 of 929 published signals had model_run_id NULL."""
    from services import rotation_model_service as rms_mod
    from services.sector_signal_service import SectorSignalService

    run = ModelRun(model_name="rotation_ranker", target_col="fwd_20d_sector_return",
                   is_active=True, status="completed")
    daily_panel.add(run)
    daily_panel.flush()

    def _load(self):
        self.active_run_id = run.id

    ranked = pd.DataFrame({"sector_code": ["BANK", "TECH", "OIL"],
                           "rank": [1, 2, 3], "score": [0.3, 0.2, 0.1]})
    monkeypatch.setattr(rms_mod.RotationModelService, "_load_active_model", _load)
    monkeypatch.setattr(rms_mod.RotationModelService, "predict_today", lambda self: ranked)

    out = SectorSignalService(daily_panel).publish()
    assert len(out) == 3
    rows = daily_panel.query(SectorSignal).filter_by(date=clock.today_str()).all()
    assert {r.model_run_id for r in rows} == {run.id}


# ------------------------------------- §4.1/11: weekend and holiday publishing

def test_signals_are_not_published_on_a_non_session(daily_panel, monkeypatch):
    """14 of 62 signal dates were weekends or holidays: the -Daily trigger runs
    the job, and each run re-stamped the last session's features. The ranking
    is stubbed so the calendar is the only thing that can stop the publish."""
    from services import rotation_model_service as rms_mod
    from services.sector_signal_service import SectorSignalService

    ranked = pd.DataFrame({"sector_code": ["BANK", "TECH", "OIL"],
                           "rank": [1, 2, 3], "score": [0.3, 0.2, 0.1]})
    monkeypatch.setattr(rms_mod.RotationModelService, "predict_today", lambda self: ranked)
    _open_calendar_on(monkeypatch, SATURDAY)
    before = daily_panel.query(SectorSignal).count()
    assert SectorSignalService(daily_panel).publish().empty
    assert daily_panel.query(SectorSignal).count() == before


def test_a_session_day_is_not_refused(monkeypatch):
    """Negative control for the test above: the real calendar, on a Friday."""
    _open_calendar_on(monkeypatch, date(2026, 9, 25))
    assert clock.closed_today() is None
    _open_calendar_on(monkeypatch, SATURDAY)
    assert clock.closed_today() == "2026-09-26"


# ------------------------------------------------------- §4.1/4: the regime

def _daily_vnindex(n=320, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-06-02", periods=n)
    px = 1300 * np.cumprod(1 + rng.normal(0.0004, 0.011, n))
    return pd.Series(px, index=idx, name="vnindex")


def test_the_regime_is_never_fitted_on_the_hourly_table(macro_session, monkeypatch):
    """2026-09-22's `risk_off 0.9961` was fitted on macro_anchors rows of 1.82
    after the daily fetch failed. No daily series -> no new label; the last
    stored one comes back under its own date."""
    from services import rotation_model_service as rms_mod

    macro_session.add(SectorRegime(date="2026-09-18", regime_label="rotation",
                                   confidence=0.6, model_version="hmm"))
    macro_session.flush()
    monkeypatch.setattr(rms_mod, "fetch_vnindex_daily", lambda days=180: pd.Series(dtype=float))

    rec = rms_mod.RotationModelService(macro_session).classify_regime()
    assert (rec.date, rec.regime_label) == ("2026-09-18", "rotation")
    assert macro_session.query(SectorRegime).count() == 1, "nothing new was written"


def test_with_nothing_stored_the_refusal_writes_nothing(macro_session, monkeypatch):
    from services import rotation_model_service as rms_mod

    monkeypatch.setattr(rms_mod, "fetch_vnindex_daily", lambda days=180: pd.Series(dtype=float))
    rec = rms_mod.RotationModelService(macro_session).classify_regime()
    assert rec.date is None and rec.model_version == "unavailable"
    assert macro_session.query(SectorRegime).count() == 0


def test_the_regime_is_published_from_a_daily_series(seeded_session, monkeypatch):
    from services import rotation_model_service as rms_mod

    monkeypatch.setattr(rms_mod, "fetch_vnindex_daily", lambda days=180: _daily_vnindex())
    rec = rms_mod.RotationModelService(seeded_session).classify_regime()
    assert rec.date == clock.today_str()
    assert rec.regime_label in {"risk_on", "risk_off", "rotation", "chop"}
    assert rec.model_version in {"hmm", "heuristic"}
    assert seeded_session.query(SectorRegime).filter_by(date=rec.date).count() == 1


def test_the_regime_is_not_published_on_a_non_session(seeded_session, monkeypatch):
    from services import rotation_model_service as rms_mod

    _open_calendar_on(monkeypatch, SATURDAY)
    monkeypatch.setattr(rms_mod, "fetch_vnindex_daily", lambda days=180: _daily_vnindex())
    rms_mod.RotationModelService(seeded_session).classify_regime()
    assert seeded_session.query(SectorRegime).count() == 0


def test_fetch_vnindex_daily_drops_implausible_bars_one_by_one(monkeypatch):
    """A median check passes a series that is mostly right."""
    import utils.vn_api as vn_api
    from services.macro_service import fetch_vnindex_daily

    frame = pd.DataFrame({"time": pd.bdate_range("2026-09-01", periods=6),
                          "close": [1650.0, 1.82, 1662.0, 1.79, 1671.0, 1680.0]})
    monkeypatch.setattr(vn_api, "quote_history", lambda *a, **k: frame)
    s = fetch_vnindex_daily(days=30)
    assert list(s) == [1650.0, 1662.0, 1671.0, 1680.0]


def test_a_source_of_pure_garbage_falls_through_to_the_next(monkeypatch):
    import utils.vn_api as vn_api
    from services.macro_service import fetch_vnindex_daily

    good = pd.DataFrame({"time": pd.bdate_range("2026-09-01", periods=3),
                         "close": [1650.0, 1662.0, 1671.0]})
    bad = good.assign(close=[1.8, 1.81, 1.79])
    monkeypatch.setattr(vn_api, "quote_history",
                        lambda *a, source=None, **k: bad if source == "VCI" else good)
    assert list(fetch_vnindex_daily(days=30)) == [1650.0, 1662.0, 1671.0]


@pytest.mark.parametrize("previous,carried", [(1.82, None), (1650.0, 1650.0)])
def test_ingest_carries_forward_only_a_plausible_vnindex(seeded_session, monkeypatch,
                                                         previous, carried):
    """The one bad read of 2026-04-16 was copied into 613 rows by carry-forward.
    A plausible last value is still carried (the negative control)."""
    from services.macro_service import MacroService

    seeded_session.add(MacroAnchor(time=datetime(2026, 4, 16, 9), vnindex=previous))
    seeded_session.flush()
    monkeypatch.setattr(MacroService, "_fetch_vnindex", lambda self: None)
    monkeypatch.setattr(MacroService, "_fetch_yahoo", lambda self, t: None)
    monkeypatch.setattr(MacroService, "_fetch_fred", lambda self, t: None)
    assert MacroService(seeded_session).ingest_now().vnindex == carried


# ------------------------------------------- the ranker's macro and volume inputs

def test_macro_vn_ret_5d_is_five_sessions_of_plausible_closes(daily_panel):
    """It was pct_change(5) over HOURLY rows -- a 5-hour return -- and the
    1.82 rows made it read -99.9% / +87,000% at their edges."""
    from services.flow_feature_service import FlowFeatureService

    base = datetime(2025, 1, 1, 9)
    for day in range(12):
        level = 1200.0 + 10 * day
        for hour in range(3):                               # three snapshots a day
            daily_panel.add(MacroAnchor(time=base + timedelta(days=day, hours=hour),
                                        vnindex=level))
        if day == 7:                                        # one garbage snapshot, last of the day
            daily_panel.add(MacroAnchor(time=base + timedelta(days=day, hours=5), vnindex=1.82))
    daily_panel.flush()

    df = FlowFeatureService(daily_panel).build(with_target=False)
    got = df[df.sector_code == "BANK"].set_index("date")["macro_vn_ret_5d"]
    assert got["2025-01-06"] == pytest.approx(1250.0 / 1200.0 - 1)
    assert got["2025-01-08"] == pytest.approx(1270.0 / 1220.0 - 1), "the 1.82 bar is ignored"
    assert got["2025-01-12"] == pytest.approx(1310.0 / 1260.0 - 1)
    assert np.isnan(got["2025-01-13"]), "no macro row that day: missing, not invented"


def test_an_all_up_day_ranks_above_every_finite_ratio_in_training_and_prediction(daily_panel):
    """NULL = down volume 0. Training dropped those rows; prediction filled 0 --
    "all down" -- for the same reading."""
    from services.flow_feature_service import UPDOWN_RATIO_CAP, FlowFeatureService

    row = daily_panel.query(SectorFlowDaily).filter_by(sector_code="BANK", date="2025-01-05").one()
    row.up_down_vol_ratio = None
    big = daily_panel.query(SectorFlowDaily).filter_by(sector_code="TECH", date="2025-01-05").one()
    big.up_down_vol_ratio = 50_000.0
    daily_panel.flush()

    svc = FlowFeatureService(daily_panel)
    for frame in (svc.build(with_target=True), svc.build(with_target=False)):
        v = frame.set_index(["sector_code", "date"])["up_down_vol_ratio"]
        assert v[("BANK", "2025-01-05")] == UPDOWN_RATIO_CAP
        assert v[("TECH", "2025-01-05")] == UPDOWN_RATIO_CAP
        assert v.max() == UPDOWN_RATIO_CAP and v.notna().all()
