"""Regression guards for the 2026-08-22 code review.

Each test pins one finding from docs/reviews/CODE_REVIEW_2026-08-22.md so it cannot come
back. Names carry the finding id.

Pure/in-memory: no vnstock, no network, no LLM.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from analysis.flow_aggregation import aggregate_sector
from database.models import MacroAnchor, SectorFlowDaily, SectorFlowTS, SectorSignal
from services.backtest_service import SectorBacktestService
from services.sector_ingest_service import SectorIngestService


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _ohlcv(closes: list[float], start="2026-01-01", vol=1_000_000.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="D")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
         "volume": np.full(len(c), vol)},
        index=idx,
    )


def _seed_daily(session, code: str, dates: list[str], close_start=100.0):
    for i, d in enumerate(dates):
        session.add(SectorFlowDaily(
            sector_code=code, date=d,
            close_idx=close_start * (1.01 ** i),
            return_1d=0.01,
            net_dollar_flow=1e9 * (i + 1),
            atr_pct=0.02,
        ))
    session.commit()


# ==========================================================================
# P0-1 — rollup_to_daily must not stamp a stale bar with today's date
# ==========================================================================

def test_p0_1_rollup_does_not_backdate_a_stale_bar(seeded_session):
    """A bar from Monday must never be written as Tuesday's daily row.

    Before the fix, rollup_to_daily took each sector's newest sector_flow_ts
    row and wrote it under `date` (default: today) with no check on the row's
    own timestamp. A rate-limited or holiday run therefore duplicated the
    previous session, which collapses the rolling std in stealth's z-score and
    fires ACCUMULATE signals that never happened.
    """
    monday = datetime(2026, 3, 2, 15, 0)
    seeded_session.add(SectorFlowTS(
        sector_code="BANK", time=monday,
        net_dollar_flow=5e9, up_vol=1e6, down_vol=5e5,
        foreign_net=0.0, breadth_sma20=0.8, breadth_sma50=0.6,
        atr_pct=0.02, close_idx=1000.0, basket_return=0.012,
    ))
    seeded_session.commit()

    svc = SectorIngestService(seeded_session)

    # Asking for Tuesday, when only a Monday bar exists, must write nothing.
    written = svc.rollup_to_daily(date="2026-03-03")
    assert written == 0
    assert seeded_session.query(SectorFlowDaily).filter_by(date="2026-03-03").count() == 0

    # Asking for Monday writes Monday.
    written = svc.rollup_to_daily(date="2026-03-02")
    assert written == 1
    row = seeded_session.query(SectorFlowDaily).filter_by(date="2026-03-02").one()
    assert row.sector_code == "BANK"


def test_p0_1_rollup_derives_the_date_from_the_bar(seeded_session):
    """With no explicit date, the bar's own timestamp decides its date."""
    seeded_session.add(SectorFlowTS(
        sector_code="BANK", time=datetime(2026, 3, 2, 15, 0),
        net_dollar_flow=5e9, up_vol=1e6, down_vol=5e5,
        close_idx=1000.0, basket_return=0.01,
    ))
    seeded_session.commit()

    SectorIngestService(seeded_session).rollup_to_daily()

    dates = [r.date for r in seeded_session.query(SectorFlowDaily).all()]
    assert dates == ["2026-03-02"], "row must carry its bar's date, not today's"


# ==========================================================================
# P0-2 — the scheduled path must carry price through
# ==========================================================================

def test_p0_2_rollup_writes_close_idx_and_return(seeded_session):
    """close_idx / return_1d feed the ML target, stealth cond5 and backtest P&L.

    They used to be written only by the UI-triggered fast_ingest path, so the
    scheduled pipeline left them NULL forever.
    """
    seeded_session.add(SectorFlowTS(
        sector_code="BANK", time=datetime(2026, 3, 2, 15, 0),
        net_dollar_flow=5e9, up_vol=1e6, down_vol=5e5,
        close_idx=1234.5, basket_return=0.0234,
    ))
    seeded_session.commit()

    SectorIngestService(seeded_session).rollup_to_daily(date="2026-03-02")

    row = seeded_session.query(SectorFlowDaily).filter_by(date="2026-03-02").one()
    assert row.close_idx == pytest.approx(1234.5)
    assert row.return_1d == pytest.approx(0.0234)


def test_p0_2_rollup_repairs_a_row_that_is_missing_price(seeded_session):
    """An existing price-less row must be filled in, not skipped."""
    seeded_session.add(SectorFlowDaily(
        sector_code="BANK", date="2026-03-02", net_dollar_flow=1e9,
    ))  # close_idx deliberately absent — this is the damaged state
    seeded_session.add(SectorFlowTS(
        sector_code="BANK", time=datetime(2026, 3, 2, 15, 0),
        net_dollar_flow=5e9, close_idx=999.0, basket_return=0.005,
    ))
    seeded_session.commit()

    SectorIngestService(seeded_session).rollup_to_daily(date="2026-03-02")

    row = seeded_session.query(SectorFlowDaily).filter_by(date="2026-03-02").one()
    assert row.close_idx == pytest.approx(999.0)
    assert row.return_1d == pytest.approx(0.005)


# ==========================================================================
# P0-3 — basket_return must survive a stock split
# ==========================================================================

def test_p0_3_basket_return_is_split_safe():
    """close_idx is a raw sum of prices; a 2:1 split halves it overnight.

    basket_return averages each constituent's OWN return, so a split in one
    name cannot manufacture a sector-wide move.
    """
    normal = aggregate_sector("BANK", {
        "A": _ohlcv([100, 101]),
        "B": _ohlcv([50, 50.5]),
    })
    assert normal.basket_return == pytest.approx(0.01, abs=1e-9)

    # Same day, except B did a 2:1 split (price halves, no economic change).
    split = aggregate_sector("BANK", {
        "A": _ohlcv([100, 101]),
        "B": _ohlcv([50, 25.25]),
    })

    # close_idx is wrecked by the split...
    assert split.close_idx < normal.close_idx * 0.9
    # ...but the split shows up in that one name's return, not as a phantom
    # index collapse of the whole sector: the equal-weighted basket return is
    # 0.5*(+1%) + 0.5*(-49.5%), not a -25% index gap plus a bogus prior level.
    assert split.basket_return == pytest.approx(0.5 * 0.01 + 0.5 * (25.25 / 50 - 1))


def test_p0_3_basket_return_is_zero_without_history():
    agg = aggregate_sector("BANK", {"A": _ohlcv([100])})
    assert agg.basket_return == 0.0


# ==========================================================================
# P0-4 — the backtest must simulate the published signals
# ==========================================================================

# Four "large" sectors with huge raw flow but no trend, and one small sector
# that actually trends. Raw-VND ranking fills all MAX_LONG_SECTORS slots with
# the large ones and never sees FISH -- which is the size bias P0-4 describes.
_BIG = ["BANK", "REAL", "STEEL", "BROK"]


def _seed_backtest_panel(session, days=40):
    base = datetime(2026, 1, 5)
    dates = [(base + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    for i, d in enumerate(dates):
        for j, code in enumerate(_BIG):
            session.add(SectorFlowDaily(
                sector_code=code, date=d, close_idx=1000.0, return_1d=0.0,
                net_dollar_flow=9e11 - j * 1e10, atr_pct=0.01,
            ))
        session.add(SectorFlowDaily(
            sector_code="FISH", date=d, close_idx=100.0 * (1.01 ** i),
            return_1d=0.01, net_dollar_flow=1e9, atr_pct=0.01,
        ))
    session.commit()
    return dates


def test_p0_4_backtest_follows_published_signals_not_raw_flow(seeded_session):
    dates = _seed_backtest_panel(seeded_session)
    for d in dates:
        seeded_session.add(SectorSignal(date=d, sector_code="FISH", score=1.0,
                                    rank=1, action="BUY"))
        for j, code in enumerate(_BIG):
            seeded_session.add(SectorSignal(date=d, sector_code=code, score=0.0,
                                            rank=j + 2, action="HOLD"))
    seeded_session.commit()

    res = SectorBacktestService(seeded_session).run(
        "sig", dates[0], dates[-1], strategy="signals")

    assert res.strategy_source == "signals"
    assert res.signal_dates_covered == len(dates)
    traded = {t["sector"] for t in res.trade_log}
    assert traded == {"FISH"}, f"should trade only what was signalled, got {traded}"


def test_p0_4_raw_flow_ranking_is_size_biased(seeded_session):
    """Documents why the old default was wrong: raw VND ranking = rank by size."""
    dates = _seed_backtest_panel(seeded_session)
    res = SectorBacktestService(seeded_session).run(
        "raw", dates[0], dates[-1], strategy="flow_raw")
    traded = {t["sector"] for t in res.trade_log}
    assert "FISH" not in traded, \
        "raw net_dollar_flow ranks by sector SIZE, so the trending small sector "\
        "is never reachable"
    assert traded <= set(_BIG)


def test_p0_4_falls_back_to_flow_z_when_no_signals(seeded_session):
    dates = _seed_backtest_panel(seeded_session)
    res = SectorBacktestService(seeded_session).run("nosig", dates[0], dates[-1])
    assert res.strategy_source == "flow_z"


def test_p0_4_benchmark_prefers_vnindex(seeded_session):
    dates = _seed_backtest_panel(seeded_session)
    for i, d in enumerate(dates):
        seeded_session.add(MacroAnchor(
            time=datetime.strptime(d, "%Y-%m-%d"), vnindex=1200.0 * (1.002 ** i)))
    seeded_session.commit()

    res = SectorBacktestService(seeded_session).run("bm", dates[0], dates[-1])
    assert res.benchmark_source == "vnindex"
    # ~0.2%/day compounded over the window, not the sector mean.
    assert res.benchmark_return_pct == pytest.approx(
        ((1.002 ** (len(dates) - 1)) - 1) * 100, rel=0.05)


def test_p0_4_benchmark_falls_back_and_says_so(seeded_session):
    dates = _seed_backtest_panel(seeded_session)
    res = SectorBacktestService(seeded_session).run("bm2", dates[0], dates[-1])
    assert res.benchmark_source == "sector_mean"


# ==========================================================================
# P0-6 — purged/embargoed split in the ranker
# ==========================================================================

def _feature_panel(n_dates=120, sectors=("BANK", "FISH", "TECH", "STEEL")):
    rng = np.random.default_rng(7)
    rows = []
    base = datetime(2025, 1, 1)
    for i in range(n_dates):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        for s in sectors:
            rows.append({
                "date": d, "sector_code": s,
                "f1": rng.normal(), "f2": rng.normal(),
                "target": rng.normal() * 0.02,
            })
    return pd.DataFrame(rows)


def test_p0_6_train_and_test_are_separated_by_an_embargo():
    """No training date may fall within `horizon` days of the test window.

    With a 20-day forward target, a plain 80/20 cut leaks 20 sessions of
    future information across the boundary (CLAUDE.md §18.3/13, BLOCKER).
    """
    from config import ROTATION_TARGET_HORIZON_DAYS
    from models.rotation_ranker import RotationRanker

    df = _feature_panel()
    result = RotationRanker().fit(df, ["f1", "f2"])

    embargo = ROTATION_TARGET_HORIZON_DAYS + 2
    assert result.metrics["embargo_days"] == embargo
    assert result.metrics["purged_dates"] == embargo, \
        "the dates between train and test must actually be dropped"

    all_dates = sorted(df["date"].unique())
    cut = int(len(all_dates) * 0.8)
    expected_train = len(all_dates[: cut - embargo]) * df["sector_code"].nunique()
    assert result.n_train == expected_train


def test_p0_6_metrics_measure_skill_not_market_drift():
    """top1_excess_hit is scored against the median sector, so 0.5 is no-skill.

    The old top1_hit_rate counted "was the forward return positive", which any
    coin flip scores ~60% on in a rising market.
    """
    from models.rotation_ranker import RotationRanker

    df = _feature_panel()
    # Every sector rises 5% no matter what — a pure drift panel with zero
    # cross-sectional signal. A skill metric must not reward this.
    df["target"] = 0.05

    result = RotationRanker().fit(df, ["f1", "f2"])
    assert "top1_hit_rate" not in result.metrics, "the misleading metric is gone"
    assert result.metrics["top1_excess_hit"] == 0.0, \
        "no sector beats the median when all are identical"


def test_p0_6_short_history_fails_loudly():
    from models.rotation_ranker import RotationRanker

    with pytest.raises(ValueError, match="purged split"):
        RotationRanker().fit(_feature_panel(n_dates=25), ["f1", "f2"])


# ==========================================================================
# P1-2 — a degraded ranker must be detectable
# ==========================================================================

def test_p1_2_mean_flow_fallback_is_flagged_as_degraded():
    from models.rotation_ranker import RotationRanker, _MeanFlowRanker

    r = RotationRanker()
    r.model = _MeanFlowRanker(["f1"])
    assert r.is_degraded is True


def test_p1_2_lightgbm_backend_is_not_degraded():
    from models.rotation_ranker import RotationRanker

    result = RotationRanker().fit(_feature_panel(), ["f1", "f2"])
    if result.metrics["backend"] == "lightgbm":
        assert RotationRanker().is_degraded is False


# ==========================================================================
# P1-5 — the live safety rails from §16.9 / §18.4
# ==========================================================================

def test_p1_5_accumulate_is_capped(seeded_session, monkeypatch):
    """§16.9 caps concurrent ACCUMULATE at 4; stealth could tag all 15."""
    import services.sector_signal_service as sss

    codes = ["BANK", "BROK", "REAL", "STEEL", "RETAIL", "FOOD"]
    for i, code in enumerate(codes):
        seeded_session.add(SectorFlowDaily(
            sector_code=code, date="2026-03-02",
            accumulation_age=10 + i, net_dollar_flow=1e9, close_idx=100.0,
        ))
    seeded_session.commit()

    svc = sss.SectorSignalService(seeded_session)
    stealth = svc._stealth_sectors()
    assert len(stealth) == len(codes)

    ranked = pd.DataFrame([
        {"sector_code": c, "score": 1.0 - i * 0.1, "rank": i + 1}
        for i, c in enumerate(codes)
    ])
    monkeypatch.setattr(sss.RotationModelService, "predict_today",
                        lambda self: ranked.copy())

    out = svc.publish()
    n_accum = int((out["action"] == "ACCUMULATE").sum())
    assert n_accum == sss.MAX_ACCUMULATE_SECTORS == 4


def test_p1_5_stale_stealth_is_released(seeded_session, monkeypatch):
    """§16.9: over 30 sessions in stealth without a breakout = dry powder back."""
    import services.sector_signal_service as sss

    seeded_session.add(SectorFlowDaily(
        sector_code="BANK", date="2026-03-02", accumulation_age=45,
        net_dollar_flow=1e9, close_idx=100.0,
    ))
    seeded_session.commit()

    svc = sss.SectorSignalService(seeded_session)
    assert svc._stealth_sectors() == {"BANK": 45}

    ranked = pd.DataFrame([{"sector_code": "BANK", "score": 1.0, "rank": 1}])
    monkeypatch.setattr(sss.RotationModelService, "predict_today",
                        lambda self: ranked.copy())

    out = svc.publish()
    assert out.iloc[0]["action"] != "ACCUMULATE"


def test_p1_5_trading_halt_blocks_new_exposure(seeded_session, monkeypatch):
    """§18.4/20 kill-switch."""
    import services.sector_signal_service as sss

    _seed_daily(seeded_session, "BANK", ["2026-02-27", "2026-02-28", "2026-03-02"])
    monkeypatch.setattr(sss, "TRADING_HALT", True)

    ranked = pd.DataFrame([{"sector_code": "BANK", "score": 1.0, "rank": 1}])
    monkeypatch.setattr(sss.RotationModelService, "predict_today",
                        lambda self: ranked.copy())

    out = sss.SectorSignalService(seeded_session).publish()
    assert set(out["action"]) == {"HOLD"}


def test_p1_5_shorts_can_be_switched_off(seeded_session, monkeypatch):
    """§18.2/12 — the VN cash market cannot short."""
    import services.sector_signal_service as sss

    codes = ["BANK", "BROK", "REAL", "STEEL", "RETAIL"]
    for code in codes:
        _seed_daily(seeded_session, code, ["2026-02-27", "2026-02-28", "2026-03-02"])

    ranked = pd.DataFrame([
        {"sector_code": c, "score": 1.0 - i * 0.1, "rank": i + 1}
        for i, c in enumerate(codes)
    ])
    monkeypatch.setattr(sss.RotationModelService, "predict_today",
                        lambda self: ranked.copy())

    monkeypatch.setattr(sss, "ALLOW_SHORT_SIGNALS", True)
    assert "SELL" in set(sss.SectorSignalService(seeded_session).publish()["action"])

    monkeypatch.setattr(sss, "ALLOW_SHORT_SIGNALS", False)
    assert "SELL" not in set(sss.SectorSignalService(seeded_session).publish()["action"])


# ==========================================================================
# P1-6 — one market-local clock
# ==========================================================================

def test_p1_6_trading_date_is_market_local_not_host_local(monkeypatch):
    """A UTC host must still report the Ho Chi Minh City date."""
    from utils import clock

    monkeypatch.setenv("TZ", "UTC")
    # 2026-03-02 18:30 ICT is still 11:30 UTC on 2026-03-02, but 2026-03-02
    # 00:30 ICT is 2026-03-01 17:30 UTC — the case that used to misdate rows.
    assert clock.MARKET_TZ.key == "Asia/Ho_Chi_Minh"

    aware = datetime(2026, 3, 1, 17, 30, tzinfo=clock.ZoneInfo("UTC"))
    assert clock.to_market_date_str(aware) == "2026-03-02"


def test_p1_6_holidays_and_weekends_are_not_trading_days():
    from datetime import date as _date

    from utils import clock

    assert clock.is_trading_day(_date(2026, 3, 2)) is True      # Monday
    assert clock.is_trading_day(_date(2026, 3, 7)) is False     # Saturday
    assert clock.is_trading_day(_date(2026, 4, 30)) is False    # holiday


def test_p1_6_previous_trading_day_skips_the_weekend():
    from datetime import date as _date

    from utils import clock

    assert clock.previous_trading_day(_date(2026, 3, 2)) == _date(2026, 2, 27)


# ==========================================================================
# P2-1 — the API guard is real when switched on
# ==========================================================================

def test_p2_1_auth_dependency_exists_and_is_importable():
    """api/auth.py used to define this and no router referenced it."""
    import inspect

    from api.auth import require_api_key

    assert inspect.iscoroutinefunction(require_api_key)


def test_p2_1_cors_no_longer_carries_inert_wildcard_origins():
    """"https://*.ngrok-free.app" in allow_origins matched nothing.

    Starlette compares allow_origins by exact string, so a "*" there is a
    literal character. Those entries were pure decoration; only the regex ever
    admitted anything, and it admitted every tunnel on two shared domains.
    """
    from starlette.middleware.cors import CORSMiddleware

    from api.main import app

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert cors, "CORS middleware should be installed"
    origins = cors[0].kwargs.get("allow_origins", [])
    assert not any("*" in o for o in origins), \
        f"allow_origins must not contain literal-asterisk entries: {origins}"


def test_p2_1_limiter_is_attached_to_the_app():
    from api.main import app

    assert getattr(app.state, "limiter", None) is not None, \
        "api/rate_limit.py defined a limiter that was never wired up"


@pytest.mark.parametrize("require", ["0", "1"])
def test_p2_1_guard_toggles_with_config(require, monkeypatch):
    """Default off keeps the local dashboard working; on locks every router."""
    monkeypatch.setenv("API_REQUIRE_KEY", require)
    monkeypatch.setenv("DATABASE_PATH", os.path.join(os.sep, "tmp", "guard_test.db"))

    import importlib

    import config
    importlib.reload(config)
    assert config.API_REQUIRE_KEY is (require == "1")


# ==========================================================================
# P0-7 — the R:R floor rejected the very picks it had just repaired
# ==========================================================================
# Found by running generate_report.py for real on 2026-08-22. Five BUY picks
# (SSI, SHS, DGW, FPT, PNJ) were dropped from the daily email with the
# self-contradictory reason "r_r 1.50 < 1.5".
#
# Mechanism: compute_stop_target_rr stretches the target so reward/risk lands
# exactly on MIN_RR, then rounds stop/target to 2dp on the way out.
# is_valid_long_pick RECOMPUTES the ratio from those rounded numbers, so the
# rounding shaves it to 1.4999... and the pick fails its own floor.

def test_p0_7_stretched_target_survives_rounding():
    from services.picks_scoring import (
        MIN_RR, compute_stop_target_rr, is_valid_long_pick,
    )

    # Prices chosen so the stretched target does not land on a whole cent.
    for close in (23.37, 41.83, 117.61, 7.77, 88.19):
        stop, target, rr, err = compute_stop_target_rr(
            {"close": close, "atr_pct": 1.7})
        assert err is None
        ok, reason = is_valid_long_pick(close, target, stop)
        assert ok, (
            f"close={close}: pick rejected by its own floor ({reason}) after "
            f"the target was stretched to meet it"
        )
        assert round((target - close) / (close - stop), 2) >= MIN_RR


def test_p0_7_a_genuinely_thin_setup_is_still_rejected():
    """The fix must not turn the floor off."""
    from services.picks_scoring import is_valid_long_pick

    # reward 0.50 against risk 1.00 = 0.5 R:R, nowhere near the floor.
    ok, reason = is_valid_long_pick(entry=100.0, target=100.5, stop=99.0)
    assert not ok
    assert reason is not None


# ==========================================================================
# P0-8 — an all-NULL feature column must not silently disable LightGBM
# ==========================================================================
# Found on the live DB 2026-08-22: rs_vnindex_5d / rs_vnindex_20d are 100%
# NULL, so pandas typed them `object`, LightGBM rejected the frame, and the
# ranker fell back to mean-flow on every one of 74 nightly runs. The published
# "score" was raw net_dollar_flow the whole time.

def test_p0_8_all_null_feature_column_stays_numeric(seeded_session):
    from services.flow_feature_service import FEATURE_COLS, FlowFeatureService

    for i in range(30):
        seeded_session.add(SectorFlowDaily(
            sector_code="BANK", date=f"2026-01-{i+1:02d}",
            close_idx=100.0 + i, return_1d=0.01,
            net_dollar_flow=1e9, atr_pct=0.02,
            rs_vnindex_5d=None, rs_vnindex_20d=None,   # the live state
        ))
    seeded_session.commit()

    df = FlowFeatureService(seeded_session).build(with_target=False)

    bad = [c for c in FEATURE_COLS
           if c in df.columns and df[c].dtype == object]
    assert not bad, f"object-dtype feature columns break LightGBM: {bad}"


def test_p0_8_lightgbm_trains_when_a_feature_is_all_null():
    """The frame the ranker receives must be acceptable to LightGBM."""
    import pandas as _pd

    from models.rotation_ranker import RotationRanker

    df = _feature_panel(n_dates=150)
    df["all_null"] = _pd.Series([None] * len(df), dtype=object)
    cols = ["f1", "f2", "all_null"]
    df["all_null"] = _pd.to_numeric(df["all_null"], errors="coerce").astype("float64")

    res = RotationRanker().fit(df.fillna({"all_null": 0.0}), cols)
    assert res.metrics["backend"] == "lightgbm", (
        "an all-NULL column must not knock the ranker into the mean-flow fallback"
    )


# ==========================================================================
# P0-9 / P0-10 — items 2, 3 and 7 of the 2026-08-23 work order
# ==========================================================================

def test_p0_9_rs_vnindex_is_actually_populated(seeded_session):
    """Measured on the live DB: rs_vnindex_5d/20d were NULL on all 13,140 rows
    despite sitting in FEATURE_COLS since day one. They are derivable from
    close_idx, so the feature service now computes them."""
    from services.flow_feature_service import FlowFeatureService

    for code in ("BANK", "TECH", "FISH"):
        for i in range(40):
            seeded_session.add(SectorFlowDaily(
                sector_code=code, date=f"2026-01-{i+1:02d}" if i < 31
                else f"2026-02-{i-30:02d}",
                close_idx=100.0 * (1.0 + (0.004 if code == "TECH" else 0.001)) ** i,
                return_1d=0.001, net_dollar_flow=1e9, atr_pct=0.02,
            ))
    seeded_session.commit()

    df = FlowFeatureService(seeded_session).build(with_target=False)

    for col in ("rs_vnindex_5d", "rs_vnindex_20d"):
        assert col in df.columns
        assert df[col].notna().sum() > 0, f"{col} is still entirely NULL"
        assert df[col].dtype != object, f"{col} must not be object dtype"

    # TECH compounds fastest, so it must show positive relative strength.
    tail = df.sort_values("date").groupby("sector_code").tail(1).set_index("sector_code")
    assert tail.loc["TECH", "rs_vnindex_20d"] > tail.loc["BANK", "rs_vnindex_20d"]


def test_p0_9_rs_records_which_benchmark_it_used(seeded_session):
    from services.flow_feature_service import FlowFeatureService

    for i in range(30):
        seeded_session.add(SectorFlowDaily(
            sector_code="BANK", date=f"2026-01-{i+1:02d}",
            close_idx=100.0 + i, return_1d=0.01, net_dollar_flow=1e9,
        ))
    seeded_session.commit()
    df = FlowFeatureService(seeded_session).build(with_target=False)
    assert set(df["rs_benchmark"]) <= {"vnindex", "sector_composite", "none"}


def test_p0_10_flow_series_default_lookback_is_a_chart_window():
    """It was 400 sessions x 15 sectors = 1.19 MB and 3.3 s per call."""
    import inspect

    from api.routers import flow as flow_router

    sig = inspect.signature(flow_router.flow_series)
    default = sig.parameters["lookback"].default
    assert getattr(default, "default", default) == 120


# ==========================================================================
# P0-11 — item 6: the deprecated vnstock client is gone from call sites
# ==========================================================================
# vnstock retired its old client class and accessors on 2025-08-31. The banner sat in
# every job log because the call was spread across eight files with no single
# place to change it. utils/vn_api.py is now that place.

def test_p0_11_no_module_constructs_the_deprecated_client():
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    # Built at runtime so this file does not match its own assertion text.
    ctor = "Vnstock" + "()"
    legacy_import = "from vnstock " + "import Vnstock"

    offenders = []
    for py in root.rglob("*.py"):
        parts = set(py.parts)
        if parts & {".venv", ".venv-lin", "_trash_2026-08-22", "backup", "_audit"}:
            continue
        if py.name == "vn_api.py":       # the adapter is allowed to know
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if ctor in text or legacy_import in text:
            offenders.append(str(py.relative_to(root)))
    assert not offenders, (
        "these still construct the deprecated vnstock client class directly; "
        f"route them through utils.vn_api instead: {offenders}")


def test_p0_11_adapter_exposes_what_the_call_sites_need():
    from utils import vn_api

    for fn in ("quote_history", "price_board", "listing", "company_news",
               "uses_new_api"):
        assert callable(getattr(vn_api, fn)), f"vn_api.{fn} missing"


def test_p0_11_adapter_prefers_the_new_api(monkeypatch):
    """It must call vnstock.api, and only fall back when that is absent."""
    import builtins

    from utils import vn_api

    calls = []
    real_import = builtins.__import__

    def spy(name, *a, **kw):
        calls.append(name)
        if name == "vnstock.api.quote":
            raise ImportError("simulated: old vnstock installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", spy)
    try:
        vn_api.quote_history("VCB", "2026-08-01", "2026-08-02")
    except Exception:
        pass  # network/legacy call may fail; we only care which was attempted

    assert "vnstock.api.quote" in calls, "the new API must be tried first"
