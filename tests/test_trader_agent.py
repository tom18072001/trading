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

    monkeypatch.setattr(ta, "AGENT_PROVIDER", "glm")     # exercise the SDK transport
    monkeypatch.setattr(ta, "GLM_API_KEY", "test-key")  # don't trip the missing-key guard
    monkeypatch.setattr(ta, "query", _slow_query)
    agent = ta.TraderAgent(timeout_sec=0.2)
    report = agent.analyze_sync(
        {"as_of": "2026-04-17", "top_buys": [], "top_sells": []}, {})
    assert report.is_valid is False
    assert "timeout" in (report.error or "").lower()


# -------------------- GLM provider routing (2026-07-20) --------------------


def test_analyze_glm_without_key_fails_gracefully(monkeypatch):
    """AGENT_PROVIDER=glm with no GLM_API_KEY must return an invalid report
    with a clear error instead of stalling on an SDK auth failure."""
    import services.trader_agent as ta

    monkeypatch.setattr(ta, "AGENT_PROVIDER", "glm")
    monkeypatch.setattr(ta, "GLM_API_KEY", "")
    agent = ta.TraderAgent()
    report = agent.analyze_sync(
        {"as_of": "2026-07-20", "top_buys": [], "top_sells": []}, {})
    assert report.is_valid is False
    assert "GLM_API_KEY" in (report.error or "")


def test_analyze_glm_routes_env_and_model_to_sdk(monkeypatch):
    """With provider=glm the SDK subprocess env must carry the Z.ai base URL
    and auth token, and the configured GLM model must be requested."""
    import services.trader_agent as ta

    captured: dict = {}

    async def _fake_query(prompt, options):
        captured["env"] = options.env
        captured["model"] = options.model
        if False:
            yield None

    monkeypatch.setattr(ta, "AGENT_PROVIDER", "glm")
    monkeypatch.setattr(ta, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(ta, "GLM_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setattr(ta, "query", _fake_query)
    agent = ta.TraderAgent(model="glm-5.2")
    report = agent.analyze_sync(
        {"as_of": "2026-07-20", "top_buys": [], "top_sells": []}, {})
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "test-key"
    assert captured["model"] == "glm-5.2"
    assert report.is_valid is False  # empty stubbed response → "empty response"


def test_analyze_claude_provider_passes_no_env_override(monkeypatch):
    """AGENT_PROVIDER=claude keeps the native subscription path — no
    ANTHROPIC_* overrides injected into the SDK subprocess."""
    import services.trader_agent as ta

    captured: dict = {}

    async def _fake_query(prompt, options):
        captured["env"] = options.env
        if False:
            yield None

    monkeypatch.setattr(ta, "AGENT_PROVIDER", "claude")
    monkeypatch.setattr(ta, "query", _fake_query)
    agent = ta.TraderAgent(model="haiku")
    agent.analyze_sync(
        {"as_of": "2026-07-20", "top_buys": [], "top_sells": []}, {})
    assert captured["env"] == {}


# -------------------- local provider / Ollama transport (2026-07-20) --------------------


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("POST", "http://localhost:11434/v1/chat/completions"),
                response=self,  # type: ignore[arg-type]
            )


def _fake_client_factory(captured: dict, response=None, raise_exc=None):
    class _FakeClient:
        def __init__(self, *a, **kw):
            captured["client_kwargs"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            if raise_exc is not None:
                raise raise_exc
            return response
    return _FakeClient


def test_local_provider_posts_openai_compatible_request(monkeypatch):
    """provider=local must POST an OpenAI-style chat/completions body to the
    configured localhost endpoint and parse the reply — no SDK involved."""
    import services.trader_agent as ta

    captured: dict = {}
    reply = {
        "model": "qwen3:8b",
        "choices": [{
            "finish_reason": "stop",
            "message": {"content":
                        '```json\n{"gist":"thị trường đi ngang",'
                        '"regime_comment":"chop","top_buys":[],"avoid":[],'
                        '"portfolio_note":"giữ 50% tiền mặt"}\n```'},
        }],
    }
    monkeypatch.setattr(ta, "AGENT_PROVIDER", "local")
    monkeypatch.setattr(ta, "LOCAL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setattr(ta, "LOCAL_API_KEY", "ollama")
    monkeypatch.setattr(
        ta.httpx, "AsyncClient",
        _fake_client_factory(captured, response=_FakeResponse(reply)))

    agent = ta.TraderAgent(model="qwen3:8b")
    report = agent.analyze_sync(
        {"as_of": "2026-07-20", "top_buys": [], "top_sells": []}, {})

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["payload"]["model"] == "qwen3:8b"
    assert captured["payload"]["stream"] is False
    roles = [m["role"] for m in captured["payload"]["messages"]]
    assert roles == ["system", "user"]
    assert report.is_valid
    assert report.gist == "thị trường đi ngang"
    assert report.cost_usd == 0.0      # self-hosted → no marginal cost


def test_local_provider_connect_error_is_actionable(monkeypatch):
    """A dead endpoint must surface a clear, CORRECT message.

    2026-08-23: this used to assert the word "ollama". The message hardcoded
    "is Ollama running? (`ollama serve`)" long after the transport moved to
    9Router, so it sent people chasing a service this box does not run. The
    message must name what is actually configured.
    """
    import httpx
    import services.trader_agent as ta

    captured: dict = {}
    monkeypatch.setattr(ta, "AGENT_PROVIDER", "local")
    monkeypatch.setattr(
        ta.httpx, "AsyncClient",
        _fake_client_factory(captured, raise_exc=httpx.ConnectError("refused")))

    agent = ta.TraderAgent(model="claude-opus-5")
    report = agent.analyze_sync(
        {"as_of": "2026-07-20", "top_buys": [], "top_sells": []}, {})
    assert report.is_valid is False

    err = (report.error or "").lower()
    # names the endpoint it could not reach, and the model it was going to use
    assert ta.LOCAL_BASE_URL.lower() in err
    assert "claude-opus-5" in err
    # tells you what to do
    assert "listening" in err or "start" in err
    # and does NOT send you after a service that is not configured
    assert "ollama serve" not in err


def test_parse_response_strips_think_block():
    """Local reasoning models emit <think>...</think> containing braces — the
    no-fence fallback must not parse the monologue instead of the answer."""
    agent = _make_agent()
    raw = (
        "<think>Hmm, maybe {\"symbol\": \"XYZ\"} is a good idea? "
        "Let me reconsider.</think>\n"
        '{"gist":"ok","regime_comment":"r","top_buys":[],"avoid":[],'
        '"portfolio_note":"p"}'
    )
    r = agent._parse_response(raw, "2026-07-20", time.time(), 1, "qwen3:8b", 0.0)
    assert r.is_valid
    assert r.gist == "ok"


def test_parse_response_strips_unterminated_think_block():
    """A truncated reply can leave <think> open — must not crash or mis-parse."""
    agent = _make_agent()
    raw = (
        '```json\n{"gist":"g","regime_comment":"r","top_buys":[],"avoid":[],'
        '"portfolio_note":"p"}\n```\n<think>trailing {broken'
    )
    r = agent._parse_response(raw, "2026-07-20", time.time(), 1, "qwen3:8b", 0.0)
    assert r.is_valid
    assert r.gist == "g"
