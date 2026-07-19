"""
SecV5 — Unified Picks Briefing (replaces SecV4 as of 2026-04-23)
=====================================================================
Motivation: SecV4 and the Daily Insight page were recommending
different stocks because:
  - Daily Insight (/api/insight/daily) renders snapshot.top_buys +
    snapshot.top_sells directly (no ranker gate).
  - SecV4 email filtered picks through the ranker gate and dropped
    everything when the ranker emitted no BUY/ACCUMULATE that day.
SecV5 unifies the two into a single list per Tom's directive
(2026-04-23):

  * UNIFIED picks list = UNION(snapshot.top_buys, ranker-gated buys),
    deduped by symbol, each entry tagged with its source:
      BOTH          → shown in Daily Insight AND ranker-BUY    (consensus)
      DAILY_INSIGHT → only in snapshot.top_buys (no ranker gate)
      RANKER        → only from a ranker BUY/ACCUMULATE sector
  * EXPERT TRADER MEMO at the top of HTML + PDF — senior-PM voice,
    rationale per pick, conviction rating, catalyst + link pointer.
  * Plain-text email body = short actionable summary of BUY list
    (symbol, reason, Daily Insight link).
  * Default recipients = tka2001@gmail.com, anhchitruong18@gmail.com,
    hill.nguyen.1373@gmail.com (REPORT_EMAIL_TO env override still
    works).

Outputs:  report/secv5_<date>.html and report/secv5_<date>.pdf
Emails:   PDF + HTML + plain-text summary to the 3 recipients.

Usage:
    python generate_secv5.py              # today (local TZ)
    python generate_secv5.py 2026-04-23   # specific date
    python generate_secv5.py --no-email   # skip email
"""
import os, sys, io, sqlite3, subprocess, smtplib, base64, shutil, tempfile, json, datetime as dt
from pathlib import Path
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import warnings
warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# ========== CLI ==========
args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
REPORT_DATE = args[0] if args else dt.date.today().isoformat()
SEND_EMAIL = "--no-email" not in flags
RECENT_DAYS = 5
PRIOR_DAYS  = 10
TEMPLATE_PATH = ROOT / "report" / "report_template_secv5.html"
OUT_HTML = ROOT / "report" / f"secv5_{REPORT_DATE}.html"
OUT_PDF  = ROOT / "report" / f"secv5_{REPORT_DATE}.pdf"
DB_PATH  = os.environ.get("SECV3_DB_PATH") or str(ROOT / "vnstock_market.db")

# Dashboard link used inside the email + memo so readers can jump straight to
# the Daily Insight page for the live view.
DASHBOARD_URL = os.environ.get(
    "REPORT_DASHBOARD_URL",
    "http://localhost:5173/insight/daily",
)

print(f"[secv5] date={REPORT_DATE} db={DB_PATH}")

# ========== STYLE ==========
DARK_BG, CARD_BG, GRID_CLR, TEXT_CLR = "#0f172a", "#1e293b", "#334155", "#e2e8f0"
GREEN, RED, BLUE, YELLOW = "#22c55e", "#ef4444", "#38bdf8", "#eab308"
plt.rcParams.update({
    "figure.facecolor": DARK_BG, "axes.facecolor": CARD_BG,
    "axes.edgecolor": GRID_CLR, "axes.labelcolor": TEXT_CLR,
    "xtick.color": TEXT_CLR, "ytick.color": TEXT_CLR,
    "text.color": TEXT_CLR, "grid.color": GRID_CLR, "grid.alpha": 0.3,
    "font.size": 9, "font.family": "sans-serif",
})

def fig_to_base64(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig); buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")

def fmtM(x):
    if x is None: return "n/a"
    if abs(x) >= 1e9: return f"{x/1e9:+.2f}B"
    if abs(x) >= 1e6: return f"{x/1e6:+.2f}M"
    return f"{x:+,.0f}"

def fmtNum(x, pattern="{:,.2f}"):
    return pattern.format(x) if x is not None else "n/a"

# ========== DB (copy to tmp if network mount chokes) ==========
def _open_db(path):
    try:
        c = sqlite3.connect(path); c.execute("SELECT 1").fetchone(); return c
    except sqlite3.OperationalError:
        tmp = Path(tempfile.gettempdir()) / "secv3_vns.db"
        shutil.copyfile(path, tmp)
        return sqlite3.connect(str(tmp))

con = _open_db(DB_PATH); con.row_factory = sqlite3.Row; cur = con.cursor()

# ========== PICKS UNIVERSE (dynamic, no legacy tables) ==========
# Replaces the former _legacy_stock_prices + _legacy_stock_features path. Per
# CLAUDE.md §2 the legacy 170-symbol universe is removed; picks now come from
# services.picks_universe_service.PicksUniverseService, which discovers the
# universe from vnstock HOSE Listing and computes indicators in-memory.
from config import SECTORS  # noqa: E402
from services.picks_universe_service import get_picks_universe  # noqa: E402
_universe_snap = get_picks_universe().get_snapshot()
print(f"[secv5] universe snapshot as_of={_universe_snap.as_of} tickers={len(_universe_snap.tickers)} "
      f"is_valid={_universe_snap.is_valid}")
if not _universe_snap.is_valid:
    print(f"[secv5] STALE snapshot — errors: {_universe_snap.freshness.errors}")
    print(f"[secv5] STALE snapshot — warnings: {_universe_snap.freshness.warnings}")

# Adapter layer: re-materialize the legacy `sym_price`, `sym_daily_prices`,
# `feats`, `sym_sector` dicts that downstream code still consumes.
sym_price: dict[str, dict] = {}
sym_daily_prices: dict[str, list] = {}
feats: dict[str, dict] = {}
sym_sector: dict[str, str] = {}
for _sym, _tr in _universe_snap.tickers.items():
    sym_sector[_sym] = SECTORS.get(_tr.sector_code, _tr.sector_code)
    sym_price[_sym] = {
        "sector": sym_sector[_sym],
        "close": _tr.close,
        "ret_5d": _tr.ret_5d or 0.0,
        "dv_recent": _tr.dv_20d,
        "flow_recent": 0.0,  # not used downstream post-refactor
    }
    sym_daily_prices[_sym] = [
        {"date": dp["time"], "open": dp["open"], "close": dp["close"], "volume": dp["volume"]}
        for dp in (_tr.daily_prices or [])
    ]
    feats[_sym] = {
        "rsi_14": _tr.rsi_14,
        "macd_hist": _tr.macd_hist,
        "price_to_sma_20": (1 + (_tr.price_to_sma_20 or 0)) if _tr.price_to_sma_20 is not None else None,
        "price_to_sma_50": (1 + (_tr.price_to_sma_50 or 0)) if _tr.price_to_sma_50 is not None else None,
        "adx_14": _tr.adx_14,
        "volume_ratio_20": _tr.volume_ratio_20,
        "bb_position": _tr.bb_position,
        "atr_14_pct": _tr.atr_pct,
        "volatility_20d": _tr.volatility_20d,
        "return_20d": _tr.ret_20d,
        "bb_upper": _tr.bb_upper,
        "bb_lower": _tr.bb_lower,
    }

# ========== TRADER AGENT (Minh) — Claude Agent SDK ==========
# secv4 upgrade: inject agent analysis at the top of the email. Agent reads
# the snapshot's top_buys/top_sells + sector context and returns narrative
# + conviction-rated picks + avoid list. Report still renders if agent fails.
from services.trader_agent import get_trader_agent  # noqa: E402
from database.connection import SessionLocal as _SSAgent  # noqa: E402
from database.models import (  # noqa: E402
    SectorRegime as _SRAgent,
    SectorSignal as _SGAgent,
    SectorFlowDaily as _SFDAgent,
)

_agent_report = None
try:
    _as_of_str = (_universe_snap.as_of.isoformat()
                  if hasattr(_universe_snap.as_of, "isoformat")
                  else str(_universe_snap.as_of))
    _snap_dict = {
        "as_of": _as_of_str,
        "top_buys": [p.to_dict() for p in _universe_snap.top_buys],
        "top_sells": [p.to_dict() for p in _universe_snap.top_sells],
        "freshness": {**_universe_snap.freshness.to_dict(), "is_valid": _universe_snap.is_valid},
    }
    _asess = _SSAgent()
    try:
        _ar = _asess.query(_SRAgent).order_by(_SRAgent.date.desc()).first()
        _asigs = _asess.query(_SGAgent).filter(_SGAgent.date == _as_of_str).order_by(_SGAgent.rank.asc()).all()
        _aflow = _asess.query(_SFDAgent).filter(_SFDAgent.date == _as_of_str).all()
    finally:
        _asess.close()
    _agent_ctx = {
        "as_of": _as_of_str,
        "regime": ({"label": _ar.regime_label, "confidence": float(_ar.confidence or 0), "date": _ar.date}
                   if _ar else None),
        "sector_signals": [
            {"sector_code": s.sector_code, "action": s.action,
             "score": float(s.score or 0), "rank": s.rank}
            for s in _asigs
        ],
        "flow_daily": {
            r.sector_code: {
                "flow_z20": float(r.flow_z20) if r.flow_z20 is not None else None,
                "foreign_hit_20d": float(r.foreign_hit_20d) if r.foreign_hit_20d is not None else None,
                "rs_vnindex_20d": float(r.rs_vnindex_20d) if r.rs_vnindex_20d is not None else None,
                "accumulation_age": int(r.accumulation_age or 0),
            }
            for r in _aflow
        },
    }
    print("[secv5] trader_agent: invoking Minh...")
    _agent_report = get_trader_agent().analyze_sync(_snap_dict, _agent_ctx)
    print(f"[secv5] trader_agent done: is_valid={_agent_report.is_valid} "
          f"dur={_agent_report.duration_ms}ms cost=${_agent_report.cost_usd}")
except BaseException as _e:
    print(f"[secv5] trader_agent FAILED (non-fatal): {type(_e).__name__}: {_e}")
    _agent_report = None

# ========== SECTOR STATS (from persisted sector_flow_daily) ==========
# Flow aggregates come from sector_flow_daily, which is the canonical
# sector-level table. Breadth/returns come from the snapshot (per-ticker,
# freshly computed).
sector_daily_flow = defaultdict(lambda: defaultdict(float))
sector_recent_flow = defaultdict(float); sector_prior_flow = defaultdict(float)
sector_recent_dv   = defaultdict(float); sector_prior_dv   = defaultdict(float)
_flow_dates = [r[0] for r in cur.execute(
    "SELECT DISTINCT date FROM sector_flow_daily ORDER BY date DESC LIMIT ?",
    (RECENT_DAYS + PRIOR_DAYS,)
).fetchall()]
_flow_dates = sorted(_flow_dates)  # ascending
all_dates_sorted = _flow_dates
_recent_win = set(_flow_dates[-RECENT_DAYS:])
_prior_win  = set(_flow_dates[-(RECENT_DAYS + PRIOR_DAYS):-RECENT_DAYS]) if len(_flow_dates) >= RECENT_DAYS + PRIOR_DAYS else set()
for _r in cur.execute(
    "SELECT sector_code, date, net_dollar_flow FROM sector_flow_daily WHERE date >= ?",
    (_flow_dates[0] if _flow_dates else "1970-01-01",)
).fetchall():
    code = _r["sector_code"]; d = _r["date"]; flow = float(_r["net_dollar_flow"] or 0)
    vn_sec = SECTORS.get(code, code)
    sector_daily_flow[vn_sec][d] = flow
    if d in _recent_win:
        sector_recent_flow[vn_sec] += flow
    elif d in _prior_win:
        sector_prior_flow[vn_sec] += flow

# DV per sector from snapshot (sum of constituent dv_20d) — a stand-in for the
# legacy "recent dv" since we no longer aggregate raw daily DV.
for _sym, _tr in _universe_snap.tickers.items():
    sector_recent_dv[sym_sector[_sym]] += _tr.dv_20d or 0

sector_stats = []
for sec_vn in set(sym_sector.values()):
    rf_pd = sector_recent_flow.get(sec_vn, 0) / max(RECENT_DAYS, 1)
    pf_pd = sector_prior_flow.get(sec_vn, 0) / max(PRIOR_DAYS, 1)
    dv_r  = sector_recent_dv.get(sec_vn, 0)
    syms_in_sec = [s for s, vn in sym_sector.items() if vn == sec_vn]
    n = len(syms_in_sec)
    rets = [sym_price[s]["ret_5d"] for s in syms_in_sec if sym_price[s]["ret_5d"]]
    avg_r = (sum(rets) / len(rets)) if rets else 0
    rsi_bull = sum(1 for s in syms_in_sec if (feats[s].get("rsi_14") or 0) > 50)
    macd_bull = sum(1 for s in syms_in_sec if (feats[s].get("macd_hist") or 0) > 0)
    above_sma20 = sum(1 for s in syms_in_sec if (feats[s].get("price_to_sma_20") or 0) > 1)
    sector_stats.append({
        "sector": sec_vn, "n": n,
        "flow_recent": rf_pd, "flow_prior": pf_pd, "flow_delta": rf_pd - pf_pd,
        "dv_recent": dv_r, "dv_change_pct": 0, "avg_ret_5d": avg_r,
        "breadth_rsi":   100 * rsi_bull / n if n else 0,
        "breadth_macd":  100 * macd_bull / n if n else 0,
        "breadth_sma20": 100 * above_sma20 / n if n else 0,
    })
sector_stats.sort(key=lambda x: x["flow_delta"], reverse=True)
sector_stats_map = {s["sector"]: s for s in sector_stats}

# ========== NEW-SCHEMA: REGIME + MACRO + SIGNALS + FLOW_DAILY ==========
def _latest_regime():
    r = cur.execute("SELECT date, regime_label, confidence FROM sector_regime ORDER BY date DESC LIMIT 1").fetchone()
    return dict(r) if r else {"date":"n/a","regime_label":"chop","confidence":0.5}

def _latest_macro():
    r = cur.execute("SELECT * FROM macro_anchors ORDER BY time DESC LIMIT 1").fetchone()
    return dict(r) if r else {}

def _latest_signals():
    d = cur.execute("SELECT MAX(date) FROM sector_signals").fetchone()[0]
    if not d: return []
    return [dict(r) for r in cur.execute(
        "SELECT * FROM sector_signals WHERE date=? ORDER BY rank", (d,))]

def _latest_flow_daily():
    d = cur.execute("SELECT MAX(date) FROM sector_flow_daily").fetchone()[0]
    if not d: return {}
    out = {}
    for r in cur.execute("SELECT * FROM sector_flow_daily WHERE date=?", (d,)):
        out[r["sector_code"]] = dict(r)
    return out

def _sector_name_map():
    return {r["sector_code"]: r["name"] for r in cur.execute("SELECT sector_code, name FROM sectors")}

regime   = _latest_regime()
macro    = _latest_macro()
signals  = _latest_signals()
flow_d   = _latest_flow_daily()
code2name = _sector_name_map()
name2code = {v: k for k, v in code2name.items()}

# ========== COMPOSITE SCORING (from PicksUniverseService) ==========
# score_ticker and stop/target now come from services.picks_scoring via the
# snapshot. Legacy score_symbol() was deleted; the snapshot already computed
# score + is_valid_buy per ticker. The `scored` list format preserves the
# dict shape that downstream rendering code expects.
scored = [_tr.as_picks_dict() for _tr in _universe_snap.tickers.values()]

# --- Align with the rotation ranker (sector_signals) — Option A safe doctrine ---
# The email previously picked BUYs from raw flow_delta; that surfaced picks
# (e.g. NVL/REAL) the ranker had rated HOLD. Now the ranker is the gate:
#   in_secs  = sectors with action ∈ {BUY, ACCUMULATE} on the latest signal date
#   out_secs = sectors with action == SELL
# If the ranker emits no BUYs, the email also emits no BUYs (safe behaviour).
# Flow delta (top_in/top_out) is kept only as a display ordering aid.
try:
    from config import SECTORS as _SECTOR_CODE_NAME
    _VN_TO_CODE = {vn: code for code, vn in _SECTOR_CODE_NAME.items()}
    from database.connection import SessionLocal as _SS
    from database.models import SectorSignal as _SG
    _ssess = _SS()
    try:
        _latest = _ssess.query(_SG.date).order_by(_SG.date.desc()).first()
        _sig_action_by_code: dict[str, str] = {}
        if _latest:
            for r in _ssess.query(_SG).filter(_SG.date == _latest[0]).all():
                _sig_action_by_code[r.sector_code] = (r.action or "HOLD").upper()
    finally:
        _ssess.close()
    # Flip code -> VN name (sym_sector in secv3 uses VN names)
    sig_action_by_vn: dict[str, str] = {
        vn: _sig_action_by_code.get(code, "HOLD")
        for code, vn in _SECTOR_CODE_NAME.items()
    }
    ranker_in  = {vn for vn, a in sig_action_by_vn.items() if a in ("BUY", "ACCUMULATE")}
    ranker_out = {vn for vn, a in sig_action_by_vn.items() if a == "SELL"}
    print(f"[secv5] ranker align: BUY/ACCUMULATE={sorted(ranker_in) or 'none'}  SELL={sorted(ranker_out) or 'none'}")
except Exception as _e:  # pragma: no cover — safety net, never block the report
    print(f"[secv5] ranker align skipped ({_e}); falling back to flow_delta")
    ranker_in, ranker_out = set(), set()
    sig_action_by_vn = {}

# Flow-delta ordering still drives the "Sector Money Flow" chart, but picks
# must intersect with the ranker gate.
top_in  = sector_stats[:3]; top_out = sector_stats[-3:][::-1]
flow_in_secs  = {s["sector"] for s in top_in}
flow_out_secs = {s["sector"] for s in top_out}
# Hard gate: long-leg = ranker BUY/ACCUMULATE; short-leg = ranker SELL.
in_secs  = ranker_in if ranker_in else set()
out_secs = ranker_out if ranker_out else flow_out_secs  # only fall back on SELL side

buy_cands = [s for s in scored if s["sector"] in in_secs and s["score"] >= 3 and s["ret_5d"] > -1]
buy_cands.sort(key=lambda x: (x["score"], x["dv"]), reverse=True)
buys = buy_cands[:6]
sell_cands = [s for s in scored if s["sector"] in out_secs]
sell_cands.sort(key=lambda x: (x["score"], -x["dv"]))
sells = sell_cands[:6]
already = {b["sym"] for b in buys} | {s["sym"] for s in sells}
watch_cands = [s for s in scored if s["sym"] not in already and s["score"] >= 4]
watch_cands.sort(key=lambda x: (x["ret_5d"], x["score"]), reverse=True)
watches = watch_cands[:5]
volatile = sorted(scored, key=lambda x: (x.get("atr_pct") or 0), reverse=True)[:12]

# ========== CHARTS (reuse from v2) ==========
def make_sector_flow_chart(stats):
    fig, ax = plt.subplots(figsize=(10, max(4, len(stats)*0.4)))
    sectors = [s["sector"] for s in reversed(stats)]
    deltas  = [s["flow_delta"] for s in reversed(stats)]
    colors  = [GREEN if d >= 0 else RED for d in deltas]
    bars = ax.barh(sectors, deltas, color=colors, height=0.6)
    ax.set_xlabel("Flow Delta (VND/day)")
    ax.set_title("Sector Money Flow Delta — Recent vs Prior", fontsize=13, fontweight="bold", pad=10)
    ax.axvline(0, color=GRID_CLR, linewidth=0.8); ax.grid(axis="x", alpha=0.2)
    max_abs = max((abs(d) for d in deltas), default=1) or 1
    for bar, val in zip(bars, deltas):
        ax.text(bar.get_width() + (max_abs*0.02 * (1 if val>=0 else -1)),
                bar.get_y() + bar.get_height()/2, fmtM(val),
                ha="left" if val >= 0 else "right", va="center", fontsize=8, color=TEXT_CLR)
    fig.tight_layout(); return fig_to_base64(fig)

def make_sector_aggregate_chart(sector_stats):
    stats_sorted = sorted(sector_stats, key=lambda x: x["avg_ret_5d"])
    sectors = [s["sector"] for s in stats_sorted]
    rets = [s["avg_ret_5d"] for s in stats_sorted]
    colors = [GREEN if r >= 0 else RED for r in rets]
    fig, ax = plt.subplots(figsize=(10, max(4, len(sectors)*0.4)))
    bars = ax.barh(sectors, rets, color=colors, height=0.6)
    ax.set_xlabel("Average 5-Day Return (%)")
    ax.set_title("Sector Aggregate Performance — Avg 5d Return", fontsize=13, fontweight="bold", pad=10)
    ax.axvline(0, color=GRID_CLR, linewidth=0.8); ax.grid(axis="x", alpha=0.2)
    max_abs = max((abs(r) for r in rets), default=1) or 1
    for bar, val in zip(bars, rets):
        offset = max_abs * 0.02 * (1 if val >= 0 else -1)
        ax.text(bar.get_width() + offset, bar.get_y() + bar.get_height()/2, f"{val:+.2f}%",
                ha="left" if val >= 0 else "right", va="center", fontsize=8, color=TEXT_CLR)
    fig.tight_layout(); return fig_to_base64(fig)

def make_correlation_heatmap(sector_daily_flow, all_dates_sorted):
    sectors = sorted(sector_daily_flow.keys())
    if len(sectors) < 2: return ""
    matrix = [[sector_daily_flow[sec].get(d, 0.0) for sec in sectors] for d in all_dates_sorted]
    arr = np.array(matrix)
    n = arr.shape[1]
    corr = np.nan_to_num(np.corrcoef(arr.T), nan=0.0)
    fig, ax = plt.subplots(figsize=(max(6, n*0.55), max(5, n*0.45)))
    im = ax.imshow(corr, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(n)); ax.set_yticks(range(n))
    short = [s[:18] for s in sectors]
    ax.set_xticklabels(short, rotation=45, ha="right", fontsize=7)
    ax.set_yticklabels(short, fontsize=7)
    for i in range(n):
        for j in range(n):
            val = corr[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=6, color=("#000" if abs(val) < 0.5 else "#fff"))
    ax.set_title("Sector Money Flow Correlation", fontsize=12, fontweight="bold", pad=10)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Correlation")
    fig.tight_layout(); return fig_to_base64(fig, dpi=130)

def make_mini_chart(sym, daily_prices):
    if len(daily_prices) < 3: return None
    dates_labels = [p["date"][-5:] for p in daily_prices]
    closes = [p["close"] for p in daily_prices]
    volumes = [p["volume"] for p in daily_prices]
    x = range(len(closes))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3.2, 2.2),
                                    gridspec_kw={"height_ratios": [2.5, 1]}, sharex=True)
    color = GREEN if closes[-1] >= closes[0] else RED
    ax1.plot(x, closes, color=color, linewidth=1.5)
    ax1.fill_between(x, closes, alpha=0.15, color=color)
    ax1.set_ylabel("Price", fontsize=7); ax1.tick_params(labelsize=6); ax1.grid(alpha=0.15)
    vol_colors = [GREEN if dp["close"] >= dp["open"] else RED for dp in daily_prices]
    ax2.bar(x, volumes, color=vol_colors, width=0.6, alpha=0.7)
    ax2.set_ylabel("Vol", fontsize=7); ax2.tick_params(labelsize=6)
    ax2.set_xticks(x); ax2.set_xticklabels(dates_labels, rotation=30, fontsize=5)
    ax2.grid(alpha=0.15)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v/1e6:.0f}M" if v >= 1e6 else f"{v/1e3:.0f}K"))
    fig.suptitle(sym, fontsize=10, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig_to_base64(fig, dpi=110)

print("[secv5] rendering charts...")
chart_flow_delta  = make_sector_flow_chart(sector_stats)
chart_sector_perf = make_sector_aggregate_chart(sector_stats)
chart_correlation = make_correlation_heatmap(sector_daily_flow, all_dates_sorted)

volatile_html = ""
for v in volatile:
    dp = sym_daily_prices.get(v["sym"], [])
    b64 = make_mini_chart(v["sym"], dp)
    if b64:
        ret_cls = "pos" if v["ret_5d"] >= 0 else "neg"
        volatile_html += (
            f'<div class="mini-chart-card"><div class="sym">{v["sym"]}</div>'
            f'<div class="meta">{v["sector"]} | ATR% {v.get("atr_pct") or 0:.1f} | '
            f'5d <span class="{ret_cls}">{v["ret_5d"]:+.1f}%</span></div>'
            f'<img class="chart-img-sm" src="data:image/png;base64,{b64}"></div>\n')

# ========== NEW SECTION BUILDERS ==========
REGIME_TEXT = {
    "risk_on":  "Risk-on regime: VNINDEX momentum + USD/VND stable + foreign flow persistent. Lean long the top-ranked inflow sectors, size full weight on ACCUMULATE triggers, trail stops loosely.",
    "risk_off": "Risk-off regime: broad breadth damage, foreign selling, macro pressure (USD/VND weak or US10Y spiking). Cut gross exposure, no new BUYs, only defensive adds on oversold Dầu khí / Ngân hàng, prefer cash.",
    "rotation": "Rotation regime: index grinding sideways, sector dispersion high. This is the stealth-hunter regime — trade the inflow/outflow divergence, not the index.",
    "chop":     "Chop regime: no persistent edge, correlation elevated, reduce size, wait for a clean break of regime before new full entries. Stealth signals are most valuable here.",
}

def build_regime_banner():
    lab = (regime.get("regime_label") or "chop").lower()
    klass = lab if lab in REGIME_TEXT else "chop"
    narrative = REGIME_TEXT.get(klass, REGIME_TEXT["chop"])
    conf = regime.get("confidence") or 0.5
    narrative = f"Confidence {conf:.2f} • {narrative}"
    return klass, klass.upper().replace("_", "-"), narrative

REGIME_CLASS, REGIME_LABEL, REGIME_NARRATIVE = build_regime_banner()

# Prepend STALE banner when the picks universe snapshot is invalid (vnstock
# outage, capability floor not met, etc.). This is the degraded-mode contract.
if not _universe_snap.is_valid:
    _err_bits = "; ".join(_universe_snap.freshness.errors) or "unknown"
    _stale_html = (
        "<div style='background:#8b0000;color:#fff;padding:10px 14px;"
        "border-radius:6px;margin-bottom:8px;font-weight:600;'>"
        f"⚠ STALE SNAPSHOT — {_err_bits}. BUY picks may be missing or unreliable."
        "</div>"
    )
    REGIME_NARRATIVE = _stale_html + REGIME_NARRATIVE

def macro_cell(k, fmt="{:,.2f}"):
    v = macro.get(k)
    if v is None: return "—"
    try: return fmt.format(v)
    except Exception: return str(v)

MACRO_VNINDEX = macro_cell("vnindex", "{:,.2f}")
MACRO_USDVND  = macro_cell("usdvnd", "{:,.0f}")
MACRO_BRENT   = macro_cell("brent", "{:,.2f}")
MACRO_US10Y   = macro_cell("us10y", "{:.2f}%") if macro.get("us10y") is not None else "—"
MACRO_GOLD    = macro_cell("gold", "{:,.0f}")

# ----- Money-flow narrative (prose) -----
def build_flow_narrative():
    if not sector_stats:
        return "Not enough flow data to narrate."
    top3 = sector_stats[:3]
    bot3 = sector_stats[-3:]
    # classify the broader tone
    pos_n = sum(1 for s in sector_stats if s["flow_delta"] > 0)
    neg_n = len(sector_stats) - pos_n
    tone = ("broad-based inflows dominate" if pos_n > neg_n + 2
            else "broad-based outflows dominate" if neg_n > pos_n + 2
            else "two-sided tape with clear rotation between winners and losers")
    leader = top3[0]
    laggard = bot3[-1]
    # breadth language
    hot = [s for s in top3 if s["breadth_rsi"] >= 50 or s["breadth_macd"] >= 30]
    brittle = [s for s in top3 if s["breadth_rsi"] < 20 and s["breadth_sma20"] < 10]
    # sentences
    parts = []
    parts.append(
        f"Phiên {REPORT_DATE}: {tone}. Dẫn dắt là <b>{leader['sector']}</b> "
        f"với net-flow {fmtM(leader['flow_recent'])}/ngày (trước đó {fmtM(leader['flow_prior'])}), "
        f"Δ flow {fmtM(leader['flow_delta'])}. "
        f"Áp lực phân phối mạnh nhất ở <b>{laggard['sector']}</b> "
        f"({fmtM(laggard['flow_recent'])}/ngày, Δ {fmtM(laggard['flow_delta'])})."
    )
    if hot:
        parts.append(
            f"Nhóm hấp thụ tiền đi kèm breadth lành mạnh (RSI&gt;50 hoặc MACD+): "
            f"{', '.join(s['sector'] for s in hot)} — đây là dòng tiền có chất lượng, không chỉ 'bơm' một mã."
        )
    if brittle:
        parts.append(
            f"Thận trọng: {', '.join(s['sector'] for s in brittle)} có flow dương nhưng breadth yếu — "
            f"khả năng là pump một-hai mã, không phải diffusion — chưa đủ tin cậy để 'mua gốc'."
        )
    # stealth narrative
    stealth_sec = [c for c, d in flow_d.items() if (d.get("flow_z20") or 0) >= 1.0 and (d.get("foreign_hit_20d") or 0) >= 0.6]
    if stealth_sec:
        names = [code2name.get(c, c) for c in stealth_sec]
        parts.append(
            f"<b>Stealth radar ({len(stealth_sec)} sector):</b> {', '.join(names)} — flow z20 ≥ +1.0 "
            f"và foreign hit-rate ≥ 60% (doctrine §16.1). Đây là pha 'gốc': tiền vào âm thầm trước tin."
        )
    else:
        parts.append("Stealth radar: chưa sector nào đạt đủ 5 điều kiện §16.1 hôm nay — chờ tín hiệu trưởng thành, không fomo vào cành cao.")
    # regime bridge
    parts.append(
        f"Trong bối cảnh HMM regime = <b>{REGIME_LABEL}</b>, "
        f"ưu tiên {('full-size ACCUMULATE trên top-rank' if REGIME_CLASS=='risk_on' else 'giảm gross exposure, chỉ cược vào stealth chất lượng' if REGIME_CLASS in ('risk_off','chop') else 'đánh cặp long-short theo divergence')}."
    )
    return "<br><br>".join(parts)

FLOW_NARRATIVE = build_flow_narrative()

# ----- Sector direction predictions (NEW) -----
def build_sector_prediction_rows():
    # Build a row per sector with bias, confidence, drivers, catalyst
    rows = []
    signals_by_name = {}
    for s in signals:
        nm = code2name.get(s["sector_code"], s["sector_code"])
        signals_by_name[nm] = s
    # Common catalyst hints per sector (Vietnamese, hand-crafted — OpenClaw will later auto-enrich)
    catalyst_hints = {
        "Ngân hàng": "Theo dõi lãi suất SBV, NPL Q1, tin tín dụng BĐS.",
        "Chứng khoán": "Thanh khoản HOSE, margin debt, FUEVFVND flow.",
        "Bất động sản": "Tiến độ Luật Đất đai, tháo gỡ pháp lý dự án VHM/VIC/NVL.",
        "Thép & Vật liệu XD": "Giá quặng Trung Quốc, giải ngân đầu tư công, HPG EAF ramp.",
        "Bán lẻ": "Chỉ số bán lẻ, giá USD, tin MWG/PNJ.",
        "Thực phẩm & Đồ uống": "Giá heo hơi, CPI, tin M&A MSN/VNM.",
        "Dầu khí": "Brent, OPEC+, dự án Lô B Ô Môn (GAS/PVS/PVD).",
        "Điện & Năng lượng": "Phụ tải hè, giá than, QHĐ 8 (POW/REE/GEX).",
        "Công nghệ": "FPT earnings, tin AI / chip, FED rate path.",
        "Hàng không & Logistics": "Giá dầu, tỷ giá, sức cầu du lịch (HVN/VJC/GMD).",
        "Bảo hiểm": "Lợi suất trái phiếu, thu phí BVH/MIG.",
        "Hóa chất & Phân bón": "Giá ure/urê quốc tế, tin DPM/DCM.",
        "Dệt may": "Đơn hàng Mỹ, tỷ giá USD/VND, TNG/MSH.",
        "Cao su & Nhựa": "Giá cao su TOCOM, Brent, tin GVR/DRC.",
        "Thủy sản": "Giá tôm/cá tra, thuế chống bán phá giá Mỹ, VHC/ANV.",
    }
    for s in sector_stats:
        nm = s["sector"]
        code = name2code.get(nm)
        fd = flow_d.get(code, {})
        sig = signals_by_name.get(nm)
        # Compute bias
        score = 0
        drivers = []
        if s["flow_delta"] > 0: score += 1; drivers.append("Δflow>0")
        else: score -= 1; drivers.append("Δflow<0")
        if (fd.get("flow_z20") or 0) >= 1.0: score += 2; drivers.append(f"z20={fd.get('flow_z20'):.2f}")
        elif (fd.get("flow_z20") or 0) <= -1.0: score -= 2; drivers.append(f"z20={fd.get('flow_z20'):.2f}")
        fh = fd.get("foreign_hit_20d")
        if fh is not None:
            if fh >= 0.6: score += 1; drivers.append(f"FrgHit {fh*100:.0f}%")
            elif fh <= 0.4: score -= 1; drivers.append(f"FrgHit {fh*100:.0f}%")
        if s["breadth_rsi"] >= 50: score += 1; drivers.append(f"RSI breadth {s['breadth_rsi']:.0f}%")
        elif s["breadth_rsi"] <= 10: score -= 1; drivers.append(f"RSI breadth low")
        st = fd.get("stealth_score") or 0
        if st >= 0.8: score += 1; drivers.append(f"stealth={st:.2f}")
        if sig and sig["action"] == "BUY" and sig.get("persistence_ok"): score += 2; drivers.append(f"rank#{sig['rank']} BUY")
        elif sig and sig["action"] == "SELL": score -= 2; drivers.append(f"rank#{sig['rank']} SELL")
        # Finalize
        if score >= 3:
            bias, bclass, conf_txt = "▲ UP", "pos", "High"
        elif score >= 1:
            bias, bclass, conf_txt = "▲ Lean UP", "pos", "Med"
        elif score <= -3:
            bias, bclass, conf_txt = "▼ DOWN", "neg", "High"
        elif score <= -1:
            bias, bclass, conf_txt = "▼ Lean DOWN", "neg", "Med"
        else:
            bias, bclass, conf_txt = "• Neutral", "mut", "Low"
        # Row
        z20 = fd.get("flow_z20"); z20s = f"{z20:+.2f}" if z20 is not None else "—"
        fh_s = f"{fh*100:.0f}%" if fh is not None else "—"
        st_s = f"{st:+.2f}"
        act_class = {"BUY":"tag tag-buy","SELL":"tag tag-sell","TRIM":"tag tag-trim","ACCUMULATE":"tag tag-accum","HOLD":"tag tag-hold"}.get((sig or {}).get("action") or "HOLD","tag tag-hold")
        act_txt = (sig or {}).get("action") or "—"
        rank_txt = (sig or {}).get("rank") or "—"
        reason = ", ".join(drivers[:4])
        catalyst = catalyst_hints.get(nm, "—")
        rows.append(
            f"<tr><td class='sym'>{nm}</td>"
            f"<td class='{bclass}'>{bias}</td>"
            f"<td>{conf_txt}</td>"
            f"<td>{z20s}</td>"
            f"<td>{fh_s}</td>"
            f"<td>{st_s}</td>"
            f"<td><span class='{act_class}'>{act_txt}</span> <span class='mut'>#{rank_txt}</span></td>"
            f"<td class='mut'>{reason}. <i>Catalyst:</i> {catalyst}</td></tr>"
        )
    return "".join(rows)

SECTOR_PREDICTION_ROWS = build_sector_prediction_rows()

# ----- Stealth accumulation watchlist (§16.1) -----
def build_stealth_rows():
    rows = []
    count = 0
    for code, fd in flow_d.items():
        nm = code2name.get(code, code)
        z20 = fd.get("flow_z20")
        fh  = fd.get("foreign_hit_20d")
        br  = fd.get("breadth_sma20")
        st  = fd.get("stealth_score")
        age = fd.get("accumulation_age") or 0
        # doctrine checks
        c1 = z20 is not None and z20 >= 1.0
        c2 = fh is not None and fh >= 0.6
        c3 = br is not None and br >= 0.4   # simplified "breadth rising"
        total = sum(1 for c in (c1,c2,c3) if c)
        if total == 0: continue
        if c1 and c2 and c3:
            status, sclass = "GỐC (ACCUMULATE)", "tag tag-accum"
            count += 1
        elif total == 2:
            status, sclass = "PRE-STEALTH (watch)", "tag tag-watch"
        else:
            status, sclass = "early signal", "tag tag-hold"
        rows.append(
            f"<tr><td class='sym'>{nm}</td>"
            f"<td>{z20:+.2f}</td>"
            f"<td>{(fh or 0)*100:.0f}%</td>"
            f"<td>{(br or 0)*100:.0f}%</td>"
            f"<td>{(st or 0):+.2f}</td>"
            f"<td>{age}</td>"
            f"<td><span class='{sclass}'>{status}</span></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='7' class='mut'>Không sector nào đạt tiêu chí stealth hôm nay. Giữ tiền, chờ tín hiệu.</td></tr>")
    return "".join(rows), count

STEALTH_ROWS, NUM_STEALTH = build_stealth_rows()

# ----- Inflow / outflow thesis (v2-compatible) -----
def thesis_in_html(s):
    return (f"<p class='lead'><b class='pos'>&#9650; {s['sector']}</b> — Net flow {fmtM(s['flow_recent'])}/d "
            f"(prior {fmtM(s['flow_prior'])}/d). Breadth: {s['breadth_rsi']:.0f}% RSI&gt;50, "
            f"{s['breadth_macd']:.0f}% MACD bull, {s['breadth_sma20']:.0f}% above SMA20. "
            f"Avg 5d ret {s['avg_ret_5d']:+.2f}%. "
            f"Institutional accumulation confirmed by breadth — fade dips, not rallies.</p>")
def thesis_out_html(s):
    return (f"<p class='lead'><b class='neg'>&#9660; {s['sector']}</b> — Net flow {fmtM(s['flow_recent'])}/d "
            f"(prior {fmtM(s['flow_prior'])}/d). Breadth: {s['breadth_rsi']:.0f}% RSI&gt;50, "
            f"{s['breadth_macd']:.0f}% MACD bull, {s['breadth_sma20']:.0f}% above SMA20. "
            f"Avg 5d ret {s['avg_ret_5d']:+.2f}%. "
            f"Distribution phase — trim longs, no bottom-fishing until breadth recovers.</p>")
inflow_thesis  = "".join(thesis_in_html(s)  for s in top_in)
outflow_thesis = "".join(thesis_out_html(s) for s in top_out)

# ----- BUY / SELL / WATCH rows -----
def buy_thesis(p):
    bits = []
    if p["rsi"] and 50 <= p["rsi"] <= 70: bits.append("momentum lành")
    if p["adx"] and p["adx"] > 25: bits.append("trend mạnh")
    if p["vr20"] and p["vr20"] > 1.3: bits.append("volume xác nhận")
    if p["bb_pos"] and p["bb_pos"] > 0.7: bits.append("sát BB upper")
    # Sector-level catalyst
    catalyst_hint = {
        "Bất động sản": "Nút thắt pháp lý dự án, KQKD Q1.",
        "Công nghệ": "FPT/CMG earnings, FED cut tail.",
        "Dầu khí": "Brent, Lô B Ô Môn, KQKD GAS/PVS.",
        "Thép & Vật liệu XD": "Giá quặng, đầu tư công, HPG EAF.",
        "Chứng khoán": "Thanh khoản HOSE, KRX readiness.",
    }.get(p["sector"], "Theo tin ngành tổng hợp bởi OpenClaw.")
    return (f"Sector inflow + {', '.join(bits) if bits else 'clean technicals'}. "
            f"Accumulate, stop dưới SMA20. <i>Catalyst:</i> {catalyst_hint}")

def sell_thesis(p):
    bits = []
    if p["rsi"] and p["rsi"] < 45: bits.append("momentum mất")
    if p["macd_h"] is not None and p["macd_h"] < 0: bits.append("MACD âm")
    if p["vr20"] and p["vr20"] > 1.2: bits.append("volume phân phối")
    if p["bb_pos"] is not None and p["bb_pos"] < 0.3: bits.append("test BB dưới")
    return f"Sector outflow + {', '.join(bits) if bits else 'technicals yếu'}. Exit / tránh."

def watch_thesis(p):
    return f"Strong composite ({p['score']}) — chờ sector confirm trước khi size."

# Stop/target + validity moved to services.picks_scoring (single source of
# truth). Local adapters preserve the previous (stop, target, err) signature
# used by buy_row() below.
from services.picks_scoring import (  # noqa: E402
    PickProfile as _PickProfile,
    compute_stop_target_rr as _compute_stop_target_rr,
    is_valid_long_pick as _is_valid_long_pick,
)

def compute_stop_target(p):
    stop, target, _rr, err = _compute_stop_target_rr(p, _PickProfile.SWING)
    return stop, target, err

def is_valid_buy(p):
    stop, target, err = compute_stop_target(p)
    if err:
        return False, err
    return _is_valid_long_pick(p.get("close"), target, stop)

def buy_row(p):
    rc = "pos" if p["ret_5d"] >= 0 else "neg"
    pills = ""
    if p["rsi"]: pills += f"<span class='pill'>RSI {p['rsi']:.0f}</span>"
    if p["adx"]: pills += f"<span class='pill'>ADX {p['adx']:.0f}</span>"
    if p["vr20"]: pills += f"<span class='pill'>Vol {p['vr20']:.1f}x</span>"
    if p["atr_pct"]: pills += f"<span class='pill'>ATR% {p['atr_pct']:.1f}</span>"
    sr = ""
    if p["bb_upper"] and p["bb_lower"]:
        sr = f"<span class='mut'>S {p['bb_lower']:,.0f} / R {p['bb_upper']:,.0f}</span>"
    stop, target, _ = compute_stop_target(p)
    stop_s = f"{stop:,.0f}" if stop else "—"
    tgt_s = f"{target:,.0f}" if target else "—"
    return (f"<tr><td><span class='tag tag-buy'>BUY</span></td>"
            f"<td class='sym'>{p['sym']}</td><td class='mut'>{p['sector']}</td>"
            f"<td>{p['close']:,.0f}</td>"
            f"<td class='{rc}'>{p['ret_5d']:+.2f}%</td>"
            f"<td>{p['score']}</td><td>{pills}</td><td>{sr}</td>"
            f"<td class='neg'>{stop_s}</td><td class='pos'>{tgt_s}</td>"
            f"<td class='mut' style='max-width:260px'>{buy_thesis(p)}</td></tr>")

def pick_row(p, tag_cls, tag_text, thesis):
    rc = "pos" if p["ret_5d"] >= 0 else "neg"
    pills = ""
    if p["rsi"]: pills += f"<span class='pill'>RSI {p['rsi']:.0f}</span>"
    if p["adx"]: pills += f"<span class='pill'>ADX {p['adx']:.0f}</span>"
    if p["vr20"]: pills += f"<span class='pill'>Vol {p['vr20']:.1f}x</span>"
    if p["atr_pct"]: pills += f"<span class='pill'>ATR% {p['atr_pct']:.1f}</span>"
    sr = ""
    if p["bb_upper"] and p["bb_lower"]:
        sr = f"<span class='mut'>S {p['bb_lower']:,.0f} / R {p['bb_upper']:,.0f}</span>"
    return (f"<tr><td><span class='tag {tag_cls}'>{tag_text}</span></td>"
            f"<td class='sym'>{p['sym']}</td><td class='mut'>{p['sector']}</td>"
            f"<td>{p['close']:,.0f}</td>"
            f"<td class='{rc}'>{p['ret_5d']:+.2f}%</td>"
            f"<td>{p['score']}</td><td>{pills}</td><td>{sr}</td>"
            f"<td class='mut' style='max-width:260px'>{thesis}</td></tr>")

# Validity gate — drop picks whose stop/target are degenerate (fixes NVL-style target<close bug)
_valid_buys, _rejected_buys = [], []
for b in buy_cands:
    ok, reason = is_valid_buy(b)
    if ok:
        _valid_buys.append(b)
    else:
        _rejected_buys.append((b["sym"], reason))
    if len(_valid_buys) >= 6:
        break
buys = _valid_buys
if _rejected_buys:
    print(f"[secv5] validity gate filtered {len(_rejected_buys)} buys: "
          + ", ".join(f"{s} ({r})" for s, r in _rejected_buys[:10]))

buy_rows_html  = "".join(buy_row(b) for b in buys) or "<tr><td colspan='11' class='mut'>No qualifying BUY setups today.</td></tr>"
sell_rows_html = "".join(pick_row(s, "tag-sell", "SELL",  sell_thesis(s))  for s in sells) or "<tr><td colspan='9' class='mut'>No SELL setups.</td></tr>"
watch_rows_html= "".join(pick_row(w, "tag-watch","WATCH", watch_thesis(w)) for w in watches) or "<tr><td colspan='9' class='mut'>No watch outliers.</td></tr>"

# ----- News & Catalysts by BUY pick -----
def fetch_vnstock_news(sym, lookback_days=3):
    """Try vnstock company news; fall back silently."""
    try:
        from vnstock import Vnstock  # type: ignore
        v = Vnstock().stock(symbol=sym, source="VCI")
        df = v.company.news()
        if df is None or len(df) == 0: return []
        # Pick most recent N
        items = []
        for _, row in df.head(3).iterrows():
            items.append({
                "title": str(row.get("title") or row.get("news_title") or "")[:180],
                "src":   str(row.get("source") or row.get("publisher") or "vnstock"),
                "date":  str(row.get("date") or row.get("publish_date") or ""),
            })
        return items
    except Exception:
        return []

SECTOR_CATALYST_FALLBACK = {
    "Bất động sản": "Tháo gỡ pháp lý dự án, KQKD Q1, tin giao dịch VHM/VIC/NVL.",
    "Công nghệ": "FPT/CMG earnings, AI tailwind, FED rate path.",
    "Thép & Vật liệu XD": "Giá quặng Trung Quốc, giải ngân đầu tư công, HPG EAF.",
    "Dầu khí": "Giá Brent, OPEC+ policy, tiến độ Lô B Ô Môn (GAS/PVS/PVD).",
    "Chứng khoán": "Thanh khoản HOSE, KRX go-live, margin debt.",
    "Ngân hàng": "Lãi suất SBV, NPL Q1, tăng trưởng tín dụng.",
    "Bán lẻ": "Chỉ số bán lẻ, tỷ giá USD/VND, MWG/PNJ earnings.",
    "Thực phẩm & Đồ uống": "Giá heo hơi, CPI, tin M&A MSN/VNM.",
    "Điện & Năng lượng": "Phụ tải hè, QHĐ 8, giá than.",
    "Hàng không & Logistics": "Giá dầu, tỷ giá, sức cầu du lịch.",
    "Bảo hiểm": "Lợi suất trái phiếu 10y, thu phí BVH/MIG.",
    "Hóa chất & Phân bón": "Giá urê quốc tế, tin DPM/DCM.",
    "Dệt may": "Đơn hàng Mỹ, tỷ giá USD/VND, TNG/MSH.",
    "Cao su & Nhựa": "Giá cao su TOCOM, Brent, GVR/DRC.",
    "Thủy sản": "Giá tôm/cá tra, thuế CBPG Mỹ, VHC/ANV.",
}

def build_news_blocks():
    if not buys:
        return "<p class='mut'>Không có BUY pick hôm nay — không có news cần theo dõi.</p>"
    blocks = []
    for b in buys:
        items = fetch_vnstock_news(b["sym"])
        header = f"<h3>{b['sym']} · {b['sector']}</h3>"
        if items:
            body = "".join(
                f"<div class='news-item'>{it['title']}<div class='src'>{it['src']} · {it['date']}</div></div>"
                for it in items if it["title"])
        else:
            fallback_cat = SECTOR_CATALYST_FALLBACK.get(b["sector"], "—")
            body = (f"<div class='news-item'><i>Pending</i> — OpenClaw bot chưa thu được headline 48h "
                    f"cho <b>{b['sym']}</b>. Kiểm tra thủ công CafeF / VietstockFinance hoặc đợi briefing 17:00. "
                    f"<br><b>Catalyst khung ngành:</b> {fallback_cat}"
                    f"<div class='src'>vnstock news fallback</div></div>")
        blocks.append(f"<div>{header}{body}</div>")
    return "\n".join(blocks)

NEWS_BLOCKS = build_news_blocks()

# ----- Risk & Execution notes -----
RISK_NOTES = (
    "<b>T+2.5 Settlement:</b> mọi BUY hôm nay chỉ có thể bán từ phiên T+2; "
    "backtest Sharpe phải đã trừ 2.5d lag. "
    "<b>Fees:</b> hardcode 15bps phí + 10bps thuế bán = ~40bps round-trip. "
    "<b>Price band:</b> HOSE ±7%, HNX ±10%, UPCoM ±15%; nếu basket chạm trần, skip fill ngày đó. "
    "<b>FOL:</b> các mã cạn room ngoại (room &lt; 3%) giảm trọng số foreign_net 0.5×. "
    "<b>ATR stops:</b> mặc định 1.8×ATR20 cho BUY, 2.5×ATR20 cho ACCUMULATE (wider). "
    "<b>Kill-switch:</b> nếu sector_risk_sentinel kích hoạt liên tiếp 3 lần trong phiên, "
    "đặt cờ config.trading_halt = true — dừng toàn bộ ACCUMULATE mới. "
    "<b>ETF rebalance mask:</b> zero-out foreign_net vào ngày HOSE/ETF review để tránh nhiễu. "
    "<b>Max concurrent:</b> 4 ACCUMULATE + 3 BUY + 0 short cash (short chỉ qua VN30F1M)."
)

# ----- Next-session game plan -----
def build_game_plan():
    items = []
    # 1. Regime guidance
    items.append(f"<li>Regime = <b>{REGIME_LABEL}</b>. {('Giữ nguyên exposure' if REGIME_CLASS=='risk_on' else 'Giảm gross, chỉ đánh stealth chất lượng' if REGIME_CLASS in ('risk_off','chop') else 'Đánh cặp long-short theo divergence')}.</li>")
    # 2. Top BUY action
    if buys:
        b = buys[0]
        stop, target, _ = compute_stop_target(b)
        items.append(f"<li>BUY ưu tiên <b>{b['sym']}</b> ({b['sector']}): mua quanh {b['close']:,.0f}, stop {('{:,.0f}'.format(stop) if stop else 'BB lower')}, target {('{:,.0f}'.format(target) if target else 'BB upper')}. Size = 1× vol-target.</li>")
    # 3. Stealth candidates
    if NUM_STEALTH > 0:
        items.append(f"<li>Thêm {NUM_STEALTH} stealth ACCUMULATE (size 1.5× vol-target, stop 2.5×ATR). Đây là mua gốc — chấp nhận đi ngang 2-4 tuần trước break.</li>")
    else:
        items.append("<li>Chưa có stealth nào đủ điều kiện — giữ tiền mặt, chờ z20 crossover.</li>")
    # 4. Exit items
    if sells:
        items.append(f"<li>Thoát / tránh: {', '.join(s['sym'] for s in sells[:5])}. Không bắt đáy cho đến khi breadth phục hồi.</li>")
    # 5. Risk oversight
    items.append("<li>Kiểm tra kill-switch + T+2 lịch tiền về trước 09:00 sáng mai. Đừng full-margin khi regime = chop.</li>")
    # 6. News radar
    items.append("<li>Mở News &amp; Catalyst section ngay đầu phiên, cross-check tin 48h trước khi đặt lệnh.</li>")
    return "".join(items)

GAME_PLAN = build_game_plan()

# ========== BUILD HTML ==========
template_text = TEMPLATE_PATH.read_text(encoding="utf-8")

def sec_row(s):
    fc = "pos" if s["flow_delta"] >= 0 else "neg"
    rc = "pos" if s["avg_ret_5d"] >= 0 else "neg"
    return (f"<tr><td class='sym'>{s['sector']}</td><td>{s['n']}</td>"
            f"<td class='{fc}'>{fmtM(s['flow_recent'])}</td>"
            f"<td>{fmtM(s['flow_prior'])}</td>"
            f"<td class='{fc}'>{fmtM(s['flow_delta'])}</td>"
            f"<td>{s['dv_change_pct']:+.1f}%</td>"
            f"<td class='{rc}'>{s['avg_ret_5d']:+.2f}%</td>"
            f"<td>{s['breadth_rsi']:.0f}%</td>"
            f"<td>{s['breadth_macd']:.0f}%</td>"
            f"<td>{s['breadth_sma20']:.0f}%</td></tr>")
sec_table_rows = "".join(sec_row(s) for s in sector_stats)


# ---------- secv4: agent + snapshot-driven picks renderers ----------

def _esc(s):
    """Minimal HTML-escape for snippets rendered from agent / news text."""
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _stars(n):
    n = max(0, min(5, int(n or 0)))
    return "★" * n + "☆" * (5 - n)


def render_agent_section(report):
    """Render the Minh agent's analysis as a full HTML block. Empty string
    when the agent wasn't run or failed."""
    if report is None:
        return ""
    if not report.is_valid:
        return (
            "<div class='agent-card agent-error'>"
            "<div class='agent-header'>🧠 Trader Agent — Minh (chưa sẵn sàng)</div>"
            f"<div class='mut'>{_esc(report.error or 'phân tích chưa chạy phiên này')}</div>"
            "</div>"
        )
    buys = "".join(_render_agent_pick(p, kind="BUY") for p in report.top_buys)
    avoid = "".join(_render_agent_pick(p, kind="AVOID") for p in report.avoid)
    return (
        "<div class='agent-card'>"
        "<div class='agent-header'>"
        "<span class='agent-title'>🧠 Trader Agent — Minh</span>"
        f"<span class='mut'>{_esc(report.model)} · {report.duration_ms}ms"
        + (f" · ${report.cost_usd:.3f}" if report.cost_usd is not None else "")
        + "</span></div>"
        f"<div class='agent-gist'>{_esc(report.gist)}</div>"
        + (f"<div class='agent-regime'>{_esc(report.regime_comment)}</div>"
           if report.regime_comment else "")
        + (f"<div class='agent-section-h pos-h'>Minh khuyến nghị MUA</div>{buys}" if buys else "")
        + (f"<div class='agent-section-h neg-h'>Minh khuyến nghị TRÁNH / CẮT</div>{avoid}" if avoid else "")
        + (f"<div class='agent-portfolio'>💼 <b>Gợi ý phân bổ:</b> {_esc(report.portfolio_note)}</div>"
           if report.portfolio_note else "")
        + "</div>"
    )


def _render_agent_pick(p, kind):
    risks = ""
    if p.risks:
        risks = (
            "<div class='agent-risks'>⚠ "
            + " · ".join(_esc(r) for r in p.risks[:5])
            + "</div>"
        )
    nums = []
    if p.entry is not None:
        nums.append(f"Entry <b>{p.entry:,.2f}</b>")
    if p.target is not None:
        nums.append(f"Target <span class='pos'>{p.target:,.2f}</span>")
    if p.stop is not None:
        nums.append(f"Stop <span class='neg'>{p.stop:,.2f}</span>")
    if p.rr is not None:
        nums.append(f"R:R <span class='warn'>{p.rr:.1f}</span>")
    nums_html = " · ".join(nums)
    tag_cls = "tag-buy" if kind == "BUY" else "tag-sell"
    return (
        f"<div class='agent-pick agent-pick-{kind.lower()}'>"
        f"<div class='agent-pick-head'>"
        f"<span class='sym'>{_esc(p.symbol)}</span>"
        f"<span class='mut'>{_esc(p.sector)}</span>"
        f"<span class='tag {tag_cls}'>{kind}</span>"
        f"<span class='stars' title='Conviction {p.conviction}/5'>{_stars(p.conviction)}</span>"
        f"</div>"
        f"<div class='agent-pick-nums mono'>{nums_html}</div>"
        f"<div class='agent-pick-reasoning'>{_esc(p.reasoning)}</div>"
        f"{risks}"
        f"</div>"
    )


def render_snapshot_picks(kind):
    """Render snapshot.top_buys or top_sells as card grid (used when the agent
    isn't available or for a secondary data-driven section)."""
    rows = _universe_snap.top_buys if kind == "BUY" else _universe_snap.top_sells
    if not rows:
        return "<div class='mut'>No qualifying setups today.</div>"
    out = ["<div class='snap-grid'>"]
    for r in rows:
        bits = "".join(f"<span class='pill'>{_esc(b)}</span>"
                       for b in (r.technical_bits or [])[:6])
        news = ""
        if r.news:
            news_items = "".join(
                f"<li><a href='{_esc(n.get('url'))}' target='_blank' rel='noopener'>"
                f"{_esc(n.get('title'))}</a>"
                f" <span class='mut'>[{_esc(n.get('source'))}]</span></li>"
                for n in r.news[:3]
            )
            news = f"<ul class='snap-news'>{news_items}</ul>"
        nums = (
            f"<span>Giá <b>{r.close:,.2f}</b></span>"
            + (f" · <span class='pos'>Target {r.target:,.2f}</span>" if r.target else "")
            + (f" · <span class='neg'>Stop {r.stop:,.2f}</span>" if r.stop else "")
            + (f" · <span class='warn'>R:R {r.rr:.1f}</span>" if r.rr else "")
            + (f" · ATR {r.atr_pct:.1f}%" if r.atr_pct else "")
        )
        action_cls = "tag-buy" if kind == "BUY" else "tag-sell"
        out.append(
            f"<div class='snap-card'>"
            f"<div class='snap-head'>"
            f"<span class='sym'>{_esc(r.symbol)}</span>"
            f"<span class='mut'>{_esc(r.sector_code)}</span>"
            f"<span class='tag {action_cls}'>{kind}</span>"
            f"<span class='mut'>score {r.score:+d}</span>"
            f"</div>"
            f"<div class='snap-nums mono'>{nums}</div>"
            f"<div class='snap-bits'>{bits}</div>"
            f"<div class='snap-thesis mut'>{_esc((r.sector_name or r.sector_code))}</div>"
            f"{news}"
            f"</div>"
        )
    out.append("</div>")
    return "".join(out)


AGENT_SECTION    = render_agent_section(_agent_report)
SNAP_BUYS_GRID   = render_snapshot_picks("BUY")
SNAP_SELLS_GRID  = render_snapshot_picks("SELL")


# ========== SECV5: UNIFIED PICKS (Daily Insight ∪ Ranker BUY) ==========
# The Daily Insight page renders snapshot.top_buys / top_sells without a
# ranker gate. SecV4 rendered only ranker-gated picks. SecV5 unifies both
# sources into a single list, de-duped by symbol, each entry tagged with
# its origin (BOTH / DAILY_INSIGHT / RANKER). This is the single source of
# truth surfaced in the email, the HTML, and the PDF.

def _ticker_row_to_unified_pick(sym, action, source):
    """Build a UnifiedPick dict from snapshot.tickers[sym] (TickerRow) for
    ranker-only entries (when the symbol is NOT in snapshot.top_buys)."""
    tr = _universe_snap.tickers.get(sym)
    if tr is None:
        return None
    # Recompute stop/target (SWING profile) — same as the rest of the email.
    from services.picks_scoring import (
        PickProfile as __PP,
        compute_stop_target_rr as __cst,
    )
    stop_, target_, rr_, _ = __cst(
        {"close": tr.close, "atr_pct": tr.atr_pct,
         "bb_upper": tr.bb_upper, "bb_lower": tr.bb_lower},
        __PP.SWING,
    )
    bits = []
    if tr.rsi_14 is not None:          bits.append(f"RSI {tr.rsi_14:.0f}")
    if tr.adx_14 is not None:          bits.append(f"ADX {tr.adx_14:.0f}")
    if tr.volume_ratio_20 is not None: bits.append(f"Vol {tr.volume_ratio_20:.1f}x")
    if tr.atr_pct is not None:         bits.append(f"ATR {tr.atr_pct:.1f}%")
    if tr.price_to_sma_20 is not None and tr.price_to_sma_20 > 0:
        bits.append("above SMA20")
    sector_vn = SECTORS.get(tr.sector_code, tr.sector_code)
    upside = round((target_ - tr.close) / tr.close * 100, 2) if (target_ and tr.close) else None
    downside = round((tr.close - stop_) / tr.close * 100, 2) if (stop_ and tr.close) else None
    return {
        "symbol": sym,
        "sector_code": tr.sector_code,
        "sector_name": sector_vn,
        "action": action,
        "close": tr.close,
        "stop": stop_,
        "target": target_,
        "rr": rr_,
        "score": int(tr.score or 0),
        "atr_pct": tr.atr_pct,
        "upside_pct": upside,
        "downside_pct": downside,
        "foreign_room_pct": tr.foreign_room_pct,
        "dv_20d": tr.dv_20d,
        "technical_bits": bits,
        "thesis": f"Ranker {action} trong ngành {sector_vn}; score composite {tr.score}.",
        "news": [],   # no cached news for ranker-only picks
        "source": source,
    }


def _pick_entry_to_unified(pe, source):
    """Convert a services.picks_universe_service.PickEntry → UnifiedPick."""
    # PickEntry is a dataclass; access attrs directly.
    return {
        "symbol": pe.symbol,
        "sector_code": pe.sector_code,
        "sector_name": pe.sector_name,
        "action": pe.action,
        "close": pe.close,
        "stop": pe.stop,
        "target": pe.target,
        "rr": pe.rr,
        "score": pe.score,
        "atr_pct": pe.atr_pct,
        "upside_pct": pe.upside_pct,
        "downside_pct": pe.downside_pct,
        "foreign_room_pct": pe.foreign_room_pct,
        "dv_20d": pe.dv_20d,
        "technical_bits": list(pe.technical_bits or []),
        "thesis": pe.thesis,
        "news": list(pe.news or []),
        "source": source,
    }


def build_unified_list(kind):
    """Build the unified BUY or SELL list.

    Strategy (§v5):
      * Daily Insight source = snapshot.top_buys / snapshot.top_sells.
      * Ranker source = top-2 tickers by composite score from every sector
        whose SectorSignal.action == BUY / ACCUMULATE (for BUY kind) or
        SELL (for SELL kind). Skip tickers without a close or without a
        valid stop/target.
      * Merge by symbol. If a symbol appears in both sources → source=BOTH.
      * Order: BOTH first, then DAILY_INSIGHT, then RANKER. Within each
        bucket, sort by score descending.
    """
    # --- 1. Daily Insight side ---
    if kind == "BUY":
        di_list = list(_universe_snap.top_buys)
        ranker_sectors = ranker_in
        ranker_action_for = lambda code: sig_action_by_vn.get(
            SECTORS.get(code, code), "BUY"
        )
    else:
        di_list = list(_universe_snap.top_sells)
        ranker_sectors = ranker_out
        ranker_action_for = lambda code: "SELL"

    di_by_sym = {p.symbol: p for p in di_list}

    # --- 2. Ranker side ---
    ranker_syms = []
    # Build ranker candidates by scanning snapshot.by_sector, limited to the
    # sectors the ranker gated as BUY/ACCUMULATE (or SELL). Take top-2 per
    # sector by composite score.
    VN_TO_CODE = {vn: code for code, vn in SECTORS.items()}
    for sec_vn in ranker_sectors:
        code = VN_TO_CODE.get(sec_vn, sec_vn)  # ranker_sectors holds VN names
        bucket = _universe_snap.by_sector.get(code, [])
        for tr in bucket[:2]:
            ranker_syms.append((tr.symbol, code))

    # --- 3. Normalize both sides into UnifiedPick dicts ---------------------
    # Daily side = already-built PickEntry objects; source is decided by merge.
    daily_side = [_pick_entry_to_unified(pe, "DAILY_INSIGHT") for pe in di_list]

    # Ranker side = build from TickerRow, apply BUY validity gate inline so
    # the merge helper sees only valid candidates (mirrors §18.1).
    ranker_side = []
    for sym, code in ranker_syms:
        action = ranker_action_for(code) if kind == "BUY" else "SELL"
        up = _ticker_row_to_unified_pick(sym, action, "RANKER")
        if up is None:
            continue
        if kind == "BUY":
            ok, _why = _is_valid_long_pick(up["close"], up["target"], up["stop"])
            if not ok:
                continue
        ranker_side.append(up)

    # --- 4. Delegate the merge to services.unified_picks (testable pure fn)
    from services.unified_picks import merge_pick_sources
    return merge_pick_sources(daily_side, ranker_side)


UNIFIED_BUYS  = build_unified_list("BUY")
UNIFIED_SELLS = build_unified_list("SELL")
print(f"[secv5] unified: {len(UNIFIED_BUYS)} BUY / {len(UNIFIED_SELLS)} SELL")
_src_counts = {"BOTH": 0, "DAILY_INSIGHT": 0, "RANKER": 0}
for p in UNIFIED_BUYS:
    _src_counts[p["source"]] = _src_counts.get(p["source"], 0) + 1
print(f"[secv5] unified BUY sources: {_src_counts}")


# -------- HTML rendering for the unified picks grid -----------------------

SOURCE_LABELS = {
    "BOTH":          ("cả hai", "src-both"),
    "DAILY_INSIGHT": ("Daily Insight", "src-daily"),
    "RANKER":        ("Ranker BUY", "src-ranker"),
}


def _render_unified_card(p, kind):
    """Render one UnifiedPick as an HTML card."""
    action_cls = "tag-buy" if kind == "BUY" else "tag-sell"
    src_label, src_cls = SOURCE_LABELS.get(p["source"], (p["source"], "src-ranker"))
    # Technical bits
    bits_html = "".join(f"<span class='pill'>{_esc(b)}</span>"
                        for b in (p.get("technical_bits") or [])[:6])
    # Numbers line
    nums_parts = [f"Giá <b>{p['close']:,.2f}</b>"]
    if p.get("target") is not None:
        nums_parts.append(f"<span class='pos'>Target {p['target']:,.2f}</span>")
    if p.get("stop") is not None:
        nums_parts.append(f"<span class='neg'>Stop {p['stop']:,.2f}</span>")
    if p.get("rr") is not None:
        nums_parts.append(f"<span class='warn'>R:R {p['rr']:.1f}</span>")
    if p.get("atr_pct") is not None:
        nums_parts.append(f"ATR {p['atr_pct']:.1f}%")
    nums_html = " · ".join(nums_parts)
    # News
    news_html = ""
    if p.get("news"):
        news_items = "".join(
            f"<li><a href='{_esc(n.get('url'))}' target='_blank' rel='noopener'>"
            f"{_esc(n.get('title'))}</a> <span class='mut'>[{_esc(n.get('source') or n.get('src') or '')}]</span></li>"
            for n in p["news"][:3] if n.get("title")
        )
        if news_items:
            news_html = f"<ul class='snap-news'>{news_items}</ul>"
    return (
        f"<div class='snap-card'>"
        f"<div class='snap-head'>"
        f"<span class='sym'>{_esc(p['symbol'])}</span>"
        f"<span class='mut'>{_esc(p['sector_name'])}</span>"
        f"<span class='tag {action_cls}'>{kind}</span>"
        f"<span class='src-tag {src_cls}'>{src_label}</span>"
        f"<span class='mut'>score {p.get('score', 0):+d}</span>"
        f"</div>"
        f"<div class='snap-nums mono'>{nums_html}</div>"
        f"<div class='snap-bits'>{bits_html}</div>"
        f"<div class='snap-thesis mut'>{_esc(p.get('thesis') or '')}</div>"
        f"{news_html}"
        f"</div>"
    )


def render_unified_grid():
    """Render BOTH the BUY and SELL unified grids."""
    out = []
    if UNIFIED_BUYS:
        out.append("<h3>Nên MUA ({} picks)</h3>".format(len(UNIFIED_BUYS)))
        out.append("<div class='snap-grid'>")
        out.extend(_render_unified_card(p, "BUY") for p in UNIFIED_BUYS)
        out.append("</div>")
    else:
        out.append("<p class='mut'>Không có BUY nào hôm nay (cả Daily Insight lẫn Ranker đều im).</p>")
    if UNIFIED_SELLS:
        out.append("<h3 style='margin-top:12px'>Nên TRÁNH / CẮT ({} picks)</h3>".format(len(UNIFIED_SELLS)))
        out.append("<div class='snap-grid'>")
        out.extend(_render_unified_card(p, "SELL") for p in UNIFIED_SELLS)
        out.append("</div>")
    return "".join(out)


UNIFIED_PICKS_GRID = render_unified_grid()


# ========== SECV5: EXPERT TRADER MEMO ==========
# Senior-PM narrative at the top of the report. Not AI-generated — this is
# a deterministic, rule-based memo using the regime + unified picks + flow
# context. Keeps output stable even when the Claude agent is down.

def _conviction_bucket(p):
    """Map a UnifiedPick → (label, css-class) based on source + score."""
    if p["source"] == "BOTH":
        return ("High conviction", "high")
    score = p.get("score") or 0
    if score >= 4:
        return ("Medium", "med")
    return ("Low / watch", "low")


def build_expert_memo():
    """Return the expert trader memo HTML block."""
    regime_label = (regime.get("regime_label") or "chop").lower()
    regime_conf = float(regime.get("confidence") or 0)
    top_buys_for_memo = UNIFIED_BUYS[:5]
    top_sells_for_memo = UNIFIED_SELLS[:3]

    # Opening paragraph — market view.
    if regime_label == "risk_on":
        stance = ("Tape đang <b>risk-on</b> (HMM confidence {:.2f}). Ưu tiên long theo dòng tiền, "
                  "chấp nhận size full trên consensus picks.").format(regime_conf)
    elif regime_label == "risk_off":
        stance = ("Tape đang <b>risk-off</b> (HMM confidence {:.2f}). Giảm gross exposure, "
                  "ưu tiên bảo toàn vốn, chỉ nên giữ consensus picks với size nhỏ.").format(regime_conf)
    elif regime_label == "rotation":
        stance = ("Tape đang <b>rotation</b> (HMM confidence {:.2f}). Tránh VNINDEX beta trần, "
                  "chơi spread giữa sector inflow và outflow.").format(regime_conf)
    else:
        stance = ("Tape đang <b>chop</b> (HMM confidence {:.2f}). Không có persistent edge; "
                  "chỉ đánh stealth chất lượng và consensus picks với 0.5× size.").format(regime_conf)

    # Flow leaders / laggards.
    if sector_stats:
        lead = sector_stats[0]
        lag = sector_stats[-1]
        flow_bridge = (
            f"Dẫn dắt dòng tiền: <b>{lead['sector']}</b> ({fmtM(lead['flow_recent'])}/ngày, "
            f"Δ {fmtM(lead['flow_delta'])}); phân phối mạnh nhất: <b>{lag['sector']}</b> "
            f"({fmtM(lag['flow_recent'])}/ngày, Δ {fmtM(lag['flow_delta'])})."
        )
    else:
        flow_bridge = ""

    # Consensus line.
    consensus = [p for p in UNIFIED_BUYS if p["source"] == "BOTH"]
    daily_only = [p for p in UNIFIED_BUYS if p["source"] == "DAILY_INSIGHT"]
    ranker_only = [p for p in UNIFIED_BUYS if p["source"] == "RANKER"]
    consensus_line_parts = []
    if consensus:
        consensus_line_parts.append(
            "Consensus BUY (Daily Insight + Ranker cùng gật): <b>"
            + ", ".join(p["symbol"] for p in consensus[:8]) + "</b>"
        )
    if daily_only:
        consensus_line_parts.append(
            f"Daily-Insight-only ({len(daily_only)}): " + ", ".join(p["symbol"] for p in daily_only[:8])
        )
    if ranker_only:
        consensus_line_parts.append(
            f"Ranker-only ({len(ranker_only)}): " + ", ".join(p["symbol"] for p in ranker_only[:8])
        )
    consensus_line = ". ".join(consensus_line_parts) + ("." if consensus_line_parts else "")

    # Pick-by-pick memo — top 5 BUYs.
    pick_blocks = []
    for p in top_buys_for_memo:
        label, css = _conviction_bucket(p)
        rr = p.get("rr")
        rr_s = f"R:R {rr:.1f}" if rr else "R:R n/a"
        up_s = f"+{p['upside_pct']:.1f}%" if p.get("upside_pct") is not None else "n/a"
        dn_s = f"{-p['downside_pct']:.1f}%" if p.get("downside_pct") is not None else "n/a"
        src_label, _ = SOURCE_LABELS.get(p["source"], (p["source"], ""))
        thesis = p.get("thesis") or ""
        news_hint = ""
        if p.get("news"):
            # Just point to the first cached news link if present.
            first = p["news"][0]
            if first.get("url"):
                news_hint = (f"<br><span class='mut'>↪ <a href='{_esc(first.get('url'))}' "
                             f"target='_blank' rel='noopener' style='color:#7dd3fc'>"
                             f"{_esc((first.get('title') or '')[:90])}</a></span>")
        pick_blocks.append(
            f"<p><b>{_esc(p['symbol'])}</b> "
            f"<span class='mut'>({_esc(p['sector_name'])} · nguồn {src_label})</span> · "
            f"<span class='conviction {css}'>{label}</span> — "
            f"entry quanh <b>{p['close']:,.2f}</b>, target "
            f"<b class='pos'>{(p['target'] or 0):,.2f}</b> ({up_s}), "
            f"stop <b class='neg'>{(p['stop'] or 0):,.2f}</b> ({dn_s}), {rr_s}. "
            f"{_esc(thesis)}{news_hint}</p>"
        )

    # Avoid line.
    avoid_line = ""
    if top_sells_for_memo:
        avoid_line = (
            "<p><b>Tránh / cắt:</b> "
            + ", ".join(
                f"<b>{_esc(p['symbol'])}</b> <span class='mut'>({_esc(p['sector_name'])})</span>"
                for p in top_sells_for_memo
            )
            + ". Không bắt đáy trước khi breadth + foreign flow phục hồi.</p>"
        )

    # Action line — link to dashboard.
    link_line = (
        f"<p class='mut' style='margin-top:8px'>"
        f"<b>Live view:</b> <a href='{_esc(DASHBOARD_URL)}' target='_blank' "
        f"rel='noopener' style='color:#7dd3fc'>{_esc(DASHBOARD_URL)}</a>  "
        f"· PDF + HTML đầy đủ đính kèm email.</p>"
    )

    body = (
        f"<p>{stance} {flow_bridge}</p>"
        f"<p>{consensus_line}</p>"
        + ("".join(pick_blocks) if pick_blocks else "<p class='mut'>Hôm nay không có pick BUY nào đủ điều kiện — giữ tiền, chờ regime mới.</p>")
        + avoid_line
        + link_line
    )

    meta_line = (
        f"Regime <b>{REGIME_LABEL}</b> · "
        f"{len(UNIFIED_BUYS)} BUY ({len(consensus)} consensus) · "
        f"{len(UNIFIED_SELLS)} AVOID · Stealth {NUM_STEALTH}"
    )
    return (
        "<div class='memo-card'>"
        f"<h2>📝 Expert Trader Memo — {REPORT_DATE}</h2>"
        f"<div class='meta'>{meta_line}</div>"
        f"<div class='body'>{body}</div>"
        "</div>"
    )


EXPERT_MEMO = build_expert_memo()


# ========== SECV5: PLAIN-TEXT EMAIL BODY ==========
# The email body is plain text (MIMEText "plain") — must remain readable
# in clients that strip HTML (Outlook mobile, Gmail "plain" view, phone
# notification previews). It mirrors the memo above in compact form.

def build_plain_text_body():
    lines = []
    lines.append(f"📊 SecV5 — Unified Picks Briefing — {REPORT_DATE}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Regime: {REGIME_LABEL} (confidence {regime.get('confidence', 0):.2f})")
    if sector_stats:
        lead = sector_stats[0]; lag = sector_stats[-1]
        lines.append(f"Lead sector: {lead['sector']} (Δflow {fmtM(lead['flow_delta'])})")
        lines.append(f"Lag sector:  {lag['sector']} (Δflow {fmtM(lag['flow_delta'])})")
    lines.append("")

    # Consensus summary
    consensus = [p for p in UNIFIED_BUYS if p["source"] == "BOTH"]
    daily_only = [p for p in UNIFIED_BUYS if p["source"] == "DAILY_INSIGHT"]
    ranker_only = [p for p in UNIFIED_BUYS if p["source"] == "RANKER"]
    lines.append(f"Unified BUY ({len(UNIFIED_BUYS)} total): "
                 f"{len(consensus)} consensus · {len(daily_only)} Daily-only · {len(ranker_only)} Ranker-only")
    lines.append("")

    # BUY block
    lines.append("— NÊN MUA —")
    if not UNIFIED_BUYS:
        lines.append("  (Không có BUY nào hôm nay.)")
    else:
        for i, p in enumerate(UNIFIED_BUYS[:10], 1):
            src_label, _ = SOURCE_LABELS.get(p["source"], (p["source"], ""))
            target = p.get("target"); stop = p.get("stop"); rr = p.get("rr")
            up = p.get("upside_pct"); dn = p.get("downside_pct")
            lines.append(
                f"{i}. {p['symbol']} ({p['sector_name']}) — nguồn {src_label}"
            )
            price_line = f"   Giá {p['close']:,.2f}"
            if target is not None:
                price_line += f" · Target {target:,.2f}"
                if up is not None: price_line += f" (+{up:.1f}%)"
            if stop is not None:
                price_line += f" · Stop {stop:,.2f}"
                if dn is not None: price_line += f" (-{dn:.1f}%)"
            if rr is not None:
                price_line += f" · R:R {rr:.1f}"
            lines.append(price_line)
            thesis = p.get("thesis") or ""
            if thesis:
                # Wrap thesis to ~80 cols-ish; keep simple.
                lines.append(f"   Lý do: {thesis}")
            # Link — first news URL if available.
            if p.get("news"):
                first = p["news"][0]
                if first.get("url"):
                    lines.append(f"   Link: {first.get('url')}")
            lines.append("")

    # AVOID block
    if UNIFIED_SELLS:
        lines.append("— NÊN TRÁNH / CẮT —")
        for i, p in enumerate(UNIFIED_SELLS[:5], 1):
            src_label, _ = SOURCE_LABELS.get(p["source"], (p["source"], ""))
            lines.append(f"{i}. {p['symbol']} ({p['sector_name']}) — nguồn {src_label}")
            thesis = p.get("thesis") or ""
            if thesis:
                lines.append(f"   Lý do: {thesis}")
        lines.append("")

    # Links
    lines.append("— LINKS —")
    lines.append(f"Dashboard (Daily Insight): {DASHBOARD_URL}")
    lines.append("File đính kèm: PDF + HTML đầy đủ (charts, stealth watch, risk notes).")
    lines.append("")
    lines.append("— Trading System · SecV5 (replaces SecV4 2026-04-23) · Not investment advice.")
    return "\n".join(lines)


PLAIN_TEXT_BODY = build_plain_text_body()


replacements = {
    "{{REPORT_DATE}}": REPORT_DATE,
    "{{RECENT_DAYS}}": str(RECENT_DAYS),
    "{{PRIOR_DAYS}}": str(PRIOR_DAYS),
    "{{REGIME_CLASS}}": REGIME_CLASS,
    "{{REGIME_LABEL}}": REGIME_LABEL,
    "{{REGIME_NARRATIVE}}": REGIME_NARRATIVE,
    "{{MACRO_VNINDEX}}": MACRO_VNINDEX,
    "{{MACRO_USDVND}}": MACRO_USDVND,
    "{{MACRO_BRENT}}": MACRO_BRENT,
    "{{MACRO_US10Y}}": MACRO_US10Y,
    "{{MACRO_GOLD}}": MACRO_GOLD,
    "{{NUM_BUYS}}": str(len(buys)),
    "{{NUM_SELLS}}": str(len(sells)),
    "{{NUM_WATCHES}}": str(len(watches)),
    "{{NUM_STEALTH}}": str(NUM_STEALTH),
    "{{FLOW_NARRATIVE}}": FLOW_NARRATIVE,
    "{{CHART_SECTOR_FLOW_DELTA}}": chart_flow_delta,
    "{{CHART_SECTOR_PERFORMANCE}}": chart_sector_perf,
    "{{CHART_CORRELATION_HEATMAP}}": chart_correlation,
    "{{SECTOR_PREDICTION_ROWS}}": SECTOR_PREDICTION_ROWS,
    "{{STEALTH_ROWS}}": STEALTH_ROWS,
    "{{INFLOW_THESIS}}": inflow_thesis,
    "{{OUTFLOW_THESIS}}": outflow_thesis,
    "{{BUY_ROWS}}": buy_rows_html,
    "{{NEWS_BLOCKS}}": NEWS_BLOCKS,
    "{{SELL_ROWS}}": sell_rows_html,
    "{{WATCH_ROWS}}": watch_rows_html,
    "{{VOLATILE_STOCK_CHARTS}}": volatile_html,
    "{{SECTOR_TABLE_ROWS}}": sec_table_rows,
    "{{RISK_NOTES}}": RISK_NOTES,
    "{{GAME_PLAN}}": GAME_PLAN,
    # secv4 legacy additions
    "{{AGENT_SECTION}}": AGENT_SECTION,
    "{{SNAP_BUYS_GRID}}": SNAP_BUYS_GRID,
    "{{SNAP_SELLS_GRID}}": SNAP_SELLS_GRID,
    "{{AGENT_GIST}}": _esc(_agent_report.gist) if (_agent_report and _agent_report.is_valid) else "",
    # secv5 additions (unified picks + expert trader memo)
    "{{EXPERT_MEMO}}": EXPERT_MEMO,
    "{{UNIFIED_PICKS_GRID}}": UNIFIED_PICKS_GRID,
}
html = template_text
for k, v in replacements.items(): html = html.replace(k, v)
OUT_HTML.write_text(html, encoding="utf-8")
print(f"[secv5] HTML: {OUT_HTML} ({len(html):,} bytes)")

# ========== PDF: Chrome headless then weasyprint fallback ==========
def _render_pdf():
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if Path(chrome).exists():
        url = "file:///" + str(OUT_HTML).replace("\\", "/")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                        f"--print-to-pdf={OUT_PDF}", "--print-to-pdf-no-header",
                        "--virtual-time-budget=8000", url], check=True, timeout=120)
        return "chrome"
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string=html, base_url=str(ROOT)).write_pdf(str(OUT_PDF))
        return "weasyprint"
    except Exception as e:
        print(f"[secv5] PDF render failed: {e}")
        return None

renderer = _render_pdf()
if renderer and OUT_PDF.exists():
    print(f"[secv5] PDF via {renderer}: {OUT_PDF} ({OUT_PDF.stat().st_size:,} bytes)")
else:
    print("[secv5] PDF not generated; email will attach HTML instead.")

# ========== EMAIL ==========
if SEND_EMAIL:
    FROM = os.environ.get("REPORT_EMAIL_FROM")
    PW   = os.environ.get("REPORT_EMAIL_PASSWORD")
    # REPORT_EMAIL_TO supports a comma-separated list (multiple recipients in TO header).
    # SecV5 default recipients — 3 people per Tom's directive 2026-04-23.
    # REPORT_EMAIL_TO env var still overrides for local testing.
    TO_RAW = os.environ.get(
        "REPORT_EMAIL_TO",
        "tka2001@gmail.com,anhchitruong18@gmail.com,hill.nguyen.1373@gmail.com",
    )
    TO_LIST = [e.strip() for e in TO_RAW.split(",") if e.strip()]
    TO_HEADER = ", ".join(TO_LIST)
    if not (FROM and PW):
        print("[secv5] SMTP creds missing — skipping email (set REPORT_EMAIL_FROM/PASSWORD in .env).")
    else:
        msg = MIMEMultipart("mixed")
        msg["From"] = FROM; msg["To"] = TO_HEADER
        _stale_prefix = "[STALE] " if not _universe_snap.is_valid else ""
        msg["Subject"] = f"{_stale_prefix}[SecV5] Unified Picks Briefing — {REPORT_DATE}"
        # Plain-text body = unified picks + reasons + links (built above).
        msg.attach(MIMEText(PLAIN_TEXT_BODY, "plain", "utf-8"))
        # Attach HTML for inline view too
        msg.attach(MIMEText(html, "html", "utf-8"))
        # Attach PDF if present
        if OUT_PDF.exists():
            with open(OUT_PDF, "rb") as f:
                part = MIMEBase("application", "pdf"); part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{OUT_PDF.name}"')
            msg.attach(part)
        # Always attach HTML file
        with open(OUT_HTML, "rb") as f:
            part = MIMEBase("text", "html"); part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{OUT_HTML.name}"')
        msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(FROM, PW); s.sendmail(FROM, TO_LIST, msg.as_string())
        print(f"[secv5] [SENT] {TO_HEADER}")
else:
    print("[secv5] --no-email flag set — skipping send.")

con.close()
print("[secv5] done")
