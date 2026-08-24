"""Phase 15 — /api/insight/* (Feature E Daily Insight).

First cut is deterministic (template narrative). LLM integration is
wired later once stable daily deltas land; spec allows a template-first
implementation as long as numbers come from the snapshot.
"""
from __future__ import annotations

import logging
from datetime import date as _date, datetime as _datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter

from config import SECTORS
from database.connection import SessionLocal
from database.models import SectorFlowDaily, SectorRegime, SectorSignal
from services.picks_scoring import (
    PickProfile as _PickProfile,
    compute_stop_target_rr as _compute_stop_target_rr,
    is_valid_long_pick as _is_valid_long_pick,
)
from services.picks_universe_service import (
    FreshnessReport,
    UniverseSnapshot,
    get_picks_universe,
)
from services.trader_agent import get_trader_agent
from services import insight_refresh as _insight_refresh

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insight", tags=["daily-insight"])

PORTFOLIO_RISK_PCT = 0.01   # risk 1% of equity per trade when sizing

# T+ swing profile (VN cash: T+2.5 settlement → typical holding 3-5 sessions).
# ATR multipliers come from services.picks_scoring.PickProfile.TPLUS; constants
# here govern entry limit offset + horizon label only.
TPLUS_ENTRY_DISCOUNT  = 0.005  # limit at -0.5% (T+ needs quick fill, not deep dip)
TPLUS_HOLD_DAYS       = "3-5"


def _build_picks(top_sectors: list[tuple[str, float, str]],
                 sector_ctx: dict[str, dict[str, float | None]],
                 snapshot: "UniverseSnapshot") -> list[dict[str, Any]]:
    """Build T+ (3-5 session) picks from the PicksUniverseService snapshot.

    Picks per sector come from `snapshot.by_sector[code][:3]`, sorted by the
    composite score the service already computed. The sizing is recomputed
    with PickProfile.TPLUS (2.0× ATR target / 1.0× ATR stop), then gated by
    `is_valid_long_pick` for BUY/ACCUMULATE actions — rejected picks are
    dropped with a log line.
    """
    picks: list[dict[str, Any]] = []
    for code, score, action in top_sectors:
        ctx = sector_ctx.get(code, {})
        flow_z = ctx.get("flow_z20")
        foreign_hit = ctx.get("foreign_hit_20d")
        stealth_age = ctx.get("accumulation_age") or 0
        rs20 = ctx.get("rs_vnindex_20d")

        bucket = snapshot.by_sector.get(code, [])
        # Top-3 ranked by composite score
        for ticker in bucket[:3]:
            px = ticker.close
            # Reuse the snapshot's atr_pct (already in percent units, e.g. 2.5)
            atr_pct = (ticker.atr_pct or 0)
            # Recompute stop/target with the T+ profile (the snapshot defaults
            # to SWING; insight uses shorter horizon)
            stop_t, target_t, rr_t, _err = _compute_stop_target_rr(
                {"close": px, "atr_pct": atr_pct,
                 "bb_upper": ticker.bb_upper, "bb_lower": ticker.bb_lower},
                _PickProfile.TPLUS,
            )
            entry = round(px * (1 - TPLUS_ENTRY_DISCOUNT), 2)

            upside_pct = round((target_t - entry) / entry * 100, 2) if (target_t and entry) else 0
            downside_pct = round((entry - stop_t) / entry * 100, 2) if (stop_t and entry) else 0
            position_pct = None
            if downside_pct and downside_pct > 0:
                position_pct = round(min(PORTFOLIO_RISK_PCT * 100 / (downside_pct / 100), 25.0), 2)

            common = {
                "symbol": ticker.symbol,
                "sector": code,
                "sector_name": SECTORS.get(code, code),
                "action": action,
                "horizon": f"T+{TPLUS_HOLD_DAYS}",
                "score": round(float(score), 3),
                "ticker_score": int(ticker.score),
                "upside_pct": upside_pct,
                "downside_pct": downside_pct,
                "r_r": rr_t,
                "position_pct": position_pct,
                "flow_z20": round(flow_z, 2) if flow_z is not None else None,
                "foreign_hit_20d": round(foreign_hit, 2) if foreign_hit is not None else None,
                "stealth_age": int(stealth_age),
                "rs_vnindex_20d": round(rs20, 3) if rs20 is not None else None,
                "foreign_room_pct": (
                    round(ticker.foreign_room_pct, 2)
                    if ticker.foreign_room_pct is not None else None
                ),
                "dv_20d": round(ticker.dv_20d, 0),
            }

            # Validity gate for long actions — protects against degenerate
            # target/stop math (e.g. low-ATR penny with target < entry).
            if action in ("BUY", "ACCUMULATE"):
                ok, reason = _is_valid_long_pick(entry, target_t, stop_t)
                if not ok:
                    log.info("insight: skipping %s %s — %s", ticker.symbol, action, reason)
                    continue

            bits = [
                f"T+{TPLUS_HOLD_DAYS}",
                f"flow_z {common['flow_z20']:+.2f}" if common['flow_z20'] is not None else None,
                f"FH {int(common['foreign_hit_20d']*100)}%" if common['foreign_hit_20d'] is not None else None,
                f"RS20 {rs20:+.1%}" if rs20 is not None else None,
                f"score {ticker.score}",
            ]
            thesis = " · ".join([b for b in bits if b])
            picks.append({
                **common,
                "price": round(px, 2),
                "entry": entry,
                "target": target_t,
                "stop": stop_t,
                "thesis": thesis,
            })
    return picks


def _latest_two_days() -> pd.DataFrame:
    sess = SessionLocal()
    try:
        rows = (
            sess.query(SectorFlowDaily)
            .order_by(SectorFlowDaily.date.desc())
            .limit(15 * 3)
            .all()
        )
    finally:
        sess.close()
    return pd.DataFrame([{
        "sector": r.sector_code,
        "date": r.date,
        "flow": r.net_dollar_flow or 0.0,
        "z": r.flow_z20 or 0.0,
        "foreign_hit": r.foreign_hit_20d or 0.0,
        "stealth_score": r.stealth_score or 0.0,
    } for r in rows])


@router.get("/daily")
def insight_daily():
    df = _latest_two_days()
    if df.empty:
        return {"date": None, "narrative": "Không có dữ liệu.", "deltas": [], "actions": [], "raw": {}}

    dates = sorted(df["date"].unique(), reverse=True)
    today = df[df["date"] == dates[0]].set_index("sector")
    prev = df[df["date"] == dates[1]].set_index("sector") if len(dates) > 1 else today

    # Δ flow_z per sector
    joined = today[["z", "flow", "stealth_score"]].join(
        prev[["z"]].rename(columns={"z": "z_prev"}), how="left"
    )
    joined["dz"] = joined["z"] - joined["z_prev"].fillna(joined["z"])
    top_pos = joined["dz"].idxmax()
    top_neg = joined["dz"].idxmin()
    top_stealth = joined["stealth_score"].idxmax()

    def _fmt(sec, key):
        r = joined.loc[sec]
        return {
            "sector": sec,
            "name": SECTORS.get(sec, sec),
            "from": float(r["z_prev"]) if pd.notna(r["z_prev"]) else None,
            "to": float(r["z"]),
            "kind": key,
        }

    deltas = [
        {
            **_fmt(top_pos, "flow_z_up"),
            "what_changed": f"flow_z20 tăng {joined.loc[top_pos, 'dz']:+.2f}",
            "why_it_matters": "Dòng tiền vào nhanh nhất trong phiên",
            "what_to_do": "Theo dõi khối ngoại trước khi vào lệnh",
        },
        {
            **_fmt(top_neg, "flow_z_down"),
            "what_changed": f"flow_z20 giảm {joined.loc[top_neg, 'dz']:+.2f}",
            "why_it_matters": "Tiền đang rút mạnh nhất",
            "what_to_do": "Xem xét cắt long nếu giữ",
        },
        {
            **_fmt(top_stealth, "stealth_top"),
            "what_changed": f"stealth_score {joined.loc[top_stealth, 'stealth_score']:.2f}",
            "why_it_matters": "Điểm tích luỹ âm thầm cao nhất",
            "what_to_do": "Mở Stealth Watch xem gate 5 điều kiện",
        },
    ]

    narrative = (
        f"Ngày {dates[0]}: {SECTORS.get(top_pos, top_pos)} có flow_z20 bật tăng "
        f"{joined.loc[top_pos, 'dz']:+.2f} lên {joined.loc[top_pos, 'z']:.2f}, mạnh nhất phiên. "
        f"Ngược lại, {SECTORS.get(top_neg, top_neg)} flow_z20 rơi {joined.loc[top_neg, 'dz']:+.2f} "
        f"xuống {joined.loc[top_neg, 'z']:.2f} — cảnh báo rotation. "
        f"Sector có stealth_score cao nhất hôm nay: {SECTORS.get(top_stealth, top_stealth)} "
        f"({joined.loc[top_stealth, 'stealth_score']:.2f})."
    )

    actions = [
        f"Theo dõi {top_pos}: kiểm tra foreign net buổi chiều",
        f"Rà soát long {top_neg}: nếu flow_z20 vẫn âm ngày mai → giảm vị thế",
        f"Mở Stealth Watch cho {top_stealth} để xem gate chi tiết",
    ]

    # ----- Stock picks (entry / target / stop) -----
    sess = SessionLocal()
    try:
        latest_sig = (
            sess.query(SectorSignal.date)
            .order_by(SectorSignal.date.desc())
            .first()
        )
        sig_date = latest_sig[0] if latest_sig else None
        sig_rows = []
        if sig_date:
            sig_rows = (
                sess.query(SectorSignal)
                .filter(SectorSignal.date == sig_date)
                .order_by(SectorSignal.rank.asc())
                .all()
            )
    finally:
        sess.close()
    top_sectors: list[tuple[str, float, str]] = []
    for s in sig_rows:
        if s.action in ("BUY", "ACCUMULATE") and len(top_sectors) < 3:
            top_sectors.append((s.sector_code, float(s.score), s.action))
    # Fallback: if no BUY today, still surface top-2 ranked sectors as "watch"
    if not top_sectors and sig_rows:
        for s in sig_rows[:2]:
            top_sectors.append((s.sector_code, float(s.score), s.action or "HOLD"))

    # Per-sector context from today's flow_daily row (ATR, flow z, stealth age, RS…)
    sector_ctx: dict[str, dict[str, float | None]] = {}
    sess = SessionLocal()
    try:
        ctx_rows = (
            sess.query(SectorFlowDaily)
            .filter(SectorFlowDaily.date == dates[0])
            .all()
        )
    finally:
        sess.close()
    for r in ctx_rows:
        sector_ctx[r.sector_code] = {
            "atr_pct": float(r.atr_pct) if r.atr_pct is not None else None,
            "flow_z20": float(r.flow_z20) if r.flow_z20 is not None else None,
            "foreign_hit_20d": float(r.foreign_hit_20d) if r.foreign_hit_20d is not None else None,
            "accumulation_age": int(r.accumulation_age) if r.accumulation_age is not None else 0,
            "rs_vnindex_20d": float(r.rs_vnindex_20d) if r.rs_vnindex_20d is not None else None,
            "return_1d": float(r.return_1d) if r.return_1d is not None else None,
        }

    # Universe snapshot — CACHE-ONLY read. get_snapshot() on a cold cache used
    # to run the full KBS fan-out (18 req/min throttle) synchronously inside
    # this request, hanging /daily for 2-10 min (observed 2026-07-19). Cold
    # cache now serves an empty invalid snapshot: the UI's degraded-data
    # banner lights up and POST /refresh does the slow build asynchronously.
    snapshot = get_picks_universe().peek()
    if snapshot is None:
        _fr = FreshnessReport(
            as_of=dates[0] if isinstance(dates[0], _date) else _date.today(),
            built_at=_datetime.now(),
            errors=["chưa có snapshot picks trong cache — bấm Refresh để build"],
        )
        snapshot = UniverseSnapshot(
            as_of=_fr.as_of, built_at=_fr.built_at,
            tickers={}, by_sector={c: [] for c in SECTORS},
            freshness=_fr, is_valid=False,
        )
    # Prefer the snapshot's pre-computed top-5 BUY / top-5 SELL list (with
    # news + technical thesis). Fall back to the legacy per-sector loop when
    # the snapshot has no top picks (e.g. is_valid=False).
    if snapshot.top_buys or snapshot.top_sells:
        picks = [p.to_dict() for p in snapshot.top_buys + snapshot.top_sells]
    else:
        picks = _build_picks(top_sectors, sector_ctx, snapshot)

    # ----- Market context: regime + stealth count + top / bottom sector -----
    sess = SessionLocal()
    try:
        regime_row = (
            sess.query(SectorRegime)
            .order_by(SectorRegime.date.desc())
            .first()
        )
    finally:
        sess.close()
    regime = (
        {
            "date": regime_row.date,
            "label": regime_row.regime_label,
            "confidence": round(float(regime_row.confidence or 0), 3),
        }
        if regime_row else None
    )
    stealth_count = sum(1 for c in sector_ctx.values() if (c.get("accumulation_age") or 0) > 0)
    buy_count = sum(1 for s in sig_rows if s.action in ("BUY", "ACCUMULATE"))
    sell_count = sum(1 for s in sig_rows if s.action == "SELL")

    market_context = {
        "regime": regime,
        "stealth_count": stealth_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "sectors_covered": len(sector_ctx),
    }

    generated_at = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").isoformat()

    # Trader agent — reads from the snapshot cache. Returns the cached report
    # when as_of unchanged; otherwise agent is re-invoked on /refresh only
    # (not on every /daily hit) to keep this endpoint fast.
    agent_report_dict: dict[str, Any] | None = None
    try:
        agent = get_trader_agent()
        if agent._cache is not None:  # only attach if already produced
            agent_report_dict = agent._cache.to_dict()
    except Exception as e:
        log.warning("[insight] trader_agent cache read failed: %s", e)

    # Freshness of the picks universe snapshot — UI renders a stale banner
    # when is_valid=False. On top of the snapshot's own health, flag DB
    # staleness: the 2026-06/07 incident had every ingest job failing for
    # 25 days while the UI showed empty-but-normal lists. A visible
    # "DB đứng N ngày" line makes a dead pipeline impossible to miss.
    freshness_out = {**snapshot.freshness.to_dict(), "is_valid": snapshot.is_valid}
    freshness_out["errors"] = list(freshness_out.get("errors") or [])
    # SectorFlowDaily.date is String(20) "YYYY-MM-DD", not a date object.
    try:
        _latest = _datetime.strptime(str(dates[0])[:10], "%Y-%m-%d").date()
    except ValueError:
        _latest = None
    if _latest is not None:
        db_gap = (_date.today() - _latest).days
        freshness_out["db_gap_days"] = db_gap
        if db_gap > 5:  # weekends + VN holiday clusters stay under 5
            freshness_out["is_valid"] = False
            freshness_out["errors"].append(
                f"DB đứng {db_gap} ngày (mới nhất {dates[0]}) — "
                "kiểm tra scheduled jobs SectorFlow_*"
            )

    return {
        "date": dates[0],
        "generated_at": generated_at,
        "narrative": narrative,
        "deltas": deltas,
        "actions": actions,
        "picks": picks,
        "market_context": market_context,
        "freshness": freshness_out,
        # Trader agent output (may be null if never run or /refresh failed).
        "agent_report": agent_report_dict,
        "raw": {"latest_date": dates[0], "sector_count": int(joined.shape[0])},
    }


@router.post("/refresh")
def insight_refresh():
    """Kick off a background refresh and return immediately.

    The full pipeline — publish signals → rebuild HOSE picks-universe via KBS
    → run the Claude trader agent → reassemble /daily — routinely exceeds the
    frontend's 5-minute axios timeout. Running it synchronously inside the
    request handler meant the UI saw a hard `timeout of 300000ms exceeded`
    with no way to recover other than blindly retrying (and triggering the
    same problem).

    This endpoint is now async: it starts a background job via
    `services.insight_refresh.InsightRefreshRunner` and returns the `run_id`.
    The UI polls GET /api/insight/refresh/status for stage + progress %, and
    reads the final /daily payload from the status response once the stage
    flips to `done`.

    Idempotent: a second click while a run is in flight returns the *same*
    run_id (no duplicate KBS calls, no wasted Claude tokens).
    """
    from services.insight_refresh import get_refresh_runner
    runner = get_refresh_runner()
    existing = runner.status()
    already_running = (
        existing is not None
        and existing.get("is_running") is True
    )
    run = runner.start()
    return {
        "run_id": run.run_id,
        "stage": run.stage,
        "stage_label": run.progress_label,
        "started_at": run.started_at,
        "already_running": already_running,
    }


@router.get("/refresh/status")
def insight_refresh_status(run_id: str | None = None):
    """Poll the in-flight refresh. Returns stage + progress + (once done) the
    full /daily payload.

    The frontend polls this roughly every 2 seconds while the run is active.
    When `is_done=True`, the `payload` field carries the same shape the old
    sync /refresh used to return, so the UI can drop it straight into state.
    """
    from services.insight_refresh import get_refresh_runner
    status = get_refresh_runner().status(run_id=run_id)
    if status is None:
        return {"run_id": None, "stage": "idle", "is_running": False,
                "is_done": False, "is_error": False, "payload": None}
    return status


@router.get("/delta")
def insight_delta():
    data = insight_daily()
    return {"rows": data["deltas"]}


# The refresh runner's last stage returns this same payload. Push the builder
# down to it here instead of letting it import back up — `services -> api`
# was a real cycle, quiet only because both ends imported lazily. See
# `services/insight_refresh.py`'s module docstring.
_insight_refresh.set_payload_builder(insight_daily)
