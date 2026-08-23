# ============================================
# utils/vn_api.py -- one adapter over the vnstock client
# ============================================
# vnstock retired the `Vnstock()` class and its `.stock()/.fx()/.crypto()`
# accessors on 2025-08-31. Every job log in this repo carries the banner:
#
#     Lop Vnstock va cac phuong thuc cu (stock, fx, crypto, world_index,
#     fund...) da chinh thuc bi ngung ho tro.
#     ... vui long chuyen sang dung bo thu vien `vnstock.api`.
#
# The call was spread across eight files, each constructing the client its own
# way. That is why the deprecation sat unaddressed: there was no single place
# to change. There is now.
#
# Probed against the installed client on 2026-08-23, the new surface is:
#
#     Quote(symbol=..., source=...).history(start=, end=, interval=)
#         -> DataFrame[time, open, high, low, close, volume]
#     Trading(symbol=..., source=...).price_board([symbols])
#     Listing(source=...).symbols_by_industries() / all_symbols()
#
# which is shape-compatible with what the old accessors returned, so this is an
# adapter rather than a rewrite. The legacy path is kept as a fallback so an
# older vnstock still works, but it is only reached if `vnstock.api` is absent.

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

_WARNED = False


def _legacy_warn(what: str) -> None:
    global _WARNED
    if not _WARNED:
        log.warning(
            "[vn_api] falling back to the deprecated Vnstock() class for %s -- "
            "installed vnstock has no `vnstock.api`. Upgrade with "
            "`uv pip install -U vnstock`.", what)
        _WARNED = True


def quote_history(symbol: str, start: str, end: str,
                  interval: str = "1D", source: str | None = None) -> pd.DataFrame:
    """Daily/intraday OHLCV for one symbol."""
    from config import DATA_SOURCE
    src = source or DATA_SOURCE
    try:
        from vnstock.api.quote import Quote
        return Quote(symbol=symbol, source=src).history(
            start=start, end=end, interval=interval)
    except ImportError:
        _legacy_warn("quote_history")
        from vnstock import Vnstock
        return Vnstock().stock(symbol=symbol, source=src).quote.history(
            start=start, end=end, interval=interval)


def price_board(symbols: list[str], source: str | None = None) -> Any:
    """Live board for one or more symbols."""
    from config import DATA_SOURCE
    src = source or DATA_SOURCE
    try:
        from vnstock.api.trading import Trading
        return Trading(symbol=symbols[0], source=src).price_board(symbols)
    except ImportError:
        _legacy_warn("price_board")
        from vnstock import Vnstock
        return Vnstock().stock(symbol=symbols[0], source=src).trading.price_board(symbols)


def listing(source: str | None = None) -> Any:
    """Listing client (symbols_by_industries / all_symbols / ...)."""
    from config import DATA_SOURCE
    src = source or DATA_SOURCE
    try:
        from vnstock.api.listing import Listing
        return Listing(source=src)
    except ImportError:
        _legacy_warn("listing")
        from vnstock import Listing as LegacyListing
        return LegacyListing()


def company_news(symbol: str, source: str = "KBS") -> Any:
    """Company client, used for the news blocks in the daily report."""
    try:
        from vnstock.api.company import Company
        return Company(symbol=symbol, source=source)
    except ImportError:
        _legacy_warn("company_news")
        from vnstock import Vnstock
        return Vnstock().stock(symbol=symbol, source=source).company


def uses_new_api() -> bool:
    """True when the non-deprecated client is what will actually be used."""
    try:
        import vnstock.api  # noqa: F401
        return True
    except ImportError:
        return False
