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


# ---- 2026-09-25: the sector ATR was divided by n twice (review §4.1/3) ------

def test_sector_atr_is_the_mean_of_its_constituents_not_a_fifth_of_it():
    """Five identical names must give the sector exactly their own ATR%. The
    old code added atr*(1/n) and then divided by n again: 1/5 of the truth,
    which is how §16.15 came to believe the median daily ATR was 0.57%."""
    from analysis.flow_aggregation import _atr_pct
    one = _df([10, 11, 12, 13, 14] * 12)
    agg = aggregate_sector("BANK", {s: one.copy() for s in "ABCDE"})
    assert agg.atr_pct == pytest.approx(_atr_pct(one), rel=1e-12)


def test_sector_atr_weights_the_names_that_have_an_atr():
    """A name too short for a 14-bar ATR drops out of the mean; it does not
    drag it towards zero."""
    from analysis.flow_aggregation import _atr_pct
    long_ = _df([10, 11, 12, 13, 14] * 12)
    short = _df([20, 21, 22])
    agg = aggregate_sector("BANK", {"A": long_, "B": short})
    assert agg.atr_pct == pytest.approx(_atr_pct(long_), rel=1e-12)


def test_chain_close_idx_moves_only_by_the_basket_return():
    """The stored level is chained, so a constituent that fails to fetch
    changes nothing but that day's return -- the raw price sum jumped +62%
    then -39% on STEEL when one did (2026-09-22/23)."""
    from analysis.flow_aggregation import chain_close_idx
    assert chain_close_idx(200.0, 0.01) == pytest.approx(202.0)
    assert chain_close_idx(None, 0.01) == pytest.approx(101.0)        # new chain at 100
    assert chain_close_idx(200.0, None) == 200.0                      # no move invented
    assert chain_close_idx(float("nan"), -0.02) == pytest.approx(98.0)
