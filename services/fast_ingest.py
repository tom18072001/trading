"""Fast incremental ingest — bypasses vnstock entirely.

Uses VCI TradingView API for OHLCV and VNDirect API for foreign flow.
Designed for the manual "Refresh" button: fetches only missing dates,
completes in ~15-30s for all 15 sectors.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import requests
from sqlalchemy.orm import Session

from config import PROXY_BASKETS, SECTORS
from database.models import SectorFlowDaily

VCI_URL = "https://histdatafeed.vps.com.vn/tradingview/history"
VNDIRECT_URL = "https://api-finfo.vndirect.com.vn/v4/foreigns"


def _last_trading_day() -> str:
    """Return the most recent weekday (Mon-Fri) as YYYY-MM-DD.
    If today is Sat/Sun, returns Friday."""
    d = datetime.now()
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _fetch_ohlcv_vci(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch daily OHLCV via VCI TradingView endpoint. Fast, no rate limit."""
    try:
        start_ts = int(pd.Timestamp(start).timestamp())
        end_ts = int(pd.Timestamp(end + " 23:59:59").timestamp())
        r = requests.get(VCI_URL, params={
            "symbol": symbol, "resolution": "D",
            "from": start_ts, "to": end_ts,
        }, timeout=10)
        r.raise_for_status()
        d = r.json()
        if d.get("s") == "no_data" or "c" not in d or "t" not in d:
            return pd.DataFrame()
        dates = pd.to_datetime(d["t"], unit="s")
        df = pd.DataFrame({
            "open": d["o"], "high": d["h"], "low": d["l"],
            "close": d["c"], "volume": d["v"],
        }, index=dates).astype(float)
        return df
    except Exception:
        return pd.DataFrame()


def _fetch_foreign_vndirect(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch foreign buy/sell/net from VNDirect for a date range."""
    try:
        r = requests.get(VNDIRECT_URL, params={
            "q": f"code:{symbol}~tradingDate:gte:{start}~tradingDate:lte:{end}",
            "size": 200,
            "sort": "tradingDate:desc",
            "page": 1,
        }, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["tradingDate"]).dt.strftime("%Y-%m-%d")
        return df
    except Exception:
        return pd.DataFrame()


def get_freshness(session: Session) -> dict:
    """Check current DB freshness and what needs updating."""
    from sqlalchemy import func
    latest = session.query(func.max(SectorFlowDaily.date)).scalar()
    last_td = _last_trading_day()
    today = datetime.now().strftime("%Y-%m-%d")
    is_weekend = datetime.now().weekday() >= 5

    # Count how many dates are missing
    if latest:
        latest_dt = pd.Timestamp(latest)
        target_dt = pd.Timestamp(last_td)
        gap_days = (target_dt - latest_dt).days
    else:
        gap_days = 0

    return {
        "latest_date": latest,
        "last_trading_day": last_td,
        "today": today,
        "is_weekend": is_weekend,
        "is_fresh": latest == last_td or (is_weekend and latest == last_td),
        "gap_days": max(0, gap_days),
    }


def incremental_ingest(session: Session, progress_cb=None) -> dict:
    """Fetch only missing dates for all 15 sectors. Returns report dict.

    Uses VCI for OHLCV (no rate limit, ~0.3s/symbol) and VNDirect for foreign.
    Total: 75 OHLCV calls + 75 foreign calls ≈ 15-30s.

    progress_cb(sector_code, step, total_steps) called for UI updates.
    """
    from analysis.flow_aggregation import aggregate_sector
    from sqlalchemy import func

    freshness = get_freshness(session)
    if freshness["is_fresh"]:
        return {"status": "already_fresh", **freshness}

    latest_date = freshness["latest_date"]
    last_td = freshness["last_trading_day"]

    # Fetch window: from (latest - 120d) for rolling stats, but only INSERT new dates
    start_fetch = (pd.Timestamp(latest_date) - timedelta(days=120)).strftime("%Y-%m-%d")
    end_fetch = last_td

    codes = list(SECTORS.keys())
    total_steps = len(codes)
    report = {
        "status": "updated",
        "latest_date_before": latest_date,
        "sectors": {},
        "total_new_rows": 0,
    }

    for step_i, code in enumerate(codes):
        if progress_cb:
            progress_cb(code, step_i + 1, total_steps)

        symbols = PROXY_BASKETS.get(code, [])

        # 1) Fetch OHLCV for all constituents (parallel-ish, fast)
        constituents: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = _fetch_ohlcv_vci(sym, start_fetch, end_fetch)
            if not df.empty:
                constituents[sym] = df
            time.sleep(0.05)  # minimal politeness

        if not constituents:
            report["sectors"][code] = 0
            continue

        # 2) Fetch foreign data for the missing date range only
        foreign_by_date: dict[str, dict] = defaultdict(
            lambda: {"buy": 0.0, "sell": 0.0, "net": 0.0}
        )
        for sym in symbols:
            fdf = _fetch_foreign_vndirect(sym, latest_date, end_fetch)
            if not fdf.empty:
                for _, row in fdf.iterrows():
                    d = row["date"]
                    foreign_by_date[d]["buy"] += float(row.get("buyVal") or 0)
                    foreign_by_date[d]["sell"] += float(row.get("sellVal") or 0)
                    foreign_by_date[d]["net"] += float(row.get("netVal") or 0)
            time.sleep(0.05)

        # 3) Which dates do we have constituent bars for?
        #
        # Review 2026-08-22, P0-2: this used to subtract `existing_dates` and
        # skip anything already present. Combined with the 16:00 EOD job --
        # which wrote a row with NO close_idx -- that meant the scheduler
        # claimed each date first and this path, the only one that knows how to
        # write close_idx, then skipped it FOREVER. close_idx stayed NULL
        # permanently, which is what scripts/fix_close_idx.py,
        # scripts/backfill_close_idx.py and the STEALTH_SYNTHETIC_CLOSE flag
        # were all invented to paper over.
        #
        # It now upserts, so it can repair a date the scheduler left incomplete.
        existing_rows = {
            r.date: r for r in
            session.query(SectorFlowDaily)
            .filter_by(sector_code=code)
            .filter(SectorFlowDaily.date > latest_date)
            .all()
        }

        # Get all dates from constituents that are after latest_date
        all_dates = set()
        for df in constituents.values():
            for ts in df.index:
                d = ts.strftime("%Y-%m-%d")
                if d > latest_date:
                    all_dates.add(d)

        new_dates = sorted(all_dates)
        if not new_dates:
            report["sectors"][code] = 0
            continue

        # 4) Aggregate & write each new date
        written = 0
        for date_str in new_dates:
            # Slice constituents up to this date
            sliced = {}
            for sym, df in constituents.items():
                mask = df.index <= pd.Timestamp(date_str + " 23:59:59")
                s = df.loc[mask]
                if not s.empty:
                    sliced[sym] = s
            if len(sliced) < 2:
                continue

            # Foreign for this date
            fg = foreign_by_date.get(date_str, {"buy": 0, "sell": 0, "net": 0})
            foreign_net_map = {sym: fg["net"] / max(len(sliced), 1) for sym in sliced}
            foreign_buy_map = {sym: fg["buy"] / max(len(sliced), 1) for sym in sliced}
            foreign_sell_map = {sym: fg["sell"] / max(len(sliced), 1) for sym in sliced}

            try:
                agg = aggregate_sector(
                    code, sliced,
                    foreign_net_by_symbol=foreign_net_map,
                    foreign_buy_by_symbol=foreign_buy_map,
                    foreign_sell_by_symbol=foreign_sell_map,
                )
            except Exception:
                continue

            up_dn = (agg.up_vol / agg.down_vol) if (agg.down_vol and agg.down_vol > 0) else None

            row = existing_rows.get(date_str)
            if row is None:
                row = SectorFlowDaily(sector_code=code, date=date_str)
                session.add(row)
                existing_rows[date_str] = row

            row.net_dollar_flow = agg.net_dollar_flow
            row.foreign_net = fg["net"]
            row.foreign_buy_val = fg["buy"]
            row.foreign_sell_val = fg["sell"]
            row.up_down_vol_ratio = up_dn
            row.breadth_sma20 = agg.breadth_sma20
            row.breadth_sma50 = agg.breadth_sma50
            row.atr_pct = agg.atr_pct
            row.close_idx = agg.close_idx
            row.return_1d = agg.basket_return
            written += 1

        report["sectors"][code] = written
        report["total_new_rows"] += written

    session.commit()

    # 5) Rebuild leading features for new rows
    if report["total_new_rows"] > 0:
        _rebuild_leading_features_fast(session)

    latest_after = session.query(func.max(SectorFlowDaily.date)).scalar()
    report["latest_date_after"] = latest_after
    return report


def _rebuild_leading_features_fast(session: Session):
    """Recompute flow_z20, foreign_hit_20d, stealth_score etc for all rows."""
    from analysis.stealth import compute_leading_features

    rows = session.query(SectorFlowDaily).order_by(
        SectorFlowDaily.sector_code, SectorFlowDaily.date
    ).all()
    df = pd.DataFrame([{
        "date": r.date, "sector_code": r.sector_code,
        "net_dollar_flow": r.net_dollar_flow or 0.0,
        "foreign_net": r.foreign_net or 0.0,
        "atr_pct": r.atr_pct or 0.0,
        "close_idx": r.close_idx or 0.0,
        "breadth_sma20": r.breadth_sma20 or 0.0,
    } for r in rows])

    feat = compute_leading_features(df)
    by_key = {(r.sector_code, r.date): r for r in rows}

    for _, f in feat.iterrows():
        r = by_key.get((f["sector_code"], f["date"]))
        if r is None:
            continue
        r.flow_z20 = float(f["flow_z20"]) if pd.notna(f["flow_z20"]) else None
        r.flow_z60 = float(f["flow_z60"]) if pd.notna(f["flow_z60"]) else None
        r.foreign_streak = int(f["foreign_streak"]) if pd.notna(f["foreign_streak"]) else 0
        r.foreign_hit_20d = float(f["foreign_hit_20d"]) if pd.notna(f["foreign_hit_20d"]) else 0.0
        r.stealth_score = float(f["stealth_score"]) if pd.notna(f["stealth_score"]) else 0.0
        r.flow_price_divergence = float(f["flow_price_divergence"]) if pd.notna(f["flow_price_divergence"]) else 0.0
        r.accumulation_age = int(f["accumulation_age"])

    session.commit()


# ---------- Background job management ----------
import threading

_job_lock = threading.Lock()
_job_state: dict = {"running": False, "progress": None, "result": None}


def start_ingest_job(session_factory) -> dict:
    """Launch incremental ingest in background thread. Returns immediately."""
    with _job_lock:
        if _job_state["running"]:
            return {"status": "already_running", "progress": _job_state["progress"]}
        _job_state["running"] = True
        _job_state["progress"] = {"sector": None, "step": 0, "total": len(SECTORS)}
        _job_state["result"] = None

    def _worker():
        sess = session_factory()
        try:
            def _on_progress(sector, step, total):
                with _job_lock:
                    _job_state["progress"] = {"sector": sector, "step": step, "total": total}

            result = incremental_ingest(sess, progress_cb=_on_progress)
            with _job_lock:
                _job_state["result"] = result
                _job_state["running"] = False
        except Exception as e:
            with _job_lock:
                _job_state["result"] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
                _job_state["running"] = False
        finally:
            sess.close()

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "started", "progress": _job_state["progress"]}


def get_ingest_status() -> dict:
    """Poll current ingest job status."""
    with _job_lock:
        return {
            "running": _job_state["running"],
            "progress": _job_state["progress"],
            "result": _job_state["result"],
        }
