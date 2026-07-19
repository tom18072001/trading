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


def fetch_vnindex_daily(days: int = 180) -> pd.Series:
    """Daily VNINDEX close series from vnstock, date-indexed (ascending).

    Returns an empty Series on failure. Used by the regime classifier as a
    self-sufficient market-state input — the hourly macro_anchors table is
    unreliable in this environment (external FX/commodity/rate sources are
    network-blocked; only vnstock/KBS is reachable). Index level scale is
    irrelevant to the classifier, which works on pct_change. (2026-06-19)
    """
    try:
        from vnstock import Vnstock
        from config import DATA_SOURCE
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        idx = Vnstock().stock(symbol="VNINDEX", source=DATA_SOURCE)
        df = idx.quote.history(start=start, end=end, interval="1D")
        if df is None or df.empty or "close" not in df.columns:
            return pd.Series(dtype=float)
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"])
        s = df.set_index("time")["close"].astype(float).sort_index()
        s.name = "vnindex"
        return s
    except Exception as e:
        log.warning("[macro] fetch_vnindex_daily failed: %s", e)
        return pd.Series(dtype=float)


class MacroService:
    def __init__(self, session: Session):
        self.session = session

    def _fetch_vnindex(self) -> Optional[float]:
        try:
            from vnstock import Vnstock
            from config import DATA_SOURCE
            idx = Vnstock().stock(symbol="VNINDEX", source=DATA_SOURCE)
            df = idx.quote.history(
                start=(datetime.now()).strftime("%Y-%m-%d"),
                end=datetime.now().strftime("%Y-%m-%d"),
                interval="1D",
            )
            if df is not None and not df.empty:
                return float(df["close"].iloc[-1])
        except Exception:
            return None
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
