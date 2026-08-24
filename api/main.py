# ============================================
# api/main.py — FastAPI Entry (Sector Money-Flow)
# ============================================
# Run:
#   uvicorn api.main:app --reload --port 8000
# Source of truth: CLAUDE.md (Sector Money-Flow Redesign)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import (
    sectors_backtest, sectors_flow, sectors_handoff,
    sectors_ranking, sectors_regime, sectors_risk,
)
from api.routers import flow as flow_router  # Phase 15 — Money Flow Monitor
from api.routers import rotation as rotation_router
from api.routers import stealth as stealth_router
from api.routers import pulse as pulse_router
from api.routers import insight as insight_router
from api.routers import state as state_router
from config import (
    API_ALLOW_TUNNEL_ORIGINS, API_HOST, API_PORT, API_REQUIRE_KEY, FRONTEND_URLS,
)
from database.connection import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB schema + seed sectors."""
    init_db()
    yield


app = FastAPI(
    title="VN Sector Money-Flow API",
    description="Sector-level money flow tracking and rotation prediction "
                "for the Vietnamese stock market. See CLAUDE.md.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS (review 2026-08-22, P2-1).
# The two "https://*.ngrok-free.app" style entries that used to sit in
# allow_origins were dead weight: Starlette compares allow_origins by exact
# string, so a "*" there is a literal character that matches nothing. Only the
# regex ever did any work, and it admitted EVERY tunnel on two shared public
# domains -- with allow_credentials=True. It is opt-out now.
_cors_kwargs = {
    "allow_origins": [o.strip() for o in FRONTEND_URLS if o.strip()],
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if API_ALLOW_TUNNEL_ORIGINS:
    _cors_kwargs["allow_origin_regex"] = r"https://.*\.(ngrok-free\.app|trycloudflare\.com)"

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# Rate limiting. api/rate_limit.py has defined this limiter since March and
# nothing ever attached it to the app, so the "RATE_LIMIT_EXCEEDED" response
# body it carefully formats could never be returned.
from slowapi.errors import RateLimitExceeded          # noqa: E402
from slowapi.middleware import SlowAPIMiddleware      # noqa: E402

from api.rate_limit import limiter, rate_limit_exceeded_handler  # noqa: E402

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Auth. `require_api_key` existed but was wired to nothing; it is applied to
# every router here when API_REQUIRE_KEY is set. Default off so the local
# dashboard keeps working unchanged -- turn it on before exposing the API.
_guard: list = []
if API_REQUIRE_KEY:
    from fastapi import Depends

    from api.auth import require_api_key
    _guard = [Depends(require_api_key)]
    print("[api] API key required on all routers (API_REQUIRE_KEY=1)")
else:
    print("[api] WARNING: no API key required. Do not expose this port "
          "beyond localhost without setting API_REQUIRE_KEY=1.")

# Sector routers — the only routers in the new design.
app.include_router(sectors_flow.router, dependencies=_guard)
app.include_router(sectors_ranking.router, dependencies=_guard)
app.include_router(sectors_regime.router, dependencies=_guard)
app.include_router(sectors_backtest.router, dependencies=_guard)
app.include_router(sectors_risk.router, dependencies=_guard)
app.include_router(sectors_handoff.router, dependencies=_guard)
# agent_briefing router removed 2026-04-18 — replaced by services.trader_agent
# (invoked from /api/insight/refresh). See specs/trader_agent.md.
app.include_router(flow_router.router, dependencies=_guard)  # Phase 15 — /api/flow/*
app.include_router(rotation_router.router, dependencies=_guard)
app.include_router(stealth_router.router, dependencies=_guard)
app.include_router(pulse_router.router, dependencies=_guard)
app.include_router(insight_router.router, dependencies=_guard)
app.include_router(state_router.router, dependencies=_guard)  # kill-switch + positions


@app.get("/", tags=["health"])
def root():
    return {
        "name": "VN Sector Money-Flow API",
        "version": "2.0.0",
        "docs": "/docs",
        "spec": "CLAUDE.md",
    }


@app.get("/api/health", tags=["health"])
def health_check():
    from sqlalchemy import text
    from database.connection import engine
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=API_HOST, port=API_PORT, reload=True)
