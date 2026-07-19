"""News enrichment for Daily Insight picks.

Layered sources (first hit wins, stop on N items):
  1. vnstock KBS `company.news()` — local, attribution-rich, sometimes sparse.
  2. Google News RSS — `news.google.com/rss/search?q=<ticker>` — large
     aggregate pool covering CafeF, 24HMoney, nguoiquansat.vn, etc. Stable
     because it's Google's public RSS, not the VN publisher HTML (which
     shifts frequently).

Return shape: list[{"title", "url", "published", "source"}]. Timestamps ISO.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    url: str
    published: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url,
                "published": self.published, "source": self.source}


# --- Simple 30-min cache per (symbol, company_name) ---
_NEWS_CACHE: dict[str, tuple[list[NewsItem], float]] = {}
_NEWS_TTL_SEC = 1800


def fetch_news(symbol: str, company_name: str | None = None,
               max_items: int = 5) -> list[NewsItem]:
    """Return up to max_items news items for the given ticker.

    KBS news is attempted first because it has stable attribution. Google
    News RSS is the fallback/top-up path — almost always returns dozens of
    articles in VN, even for small caps.
    """
    key = f"{symbol}:{company_name or ''}"
    now = time.time()
    cached = _NEWS_CACHE.get(key)
    if cached and (now - cached[1]) < _NEWS_TTL_SEC:
        return cached[0][:max_items]

    items: list[NewsItem] = []
    items.extend(_fetch_kbs(symbol, limit=max_items))
    if len(items) < max_items:
        remaining = max_items - len(items)
        items.extend(_fetch_google_news_rss(symbol, company_name, limit=remaining + 2))
    # De-dupe by URL
    seen: set[str] = set()
    out: list[NewsItem] = []
    for it in items:
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
        if len(out) >= max_items:
            break

    _NEWS_CACHE[key] = (out, now)
    return out


def _fetch_kbs(symbol: str, limit: int) -> list[NewsItem]:
    try:
        from vnstock import Vnstock
        s = Vnstock().stock(symbol=symbol, source="KBS")
        df = s.company.news()
    except BaseException as e:
        log.debug("[picks-news] KBS news %s failed: %s", symbol, e)
        return []
    if df is None or df.empty:
        return []
    out: list[NewsItem] = []
    for _, r in df.head(limit).iterrows():
        title = str(r.get("title") or r.get("head") or "").strip()
        url = str(r.get("url") or "").strip()
        pub = str(r.get("publish_time") or r.get("date") or "")
        if not title:
            continue
        out.append(NewsItem(title=title[:220], url=url, published=pub, source="KBS"))
    return out


# Google News RSS — minimal regex-based parser (avoid lxml/feedparser deps).
# Items look like:
# <item><title><![CDATA[...]]></title><link>https://...</link><pubDate>...</pubDate>
#   <source url="...">[Publisher]</source></item>
_ITEM_RX = re.compile(
    r"<item>\s*<title>(?:<!\[CDATA\[)?(?P<title>.*?)(?:\]\]>)?</title>\s*"
    r"<link>(?P<link>.*?)</link>\s*"
    r"<guid[^>]*>.*?</guid>\s*"
    r"<pubDate>(?P<pub>.*?)</pubDate>.*?"
    r"(?:<source[^>]*>(?:<!\[CDATA\[)?(?P<src>.*?)(?:\]\]>)?</source>)?",
    re.S,
)


def _fetch_google_news_rss(symbol: str, company_name: str | None,
                           limit: int) -> list[NewsItem]:
    import requests
    q = symbol
    if company_name:
        q = f"{symbol} {company_name}"
    url = "https://news.google.com/rss/search"
    params = {"q": q, "hl": "vi", "gl": "VN", "ceid": "VN:vi"}
    try:
        r = requests.get(url, params=params,
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    except BaseException as e:
        log.debug("[picks-news] gnews %s failed: %s", symbol, e)
        return []
    if r.status_code != 200 or not r.text:
        return []
    out: list[NewsItem] = []
    for m in _ITEM_RX.finditer(r.text):
        title = _clean_cdata(m.group("title")).strip()
        link = _clean_cdata(m.group("link")).strip()
        pub = _clean_cdata(m.group("pub")).strip()
        src = _clean_cdata(m.group("src") or "Google News").strip()
        # Filter to items that actually mention the symbol (Google returns
        # some loose matches; we want the ticker in title or source)
        if symbol.upper() not in title.upper() and (
            not company_name or company_name.lower() not in title.lower()
        ):
            continue
        out.append(NewsItem(title=title[:220], url=link, published=pub, source=src))
        if len(out) >= limit:
            break
    return out


def _clean_cdata(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"<!\[CDATA\[|\]\]>", "", s)


__all__ = ["NewsItem", "fetch_news"]
