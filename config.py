# ============================================
# config.py — Sector Money-Flow Redesign
# ============================================
# Source of truth: CLAUDE.md (Sector Money-Flow Redesign, approved 2026-04-08)
# All settings here serve sector-level analysis only.

import os
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ===== Folders =====
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_DIR = os.path.join(BASE_DIR, "models")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SAVED_MODELS_DIR = os.path.join(MODEL_DIR, "saved")
for d in [DATA_DIR, MODEL_DIR, OUTPUT_DIR, SAVED_MODELS_DIR]:
    os.makedirs(d, exist_ok=True)

# ===== Database =====
_db_path = os.environ.get("DATABASE_PATH", "vnstock_market.db")
DATABASE_PATH = _db_path if os.path.isabs(_db_path) else os.path.join(BASE_DIR, _db_path)
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# ===== Data source =====
# Data source for vnstock.
# 2026-04-18: switched default VCI → KBS. VCI restricted free tier (returns
# empty {} from its GraphQL since ~mid-April 2026, see issue thinh-vu/vnstock#172).
# TCBS is deprecated since March 2026. KBS currently returns full HOSE data
# including foreign_room via price_board. Override via env var if upstream
# swaps again.
DATA_SOURCE = os.environ.get("DATA_SOURCE", "KBS")
END_DATE = os.environ.get("END_DATE", datetime.now().strftime("%Y-%m-%d"))
START_DATE = os.environ.get("START_DATE", "2021-01-01")  # 5y backfill default

# ===== API =====
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))
FRONTEND_URLS = os.environ.get(
    "FRONTEND_URLS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
).split(",")

# --- API exposure (review 2026-08-22, P2-1) ---
# api/auth.py has defined require_api_key since March and NO router ever used
# it; api/rate_limit.py defined a limiter that was never attached to the app.
# So every POST -- /insight/refresh, /sectors/ranking/publish,
# /sectors/regime/classify, /sectors/backtest/run, /flow/ingest -- was open,
# on an app bound to 0.0.0.0 and historically exposed through a cloudflared
# tunnel. Anyone with the tunnel URL could loop a universe rebuild and burn
# the KBS quota and the LLM budget.
#
# Defaults keep the current behaviour so the local dashboard is not broken by
# this review. Turn API_REQUIRE_KEY on whenever the API leaves localhost.
API_REQUIRE_KEY = os.environ.get("API_REQUIRE_KEY", "0").lower() in ("1", "true", "yes")
# Tunnel origins are opt-in now. The old code listed "https://*.ngrok-free.app"
# in allow_origins, where a "*" is a literal character and matches nothing --
# only the regex below ever worked, and it admitted every tunnel on those two
# shared domains.
API_ALLOW_TUNNEL_ORIGINS = os.environ.get(
    "API_ALLOW_TUNNEL_ORIGINS", "1").lower() in ("1", "true", "yes")
# Per-IP ceiling on the expensive POST endpoints (universe rebuild, retrain,
# backtest). Generous by default -- this stops a loop, not a person.
API_WRITE_RATE_LIMIT = os.environ.get("API_WRITE_RATE_LIMIT", "20/minute")

# ===== 15 VN Sectors — sector_code → display name =====
# sector_code is the canonical key used everywhere in the system.
SECTORS: dict[str, str] = {
    "BANK":   "Ngân hàng",
    "BROK":   "Chứng khoán",
    "REAL":   "Bất động sản",
    "STEEL":  "Thép & Vật liệu XD",
    "RETAIL": "Bán lẻ",
    "FOOD":   "Thực phẩm & Đồ uống",
    "OIL":    "Dầu khí",
    "POWER":  "Điện & Năng lượng",
    "TECH":   "Công nghệ",
    "LOGIS":  "Hàng không & Logistics",
    "INSUR":  "Bảo hiểm",
    "CHEM":   "Hóa chất & Phân bón",
    "TEXT":   "Dệt may",
    "RUBBER": "Cao su & Nhựa",
    "FISH":   "Thủy sản",
}

# ===== Proxy baskets — top 5 by market cap per sector =====
# These constituents are used ONLY to compute sector aggregates. They are NOT
# predicted individually and their raw OHLCV is discarded after aggregation
# (rolling 60-day window kept for recompute).
#
# DEPRECATED for picks: since 2026-04-17 the per-ticker picks pipeline reads
# from services.picks_universe_service.PicksUniverseService, which discovers
# the universe dynamically from vnstock Listing (HOSE). PROXY_BASKETS is kept
# ONLY as a seed for sector aggregates (sector_flow_daily) and as a fallback
# override table in sector_constituents during the 2-week shadow run before
# the legacy _legacy_stock_* tables are dropped.
PROXY_BASKETS: dict[str, list[str]] = {
    "BANK":   ["VCB", "BID", "CTG", "TCB", "MBB"],
    "BROK":   ["SSI", "VND", "HCM", "VCI", "SHS"],
    "REAL":   ["VHM", "VIC", "NVL", "KDH", "DXG"],
    "STEEL":  ["HPG", "HSG", "NKG", "TLH", "POM"],
    "RETAIL": ["MWG", "FRT", "DGW", "PNJ", "VRE"],
    "FOOD":   ["VNM", "MSN", "SAB", "QNS", "MCH"],
    "OIL":    ["GAS", "PLX", "PVD", "PVS", "BSR"],
    "POWER":  ["POW", "GEG", "PC1", "REE", "NT2"],
    "TECH":   ["FPT", "CMG", "ELC", "SAM", "ITD"],
    "LOGIS":  ["VJC", "HVN", "ACV", "GMD", "VTP"],
    "INSUR":  ["BVH", "BMI", "MIG", "PVI", "BIC"],
    "CHEM":   ["DPM", "DCM", "DGC", "LAS", "BFC"],
    "TEXT":   ["TCM", "STK", "MSH", "TNG", "VGT"],
    "RUBBER": ["GVR", "DRC", "CSM", "BMP", "NTP"],
    "FISH":   ["VHC", "IDI", "ANV", "CMX", "MPC"],
}

# Execution universe: top-3 of each basket (CLAUDE.md §14 default).
# DEPRECATED for picks — same rationale as PROXY_BASKETS above.
EXECUTION_BASKETS: dict[str, list[str]] = {
    code: syms[:3] for code, syms in PROXY_BASKETS.items()
}

# ===== Macro anchors =====
MACRO_TICKERS = {
    "vnindex": "VNINDEX",      # via vnstock
    "usdvnd":  "USDVND=X",     # FX
    "brent":   "BZ=F",          # Brent crude
    "us10y":   "DGS10",         # FRED
    "gold":    "GC=F",          # Gold futures
}

# ===== Flow window / aggregation =====
INTRADAY_INTERVAL = "15m"        # vnstock proxy fetch cadence
ROLLING_RAW_DAYS = 60             # raw constituent OHLCV retention
DAILY_LOOKBACK_FOR_BACKFILL_YEARS = 5

# ===== Rotation model =====
# 2026-06-18: switched 5d → 20d per CLAUDE.md §16.4. 5d rewards noise-chasing;
# 20d rewards real rotations (the persistent edge the system is built for).
# Override via env for experiments without editing source.
ROTATION_TARGET_HORIZON_DAYS = int(os.environ.get("ROTATION_TARGET_HORIZON_DAYS", "20"))
PERSISTENCE_FILTER_SESSIONS = 3
MAX_LONG_SECTORS = 3
MAX_SHORT_SECTORS = 2

# --- Live-signal safety rails (review 2026-08-22, P1-5) ---
# All three were promised by the approved plan and existed nowhere in code.
#
# §16.9 — at most this many concurrent ACCUMULATE positions. Stealth used to
#   be able to tag all 15 sectors at once, which is not a portfolio.
MAX_ACCUMULATE_SECTORS = int(os.environ.get("MAX_ACCUMULATE_SECTORS", "4"))
# §16.9 — a stealth event that has not broken out after this many sessions is
#   dead money; release it instead of holding the slot forever.
ACCUMULATE_MAX_AGE_SESSIONS = int(os.environ.get("ACCUMULATE_MAX_AGE_SESSIONS", "30"))
# §18.4/20 — global kill-switch. Read at the top of SectorSignalService.publish();
#   when true, no new ACCUMULATE or BUY is emitted (everything becomes HOLD).
TRADING_HALT = os.environ.get("TRADING_HALT", "0").lower() in ("1", "true", "yes")
# §18.2/12 — the VN cash market cannot short; shorts belong in a VN30F1M hedge.
#   Defaults to TRUE so this review does not silently change the daily email.
#   Set ALLOW_SHORT_SIGNALS=0 to stop publishing SELL, which is what §18.2/12
#   actually calls for. See CODE_REVIEW_2026-08-22.md P1-5.
ALLOW_SHORT_SIGNALS = os.environ.get("ALLOW_SHORT_SIGNALS", "1").lower() in ("1", "true", "yes")

# Regime states for HMM
REGIME_STATES = ["risk_on", "risk_off", "rotation", "chop"]

LIGHTGBM_RANKER_PARAMS = {
    "objective": "lambdarank",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": 8,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}

# ===== Backtest =====
BACKTEST_INITIAL_CAPITAL = 100_000_000   # 100M VND
BACKTEST_COMMISSION_PCT = 0.0018         # legacy flat round-trip (kept for compat)
BACKTEST_SLIPPAGE_PCT = 0.002            # legacy flat slippage (kept for compat)
BENCHMARK = "VNINDEX"

# --- VN-realistic friction model (2026-06-18, CLAUDE.md §18.2) ---
# Applied by SectorBacktestService instead of the old flat daily cost.
BACKTEST_FEE_BPS         = 15     # broker fee per side (0.15%) — §18.2/10
BACKTEST_SELL_TAX_BPS    = 10     # HOSE sell tax on proceeds (0.10%) — §18.2/10
BACKTEST_SLIPPAGE_MIN_PCT = 0.003 # slippage floor 0.3% — §18.2/9
BACKTEST_SLIPPAGE_ATR_MULT = 0.5  # slippage = max(min, 0.5 × ATR%) — §18.2/9
BACKTEST_PRICE_BAND_PCT  = 0.07   # HOSE ±7% daily band; skip fills on gap days — §18.2/9
BACKTEST_SETTLEMENT_LAG  = 2      # T+2 cash settlement; capital locked — §18.2/7
BACKTEST_LONG_ONLY       = True   # VN cash market cannot short — §18.2/12

# ===== Trader agent (Daily Insight "Minh") =====
# 2026-06-18: the agent had NO enforced timeout — if the Claude SDK transport
# stalls, the /insight/refresh background run hangs in the trader_agent stage
# until the frontend's 20-min ceiling, surfacing as "time exceed". These knobs
# bound it. Tune via env without editing source.
# 2026-07-20: provider switch. Three transports, selected by AGENT_PROVIDER:
#   "local" (default) — plain HTTP to an OpenAI-compatible server on this box
#       (Ollama / LM Studio / llama.cpp). No API key, no cost, no internet, and
#       no claude_agent_sdk subprocess. Best fit for a 1-call/day agent.
#   "glm"   — claude_agent_sdk transport pointed at Z.ai's Anthropic-compatible
#       endpoint (GLM models). Needs GLM_API_KEY in .env.
#   "claude"— native Claude Code subscription path via claude_agent_sdk (no key).
AGENT_PROVIDER     = os.environ.get("AGENT_PROVIDER", "local").lower()

# --- local (Ollama-style OpenAI-compatible endpoint) ---
# LOCAL_MODEL must match a tag you have actually pulled — check `ollama list`.
# Sized for a 6GB-VRAM card: an 8B at Q4 sits ~5GB and stays fully on the GPU.
LOCAL_BASE_URL     = os.environ.get("LOCAL_BASE_URL", "http://localhost:11434/v1")
LOCAL_API_KEY      = os.environ.get("LOCAL_API_KEY", "ollama")  # Ollama ignores it; LM Studio wants something
LOCAL_MODEL        = os.environ.get("LOCAL_MODEL", "qwen3:8b")

# --- glm (Z.ai) ---
GLM_BASE_URL       = os.environ.get("GLM_BASE_URL", "https://api.z.ai/api/anthropic")
GLM_API_KEY        = os.environ.get("GLM_API_KEY", "")

_DEFAULT_MODEL_BY_PROVIDER = {"local": LOCAL_MODEL, "glm": "glm-5.2", "claude": "haiku"}
AGENT_MODEL        = os.environ.get(
    "AGENT_MODEL", _DEFAULT_MODEL_BY_PROVIDER.get(AGENT_PROVIDER, "haiku"))
# Local models on a 6GB card are slower than a hosted frontier API — a 500-token
# VN JSON reply runs ~20-40s on an 8B. 120s stays adequate; raise for MoE offload.
AGENT_TIMEOUT_SEC  = float(os.environ.get("AGENT_TIMEOUT_SEC", "120"))  # hard wall on the agent call
AGENT_MAX_BUYS     = int(os.environ.get("AGENT_MAX_BUYS", "3"))   # cap output size → faster
AGENT_MAX_AVOID    = int(os.environ.get("AGENT_MAX_AVOID", "2"))
# 2026-06-18: candidate caps lowered (10→6 / 6→4) and news-per-candidate cut
# (3→2 in trader_agent._trim_pick) to shrink the agent's INPUT prompt — the
# dominant token cost per refresh/rerun. Top picks are 5 BUY / 5 SELL anyway,
# so 6/4 still gives the agent real choice. Tune up via env if you want the
# agent to see more candidates at higher token cost.
AGENT_MAX_BUY_CANDIDATES  = int(os.environ.get("AGENT_MAX_BUY_CANDIDATES", "6"))   # cap input size
AGENT_MAX_SELL_CANDIDATES = int(os.environ.get("AGENT_MAX_SELL_CANDIDATES", "4"))
AGENT_NEWS_PER_CANDIDATE  = int(os.environ.get("AGENT_NEWS_PER_CANDIDATE", "2"))   # news titles/candidate in prompt

# ===== Risk =====
RISK_CONFIG = {
    "max_sector_exposure": 0.40,
    "stop_atr_multiple": 1.5,
    "var_confidence": 0.95,
    "var_lookback_days": 60,
}

# ===== Vietnam market hours (Asia/Ho_Chi_Minh, UTC+7) =====
TIMEZONE = "Asia/Ho_Chi_Minh"
MARKET_OPEN = "09:00"
MARKET_CLOSE = "15:00"
MARKET_BREAK_START = "11:30"
MARKET_BREAK_END = "13:00"

VN_MARKET_HOLIDAYS_2026 = [
    "2026-01-01",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-04-06", "2026-04-30", "2026-05-01", "2026-09-02",
]

# =====================================================================
#  PicksUniverseService — dynamic ticker universe for report + insight
# =====================================================================
# Capability filter (all three must hold for a ticker to enter the universe):
MIN_DV_20D_VND            = 5_000_000_000   # 20d avg daily value ≥ 5B VND
MIN_HISTORY_SESSIONS      = 60               # ≥ 60 trading sessions of OHLCV
MIN_FOREIGN_ROOM_PCT      = 0.0              # foreign_room must be STRICTLY > 0

# Build pipeline
# 2026-04-18: Workers reduced from 8 → 2 and throttled because KBS free tier
# caps at 20 req/min for guests. With 75 PROXY_BASKETS constituents + news
# per final pick, 2 workers keeps us inside the limit and the build finishes
# in ~4 min. If you acquire a community (60/min) or sponsor (180+/min) API
# key, bump this back to 6–8.
UNIVERSE_BUILD_WORKERS        = 2
UNIVERSE_OHLCV_FAIL_PCT_MAX   = 0.25  # abort build if ≥ 25% tickers fail OHLCV
# Minimum passing tickers for a snapshot to be considered "valid". With ~75
# constituents in universe we expect ≥ 50. On the old full-HOSE scan (~500)
# this was also 50 — kept identical because both surfaces need at least this
# for meaningful top-N selection.
UNIVERSE_MIN_PASS             = 50
# 2026-06-18: degraded-mode picks floor. Top-5 BUY/SELL picks are now built
# whenever ≥ this many tickers pass capability, EVEN IF is_valid=False (e.g.
# ohlcv_fail_pct ≥ 25%, stale signal, a BUY sector missing picks). The STALE
# banner (driven by is_valid) still warns the user; this only stops the Daily
# Insight page from collapsing to the legacy 1-pick fallback on a noisy data
# day. Set ≥ UNIVERSE_MIN_PASS/2 so selection stays meaningful.
UNIVERSE_PICKS_FLOOR          = int(os.environ.get("UNIVERSE_PICKS_FLOOR", "20"))

# ICB supersector → our 15 sector codes. Populated incrementally — additions
# land in MODIFICATION_LOG.md. Unlisted ICBs fall through to the VN-keyword
# classifier in PicksUniverseService.
ICB_TO_SECTOR: dict[str, str] = {
    # Maps vnstock `industry_code` (Listing.symbols_by_industries()) to our 15
    # sector codes. Values are strings because the classifier normalizes via
    # str() before lookup. Codes not listed here fall through to the VN-keyword
    # classifier in picks_universe_service.
    #
    # --- Primary (clean 1:1 mapping) ---
    "2":  "INSUR",    # Bảo hiểm
    "3":  "REAL",     # Bất động sản
    "5":  "BROK",     # Chứng khoán
    "6":  "TECH",     # Công nghệ và thông tin
    "7":  "RETAIL",   # Bán lẻ
    "11": "BANK",     # Ngân hàng
    "17": "RUBBER",   # Sản phẩm cao su
    "18": "CHEM",     # SX Nhựa - Hóa chất
    "19": "FOOD",     # Thực phẩm - Đồ uống
    "20": "FISH",     # Chế biến Thủy sản
    "21": "STEEL",    # Vật liệu xây dựng (thép + xi măng + ceramic)
    "22": "POWER",    # Tiện ích (điện nước)
    "23": "LOGIS",    # Vận tải - kho bãi
    #
    # --- Extended (best-fit mapping, added 2026-04-17) ---
    # These codes previously fell through to VN-keyword classifier, causing
    # ~130+ HOSE symbols to be unclassified. Each is mapped to the closest
    # of our 15 sector codes. Borderline tickers (e.g. PLX in wholesale,
    # PVD in mining) are further refined via sector_constituents overrides
    # or the VN-keyword fallback which runs BEFORE ICB for override symbols.
    "1":  "RETAIL",   # Bán buôn (wholesale/distribution → closest = Bán lẻ)
    "8":  "CHEM",     # Chăm sóc sức khỏe (pharma/health → Hóa chất & Dược)
    "10": "OIL",      # Khai khoáng (mining/extraction → Dầu khí & Khoáng sản)
    "12": "FOOD",     # Nông - Lâm - Ngư (agriculture → Thực phẩm)
    "15": "TECH",     # SX Thiết bị, máy móc (machinery → Công nghệ)
    "16": "TEXT",     # SX Hàng gia dụng (consumer goods, mostly textiles)
    "24": "STEEL",    # Xây dựng (construction → Thép & Vật liệu XD)
    "25": "RETAIL",   # Dịch vụ lưu trú, ăn uống, giải trí (hospitality → Bán lẻ)
    "26": "CHEM",     # SX Phụ trợ (supporting manufacturing → Hóa chất)
    "27": "POWER",    # Thiết bị điện (electrical equipment → Điện & NL)
    "28": "RETAIL",   # Dịch vụ tư vấn, hỗ trợ (consulting/services → Bán lẻ)
    "29": "INSUR",    # Tài chính khác (other finance → Bảo hiểm)
}

