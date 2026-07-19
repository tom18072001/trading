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
AGENT_MODEL        = os.environ.get("AGENT_MODEL", "haiku")   # haiku = fast + cheap for structured JSON
AGENT_TIMEOUT_SEC  = float(os.environ.get("AGENT_TIMEOUT_SEC", "120"))  # hard wall on the SDK call
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

