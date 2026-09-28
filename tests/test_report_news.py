"""The report's news blocks must never end the report.

2026-09-28: the 17:00 report built the buy list, rendered the charts, then
asked vnstock for each buy's headlines inside an `except Exception`. vnai's
quota guard ends the process with `sys.exit()` at 20 req/min -- SystemExit is
not an Exception -- and the universe snapshot had just spent the minute. The
log ends "Rate limit exceeded. ... Process terminated.": no HTML, no PDF, no
email, so Tom saw no buy suggestions that day.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _report():
    sys.modules.pop("generate_report", None)
    return importlib.import_module("generate_report")


@pytest.fixture(autouse=True)
def _no_cached_news():
    from services import picks_news
    picks_news._NEWS_CACHE.clear()
    yield
    picks_news._NEWS_CACHE.clear()


def _quota_exit(*a, **k):
    raise SystemExit("Rate limit exceeded. Gioi han 20 requests/phut Process terminated.")


def test_the_vnstock_quota_exit_does_not_end_the_report(monkeypatch):
    monkeypatch.setattr("utils.vn_api.company_news", _quota_exit)
    monkeypatch.setattr("services.picks_news._fetch_google_news_rss", lambda *a, **k: [])
    assert _report().pick_news("NTP") == []


def test_a_quota_exit_raised_past_picks_news_is_contained_too(monkeypatch):
    monkeypatch.setattr("services.picks_news.fetch_news", _quota_exit)
    assert _report().pick_news("NTP") == []


def test_headlines_come_back_in_the_news_block_shape(monkeypatch):
    from services.picks_news import NewsItem
    monkeypatch.setattr("services.picks_news._fetch_kbs",
                        lambda s, limit: [NewsItem("t" * 300, "u1", "2026-09-28", "KBS")])
    monkeypatch.setattr("services.picks_news._fetch_google_news_rss",
                        lambda *a, **k: [NewsItem("g", "u2", "2026-09-27", "CafeF")])
    assert _report().pick_news("NTP") == [
        {"title": "t" * 180, "src": "KBS", "date": "2026-09-28"},
        {"title": "g", "src": "CafeF", "date": "2026-09-27"},
    ]


def test_the_report_asks_for_news_only_through_pick_news():
    body = (ROOT / "generate_report.py").read_text(encoding="utf-8").split("def main(", 1)[1]
    assert "company_news" not in body
    assert "pick_news(b[\"sym\"])" in body
