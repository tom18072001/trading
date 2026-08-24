"""`stealth_events()` — turning stored `accumulation_age` into scored runs.

`/api/stealth/history` returned a hardcoded `{"rows": []}` from the day it was
written until 2026-08-24. It looked correct for months because the §16.1 AND
gate genuinely produced zero events (see test_stealth_gate.py); once the gate
became a score, 53 rows carried `accumulation_age > 0` and the stub became a
lie the page had no way to notice.

The two tests carrying the feature are:

  - `test_a_long_open_run_is_not_scored_even_though_it_could_be` — the run at
    the right edge of the panel has not finished. Calling it a false positive
    is the single easiest way to make a working gate look broken, and it would
    do so every day, permanently. This one is the guard's *only* real test: a
    short open run is unscored anyway because it has no forward bars, so it
    passes with `still_running` deleted (verified by negative control). A long
    one has bars and would be judged.
  - `test_a_gap_of_one_session_splits_the_run` — run boundaries are the whole
    derivation. Get this wrong and 23 events become 1 per sector.

Numbers here are synthetic. The real panel is pinned by the doc: over 13,485
rows the endpoint returns 21 events / 20 scored / 40% hit / median lead 21,
matching `scripts/stealth_leadtime_experiment.py` exactly — which is the point
of both reading the same `breakout_bar_scaled`.
"""
from __future__ import annotations

import numpy as np
import pytest

from analysis import stealth as S


def _rows(ages, closes, *, code="TEST", atr=0.01, pad=60):
    """A panel with `pad` quiet sessions in front, then the given ages/closes.

    The pad exists so `breakout_bar_baseline` has its >=20 ATR observations; a
    panel that starts at the event would silently fall back to the 0.02 default
    and score against a different bar than production does.
    """
    n = pad + len(ages)
    dates = [f"2025-{1 + (i // 20) % 12:02d}-{1 + i % 20:02d}" for i in range(n)]
    # Dates only need to sort correctly; they are never parsed.
    dates = [f"2025-01-{i + 1:03d}" for i in range(n)]
    return [{
        "sector_code": code,
        "date": dates[i],
        "accumulation_age": ([0] * pad + list(ages))[i],
        "close_idx": ([100.0] * pad + list(closes))[i],
        "atr_pct": atr,
        "stealth_score": 1.0,
    } for i in range(n)]


def test_a_run_of_ages_becomes_one_event_not_one_per_row():
    """53 stored rows are 23 runs. The column is per-row; an event is not."""
    ages = [1, 2, 3, 4] + [0] * 50
    closes = [100.0] * 54
    ev = S.stealth_events(_rows(ages, closes))
    assert len(ev) == 1
    assert ev[0]["sessions"] == 4


def test_a_gap_of_one_session_splits_the_run():
    """age resetting to 0 and restarting at 1 is the boundary.

    Without this the two FOOD runs in April 2026 (01-06 and 10) merge into one
    9-session event that never happened.
    """
    ages = [1, 2, 0, 1, 2, 3] + [0] * 50
    ev = S.stealth_events(_rows(ages, [100.0] * 56))
    assert [e["sessions"] for e in sorted(ev, key=lambda e: e["start_date"])] == [2, 3]


def test_an_open_run_is_not_scored_as_a_failure():
    """A run still going at the panel edge has no verdict yet.

    `classification` is None and `resolved` is False — NOT "false_positive".
    The forward window has not elapsed, so calling it a miss understates the
    gate on every single refresh.
    """
    ev = S.stealth_events(_rows([1, 2, 3], [100.0, 100.0, 100.0]))
    assert len(ev) == 1
    assert ev[0]["classification"] is None
    assert ev[0]["resolved"] is False
    assert ev[0]["end_date"] is None, "an open run must not report today as its end"


def test_a_long_open_run_is_not_scored_even_though_it_could_be():
    """The `still_running` guard, isolated from the `judgeable` one.

    The test above cannot see this guard: a 3-session run at the edge has no
    forward bars, so `judgeable` is already False and it stays unscored with
    `still_running` deleted. Verified by negative control — that edit passed
    all 13 tests.

    Here the run is 25 sessions and still going, so it has 24 forward bars of
    its own: `judgeable` is True, the price clears the bar, and only the
    `still_running` check keeps it out of the scored set. It must stay out —
    the run has not finished, so `sessions` is not its final length and
    `dry_powder_timeout` is still reachable.
    """
    ages = list(range(1, 26))
    closes = [100.0] * 12 + [130.0] * 13
    ev = S.stealth_events(_rows(ages, closes))
    assert len(ev) == 1
    assert ev[0]["classification"] is None, "an unfinished run has no verdict"
    assert ev[0]["end_date"] is None
    # The breakout WAS detected — this is not the judgeable guard firing.
    assert ev[0]["lead_days_to_price"] == 12


def test_a_run_too_close_to_the_panel_edge_is_also_unscored():
    """Same reasoning, one step in: fewer than 10 forward bars is not judgeable.

    Distinct from the open-run case — this run has *ended*, so a naive
    implementation would happily score it against a 3-bar future.
    """
    ages = [1, 2, 0, 0, 0]
    ev = S.stealth_events(_rows(ages, [100.0] * 5))
    assert ev[0]["classification"] is None


def test_a_price_clearing_the_bar_is_a_hit_with_its_lead_time():
    """Breakout = forward max clears entry x (1 + 2 x median ATR x sqrt(40)).

    Lead time counts from the entry row, and the forward window starts at the
    row *after* it — so the run's own later sessions are inside the window.
    Here entry is index 0 of `closes` and the jump is index 10, which is 10
    sessions later.
    """
    ages = [1, 2] + [0] * 50
    closes = [100.0] * 10 + [130.0] + [130.0] * 41
    ev = S.stealth_events(_rows(ages, closes))
    assert ev[0]["classification"] == "hit"
    assert ev[0]["lead_days_to_price"] == 10
    assert ev[0]["peak_return_pct"] == pytest.approx(30.0, abs=0.01)


def test_a_flat_forward_window_is_a_false_positive():
    ages = [1, 2] + [0] * 50
    ev = S.stealth_events(_rows(ages, [100.0] * 52))
    assert ev[0]["classification"] == "false_positive"
    assert ev[0]["lead_days_to_price"] is None


def test_a_long_run_that_never_breaks_out_is_dry_powder_not_a_false_positive():
    """§16.9's 30-session auto-exit is a different outcome from a miss.

    "Dry powder reclaimed" means capital sat idle and was released — no loss,
    no gain. Filing it as a false positive inflates the error rate with trades
    that were never taken.
    """
    n = S._ACCUM_MAX_AGE
    ages = list(range(1, n + 1)) + [0] * 50
    ev = S.stealth_events(_rows(ages, [100.0] * (n + 50)))
    assert ev[0]["sessions"] == n
    assert ev[0]["classification"] == "dry_powder_timeout"


def test_two_sectors_do_not_bleed_into_each_other():
    """Runs are per sector. A shared index would concatenate them."""
    rows = _rows([1, 2] + [0] * 50, [100.0] * 52, code="AAA")
    rows += _rows([1, 2, 3] + [0] * 50, [100.0] * 53, code="BBB")
    ev = S.stealth_events(rows)
    assert {e["sector_code"] for e in ev} == {"AAA", "BBB"}
    assert sorted(e["sessions"] for e in ev) == [2, 3]


def test_a_sector_with_no_stealth_contributes_nothing():
    assert S.stealth_events(_rows([0] * 10, [100.0] * 10)) == []


def test_events_are_newest_first():
    """The page renders the list unsorted; ordering is the endpoint's job."""
    ages = [1, 2] + [0] * 20 + [1, 2, 3] + [0] * 50
    ev = S.stealth_events(_rows(ages, [100.0] * 75))
    assert [e["start_date"] for e in ev] == sorted(
        [e["start_date"] for e in ev], reverse=True)


def test_a_missing_close_makes_the_run_unjudgeable_rather_than_a_miss():
    """close_idx was null on the whole daily table until §20.1's fix.

    A zero entry price must not be scored — dividing by it or comparing against
    it invents a verdict from absent data.
    """
    ages = [1, 2] + [0] * 50
    closes = [0.0, 0.0] + [100.0] * 50
    ev = S.stealth_events(_rows(ages, closes))
    assert ev[0]["classification"] is None


def test_the_breakout_bar_is_horizon_scaled_not_a_daily_range():
    """§16.15: `2 * atr_pct` is ~1.15%, which 83% of sector-days clear.

    Pinning the relationship rather than the constant — the multiplier and the
    window are both tunable, but the scaled bar must stay sqrt(40)x the daily
    one or the endpoint silently reverts to a liveness test.
    """
    atr = np.full(600, 0.006)
    daily = S.breakout_bar_baseline(atr, 599)
    scaled = S.breakout_bar_scaled(atr, 599)
    assert scaled == pytest.approx(daily * np.sqrt(S.BREAKOUT_WINDOW))
    assert 0.05 < scaled < 0.12, f"expected a ~7% bar, got {scaled:.4f}"


def test_the_bench_and_the_endpoint_share_one_breakout_definition():
    """The reason the bar moved out of scripts/ and into analysis/.

    Two copies drift, and the drift is invisible: the bench keeps reporting a
    number the page stopped using. Identity, not equality of output.
    """
    from scripts import stealth_leadtime_experiment as bench

    assert bench._bar_atr_scaled is S.breakout_bar_scaled
    assert bench._bar_atr_baseline is S.breakout_bar_baseline
    assert bench.BREAKOUT_WINDOW == S.BREAKOUT_WINDOW
