# ============================================
# utils/clock.py — one definition of "today" for the whole system
# ============================================
# Why this exists (review 2026-08-22, finding P1-6):
#   `config.TIMEZONE = "Asia/Ho_Chi_Minh"` was declared and used nowhere.
#   Every place that decided what day it is called a naive
#   `datetime.now()`, which reads the HOST's timezone:
#
#     services/sector_signal_service.py   publish() date
#     services/rotation_model_service.py  classify_regime() date
#     services/sector_ingest_service.py   ingest / rollup windows
#     generate_report.py                   REPORT_DATE
#
#   The 17:00 ICT publish job on a box set to UTC stamps 10:00 UTC of the
#   SAME day, which is fine — but the 09:00 ICT macro job stamps 02:00 UTC,
#   and anything running after 17:00 ICT (= 10:00 UTC) near a month
#   boundary, or on a laptop that travels, silently writes the wrong date.
#   `analysis/flow_aggregation.py` also had a fallback on
#   `pd.Timestamp.utcnow()`, mixing two frames of reference in one table.
#
#   Market data is dated in exchange-local time. So is the trading day.
#   Everything that needs "today" goes through here.

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import TIMEZONE, VN_MARKET_HOLIDAYS_2026

MARKET_TZ = ZoneInfo(TIMEZONE)


def now() -> datetime:
    """Current wall-clock time in the exchange's timezone (tz-aware)."""
    return datetime.now(MARKET_TZ)


def today() -> date:
    """Today's calendar date in the exchange's timezone."""
    return now().date()


def today_str() -> str:
    """Today's date as YYYY-MM-DD in the exchange's timezone."""
    return today().isoformat()


def is_trading_day(d: date | None = None) -> bool:
    """Weekday and not a published HOSE holiday."""
    d = d or today()
    if d.weekday() >= 5:            # 5 = Saturday, 6 = Sunday
        return False
    return d.isoformat() not in set(VN_MARKET_HOLIDAYS_2026)


def closed_today() -> str | None:
    """Today's date (ISO) if the exchange has no session today, else None.

    The scheduled jobs are registered `-Daily` (CLAUDE.md §8), so they also run
    on weekends and holidays; 14 of 62 published signal dates were such days,
    each a copy of the last session under a new date (review 2026-09-24
    §4.1/11). Publishers ask this before writing a dated row. One seam, so the
    test suite pins the calendar in one place (`tests/conftest.py`).
    """
    d = today()
    return None if is_trading_day(d) else d.isoformat()


def previous_trading_day(d: date | None = None) -> date:
    """The most recent trading day strictly before `d`."""
    d = d or today()
    probe = d - timedelta(days=1)
    for _ in range(14):             # a VN Tet break is at most ~9 days
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return probe


def next_trading_day(d: date | None = None, n: int = 1) -> date:
    """The n-th trading day strictly after `d`.

    The mirror of previous_trading_day, and the reason it exists: "when does
    the 4-8 week sell window open" is a count of SESSIONS, not of calendar days.
    `DailyInsightPage.tsx` once did `setDate(+3)`, so a Thursday buy claimed a
    Sunday sell date; 20 calendar days is not 20 sessions either.
    """
    d = d or today()
    probe = d
    for _ in range(n):
        probe += timedelta(days=1)
        for _ in range(14):         # a VN Tet break is at most ~9 days
            if is_trading_day(probe):
                break
            probe += timedelta(days=1)
    return probe


def sessions_between(start: date, end: date | None = None) -> int:
    """Trading days from `start` (exclusive) to `end` (inclusive). Never negative."""
    end = end or today()
    if end <= start:
        return 0
    n, probe = 0, start
    while probe < end:
        probe += timedelta(days=1)
        if is_trading_day(probe):
            n += 1
    return n


def to_market_date(value) -> date:
    """Coerce a datetime / date / 'YYYY-MM-DD' string to a market-local date.

    A naive datetime is assumed to already be market-local (that is how every
    row written before this module existed was stamped). An aware datetime is
    converted properly.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(MARKET_TZ).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def to_market_date_str(value) -> str:
    return to_market_date(value).isoformat()
