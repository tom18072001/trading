# ============================================
# services/sector_ingest_service.py
# ============================================
# Pulls proxy basket OHLCV from vnstock, computes sector aggregates,
# writes to sector_flow_ts. Raw constituent data is NOT persisted —
# the in-memory frames are aggregated then dropped.

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd
from sqlalchemy.orm import Session

from analysis.flow_aggregation import aggregate_sector
from config import PROXY_BASKETS, SECTORS
from database.models import SectorFlowDaily, SectorFlowTS
from utils.clock import now as market_now, to_market_date_str, today_str
from utils.vnstock_gate import call as gated_call


class SectorIngestService:
    def __init__(self, session: Session):
        self.session = session

    # ----- vnstock fetch (best effort, falls back to synthetic) -----
    # 2026-08-22: every outbound call now goes through utils.vnstock_gate,
    # which enforces the KBS ~20 req/min ceiling and backs off on a 429
    # instead of sprinting through the remaining symbols. The old code
    # paced by SYMBOL (time.sleep 3.2s) while spending TWO calls per
    # symbol, so it ran at ~37 calls/min and rate-limited every run.
    def _fetch_constituent_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        def _pull():
            from utils.vn_api import quote_history
            return quote_history(symbol, start, end, interval="1D")

        df = gated_call(_pull, what=f"history {symbol}")
        if df is None or df.empty:
            return pd.DataFrame()
        try:
            df = df.rename(columns=str.lower)
            if "time" in df.columns:
                df = df.set_index(pd.to_datetime(df["time"]))
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            # 2026-06-18 fix: vnstock (KBS) intermittently returns the latest
            # trading-day bar TWICE. A duplicated trailing row makes
            # close == prev_close → sign(tick)=0 → net_dollar_flow/up/down all
            # collapse to 0 in flow_aggregation. Drop dup index, keep last.
            return df[~df.index.duplicated(keep="last")].sort_index()
        except BaseException as e:
            print(f"[ingest] vnstock shape/parse fail {symbol}: {e}")
            return pd.DataFrame()

    # ----- foreign flow -----------------------------------------------
    # 2026-08-23: this used to parse vnstock's price_board directly and it
    # returned 0 for every symbol on every run since the day it was written --
    # sector_flow_ts holds 0 non-zero foreign rows out of 12,175. KBS exposes
    # foreign_buy_volume / foreign_sell_volume (share counts) but no *_value
    # column, and the volume x price conversion could not find a price column,
    # so it silently produced 0.0. Moved to services/foreign_flow, which reads
    # VNDirect (VND values directly, plus history) and raises instead of
    # returning a zero it cannot stand behind.

    def _fetch_foreign(self, symbol: str) -> tuple[float, float, float]:
        """Latest session's (buy_val, sell_val, net_val) for one symbol."""
        from services import foreign_flow

        try:
            return foreign_flow.fetch_latest(symbol)
        except foreign_flow.ForeignFlowUnavailable as e:
            print(f"[ingest] foreign unavailable for {symbol}: {e}")
        except Exception as e:
            print(f"[ingest] foreign fetch failed for {symbol}: {type(e).__name__}: {e}")

        # Fallback: the old price_board route, now loud when it cannot work.
        def _pull():
            from utils.vn_api import price_board
            return price_board([symbol])

        board = gated_call(_pull, what=f"price_board {symbol}")
        if board is None:
            return 0.0, 0.0, 0.0
        try:
            return foreign_flow.from_price_board(board)
        except Exception as e:
            print(f"[ingest] price_board foreign fallback failed for {symbol}: {e}")
            return 0.0, 0.0, 0.0

    # Back-compat thin wrappers (kept in case other callers import them).
    def _fetch_foreign_net(self, symbol: str) -> float:
        return self._fetch_foreign(symbol)[2]

    def _fetch_foreign_buy_sell(self, symbol: str) -> tuple[float, float]:
        b, s, _ = self._fetch_foreign(symbol)
        return b, s

    # ----- ingestion -----
    def ingest_intraday_now(self, sector_codes: Iterable[str] | None = None) -> int:
        """Fetch latest daily bar for each constituent, aggregate, write
        one sector_flow_ts row per sector. Returns number of rows written.
        """
        codes = list(sector_codes) if sector_codes else list(SECTORS.keys())
        end = today_str()
        # Use 60d window so SMA20/50/ATR14 work
        from datetime import timedelta
        start = (market_now() - timedelta(days=120)).strftime("%Y-%m-%d")

        written = 0
        for code in codes:
            symbols = PROXY_BASKETS.get(code, [])
            constituents = {}
            foreign = {}
            foreign_buy: dict[str, float] = {}
            foreign_sell: dict[str, float] = {}
            for sym in symbols:
                df = self._fetch_constituent_daily(sym, start, end)
                if not df.empty:
                    constituents[sym] = df
                    fb, fs, fnet = self._fetch_foreign(sym)
                    foreign[sym] = fnet
                    foreign_buy[sym] = fb
                    foreign_sell[sym] = fs
                # No manual sleep here any more: utils.vnstock_gate paces by
                # CALL, which is the unit the API actually meters.

            if not constituents:
                continue

            agg = aggregate_sector(
                code, constituents,
                foreign_net_by_symbol=foreign,
                foreign_buy_by_symbol=foreign_buy,
                foreign_sell_by_symbol=foreign_sell,
            )
            ts = pd.Timestamp(agg.time).to_pydatetime()
            existing = (
                self.session.query(SectorFlowTS)
                .filter_by(sector_code=code, time=ts)
                .one_or_none()
            )
            if existing is None:
                self.session.add(SectorFlowTS(
                    sector_code=code, time=ts,
                    net_dollar_flow=agg.net_dollar_flow, up_vol=agg.up_vol, down_vol=agg.down_vol,
                    foreign_net=agg.foreign_net,
                    foreign_buy_val=agg.foreign_buy_val,
                    foreign_sell_val=agg.foreign_sell_val,
                    foreign_intensity=agg.foreign_intensity,
                    breadth_sma20=agg.breadth_sma20,
                    breadth_sma50=agg.breadth_sma50, atr_pct=agg.atr_pct,
                    close_idx=agg.close_idx, basket_return=agg.basket_return,
                ))
            else:
                existing.net_dollar_flow = agg.net_dollar_flow
                existing.up_vol = agg.up_vol
                existing.down_vol = agg.down_vol
                existing.foreign_net = agg.foreign_net
                existing.foreign_buy_val = agg.foreign_buy_val
                existing.foreign_sell_val = agg.foreign_sell_val
                existing.foreign_intensity = agg.foreign_intensity
                existing.breadth_sma20 = agg.breadth_sma20
                existing.breadth_sma50 = agg.breadth_sma50
                existing.atr_pct = agg.atr_pct
                existing.close_idx = agg.close_idx
                existing.basket_return = agg.basket_return
            written += 1
        self.session.commit()
        return written

    # ----- 2y backfill: one sector at a time, one row per day -----
    def backfill_sector(self, code: str, years: int = 2) -> int:
        from datetime import timedelta
        from analysis.flow_aggregation import aggregate_sector
        end = today_str()
        start = (market_now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
        symbols = PROXY_BASKETS.get(code, [])
        if not symbols:
            return 0
        from services import foreign_flow

        constituents: dict[str, pd.DataFrame] = {}
        # date -> {symbol: net_val}. Backfill used to pass an EMPTY foreign map
        # (aggregate_sector(..., foreign_net_by_symbol={})), so every row it
        # wrote had foreign_net = 0 -- and then the nightly price_board path
        # wrote zeros too, which is how the "killer VN signal" ended up
        # contributing nothing. VNDirect serves this per date, so use it.
        foreign_by_date: dict[str, dict[str, float]] = {}
        for sym in symbols:
            df = self._fetch_constituent_daily(sym, start, end)
            if not df.empty:
                constituents[sym] = df
            hist = foreign_flow.fetch_history(sym, start, end)
            for _, fr in hist.iterrows():
                foreign_by_date.setdefault(fr["date"], {})[sym] = float(fr["net_val"])
            # pacing handled by utils.vnstock_gate
        if not constituents:
            return 0
        # Find common date index
        idx = None
        for df in constituents.values():
            idx = df.index if idx is None else idx.union(df.index)
        idx = sorted(set(idx))  # type: ignore
        # Existing timestamps to skip (incremental)
        have = {
            r.time for r in self.session.query(SectorFlowTS.time).filter_by(sector_code=code).all()
        }
        written = 0
        for day in idx:
            ts = pd.Timestamp(day).to_pydatetime()
            if ts in have:
                continue
            # Build per-symbol slice up to `day` inclusive for rolling stats
            sliced = {s: df.loc[:day] for s, df in constituents.items() if not df.loc[:day].empty}
            if len(sliced) < 2:
                continue
            try:
                agg = aggregate_sector(
                    code, sliced,
                    foreign_net_by_symbol=foreign_by_date.get(ts.strftime("%Y-%m-%d"), {}),
                )
            except Exception:
                continue
            self.session.add(SectorFlowTS(
                sector_code=code, time=ts,
                net_dollar_flow=agg.net_dollar_flow, up_vol=agg.up_vol, down_vol=agg.down_vol,
                foreign_net=agg.foreign_net, breadth_sma20=agg.breadth_sma20,
                breadth_sma50=agg.breadth_sma50, atr_pct=agg.atr_pct,
                close_idx=agg.close_idx, basket_return=agg.basket_return,
            ))
            # Also write a daily rollup row
            up_dn = (agg.up_vol / agg.down_vol) if (agg.down_vol and agg.down_vol > 0) else None
            date_str = ts.strftime("%Y-%m-%d")
            existing_daily = (
                self.session.query(SectorFlowDaily)
                .filter_by(sector_code=code, date=date_str).one_or_none()
            )
            if existing_daily is None:
                self.session.add(SectorFlowDaily(
                    sector_code=code, date=date_str,
                    net_dollar_flow=agg.net_dollar_flow, foreign_net=agg.foreign_net,
                    up_down_vol_ratio=up_dn, breadth_sma20=agg.breadth_sma20,
                    breadth_sma50=agg.breadth_sma50, atr_pct=agg.atr_pct,
                    close_idx=agg.close_idx, return_1d=agg.basket_return,
                ))
            written += 1
        self.session.commit()
        return written

    def rollup_to_daily(self, date: str | None = None) -> int:
        """Roll each sector's latest intraday bar into `sector_flow_daily`.

        Review 2026-08-22, P0-1 -- the previous version took the newest
        `sector_flow_ts` row per sector and wrote it under TODAY's date without
        ever checking what day that row belonged to. When the intraday job was
        rate-limited (see the post-mortem in utils/vnstock_gate.py) or the
        market was shut, the prior session's numbers were re-stamped as a new
        session. A repeated flat value collapses the rolling std in
        `analysis.stealth._rolling_z`, which inflates flow_z20 and fires
        stealth triggers that never happened; the ML target is then computed
        across duplicated bars.

        The row's own timestamp now decides its date. Passing `date`
        restricts the rollup to bars from that day and skips sectors that have
        none -- a missing row is recoverable, a wrong one is not.

        Also P3-4: this used to load the entire sector_flow_ts table into
        memory (`.all()` with no filter) just to find one row per sector.
        """
        target = date  # None = "whatever day each sector's latest bar is on"

        written = 0
        skipped: list[str] = []
        for code in SECTORS:
            q = self.session.query(SectorFlowTS).filter(SectorFlowTS.sector_code == code)
            if target is not None:
                # SectorFlowTS.time is a naive market-local datetime; bars are
                # stamped at the bar's own open, so a half-open day window is
                # the correct filter.
                day_start = datetime.fromisoformat(target)
                day_end = day_start + timedelta(days=1)
                q = q.filter(SectorFlowTS.time >= day_start, SectorFlowTS.time < day_end)
            r = q.order_by(SectorFlowTS.time.desc()).first()
            if r is None:
                skipped.append(code)
                continue

            row_date = to_market_date_str(r.time)
            if target is not None and row_date != target:
                skipped.append(code)
                continue

            up_dn = (r.up_vol / r.down_vol) if (r.down_vol and r.down_vol > 0) else None

            # return_1d: prefer the split-safe basket return computed at
            # aggregation time; fall back to a close_idx ratio against the
            # previous daily row only when the bar predates migration 11.
            ret_1d = r.basket_return
            if ret_1d is None and r.close_idx:
                prev = (
                    self.session.query(SectorFlowDaily)
                    .filter(SectorFlowDaily.sector_code == code,
                            SectorFlowDaily.date < row_date,
                            SectorFlowDaily.close_idx.isnot(None),
                            SectorFlowDaily.close_idx > 0)
                    .order_by(SectorFlowDaily.date.desc())
                    .first()
                )
                if prev is not None:
                    ret_1d = r.close_idx / prev.close_idx - 1.0

            existing = (
                self.session.query(SectorFlowDaily)
                .filter_by(sector_code=code, date=row_date).one_or_none()
            )
            if existing is None:
                existing = SectorFlowDaily(sector_code=code, date=row_date)
                self.session.add(existing)

            existing.net_dollar_flow = r.net_dollar_flow
            existing.foreign_net = r.foreign_net
            existing.foreign_buy_val = r.foreign_buy_val
            existing.foreign_sell_val = r.foreign_sell_val
            existing.foreign_intensity = r.foreign_intensity
            existing.up_down_vol_ratio = up_dn
            existing.breadth_sma20 = r.breadth_sma20
            existing.breadth_sma50 = r.breadth_sma50
            existing.atr_pct = r.atr_pct
            # P0-2: the scheduled path now carries price through. These three
            # columns feed the ML target, stealth condition 5 and the backtest
            # P&L, and used to be filled only by the UI-triggered fast_ingest.
            if r.close_idx is not None:
                existing.close_idx = r.close_idx
            if ret_1d is not None:
                existing.return_1d = ret_1d
            written += 1

        if skipped:
            print(f"[ingest] rollup skipped {len(skipped)} sector(s) with no bar"
                  f"{' for ' + target if target else ''}: {', '.join(skipped)}")

        self.session.commit()
        return written
