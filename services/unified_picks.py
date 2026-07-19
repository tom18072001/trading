"""Unified Picks — deterministic union-merge of pick sources (SecV5).

Motivation
----------
Daily Insight (``/api/insight/daily``) and the SecV4 email were recommending
different tickers because they read from different pipelines:

* Daily Insight renders ``snapshot.top_buys`` / ``snapshot.top_sells`` from
  :mod:`services.picks_universe_service` directly — no ranker gate.
* SecV4 email filtered picks through ``SectorSignal.action ∈ {BUY,
  ACCUMULATE}`` and dropped everything when the ranker stayed silent.

SecV5's ``generate_secv5.py`` unifies both sources via :func:`merge_pick_sources`
in this module so the email and dashboard always agree. Each merged entry is
tagged with its origin:

* ``BOTH``          — symbol present in BOTH sides (consensus, highest conviction).
* ``DAILY_INSIGHT`` — symbol only in ``snapshot.top_buys``.
* ``RANKER``        — symbol only surfaced by the ranker gate.

This module is intentionally free of DB / vnstock imports so the merge rule can
be unit-tested in isolation.
"""
from __future__ import annotations

from typing import Any, Iterable

_SOURCE_ORDER: dict[str, int] = {"BOTH": 0, "DAILY_INSIGHT": 1, "RANKER": 2}


def merge_pick_sources(
    daily_side: "Iterable[dict[str, Any]]",
    ranker_side: "Iterable[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    """Merge two pick-source lists into one, de-duped by ``symbol``.

    Parameters
    ----------
    daily_side:
        Picks from the Daily Insight side (``snapshot.top_buys`` /
        ``snapshot.top_sells``). Each entry is a dict with at minimum a
        ``symbol`` key. If an entry carries a ``score`` key it is used for
        the intra-bucket sort (descending).
    ranker_side:
        Ranker-gated picks (BUY/ACCUMULATE or SELL, one-or-more per sector).
        Same dict shape.

    Returns
    -------
    list[dict]
        A new list containing one entry per unique symbol, with an added
        ``source`` key ∈ ``{"BOTH", "DAILY_INSIGHT", "RANKER"}``.

        Stable ordering: ``BOTH`` first, then ``DAILY_INSIGHT``, then
        ``RANKER``. Within each bucket, entries are sorted by ``score``
        descending (missing score → 0).

        Input dicts are not mutated — the returned entries are shallow
        copies with the new ``source`` key.
    """
    # Materialize so we can scan twice without surprises on exhausted iterators.
    daily_list: list[dict[str, Any]] = [dict(p) for p in daily_side]
    ranker_list: list[dict[str, Any]] = [dict(p) for p in ranker_side]

    daily_syms = {p["symbol"] for p in daily_list}
    ranker_syms = {p["symbol"] for p in ranker_list}

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Pass A — Daily Insight side. Consensus picks (also in ranker) → BOTH,
    # otherwise DAILY_INSIGHT.
    for p in daily_list:
        sym = p["symbol"]
        p["source"] = "BOTH" if sym in ranker_syms else "DAILY_INSIGHT"
        merged.append(p)
        seen.add(sym)

    # Pass B — ranker-only picks.
    for p in ranker_list:
        sym = p["symbol"]
        if sym in seen:
            continue
        p["source"] = "RANKER"
        merged.append(p)
        seen.add(sym)

    # Stable sort: source order, then score desc.
    merged.sort(
        key=lambda p: (
            _SOURCE_ORDER.get(p.get("source", ""), 9),
            -(p.get("score") or 0),
        )
    )
    return merged


__all__ = ["merge_pick_sources"]
