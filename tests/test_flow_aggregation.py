# tests/test_flow_aggregation.py
import numpy as np
import pandas as pd
import pytest

from analysis.flow_aggregation import (
    aggregate_sector, relative_strength,
)


def _df(closes, vols=None):
    n = len(closes)
    vols = vols or [1000] * n
    return pd.DataFrame({
        "open":  [c - 0.1 for c in closes],
        "high":  [c + 0.2 for c in closes],
        "low":   [c - 0.2 for c in closes],
        "close": closes,
        "volume": vols,
    }, index=pd.date_range("2025-01-01", periods=n, freq="D"))


def test_aggregate_sector_basic():
    constituents = {
        "A": _df([10, 11, 12, 13, 14] * 12),  # 60 bars
        "B": _df([20, 19, 21, 22, 23] * 12),
    }
    agg = aggregate_sector("BANK", constituents)
    assert agg.sector_code == "BANK"
    assert agg.close_idx > 0
    assert isinstance(agg.net_dollar_flow, float)
    assert 0.0 <= agg.breadth_sma20 <= 1.0
    assert agg.atr_pct >= 0


def test_aggregate_sector_empty_raises():
    with pytest.raises(ValueError):
        aggregate_sector("BANK", {})


def test_aggregate_sector_missing_columns():
    bad = pd.DataFrame({"close": [1, 2, 3]})
    with pytest.raises(ValueError):
        aggregate_sector("BANK", {"X": bad})


def test_relative_strength_outperforms():
    s = pd.Series([100, 102, 104, 106, 108, 110])
    b = pd.Series([100, 100, 100, 100, 100, 100])
    rs = relative_strength(s, b, lookback=5)
    assert rs > 0


def test_relative_strength_underperforms():
    s = pd.Series([100, 99, 98, 97, 96, 95])
    b = pd.Series([100, 101, 102, 103, 104, 105])
    rs = relative_strength(s, b, lookback=5)
    assert rs < 0


def test_relative_strength_too_short_returns_nan():
    s = pd.Series([100, 101])
    b = pd.Series([100, 101])
    assert np.isnan(relative_strength(s, b, lookback=10))
