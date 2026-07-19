# TraderAgent — Claude-powered VN trader expert

Status: ACTIVE (2026-04-18). Replaces the legacy OpenClaw "Trung" agent.
Module: `services/trader_agent.py`.

## 1. Purpose & non-goals

**Purpose.** Produce a short, structured BUY/AVOID recommendation for today
by reasoning over the sector money-flow + per-ticker picks cache assembled
by `PicksUniverseService`. The agent adds what the rule-based picks can't:
a VN-language narrative that weighs news against technical bits and sector
rotation, and a conviction star rating.

**Non-goals.**
- Not a trading bot. No order placement.
- Not a replacement for `SectorSignalService` (the rotation ranker) — the
  agent consumes its output, does not override it.
- Does NOT invent new tickers — it can only pick from the `BUY_CANDIDATES`
  and `AVOID_CANDIDATES` lists the service hands it (the snapshot's
  `top_buys` / `top_sells`).
- No web browsing, no tool use. One-shot, JSON-only output.

## 2. Transport

`claude_agent_sdk` — executes through the user's existing Claude Code
subscription. No `ANTHROPIC_API_KEY` required. One-shot call via
`claude_agent_sdk.query()`:

- `max_turns=1`, no tool use, `thinking=disabled`.
- `model="sonnet"` by default (maps to `claude-sonnet-4-6` in the SDK
  resolver as of 2026-04).
- Ambient cost: ~$0.10–0.15 / call at today's pricing (visible in the
  `ResultMessage.total_cost_usd` field — surfaced in the frontend header).

## 3. Invocation surface

Agent is invoked ONLY from `POST /api/insight/refresh` (explicit user click
on the Daily Insight refresh button).

- `/api/insight/refresh`: invalidates both the picks-universe snapshot and
  the agent's own cache, publishes fresh ranker signals, rebuilds the
  snapshot, calls `agent.analyze_sync(snap_dict, ctx)`, then returns the
  usual `/daily` payload augmented with `agent_report` + `refresh`.
- `/api/insight/daily` (read-only): attaches the last cached agent report
  if one exists, never runs the agent itself.

Agent has its own in-memory cache (TTL 10 min, keyed on
`as_of + len(buys) + len(sells)`). Callers that want a fresh report must
hit `/refresh`.

## 4. Prompt structure

System prompt (constant; see `services/trader_agent.py::SYSTEM_PROMPT`):

- Identity: "Minh", 15 năm kinh nghiệm VN HOSE/HNX/UPCoM.
- Framework: MACRO → SECTOR → STOCK → TIMING.
- Hard rules: R:R ≥ 1.5 on BUY; pick ONLY from provided candidates; JSON
  fenced output, no free-form text.

User message: a single JSON blob containing
- `as_of`, `regime`, `sector_signals`, `sector_flow_context`, `freshness`,
- `BUY_CANDIDATES` (from `snapshot.top_buys`, trimmed to essentials +
  up to 3 news items per ticker),
- `AVOID_CANDIDATES` (from `snapshot.top_sells`, same trim).

## 5. Output schema

Fenced JSON:

```json
{
  "gist": "≤ 120 char VN market summary",
  "regime_comment": "2-3 sentence VN regime + rotation read",
  "top_buys": [
    {"symbol": "FPT", "sector": "TECH", "action": "BUY", "conviction": 4,
     "entry": 76.0, "target": 82.1, "stop": 71.9, "rr": 1.5,
     "reasoning": "...", "risks": ["..."]}
  ],
  "avoid": [
    {"symbol": "PC1", "sector": "POWER", "action": "AVOID", "conviction": 4,
     "entry": null, "target": null, "stop": 25.1, "rr": null,
     "reasoning": "...", "risks": []}
  ],
  "portfolio_note": "Gợi ý phân bổ 1-2 câu"
}
```

Parsed into `AgentReport` (services.trader_agent). Invalid responses
(empty, no JSON block, parse error) produce an `AgentReport` with
`is_valid=False` + `error` set. Frontend shows a dimmed "chưa sẵn sàng"
card in that case.

## 6. Failure modes

| Mode | Behaviour |
|---|---|
| Claude SDK transport error (not signed in, no subscription, etc.) | `analyze()` returns `AgentReport(is_valid=False, error=...)`. Frontend renders fallback card. |
| Empty text response | Same as above, `error="empty response"`. |
| JSON parse failure | Same, `error="JSON parse: ..."`; full reply retained in `raw_text` for debugging. |
| Picks snapshot invalid (`is_valid=False`) | Refresh still runs the agent, but the snapshot's freshness block is included in the prompt — the agent is expected to downgrade conviction or skip BUYs. |
| Rate limit (Claude Code 5h budget) | SDK surfaces `RateLimitEvent`; `query()` completes with whatever came before. If only `RateLimitEvent` arrived (no `AssistantMessage`), report is invalid with empty text. |

## 7. Observability

Logger prefix: `[trader-agent]`.
Logs emitted:
- `cache hit as_of=...`
- `as_of=... dur=Nms cost=$X stop=... chars=N`
- `query failed: ...` on exception (with traceback)

Frontend header shows `model · duration · cost` inline on the agent card.

## 8. Security & sandboxing

- No tool use enabled (`allowed_tools=[]`). The agent cannot read files,
  run shell, or call MCP servers.
- Input data is bounded: only pre-trimmed snapshot dict + sector context.
  No raw user text reaches the agent.
- Output is always wrapped in `fenced JSON` and parsed by a strict regex
  + `json.loads`. No code execution path.

## 9. Future work

- Extend with a sector-level brief on weekly refresh (different prompt,
  different trigger).
- Consider gating agent calls behind `picks_universe.is_valid=True` to
  skip the API call on stale data — current behavior runs it regardless.
- Add persistent storage of agent reports for historical review (currently
  lost when process restarts).
