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


def previous_trading_day(d: date | None = None) -> date:
    """The most recent trading day strictly before `d`."""
    d = d or today()
    probe = d - timedelta(days=1)
    for _ in range(14):             # a VN Tet break is at most ~9 days
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return probe


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
