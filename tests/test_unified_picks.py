"""Tests for services.unified_picks — the union-merge rule used by SecV5.

The merge rule is the central new piece introduced 2026-04-23 to fix the
Daily Insight vs email mismatch (MODIFICATION_LOG.md 2026-04-23). These tests
anchor the four invariants:

  1. Consensus picks (in BOTH sides) get ``source="BOTH"`` and float to the
     top of the returned list.
  2. Daily-only picks keep ``source="DAILY_INSIGHT"``.
  3. Ranker-only picks keep ``source="RANKER"`` and come AFTER all Daily
     Insight picks.
  4. Empty ranker side → merged list == Daily side with every entry tagged
     ``DAILY_INSIGHT`` (graceful fallback when the ranker is silent — this
     is the specific regression we were trying to prevent).

Inputs are intentionally plain dicts so the test doesn't depend on the
PickEntry dataclass (which pulls in the DB / vnstock import chain).
"""
from __future__ import annotations

from services.unified_picks import merge_pick_sources


def _mk(sym: str, score: int = 0, **extra) -> dict:
    """Shorthand — build a minimal pick dict."""
    return {"symbol": sym, "score": score, **extra}


# =====================================================================
#  Invariant 1 — consensus floats to the top
# =====================================================================

def test_consensus_picks_get_both_and_sort_first():
    daily = [_mk("HPG", score=5), _mk("FPT", score=4)]
    ranker = [_mk("HPG", score=3), _mk("MSN", score=6)]

    merged = merge_pick_sources(daily, ranker)

    # HPG is in both → BOTH and first (within-BOTH sort by score desc; only
    # one BOTH here so trivially first).
    assert merged[0]["symbol"] == "HPG"
    assert merged[0]["source"] == "BOTH"

    # FPT is Daily-only, MSN is Ranker-only. Daily bucket comes before Ranker.
    sources = [p["source"] for p in merged]
    # Order must be: BOTH → DAILY_INSIGHT → RANKER.
    assert sources == ["BOTH", "DAILY_INSIGHT", "RANKER"]


def test_multiple_both_picks_sorted_by_score_desc():
    daily = [_mk("A", score=2), _mk("B", score=8), _mk("C", score=5)]
    ranker = [_mk("A", score=0), _mk("B", score=0), _mk("C", score=0)]
    # All three are consensus. Sort by daily score desc: B, C, A.
    merged = merge_pick_sources(daily, ranker)

    assert [p["symbol"] for p in merged] == ["B", "C", "A"]
    assert all(p["source"] == "BOTH" for p in merged)


# =====================================================================
#  Invariant 2 & 3 — bucket ordering with mixed sources
# =====================================================================

def test_three_buckets_source_ordering():
    daily = [_mk("A", score=10), _mk("B", score=9)]   # A in both, B daily-only
    ranker = [_mk("A", score=1), _mk("C", score=7)]   # A in both, C ranker-only

    merged = merge_pick_sources(daily, ranker)

    # Order must be: BOTH → DAILY_INSIGHT → RANKER.
    assert [p["symbol"] for p in merged] == ["A", "B", "C"]
    assert [p["source"] for p in merged] == ["BOTH", "DAILY_INSIGHT", "RANKER"]


def test_multiple_ranker_only_sorted_by_score_desc():
    daily = [_mk("A", score=3)]
    ranker = [_mk("B", score=2), _mk("C", score=9), _mk("D", score=5)]

    merged = merge_pick_sources(daily, ranker)

    # Daily first, then Ranker-only by score desc (C, D, B).
    assert [p["symbol"] for p in merged] == ["A", "C", "D", "B"]
    assert [p["source"] for p in merged] == [
        "DAILY_INSIGHT", "RANKER", "RANKER", "RANKER"
    ]


# =====================================================================
#  Invariant 4 — empty ranker → pure Daily Insight fallback
# =====================================================================

def test_empty_ranker_falls_back_to_daily_only():
    """This is the exact regression we were trying to prevent — under
    SecV4, an empty ranker meant an empty email. SecV5 must instead fall
    back to whatever Daily Insight surfaced."""
    daily = [_mk("HPG", score=5), _mk("FPT", score=4), _mk("MSN", score=3)]
    ranker: list[dict] = []

    merged = merge_pick_sources(daily, ranker)

    assert len(merged) == 3
    assert [p["source"] for p in merged] == [
        "DAILY_INSIGHT", "DAILY_INSIGHT", "DAILY_INSIGHT"
    ]
    # Order preserved by score desc within the DAILY_INSIGHT bucket.
    assert [p["symbol"] for p in merged] == ["HPG", "FPT", "MSN"]


def test_empty_daily_falls_back_to_ranker_only():
    daily: list[dict] = []
    ranker = [_mk("HPG", score=5), _mk("FPT", score=4)]

    merged = merge_pick_sources(daily, ranker)

    assert len(merged) == 2
    assert all(p["source"] == "RANKER" for p in merged)
    assert [p["symbol"] for p in merged] == ["HPG", "FPT"]


def test_empty_both_sides_returns_empty():
    assert merge_pick_sources([], []) == []


# =====================================================================
#  Non-regression details
# =====================================================================

def test_extra_fields_preserved_through_merge():
    """The merge copies each input dict so extra fields (thesis, news,
    target, stop, etc.) flow through to the result unchanged."""
    daily = [_mk("HPG", score=5, thesis="banks leading", target=30, stop=25)]
    ranker = [_mk("HPG", score=1, thesis="ranker thinks so too", sector_code="BANK")]

    merged = merge_pick_sources(daily, ranker)

    assert merged[0]["source"] == "BOTH"
    # Daily Pass comes first, so its fields win on collision.
    assert merged[0]["thesis"] == "banks leading"
    assert merged[0]["target"] == 30
    assert merged[0]["stop"] == 25
    # Daily side did NOT carry sector_code; it must not leak from ranker side
    # (merge only tags source, it does not cross-pollinate fields).
    assert "sector_code" not in merged[0]


def test_input_lists_are_not_mutated():
    """Merge must not mutate its inputs — callers rely on being able to
    reuse the daily / ranker lists for other rendering passes."""
    d1 = _mk("A", score=5)
    r1 = _mk("A", score=1)
    daily = [d1]
    ranker = [r1]

    _ = merge_pick_sources(daily, ranker)

    # Originals must stay free of the "source" key.
    assert "source" not in d1
    assert "source" not in r1


def test_missing_score_defaults_to_zero_for_sort():
    """Pick without a score must sort as if score=0 (tiebreaker behaviour)."""
    daily = [_mk("A"), _mk("B", score=5)]
    ranker: list[dict] = []

    merged = merge_pick_sources(daily, ranker)

    # B (score=5) comes first, A (no score → 0) second.
    assert [p["symbol"] for p in merged] == ["B", "A"]
