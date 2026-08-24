"""Two number formatters shared by the charts and the prose.

Separate from `charts.py` because `fmtM` is used in the narrative, the sector
table and the plain-text email body — importing matplotlib to format a number
would be absurd.
"""
from __future__ import annotations

__all__ = ["fmtM", "fmtNum"]


def fmtM(x: float | None) -> str:
    """VND with a magnitude suffix and an explicit sign.

    The sign is not decoration: every caller is showing a *flow*, and a flow
    without a direction is not a number anyone can act on.
    """
    if x is None:
        return "n/a"
    if abs(x) >= 1e9:
        return f"{x / 1e9:+.2f}B"
    if abs(x) >= 1e6:
        return f"{x / 1e6:+.2f}M"
    return f"{x:+,.0f}"


def fmtNum(x: float | None, pattern: str = "{:,.2f}") -> str:
    """Format or "n/a" — never crash the report on a missing macro anchor."""
    return pattern.format(x) if x is not None else "n/a"
