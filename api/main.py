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
from config import API_HOST, API_PORT, FRONTEND_URLS
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

_cors_origins = FRONTEND_URLS + [
    "https://*.ngrok-free.app",
    "https://*.trycloudflare.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.(ngrok-free\.app|trycloudflare\.com)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sector routers — the only routers in the new design.
app.include_router(sectors_flow.router)
app.include_router(sectors_ranking.router)
app.include_router(sectors_regime.router)
app.include_router(sectors_backtest.router)
app.include_router(sectors_risk.router)
app.include_router(sectors_handoff.router)
# agent_briefing router removed 2026-04-18 — replaced by services.trader_agent
# (invoked from /api/insight/refresh). See specs/trader_agent.md.
app.include_router(flow_router.router)  # Phase 15 — /api/flow/*
app.include_router(rotation_router.router)
app.include_router(stealth_router.router)
app.include_router(pulse_router.router)
app.include_router(insight_router.router)


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
