"""_audit/check_agent.py -- prove the trader agent can actually reach its model.

Run: uv run python _audit\\check_agent.py

Prints the resolved config (key masked) and then makes ONE real call.
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config as c  # noqa: E402

SEP = "=" * 78
print(SEP)
print("  Resolved agent config")
print(SEP)
key = c.LOCAL_API_KEY or ""
print(f"  AGENT_PROVIDER   = {c.AGENT_PROVIDER}")
print(f"  LOCAL_BASE_URL   = {c.LOCAL_BASE_URL}")
print(f"  LOCAL_MODEL      = {c.LOCAL_MODEL}")
print(f"  AGENT_MODEL      = {c.AGENT_MODEL}")
print(f"  AGENT_TIMEOUT_SEC= {c.AGENT_TIMEOUT_SEC}")
print(f"  LOCAL_API_KEY    = {key[:6]}...{'' if not key else str(len(key)) + ' chars'}")

print()
print(SEP)
print("  Reachability of the endpoint")
print(SEP)
import requests  # noqa: E402

try:
    r = requests.get(f"{c.LOCAL_BASE_URL}/models",
                     headers={"Authorization": f"Bearer {c.LOCAL_API_KEY}"},
                     timeout=15)
    print(f"  GET /models -> HTTP {r.status_code}")
    ids = [m.get("id") for m in r.json().get("data", [])]
    claude_ids = [i for i in ids if i and "claude" in i.lower()]
    print(f"  models offered: {len(ids)}  (claude-family: {len(claude_ids)})")
    print(f"  claude models : {', '.join(claude_ids[:10])}")
    if c.LOCAL_MODEL not in ids:
        print(f"  *** WARNING: configured LOCAL_MODEL {c.LOCAL_MODEL!r} is NOT in the list ***")
    else:
        print(f"  configured model {c.LOCAL_MODEL!r} is available")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {e}")

print()
print(SEP)
print("  One real TraderAgent call")
print(SEP)

from services.trader_agent import TraderAgent  # noqa: E402

# Shapes taken from TraderAgent._build_prompt: snapshot carries as_of /
# top_buys / top_sells / freshness; context is a DICT with regime,
# sector_signals and flow_daily.
snapshot = {
    "as_of": "2026-08-23",
    "top_buys": [
        {"symbol": "FPT", "score": 0.82, "sector_code": "TECH",
         "close": 118.4, "target": 128.0, "stop": 112.0,
         "reason": "flow z20 +1.4, breadth rising"},
        {"symbol": "SSI", "score": 0.71, "sector_code": "BROK",
         "close": 31.2, "target": 34.5, "stop": 29.4,
         "reason": "foreign net positive 12 sessions"},
    ],
    "top_sells": [
        {"symbol": "DGC", "score": -0.55, "sector_code": "CHEM",
         "close": 96.0, "reason": "flow rolling over from a high base"},
    ],
    "freshness": {"is_valid": True, "as_of": "2026-08-23"},
}

context = {
    "as_of": "2026-08-23",
    "regime": {"regime_label": "chop", "confidence": 0.42},
    "sector_signals": [
        {"sector_code": "TECH", "action": "BUY", "score": -0.105, "rank": 1},
        {"sector_code": "BROK", "action": "BUY", "score": -0.347, "rank": 3},
        {"sector_code": "CHEM", "action": "SELL", "score": -1.422, "rank": 15},
    ],
    "flow_daily": {"TECH": {"flow_z20": 1.4}, "BROK": {"flow_z20": 0.9}},
}

agent = TraderAgent()
t0 = time.perf_counter()
try:
    out = agent.analyze_sync(snapshot, context)
    dt = time.perf_counter() - t0
    print(f"  call completed in {dt:.1f}s")
    print(f"  is_valid  = {getattr(out, 'is_valid', None)}")
    err = getattr(out, "error", None)
    if err:
        print(f"  error     = {err}")
    for attr in ("summary", "buys", "avoid", "raw"):
        v = getattr(out, attr, None)
        if v:
            text = str(v)
            print(f"  {attr:<9} = {text[:300]}{'...' if len(text) > 300 else ''}")
except Exception as e:
    dt = time.perf_counter() - t0
    print(f"  FAILED after {dt:.1f}s: {type(e).__name__}: {e}")

print("\ndone.")
