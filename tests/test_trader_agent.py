"""Tests for services.trader_agent — JSON response parsing + cache behaviour.

We do NOT actually call Claude in these tests — the agent is tested as a
pure parser/cache over stubbed response strings. A separate manual smoke
test (POST /api/insight/refresh) verifies the live SDK transport.
"""
from __future__ import annotations

import time

from services.trader_agent import (
    AgentReport,
    TraderAgent,
    _parse_pick,
    _trim_flow,
    _trim_pick,
    get_trader_agent,
)


# -------------------- _parse_pick --------------------


def test_parse_pick_coerces_numeric_strings():
    p = {"symbol": "hpg", "sector": "steel", "action": "buy",
         "conviction": "4", "entry": "28.0", "target": "30",
         "stop": "26.5", "rr": "1.8", "reasoning": "x", "risks": ["a"]}
    out = _parse_pick(p)
    assert out.symbol == "HPG"     # upper-cased
    assert out.action == "BUY"     # upper-cased
    assert out.conviction == 4
    assert out.entry == 28.0
    assert out.rr == 1.8


def test_parse_pick_handles_nulls_and_invalid_types():
    p = {"symbol": "X", "entry": None, "target": "not-a-number",
         "stop": None, "rr": ""}
    out = _parse_pick(p)
    assert out.entry is None
    assert out.target is None       # invalid string → None
    assert out.stop is None
    assert out.rr is None


def test_parse_pick_truncates_long_reasoning():
    p = {"symbol": "X", "reasoning": "a" * 2000}
    out = _parse_pick(p)
    assert len(out.reasoning) <= 600


# -------------------- _trim_pick / _trim_flow --------------------


def test_trim_pick_keeps_only_prompt_relevant_fields():
    """The prompt is passed by value to Claude — we must not leak oversized
    fields like `daily_prices` (30-row OHLCV list) into it."""
    input_pick = {
        "symbol": "HPG", "sector_code": "STEEL", "sector_name": "Thép",
        "close": 28.0, "stop": 26.5, "target": 30.0, "rr": 1.5,
        "score": 5, "atr_pct": 2.5, "upside_pct": 7.0, "downside_pct": 5.0,
        "technical_bits": ["RSI 58"], "foreign_room_pct": 500e6,
        "news": [{"source": "KBS", "title": "X", "url": "u", "published": "p"}] * 5,
        "daily_prices": [{"time": "2026-01-01", "close": 28} for _ in range(30)],
        "thesis": "bullish",
    }
    out = _trim_pick(input_pick)
    assert "daily_prices" not in out
    assert "thesis" not in out        # thesis already absorbed into reasoning
    # News is capped to AGENT_NEWS_PER_CANDIDATE (2 since 2026-06-18) to trim tokens
    from config import AGENT_NEWS_PER_CANDIDATE
    assert len(out["news"]) == AGENT_NEWS_PER_CANDIDATE
    # Only source+title kept per news item
    assert set(out["news"][0].keys()) == {"source", "title"}


def test_trim_flow_keeps_four_key_columns_per_sector():
    flow = {
        "STEEL": {
            "flow_z20": 2.5, "foreign_hit_20d": 0.7,
            "rs_vnindex_20d": 0.03, "accumulation_age": 3,
            "net_dollar_flow": 123, "breadth_sma20": 0.6, "atr_pct": 2.5,
        }
    }
    out = _trim_flow(flow)
    assert set(out["STEEL"].keys()) == {
        "flow_z20", "foreign_hit_20d", "rs_vnindex_20d", "accumulation_age"
    }


def test_trim_flow_ignores_malformed_rows():
    out = _trim_flow({"STEEL": "not-a-dict", "TECH": None})
    assert out == {}


# -------------------- response parsing --------------------


def _make_agent() -> TraderAgent:
    return TraderAgent()


def test_parse_response_extracts_fenced_json():
    agent = _make_agent()
    raw = """Let me analyze.
```json
{"gist":"market chop","regime_comment":"steel + tech only",
 "top_buys":[{"symbol":"HPG","sector":"STEEL","action":"BUY","conviction":4,
   "entry":28.0,"target":30.0,"stop":26.5,"rr":1.5,
   "reasoning":"solid momentum","risks":["macro"]}],
 "avoid":[{"symbol":"PC1","sector":"POWER","action":"AVOID","conviction":4,
   "entry":null,"target":null,"stop":25.1,"rr":null,
   "reasoning":"dilution risk","risks":[]}],
 "portfolio_note":"50% cash"}
```
End."""
    r = agent._parse_response(raw, "2026-04-17", time.time(), 1000, "sonnet", 0.12)
    assert r.is_valid
    assert r.gist == "market chop"
    assert len(r.top_buys) == 1
    assert r.top_buys[0].symbol == "HPG"
    assert r.top_buys[0].conviction == 4
    assert len(r.avoid) == 1
    assert r.avoid[0].symbol == "PC1"
    assert r.portfolio_note == "50% cash"


def test_parse_response_falls_back_to_bare_json_block():
    """If the model forgot the ```json fence, we still try to parse the first {}."""
    agent = _make_agent()
    raw = '{"gist":"x","regime_comment":"y","top_buys":[],"avoid":[],"portfolio_note":"z"}'
    r = agent._parse_response(raw, "2026-04-17", time.time(), 1, "sonnet", 0.0)
    assert r.is_valid
    assert r.gist == "x"


def test_parse_response_flags_empty():
    agent = _make_agent()
    r = agent._parse_response("", "2026-04-17", time.time(), 1, "sonnet", 0.0)
    assert not r.is_valid
    assert r.error == "empty response"


def test_parse_response_flags_no_json():
    agent = _make_agent()
    r = agent._parse_response("just prose, no JSON here", "2026-04-17", time.time(), 1, "sonnet", 0.0)
    assert not r.is_valid
    assert r.error == "no JSON block"


def test_parse_response_flags_malformed_json():
    agent = _make_agent()
    r = agent._parse_response("```json\n{not valid json}\n```", "2026-04-17", time.time(), 1, "sonnet", 0.0)
    assert not r.is_valid
    assert "JSON parse" in r.error


def test_parse_response_truncates_oversized_fields():
    agent = _make_agent()
    long_gist = "x" * 500
    long_comment = "y" * 1000
    raw = f'```json\n{{"gist":"{long_gist}","regime_comment":"{long_comment}",' \
          '"top_buys":[],"avoid":[],"portfolio_note":""}\n```'
    r = agent._parse_response(raw, "2026-04-17", time.time(), 1, "sonnet", 0.0)
    assert r.is_valid
    assert len(r.gist) <= 240
    assert len(r.regime_comment) <= 600


# -------------------- cache behaviour --------------------


def test_invalidate_clears_agent_cache():
    agent = _make_agent()
    agent._cache = AgentReport(
        built_at=time.time(), as_of="2026-04-17", model="sonnet",
        duration_ms=1, cost_usd=0.1, gist="x", regime_comment="",
        top_buys=[], avoid=[], portfolio_note="", raw_text="",
    )
    agent._cache_key = "key"
    agent.invalidate()
    assert agent._cache is None
    assert agent._cache_key is None


def test_get_trader_agent_returns_singleton():
    a = get_trader_agent()
    b = get_trader_agent()
    assert a is b


# -------------------- to_dict shape --------------------


def test_agent_report_to_dict_is_json_safe():
    import json
    r = AgentReport(
        built_at=time.time(), as_of="2026-04-17", model="sonnet",
        duration_ms=100, cost_usd=0.12, gist="g", regime_comment="rc",
        top_buys=[_parse_pick({"symbol": "X", "sector": "S", "action": "BUY",
                                "conviction": 3})],
        avoid=[],
        portfolio_note="pn", raw_text="raw",
    )
    d = r.to_dict()
    json.dumps(d)  # must not raise
    assert d["gist"] == "g"
    assert d["top_buys"][0]["symbol"] == "X"
    assert d["is_valid"] is True


# -------------------- timeout guard (2026-06-18) --------------------


def test_analyze_enforces_hard_timeout(monkeypatch):
    """A stalled SDK transport must NOT hang the refresh — wait_for caps it and
    returns a graceful invalid report (the old behaviour hung until the 20-min
    frontend ceiling → 'time exceed')."""
    import asyncio
    import services.trader_agent as ta

    async def _slow_query(*args, **kwargs):  # async generator that never yields in time
        await asyncio.sleep(10)
        if False:
            yield None

    monkeypatch.setattr(ta, "query", _slow_query)
    agent = ta.TraderAgent(timeout_sec=0.2)
    report = agent.analyze_sync(
        {"as_of": "2026-04-17", "top_buys": [], "top_sells": []}, {})
    assert report.is_valid is False
    assert "timeout" in (report.error or "").lower()
