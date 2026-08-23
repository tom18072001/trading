# ============================================
# services/foreign_flow.py -- one source of truth for foreign buy/sell/net
# ============================================
# Why this exists (measured on the live box, 2026-08-23):
#
#   The system had TWO foreign-flow readers with different reliability:
#
#     scheduled path  SectorIngestService._fetch_foreign
#                     -> vnstock price_board
#                     -> returned 0 for EVERY symbol, EVERY run, forever.
#                        sector_flow_ts: 0 non-zero rows out of 12,175.
#
#     UI-button path  fast_ingest._fetch_foreign_vndirect
#                     -> VNDirect /v4/foreigns
#                     -> works, and has history.
#
#   So `foreign_net` in sector_flow_daily stops on 2026-06-22 -- which is not
#   the day the data stopped existing, it is the day somebody last clicked
#   Refresh. The upstream source was never down: probed on 2026-08-23 it
#   returned 60 sessions through 2026-08-21 without complaint.
#
#   Why price_board returned zero: KBS exposes `foreign_buy_volume` and
#   `foreign_sell_volume` (SHARE COUNTS, e.g. 527,101) but no *_value column.
#   The 2026-06-18 parser was meant to convert volume x price -- except its
#   price lookup matched none of KBS's column names, so `price` stayed None,
#   the conversion never ran, and `buy or 0.0` quietly produced 0.0. A missing
#   price silently became "no foreign flow today".
#
#   This module makes VNDirect the primary (it returns VND values directly, so
#   there is no price to guess at), keeps the price_board conversion as a
#   fallback with a WIDER price search, and -- the part that actually matters --
#   never returns a silent zero. If both paths fail it says so.

from __future__ import annotations

import logging

import pandas as pd
import requests

log = logging.getLogger(__name__)

VNDIRECT_URL = "https://api-finfo.vndirect.com.vn/v4/foreigns"
_TIMEOUT = 15
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class ForeignFlowUnavailable(RuntimeError):
    """Neither source could produce a foreign-flow value.

    Raised instead of returning zero, because a zero is indistinguishable from
    'foreigners were flat today' and that ambiguity is what hid this bug for
    two months.
    """


# ---------------------------------------------------------------------------
# primary: VNDirect, returns VND values directly
# ---------------------------------------------------------------------------

def fetch_history(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Daily foreign buy/sell/net VALUE (VND) for one symbol over a range.

    Returns a frame with columns date / buy_val / sell_val / net_val, oldest
    first. Empty frame when the API has nothing for the range.
    """
    try:
        r = requests.get(
            VNDIRECT_URL,
            params={
                "q": f"code:{symbol}~tradingDate:gte:{start}~tradingDate:lte:{end}",
                "size": 500,
                "sort": "tradingDate:desc",
                "page": 1,
            },
            timeout=_TIMEOUT,
            headers=_HEADERS,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        log.warning("[foreign] vndirect %s %s..%s failed: %s", symbol, start, end, e)
        return pd.DataFrame(columns=["date", "buy_val", "sell_val", "net_val"])

    if not rows:
        return pd.DataFrame(columns=["date", "buy_val", "sell_val", "net_val"])

    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["tradingDate"]).dt.strftime("%Y-%m-%d"),
        "buy_val": pd.to_numeric(df.get("buyVal"), errors="coerce").fillna(0.0),
        "sell_val": pd.to_numeric(df.get("sellVal"), errors="coerce").fillna(0.0),
        "net_val": pd.to_numeric(df.get("netVal"), errors="coerce").fillna(0.0),
    })
    return out.sort_values("date").reset_index(drop=True)


def fetch_latest(symbol: str, lookback_days: int = 10) -> tuple[float, float, float]:
    """Most recent session's (buy_val, sell_val, net_val) for one symbol.

    Raises ForeignFlowUnavailable rather than returning a silent zero.
    """
    from utils.clock import now as market_now

    end = market_now().strftime("%Y-%m-%d")
    start = (market_now() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    df = fetch_history(symbol, start, end)
    if df.empty:
        raise ForeignFlowUnavailable(
            f"no foreign flow for {symbol} in {start}..{end}")
    last = df.iloc[-1]
    return float(last.buy_val), float(last.sell_val), float(last.net_val)


# ---------------------------------------------------------------------------
# fallback: vnstock price_board, volume x price
# ---------------------------------------------------------------------------

def _flatten(df: pd.DataFrame) -> dict[str, object]:
    """lowercased flattened column name -> original column key."""
    out: dict[str, object] = {}
    for c in df.columns:
        name = "_".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
        out[name.lower()] = c
    return out


def _pick(row, flat: dict[str, object], *substrs: str) -> float | None:
    for low, orig in flat.items():
        if all(s in low for s in substrs):
            try:
                v = row[orig]
            except (TypeError, ValueError, KeyError):
                continue
            if v is not None and not pd.isna(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    return None


def _find_price(row, flat: dict[str, object]) -> float | None:
    """Any plausible last-traded price on the board.

    Deliberately broad. The old lookup required one of four exact shapes and
    matched none of KBS's columns, which is the whole reason foreign flow read
    as zero for months. Ordered from most to least specific; a price is only
    accepted if it is positive and finite.
    """
    ordered = [
        ("match", "price"), ("last", "price"), ("close",),
        ("price",), ("ref", ""), ("ceiling",),
    ]
    for pattern in ordered:
        v = _pick(row, flat, *[p for p in pattern if p])
        if v is not None and v > 0:
            return v
    return None


def from_price_board(board: pd.DataFrame) -> tuple[float, float, float]:
    """(buy_val, sell_val, net_val) from a vnstock price_board frame.

    Uses *_value columns when the source provides them; otherwise converts
    *_volume x price. Raises ForeignFlowUnavailable when it cannot do either --
    it never reports a guess as zero.
    """
    if board is None or board.empty:
        raise ForeignFlowUnavailable("empty price_board")

    flat = _flatten(board)
    row = board.iloc[0]

    buy = _pick(row, flat, "foreign", "buy", "val")
    sell = _pick(row, flat, "foreign", "sell", "val")
    net = _pick(row, flat, "foreign", "net", "val")

    if buy is None and sell is None and net is None:
        bvol = _pick(row, flat, "foreign", "buy", "vol")
        svol = _pick(row, flat, "foreign", "sell", "vol")
        if bvol is None and svol is None:
            raise ForeignFlowUnavailable(
                "price_board has no foreign value or volume columns; saw: "
                + ", ".join(sorted(k for k in flat if "foreign" in k)))
        price = _find_price(row, flat)
        if price is None:
            raise ForeignFlowUnavailable(
                "price_board has foreign volumes but no usable price column, "
                "so they cannot be converted to value; columns: "
                + ", ".join(sorted(flat)[:25]))
        buy = (bvol or 0.0) * price
        sell = (svol or 0.0) * price

    buy = buy or 0.0
    sell = sell or 0.0
    if net is None:
        net = buy - sell
    return float(buy), float(sell), float(net)
