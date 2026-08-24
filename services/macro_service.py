# ============================================
# services/macro_service.py
# ============================================
# Hourly macro anchor ingestion. Best-effort: any source that fails is
# silently skipped — the row is still written with the values that did load.

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from database.models import MacroAnchor

log = logging.getLogger(__name__)

# VNINDEX has never traded near this level (all-time low ~130 in 2001, >900
# since 2020). Anything below it is a wrong symbol, not a crash — which is
# exactly how KBS's ~1.79 answer got written into 613 of 623 rows.
VNINDEX_MIN_PLAUSIBLE = 200.0


def fetch_vnindex_daily(days: int = 180) -> pd.Series:
    """Daily VNINDEX close series from vnstock, date-indexed (ascending).

    Returns an empty Series on failure. Used by the regime classifier as a
    self-sufficient market-state input — the hourly macro_anchors table is
    unreliable in this environment (external FX/commodity/rate sources are
    network-blocked; only vnstock is reachable). (2026-06-19)

    2026-08-24: hardened, but this path was NOT the source of the bad data —
    it asks for a date range and returns correct index levels from either
    source (measured: KBS 1784.24, VCI 1784.29 on 2026-08-24). The ~1.79 rows
    in `macro_anchors` came from `MacroService._fetch_vnindex`, which asked for
    a single day. The fallback ladder and the plausibility floor are here so a
    future source swap cannot poison the classifier silently.
    """
    try:
        from utils.vn_api import quote_history
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        for source in ("VCI", None):        # None = config.DATA_SOURCE
            df = quote_history("VNINDEX", start, end, interval="1D", source=source)
            if df is None or df.empty or "close" not in df.columns:
                continue
            df = df.copy()
            df["time"] = pd.to_datetime(df["time"])
            s = df.set_index("time")["close"].astype(float).sort_index()
            if s.median() < VNINDEX_MIN_PLAUSIBLE:
                log.warning("[macro] source %s returned a median of %.2f for VNINDEX — "
                            "not an index level, ignoring", source or "default", s.median())
                continue
            s.name = "vnindex"
            return s
        return pd.Series(dtype=float)
    except Exception as e:
        log.warning("[macro] fetch_vnindex_daily failed: %s", e)
        return pd.Series(dtype=float)


class MacroService:
    def __init__(self, session: Session):
        self.session = session

    def _fetch_vnindex(self) -> Optional[float]:
        """Last VNINDEX close.

        Fixed 2026-08-24. `macro_anchors.vnindex` is **1.82 on 613 of its 623
        rows** — every row between 2026-04-16 and 2026-08-23. Two causes, and
        the second is what made one bad fetch permanent:

        1. **Window.** It asked for `today..today`. A single-day request is the
           fragile case: empty on a weekend or holiday, and apparently able to
           return some other instrument's price when the index has not printed.
           A 10-day window is asking the same question with room to fail on.
        2. **Carry-forward amplification.** `ingest_now` reuses the previous
           value when a fetch returns None — correct for a *missing* value, but
           it cannot tell a missing value from a wrong one. So the single bad
           1.82 read on 2026-04-16 was copied forward 613 times. A guard on the
           fetch is the only place to stop that; carry-forward is downstream of
           the mistake.

        The sanity floor is the guard: VNINDEX has never traded below 200, so
        1.82 can only be wrong. Returning None makes carry-forward keep the
        last *good* value instead of laundering a bad one into the series.

        Source order is belt-and-braces. Both KBS and VCI answer correctly when
        given a range, so this is not a fix for a wrong source — it is a second
        chance when the first returns nothing.

        ponytail: the 613 existing rows are left as-is. Nothing reads this
        column — `classify_regime` overwrites `macro_df` with
        `fetch_vnindex_daily()` before use — so a backfill would be tidying,
        not repair. Backfill it if anything ever starts reading it.
        """
        from datetime import timedelta

        end = datetime.now()
        start = end - timedelta(days=10)     # cover a long holiday
        for source in ("VCI", None):         # None = config.DATA_SOURCE
            try:
                from utils.vn_api import quote_history
                df = quote_history(
                    "VNINDEX",
                    start.strftime("%Y-%m-%d"),
                    end.strftime("%Y-%m-%d"),
                    interval="1D",
                    source=source,
                )
                if df is not None and not df.empty:
                    v = float(df["close"].iloc[-1])
                    if v >= VNINDEX_MIN_PLAUSIBLE:
                        return v
                    log.warning("[macro] source %s returned %.2f for VNINDEX — "
                                "not an index level, ignoring", source or "default", v)
            except Exception as e:
                log.warning("[macro] VNINDEX fetch via %s failed: %s", source or "default", e)
        return None

    def _fetch_yahoo(self, ticker: str) -> Optional[float]:
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception:
            return None

    def _fetch_fred(self, series_id: str) -> Optional[float]:
        try:
            import urllib.request, json, os
            api_key = os.environ.get("FRED_API_KEY", "")
            if not api_key:
                return None
            url = (
                f"https://api.stlouisfed.org/fred/series/observations?"
                f"series_id={series_id}&api_key={api_key}&file_type=json&limit=1&sort_order=desc"
            )
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read())
            obs = data.get("observations", [])
            if obs and obs[0]["value"] not in (".", ""):
                return float(obs[0]["value"])
        except Exception:
            return None
        return None

    def ingest_now(self) -> MacroAnchor:
        # Carry-forward: external FX/commodity/rate sources (yfinance/FRED) are
        # frequently unreachable here. A None fetch must NOT clobber the last
        # known value with a null row — reuse the most recent non-null instead,
        # so the series stays usable for the regime classifier. (2026-06-19)
        prev = (
            self.session.query(MacroAnchor)
            .order_by(MacroAnchor.time.desc())
            .first()
        )

        def _cf(fetched: Optional[float], attr: str) -> Optional[float]:
            if fetched is not None:
                return fetched
            return getattr(prev, attr, None) if prev is not None else None

        row = MacroAnchor(
            time=datetime.utcnow(),
            vnindex=_cf(self._fetch_vnindex(), "vnindex"),
            usdvnd=_cf(self._fetch_yahoo("USDVND=X"), "usdvnd"),
            brent=_cf(self._fetch_yahoo("BZ=F"), "brent"),
            us10y=_cf(self._fetch_fred("DGS10"), "us10y"),
            gold=_cf(self._fetch_yahoo("GC=F"), "gold"),
        )
        self.session.add(row)
        self.session.commit()
        return row
