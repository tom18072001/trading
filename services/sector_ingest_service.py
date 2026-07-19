# ============================================
# services/sector_ingest_service.py
# ============================================
# Pulls proxy basket OHLCV from vnstock, computes sector aggregates,
# writes to sector_flow_ts. Raw constituent data is NOT persisted —
# the in-memory frames are aggregated then dropped.

from __future__ import annotations

import time
from datetime import datetime
from typing import Iterable

import pandas as pd
from sqlalchemy.orm import Session

from analysis.flow_aggregation import aggregate_sector
from config import PROXY_BASKETS, SECTORS, START_DATE, END_DATE, DATA_SOURCE
from database.models import SectorFlowDaily, SectorFlowTS


class SectorIngestService:
    def __init__(self, session: Session):
        self.session = session

    # ----- vnstock fetch (best effort, falls back to synthetic) -----
    def _fetch_constituent_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        try:
            from vnstock import Vnstock
            stock = Vnstock().stock(symbol=symbol, source=DATA_SOURCE)
            df = stock.quote.history(start=start, end=end, interval="1D")
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.rename(columns=str.lower)
            if "time" in df.columns:
                df = df.set_index(pd.to_datetime(df["time"]))
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            # 2026-06-18 fix: vnstock (KBS) intermittently returns the latest
            # trading-day bar TWICE. A duplicated trailing row makes
            # close == prev_close → sign(tick)=0 → net_dollar_flow/up/down all
            # collapse to 0 in flow_aggregation. Drop dup index, keep last.
            df = df[~df.index.duplicated(keep="last")].sort_index()
            return df
        except SystemExit as e:
            print(f"[ingest] vnstock rate-limit SystemExit {symbol}: {e}")
            return pd.DataFrame()
        except BaseException as e:
            print(f"[ingest] vnstock fail {symbol}: {e}")
            return pd.DataFrame()

    # ----- foreign-flow parsing (2026-06-18 rewrite) --------------------
    # KBS `price_board` exposes foreign_buy_volume / foreign_sell_volume
    # (SHARE COUNTS), NOT *_value. The old code only looked for *_value
    # columns → returned 0 for every symbol since 2026-04-16 → cond2_foreign
    # failed for all 15 sectors → ACCUMULATE could never fire.
    #
    # This parser: (1) uses *_value columns if present; (2) otherwise converts
    # *_volume × price → value. Column names are matched fuzzily because
    # vnstock flattens MultiIndex price_board frames with varying prefixes
    # (e.g. "foreign.buy_volume", "match.match_price").
    @staticmethod
    def _flatten_board(df: pd.DataFrame) -> dict[str, object]:
        """Map lowercased flattened column-name → original column key."""
        out: dict[str, object] = {}
        for c in df.columns:
            name = "_".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
            out[name.lower()] = c
        return out

    @classmethod
    def _parse_foreign_board(cls, df: pd.DataFrame) -> tuple[float, float, float]:
        """Return (buy_val, sell_val, net_val) from a price_board frame."""
        if df is None or df.empty:
            return 0.0, 0.0, 0.0
        flat = cls._flatten_board(df)
        row = df.iloc[0]

        def pick(*substrs: str) -> float | None:
            for low, orig in flat.items():
                if all(s in low for s in substrs):
                    try:
                        v = row[orig]
                        if v is not None and not pd.isna(v):
                            return float(v)
                    except (TypeError, ValueError, KeyError):
                        continue
            return None

        # (1) direct value columns
        buy = pick("foreign", "buy", "val")
        sell = pick("foreign", "sell", "val")
        net = pick("foreign", "net", "val")

        # (2) fallback: volume × price
        if (buy in (None, 0.0)) and (sell in (None, 0.0)):
            price = None
            for low, orig in flat.items():
                if (("match" in low and "price" in low) or low.endswith("close")
                        or "last_price" in low or low == "price"):
                    try:
                        pv = row[orig]
                        if pv is not None and not pd.isna(pv) and float(pv) > 0:
                            price = float(pv); break
                    except (TypeError, ValueError, KeyError):
                        continue
            if price:
                bvol = pick("foreign", "buy", "vol")
                svol = pick("foreign", "sell", "vol")
                if bvol is not None:
                    buy = bvol * price
                if svol is not None:
                    sell = svol * price

        buy = buy or 0.0
        sell = sell or 0.0
        if net is None:
            net = buy - sell
        return float(buy), float(sell), float(net)

    def _fetch_foreign(self, symbol: str) -> tuple[float, float, float]:
        """Single price_board call → (buy_val, sell_val, net_val).

        Replaces the old two-call _fetch_foreign_net + _fetch_foreign_buy_sell
        (which hit price_board twice per symbol, doubling rate-limit pressure).
        """
        try:
            from vnstock import Vnstock
            stock = Vnstock().stock(symbol=symbol, source=DATA_SOURCE)
            df = stock.trading.price_board([symbol])
            return self._parse_foreign_board(df)
        except BaseException as e:
            print(f"[ingest] foreign fetch fail {symbol}: {e}")
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
        end = datetime.now().strftime("%Y-%m-%d")
        # Use 60d window so SMA20/50/ATR14 work
        from datetime import timedelta
        start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

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
                time.sleep(float(__import__("os").environ.get("INGEST_SLEEP", "3.2")))

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
            written += 1
        self.session.commit()
        return written

    # ----- 2y backfill: one sector at a time, one row per day -----
    def backfill_sector(self, code: str, years: int = 2) -> int:
        from datetime import timedelta
        from analysis.flow_aggregation import aggregate_sector
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
        symbols = PROXY_BASKETS.get(code, [])
        if not symbols:
            return 0
        constituents: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self._fetch_constituent_daily(sym, start, end)
            if not df.empty:
                constituents[sym] = df
            time.sleep(float(__import__("os").environ.get("INGEST_SLEEP", "3.2")))
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
                agg = aggregate_sector(code, sliced, foreign_net_by_symbol={})
            except Exception:
                continue
            self.session.add(SectorFlowTS(
                sector_code=code, time=ts,
                net_dollar_flow=agg.net_dollar_flow, up_vol=agg.up_vol, down_vol=agg.down_vol,
                foreign_net=agg.foreign_net, breadth_sma20=agg.breadth_sma20,
                breadth_sma50=agg.breadth_sma50, atr_pct=agg.atr_pct,
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
                ))
            written += 1
        self.session.commit()
        return written

    def rollup_to_daily(self, date: str | None = None) -> int:
        """Roll up the latest sector_flow_ts row per sector into sector_flow_daily."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        rows = (
            self.session.query(SectorFlowTS)
            .order_by(SectorFlowTS.sector_code, SectorFlowTS.time.desc())
            .all()
        )
        seen: set[str] = set()
        written = 0
        for r in rows:
            if r.sector_code in seen:
                continue
            seen.add(r.sector_code)
            up_dn = (r.up_vol / r.down_vol) if (r.down_vol and r.down_vol > 0) else float("nan")
            existing = (
                self.session.query(SectorFlowDaily)
                .filter_by(sector_code=r.sector_code, date=date).one_or_none()
            )
            if existing is None:
                self.session.add(SectorFlowDaily(
                    sector_code=r.sector_code, date=date,
                    net_dollar_flow=r.net_dollar_flow, foreign_net=r.foreign_net,
                    up_down_vol_ratio=up_dn, breadth_sma20=r.breadth_sma20,
                    breadth_sma50=r.breadth_sma50, atr_pct=r.atr_pct,
                ))
            else:
                existing.net_dollar_flow = r.net_dollar_flow
                existing.foreign_net = r.foreign_net
                existing.up_down_vol_ratio = up_dn
                existing.breadth_sma20 = r.breadth_sma20
                existing.breadth_sma50 = r.breadth_sma50
                existing.atr_pct = r.atr_pct
            written += 1
        self.session.commit()
        return written
