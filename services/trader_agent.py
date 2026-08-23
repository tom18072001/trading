"""Trader Expert Agent — Vietnamese stock analyst.

Replaces the legacy OpenClaw "Trung" agent (see CLAUDE.md §7) with an
in-process Python agent. Three transports, picked by `config.AGENT_PROVIDER`:

  "local" (default, 2026-07-20) — plain HTTP to any OpenAI-compatible
      /chat/completions endpoint reachable from this box. In practice that is
      9Router (a local router on :20128 that fronts hosted models), but LM
      Studio, llama.cpp and Ollama all speak the same shape. No
      `claude_agent_sdk` subprocess: the agent takes one turn and uses no
      tools, so the SDK was pure overhead here.
  "glm"   — `claude_agent_sdk` pointed at Z.ai's Anthropic-compatible
      endpoint (GLM models). Needs GLM_API_KEY in .env.
  "claude"— native Claude Code subscription path via `claude_agent_sdk`.

`claude_agent_sdk` is imported lazily: a local-only install does not need it.

The agent is stateless and one-shot. It consumes the snapshot assembled by
`PicksUniverseService` plus sector-level signals/regime from the DB, then
returns a structured JSON report with:
  - 1-line VN market gist
  - 3-5 actionable BUY recommendations (beyond what the rule-based picks
    already surface; the agent adds reasoning that weighs news + technicals
    + sector context)
  - 1-3 risks / SELL / avoid notes
  - portfolio allocation suggestion

Invocation:
  agent = TraderAgent()
  report = await agent.analyze(snapshot=snapshot)
  report.to_dict()  →  JSON-serializable dict for API response

Design choices:
  - JSON-only output: we prompt the agent to wrap its answer in a ```json
    fenced block and parse it out; more reliable than free-form Vietnamese
    text for downstream rendering.
  - One turn, no tool use, thinking disabled — keeps latency low.
  - HARD timeout (config.AGENT_TIMEOUT_SEC, default 120s) enforced via
    asyncio.wait_for. Before 2026-06-18 there was none, so a stalled SDK
    transport hung the whole /insight/refresh background run until the
    frontend's 20-min ceiling ("time exceed"). On timeout the agent returns a
    graceful invalid report and the refresh still assembles the /daily payload.
  - Model + output caps are config-tunable (AGENT_MODEL default "haiku" for
    fast structured JSON; AGENT_MAX_BUYS/AVOID bound the generated text).
  - Per-refresh cache (TTL 10 min): repeat /refresh within the window
    returns the last report.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from urllib.parse import urlsplit

import httpx

# Optional — only the "glm" / "claude" providers need the SDK. Keeping this
# soft lets a local-only box run the agent without installing the CLI wheel
# (~80MB) and without `import api.routers.insight` blowing up.
try:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        ThinkingConfigDisabled,
        query,
    )
    _SDK_IMPORT_ERROR: str | None = None
except ImportError as _e:            # pragma: no cover - env-dependent
    AssistantMessage = ClaudeAgentOptions = ResultMessage = None  # type: ignore
    TextBlock = ThinkingConfigDisabled = query = None             # type: ignore
    _SDK_IMPORT_ERROR = str(_e)

from config import (
    AGENT_MAX_AVOID, AGENT_MAX_BUY_CANDIDATES, AGENT_MAX_BUYS,
    AGENT_MAX_SELL_CANDIDATES, AGENT_MODEL, AGENT_NEWS_PER_CANDIDATE,
    AGENT_PROVIDER, AGENT_TIMEOUT_SEC, GLM_API_KEY, GLM_BASE_URL,
    LOCAL_API_KEY, LOCAL_BASE_URL,
)

log = logging.getLogger(__name__)


# ---------- Output schema ----------

@dataclass
class AgentPick:
    symbol: str
    sector: str
    action: str                # BUY | AVOID
    conviction: int            # 1-5 stars
    entry: float | None
    target: float | None
    stop: float | None
    rr: float | None
    reasoning: str             # VN, 2-3 sentences
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__}


@dataclass
class AgentReport:
    built_at: float
    as_of: str
    model: str
    duration_ms: int
    cost_usd: float | None
    gist: str                  # 1-line VN market summary
    regime_comment: str        # agent's read on today's regime vs signals
    top_buys: list[AgentPick]
    avoid: list[AgentPick]
    portfolio_note: str        # allocation / exposure suggestion
    raw_text: str              # full Claude reply, for debugging
    is_valid: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "built_at": self.built_at,
            "as_of": self.as_of,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "gist": self.gist,
            "regime_comment": self.regime_comment,
            "top_buys": [p.to_dict() for p in self.top_buys],
            "avoid": [p.to_dict() for p in self.avoid],
            "portfolio_note": self.portfolio_note,
            "raw_text": self.raw_text,
            "is_valid": self.is_valid,
            "error": self.error,
        }


# ---------- System prompt ----------

SYSTEM_PROMPT = """Bạn là **Minh**, trader kỳ cựu thị trường chứng khoán VN (HOSE), chuyên swing T+ (3-5 phiên). Bạn hiểu vi cấu trúc VN: T+2.5 settlement, biên độ ±7% HOSE, foreign room. Quyết định dựa trên: regime → money flow ngành → risk/reward cổ phiếu → tin tức.

NGUYÊN TẮC (ngắn gọn):
- Bảo toàn vốn trước. R:R ≥ 1.5 cho mọi BUY. Entry/target/stop lấy TỪ dữ liệu input, không bịa.
- Ưu tiên ngành BUY/ACCUMULATE có foreign net buy ổn định + breadth tăng; tránh ngành SELL / flow_z20 âm kéo dài.
- Tin xấu (lãnh đạo bán, KQKD miss, delist) → hạ conviction dù kỹ thuật đẹp.

OUTPUT: CHỈ một JSON trong fenced block ```json ... ```, KHÔNG text ngoài JSON. Schema:

{
  "gist": "1 câu tóm tắt thị trường (≤120 ký tự)",
  "regime_comment": "2 câu về regime + sector rotation",
  "top_buys": [
    {"symbol":"FPT","sector":"TECH","action":"BUY","conviction":4,"entry":76.0,"target":82.1,"stop":71.9,"rr":1.5,"reasoning":"≤2 câu VN: vì sao mua.","risks":["rủi ro 1"]}
  ],
  "avoid": [
    {"symbol":"PC1","sector":"POWER","action":"AVOID","conviction":4,"entry":null,"target":null,"stop":25.1,"rr":null,"reasoning":"≤2 câu: vì sao tránh.","risks":[]}
  ],
  "portfolio_note": "1 câu gợi ý phân bổ (vd: 40% STEEL, 20% TECH, 40% cash)."
}

RÀNG BUỘC:
- top_buys: TỐI ĐA 3 mã, chỉ chọn từ BUY_CANDIDATES. avoid: TỐI ĐA 2 mã, chỉ từ AVOID_CANDIDATES.
- reasoning ≤ 2 câu, risks ≤ 2 mục. conviction 1-5.
- Tuyệt đối không trả text ngoài JSON block. Trả lời NGAY, không giải thích quá trình.
"""


# ---------- Agent ----------

class TraderAgent:
    """Vietnamese stock trader agent — one-shot, JSON-structured output."""

    def __init__(self, model: str | None = None, max_turns: int = 1,
                 timeout_sec: float | None = None) -> None:
        self.model = model or AGENT_MODEL
        self.max_turns = max_turns
        self.timeout_sec = timeout_sec if timeout_sec is not None else AGENT_TIMEOUT_SEC
        self._cache: AgentReport | None = None
        self._cache_key: str | None = None
        self._cache_ttl_sec = 600

    def analyze_sync(self, snapshot_dict: dict[str, Any],
                     context: dict[str, Any]) -> AgentReport:
        """Synchronous wrapper for FastAPI handlers."""
        return asyncio.run(self.analyze(snapshot_dict, context))

    async def analyze(self, snapshot_dict: dict[str, Any],
                      context: dict[str, Any]) -> AgentReport:
        as_of = str(snapshot_dict.get("as_of") or context.get("as_of") or "")
        cache_key = f"{as_of}:{len(snapshot_dict.get('top_buys', []))}:{len(snapshot_dict.get('top_sells', []))}"
        now = time.time()
        if (
            self._cache is not None
            and self._cache_key == cache_key
            and (now - self._cache.built_at) < self._cache_ttl_sec
        ):
            log.info("[trader-agent] cache hit as_of=%s", as_of)
            return self._cache

        prompt = self._build_prompt(snapshot_dict, context)
        t0 = time.monotonic()

        # Mutable accumulators so the inner coroutine can fill them under wait_for.
        acc: dict[str, Any] = {"raw_text": "", "model_used": self.model,
                               "cost_usd": None, "stop_reason": None}

        # ---- provider routing (2026-07-20) ----
        if AGENT_PROVIDER == "local":
            # Plain HTTP to an OpenAI-compatible server on this box. No SDK
            # subprocess, no key, no network egress.
            async def _consume() -> None:
                await self._consume_http(prompt, acc)
        else:
            if query is None:
                return AgentReport(
                    built_at=now, as_of=as_of, model=self.model,
                    duration_ms=0, cost_usd=None,
                    gist="", regime_comment="", top_buys=[], avoid=[],
                    portfolio_note="", raw_text="", is_valid=False,
                    error=(f"claude_agent_sdk unavailable ({_SDK_IMPORT_ERROR}) — "
                           f"install it or set AGENT_PROVIDER=local"),
                )
            # "glm" keeps the SDK transport but points the CLI subprocess at
            # Z.ai's Anthropic-compatible endpoint, so GLM serves the call.
            sdk_env: dict[str, str] = {}
            if AGENT_PROVIDER == "glm":
                if not GLM_API_KEY:
                    log.error("[trader-agent] AGENT_PROVIDER=glm but GLM_API_KEY is empty")
                    return AgentReport(
                        built_at=now, as_of=as_of, model=self.model,
                        duration_ms=0, cost_usd=None,
                        gist="", regime_comment="", top_buys=[], avoid=[],
                        portfolio_note="", raw_text="",
                        is_valid=False,
                        error="GLM_API_KEY not set — add it to .env or switch AGENT_PROVIDER=local",
                    )
                sdk_env = {
                    "ANTHROPIC_BASE_URL": GLM_BASE_URL,
                    "ANTHROPIC_AUTH_TOKEN": GLM_API_KEY,
                }

            opts = ClaudeAgentOptions(
                system_prompt=SYSTEM_PROMPT,
                max_turns=self.max_turns,
                model=self.model,
                thinking=ThinkingConfigDisabled(type="disabled"),
                allowed_tools=[],   # no tool use — pure analysis
                env=sdk_env,
            )

            async def _consume() -> None:
                async for msg in query(prompt=prompt, options=opts):
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                acc["raw_text"] += block.text
                        if getattr(msg, "model", None):
                            acc["model_used"] = msg.model
                    elif isinstance(msg, ResultMessage):
                        acc["cost_usd"] = getattr(msg, "total_cost_usd", None)
                        acc["stop_reason"] = getattr(msg, "stop_reason", None)

        try:
            # HARD timeout: without this, a stalled SDK transport hangs the whole
            # /insight/refresh run until the frontend's 20-min ceiling → the
            # "time exceed" the user was seeing. On timeout we fail gracefully and
            # the refresh pipeline still assembles the (template) /daily payload.
            await asyncio.wait_for(_consume(), timeout=self.timeout_sec)
        except (asyncio.TimeoutError, TimeoutError):
            log.warning("[trader-agent] timed out after %ss (as_of=%s)", self.timeout_sec, as_of)
            return AgentReport(
                built_at=now, as_of=as_of, model=acc["model_used"],
                duration_ms=int((time.monotonic() - t0) * 1000), cost_usd=None,
                gist="", regime_comment="", top_buys=[], avoid=[],
                portfolio_note="", raw_text="",
                is_valid=False, error=f"agent timeout after {self.timeout_sec:.0f}s",
            )
        except BaseException as e:
            log.exception("[trader-agent] query failed: %s", e)
            return AgentReport(
                built_at=now, as_of=as_of, model=acc["model_used"],
                duration_ms=int((time.monotonic() - t0) * 1000),
                cost_usd=None,
                gist="", regime_comment="", top_buys=[], avoid=[],
                portfolio_note="", raw_text="",
                is_valid=False, error=str(e),
            )

        raw_text = acc["raw_text"]
        model_used = acc["model_used"]
        cost_usd = acc["cost_usd"]
        stop_reason = acc["stop_reason"]

        dur_ms = int((time.monotonic() - t0) * 1000)
        log.info("[trader-agent] as_of=%s dur=%dms cost=%s stop=%s chars=%d",
                 as_of, dur_ms, cost_usd, stop_reason, len(raw_text))

        report = self._parse_response(raw_text, as_of, now, dur_ms, model_used, cost_usd)
        if report.is_valid:
            self._cache = report
            self._cache_key = cache_key
        return report

    def invalidate(self) -> None:
        self._cache = None
        self._cache_key = None

    # ---------- local transport ----------

    async def _consume_http(self, prompt: str, acc: dict[str, Any]) -> None:
        """One-shot POST to an OpenAI-compatible /chat/completions endpoint.

        Endpoint-agnostic: 9Router, LM Studio, llama.cpp and Ollama all speak
        this shape, so nothing here assumes a particular one. Non-streaming:
        the reply is short (~500 tokens) and the caller already wraps us in
        asyncio.wait_for, so streaming buys nothing.
        """
        url = f"{LOCAL_BASE_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            # Low temp: this is structured extraction, not creative writing.
            "temperature": 0.3,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if LOCAL_API_KEY:
            headers["Authorization"] = f"Bearer {LOCAL_API_KEY}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as e:
            # Name what is actually configured. This message used to hardcode
            # "is Ollama running? (`ollama serve`)", which sent people chasing
            # a service this box does not use once the transport moved to
            # 9Router (2026-08-23). Nothing connects: the server at
            # LOCAL_BASE_URL is down, not misconfigured.
            host = urlsplit(LOCAL_BASE_URL).netloc or LOCAL_BASE_URL
            raise RuntimeError(
                f"nothing is listening at {url} (AGENT_PROVIDER=local, "
                f"model '{self.model}'). Start whatever serves {host} — on "
                f"this box that is 9Router, dashboard at http://{host.split(':')[0]}"
                f":20128/dashboard. Change LOCAL_BASE_URL in .env to point "
                f"somewhere else. [{e}]"
            ) from e
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "")[:300]
            raise RuntimeError(
                f"the model endpoint returned HTTP {e.response.status_code}: {body} "
                f"(is model '{self.model}' offered by {LOCAL_BASE_URL}? "
                f"GET {LOCAL_BASE_URL.rstrip('/')}/models lists what it has)"
            ) from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(
                f"the model endpoint returned no choices: {str(data)[:300]}")
        acc["raw_text"] = (choices[0].get("message") or {}).get("content") or ""
        acc["model_used"] = data.get("model") or self.model
        acc["stop_reason"] = choices[0].get("finish_reason")
        acc["cost_usd"] = 0.0        # self-hosted — no marginal cost per call

    # ---------- prompt assembly ----------

    def _build_prompt(self, snap: dict[str, Any], ctx: dict[str, Any]) -> str:
        """Serialize the snapshot + sector context into a compact VN prompt."""
        # Trim snapshot — the agent only needs fields relevant to picks. Cap the
        # candidate counts to bound input tokens (→ faster, cheaper, less stall risk).
        buy_cands = [_trim_pick(p) for p in snap.get("top_buys", [])[:AGENT_MAX_BUY_CANDIDATES]]
        sell_cands = [_trim_pick(p) for p in snap.get("top_sells", [])[:AGENT_MAX_SELL_CANDIDATES]]
        regime = ctx.get("regime") or {}
        sector_signals = ctx.get("sector_signals", [])
        # Only ranker's current day — keep prompt small.
        sig_rows = [
            {"code": s.get("sector_code"), "action": s.get("action"),
             "score": round(float(s.get("score") or 0), 3), "rank": s.get("rank")}
            for s in sector_signals[:15]
        ]
        flow_daily = ctx.get("flow_daily", {})
        freshness = snap.get("freshness", {}) or {}

        payload = {
            "as_of": snap.get("as_of") or ctx.get("as_of"),
            "regime": regime,
            "sector_signals": sig_rows,
            "sector_flow_context": _trim_flow(flow_daily),
            "freshness": {
                "is_valid": freshness.get("is_valid"),
                "errors": freshness.get("errors", []),
                "warnings": (freshness.get("warnings") or [])[:3],
            },
            "BUY_CANDIDATES": buy_cands,
            "AVOID_CANDIDATES": sell_cands,
        }
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)

        return (
            "Dữ liệu thị trường hôm nay (JSON, dùng làm bằng chứng duy nhất):\n\n"
            f"```json\n{payload_json}\n```\n\n"
            "Hãy phân tích và trả JSON theo schema đã quy định trong system prompt. "
            "Chỉ chọn mã từ BUY_CANDIDATES (top_buys) và AVOID_CANDIDATES (avoid). "
            "Cân nhắc tin tức trong trường `news` của mỗi candidate khi ra conviction."
        )

    # ---------- response parsing ----------

    def _parse_response(self, text: str, as_of: str, built_at: float,
                        dur_ms: int, model: str, cost_usd: float | None) -> AgentReport:
        """Extract the JSON block and convert to AgentReport."""
        if not text.strip():
            return AgentReport(
                built_at=built_at, as_of=as_of, model=model, duration_ms=dur_ms,
                cost_usd=cost_usd, gist="", regime_comment="",
                top_buys=[], avoid=[], portfolio_note="", raw_text=text,
                is_valid=False, error="empty response",
            )
        # Local reasoning models (Qwen3 & friends) prepend a <think>...</think>
        # monologue. It routinely contains braces, which would poison the
        # no-fence fallback below, so drop it before matching. An unterminated
        # block (output truncated mid-think) is dropped to end-of-text.
        search_text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        search_text = re.sub(r"<think>.*$", "", search_text, flags=re.S)

        m = re.search(r"```json\s*(\{.*?\})\s*```", search_text, re.S)
        if not m:
            # Try to grab the first {...} blob if no fence
            m = re.search(r"(\{[\s\S]*\})", search_text)
        if not m:
            return AgentReport(
                built_at=built_at, as_of=as_of, model=model, duration_ms=dur_ms,
                cost_usd=cost_usd, gist="", regime_comment="",
                top_buys=[], avoid=[], portfolio_note="", raw_text=text,
                is_valid=False, error="no JSON block",
            )
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            return AgentReport(
                built_at=built_at, as_of=as_of, model=model, duration_ms=dur_ms,
                cost_usd=cost_usd, gist="", regime_comment="",
                top_buys=[], avoid=[], portfolio_note="", raw_text=text,
                is_valid=False, error=f"JSON parse: {e}",
            )

        top_buys = [_parse_pick(p) for p in data.get("top_buys", [])][:AGENT_MAX_BUYS]
        avoid = [_parse_pick(p) for p in data.get("avoid", [])][:AGENT_MAX_AVOID]
        return AgentReport(
            built_at=built_at,
            as_of=as_of,
            model=model,
            duration_ms=dur_ms,
            cost_usd=cost_usd,
            gist=str(data.get("gist") or "")[:240],
            regime_comment=str(data.get("regime_comment") or "")[:600],
            top_buys=top_buys,
            avoid=avoid,
            portfolio_note=str(data.get("portfolio_note") or "")[:400],
            raw_text=text,
            is_valid=True,
        )


# ---------- helpers ----------

def _trim_pick(p: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields the agent needs — cuts prompt size roughly in half."""
    news = [
        {"source": n.get("source"), "title": n.get("title")}
        for n in (p.get("news") or [])[:AGENT_NEWS_PER_CANDIDATE]
    ]
    return {
        "symbol": p.get("symbol"),
        "sector": p.get("sector_code"),
        "sector_name": p.get("sector_name"),
        "close": p.get("close"),
        "stop": p.get("stop"),
        "target": p.get("target"),
        "rr": p.get("rr"),
        "score": p.get("score"),
        "atr_pct": p.get("atr_pct"),
        "upside_pct": p.get("upside_pct"),
        "downside_pct": p.get("downside_pct"),
        "technical_bits": p.get("technical_bits"),
        "foreign_room_pct": p.get("foreign_room_pct"),
        "news": news,
    }


def _trim_flow(flow: dict[str, Any]) -> dict[str, Any]:
    """Keep the 4 most informative sector-level columns (avoid blowing up prompt)."""
    out: dict[str, Any] = {}
    for code, row in (flow or {}).items():
        if not isinstance(row, dict):
            continue
        out[code] = {
            "flow_z20": row.get("flow_z20"),
            "foreign_hit_20d": row.get("foreign_hit_20d"),
            "rs_vnindex_20d": row.get("rs_vnindex_20d"),
            "accumulation_age": row.get("accumulation_age"),
        }
    return out


def _parse_pick(p: dict[str, Any]) -> AgentPick:
    return AgentPick(
        symbol=str(p.get("symbol") or "").upper(),
        sector=str(p.get("sector") or ""),
        action=str(p.get("action") or "BUY").upper(),
        conviction=int(p.get("conviction") or 3),
        entry=_num(p.get("entry")),
        target=_num(p.get("target")),
        stop=_num(p.get("stop")),
        rr=_num(p.get("rr")),
        reasoning=str(p.get("reasoning") or "")[:600],
        risks=list(p.get("risks") or [])[:5],
    )


def _num(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------- module singleton ----------

_AGENT: TraderAgent | None = None


def get_trader_agent() -> TraderAgent:
    global _AGENT
    if _AGENT is None:
        _AGENT = TraderAgent()
    return _AGENT


__all__ = ["TraderAgent", "AgentReport", "AgentPick", "get_trader_agent"]
