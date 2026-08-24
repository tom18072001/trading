"""analysis/stealth.py — the §16.1 gate after it stopped being a conjunction.

The defect these guard against, measured 2026-08-23 on the live 13,470-row
panel: requiring all five conditions simultaneously produced **zero** stealth
events in 3.5 years. The longest run of all-five across 15 sectors was 2
sessions; the gate asked for 3. `accumulation_age` was 0 on every row ever
written, and it was not because §16 was untested — the conjunction was
arithmetically unreachable.

So the load-bearing test here is `test_four_of_five_fires_where_all_five_cannot`.
The rest pin the two things easy to get wrong when a gate becomes a score:
persistence still being required, and an unevaluable condition not silently
raising the bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import stealth as S


def _panel(n=120, *, foreign=1.0, flow_hot_from=None):
    """One sector, n sessions, quiet + cheap + broadening by construction.

    Defaults satisfy c2/c3/c4/c5; c1 (flow z) is the knob.

    Deterministic on purpose. Flat flow gives sd=0 → z is NaN → c1 is False
    with no random spikes; a *ramp* (not a step) is what holds z above +1,
    because a step's z decays to 0 once the 20d mean catches up.
    """
    flow = np.full(n, 1e8)
    if flow_hot_from is not None:
        k = n - flow_hot_from
        flow[flow_hot_from:] = 1e8 + np.arange(1, k + 1) * 3e8
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "sector_code": "TEST",
        "net_dollar_flow": flow,
        "foreign_net": np.full(n, foreign),          # c2: hit rate 100%
        "atr_pct": np.linspace(0.03, 0.005, n),      # c4: falling → below median
        "close_idx": np.linspace(100, 60, n),        # c5: bottom of 60d range
        "breadth_sma20": np.linspace(0.2, 0.9, n),   # c3: rising
    })


def test_conditions_met_is_reported_per_row():
    out = S.compute_leading_features(_panel())
    assert "conditions_met" in out.columns
    assert out.conditions_met.between(0, 5).all()


def test_four_of_five_fires_where_all_five_cannot():
    """The whole point of the change.

    A panel that clears four conditions but never the fifth must produce a
    stealth event under the score gate, and none under a conjunction.
    """
    df = _panel(foreign=-1.0, flow_hot_from=60)      # c2 fails forever
    out = S.compute_leading_features(df)

    tail = out.tail(30)
    assert (tail.conditions_met == 4).any(), "fixture should reach 4/5"
    assert (tail.conditions_met == 5).sum() == 0, "fixture must never reach 5/5"
    assert out.in_stealth.any(), "4/5 sustained must fire — this is the fix"
    assert out.accumulation_age.max() >= S.STEALTH_MIN_SESSIONS


def test_three_of_five_does_not_fire_at_the_default():
    """The gate is loosened, not removed."""
    df = _panel(foreign=-1.0)                        # c2 fails, c1 never hot
    out = S.compute_leading_features(df)
    assert out.conditions_met.max() <= 3
    assert not out.in_stealth.any()


def test_persistence_is_still_required():
    """A single qualifying session is noise, not accumulation."""
    df = _panel(n=80, foreign=-1.0)
    # one lone flow spike → at most one session at 4/5
    df.loc[df.index[-1], "net_dollar_flow"] = 5e10
    out = S.compute_leading_features(df)
    assert not out.in_stealth.iloc[-1]


def test_unevaluable_condition_does_not_raise_the_bar():
    """foreign_net all-zero drops c2 from BOTH numerator and denominator.

    Counting it as a failure would mean an all-zero column silently made the
    gate stricter — which is how the old code shipped a 3-condition gate while
    the doctrine said 5.
    """
    hot = _panel(foreign=0.0, flow_hot_from=40)      # c2 unevaluable
    out = S.compute_leading_features(hot)
    assert out.conditions_met.max() <= 4, "c2 must not be counted as a pass"
    assert out.in_stealth.any(), "4 evaluable conditions all passing must fire"


def test_min_conditions_is_env_tunable(monkeypatch):
    df = _panel(foreign=-1.0, flow_hot_from=60)
    monkeypatch.setattr(S, "STEALTH_MIN_CONDITIONS", 5)
    assert not S.compute_leading_features(df).in_stealth.any()
    monkeypatch.setattr(S, "STEALTH_MIN_CONDITIONS", 4)
    assert S.compute_leading_features(df).in_stealth.any()


def test_accumulation_age_counts_the_current_run_only():
    df = _panel(foreign=-1.0, flow_hot_from=40)
    df.loc[df.index[70:75], "net_dollar_flow"] = -5e10   # break the run
    out = S.compute_leading_features(df)
    ages = out.accumulation_age.values
    assert ages.min() == 0
    # age must reset to 0 during the break, then climb again
    assert any(ages[i] == 0 and ages[i - 1] > 0 for i in range(1, len(ages)))


@pytest.mark.parametrize("col", ["flow_z20", "flow_z60", "foreign_hit_20d",
                                 "stealth_score", "flow_price_divergence"])
def test_feature_columns_survive(col):
    """§16.2 features must still be emitted — fast_ingest writes all of them."""
    assert col in S.compute_leading_features(_panel()).columns


# --- the endpoint must be gated the same way as the scanner ---------------

def test_router_defaults_come_from_the_scanner():
    """The page and the offline scanner must not drift apart again.

    Before 2026-08-23 `/api/stealth/active` classified `active` only at
    `passes == 5` with `min_sessions=5`, while `analysis/stealth.py` required 3
    sessions — so the page could show a sector the scanner would never record
    in `accumulation_age`, and vice versa. Binding the Query defaults to the
    module constants is what keeps them in step.
    """
    import inspect

    from api.routers.stealth import stealth_active

    sig = inspect.signature(stealth_active)
    assert sig.parameters["min_sessions"].default.default == S.STEALTH_MIN_SESSIONS
    assert sig.parameters["min_conditions"].default.default == S.STEALTH_MIN_CONDITIONS


def test_router_cond4_ranks_atr_rather_than_comparing_a_raw_fraction():
    """cond4 used to compare atr_pct (~0.006) to a 0.5 threshold named "rank".

    That passed for free on every sector, so the endpoint's five-condition gate
    was really four. It takes a 0..1 percentile now.
    """
    from api.routers.stealth import _build_gate

    common = {"flow_z_hot": 1.0, "foreign_hit_min": 0.6, "breadth_min": 0.5,
              "atr_rank_max": 0.5, "close_pct_60d_max": 0.4}
    noisy = _build_gate(0.0, 0.0, 0.0, 0.9, 0.9, **common)   # loudest 10%
    quiet = _build_gate(0.0, 0.0, 0.0, 0.1, 0.9, **common)   # quietest 10%
    assert noisy["cond4_atr_quiet"]["pass"] is False
    assert quiet["cond4_atr_quiet"]["pass"] is True
