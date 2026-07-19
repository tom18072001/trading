# tests/test_sector_pipeline.py
# Integration: feature build → ranker → signal publish → backtest → risk
import pytest

from services.backtest_service import SectorBacktestService
from services.flow_feature_service import FEATURE_COLS, FlowFeatureService
from services.risk_service import SectorRiskService
from services.rotation_model_service import RotationModelService
from services.sector_signal_service import SectorSignalService


def test_feature_service_builds_panel(daily_panel):
    df = FlowFeatureService(daily_panel).build(with_target=True)
    assert not df.empty
    for c in ("date", "sector_code", "target"):
        assert c in df.columns


def test_rotation_predict_today(daily_panel):
    df = RotationModelService(daily_panel).predict_today()
    if df.empty:
        pytest.skip("not enough rows")
    assert "score" in df.columns
    assert "rank" in df.columns
    assert df["rank"].is_monotonic_increasing


def test_signal_publish_writes_rows(daily_panel):
    svc = SectorSignalService(daily_panel)
    out = svc.publish()
    if out.empty:
        pytest.skip("no signals")
    assert {"BUY", "SELL", "HOLD"} >= set(out["action"].unique())


def test_backtest_runs(daily_panel):
    bt = SectorBacktestService(daily_panel).run(
        name="test", start_date="2025-01-01", end_date="2025-12-31",
    )
    assert bt.total_trades > 0
    assert isinstance(bt.sharpe_ratio, float)
    assert bt.equity_curve


def test_risk_var_report(daily_panel):
    svc = SectorRiskService(daily_panel)
    rep = svc.var_report("BANK")
    assert rep.sector_code == "BANK"
    assert rep.n_obs > 0
    assert rep.var_95 >= 0  # loss number is positive


def test_risk_stoploss_returns_list(daily_panel):
    breaches = SectorRiskService(daily_panel).stoploss_breaches()
    assert isinstance(breaches, list)


def test_regime_classify_fallback(macro_session):
    rec = RotationModelService(macro_session).classify_regime()
    assert rec.regime_label in {"risk_on", "risk_off", "rotation", "chop"}
