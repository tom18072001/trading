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
from services.picks_universe_service import (
    FreshnessReport,
    UniverseSnapshot,
    get_picks_universe,
)
from services.trader_agent import get_trader_agent
from services import insight_refresh as _insight_refresh

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insight", tags=["daily-insight"])

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
    # The snapshot's top-5 BUY / top-5 SELL is the ONLY source of picks. An
    # empty snapshot means an empty list and the degraded-data banner.
    #
    # 2026-09-25: the fallback that used to live here built "T+3-5" cards from
    # the ranker's BUY sectors with the TPLUS geometry (2.0x/1.0x ATR, entry
    # -0.5%). Both halves are gone: the T+ mode was removed (Tom: "chỉ sử dụng
    # 4 tuần và 8 tuần"), and a sector gate on buys has no measured edge
    # (review 2026-09-24 §4.2). A list nobody can buy from on a degraded day is
    # the honest answer; a list rebuilt from a different rule is not.
    picks = [p.to_dict() for p in snapshot.top_buys + snapshot.top_sells]

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
    from analysis import verification
    from analysis.regime import confidence_phrase
    from services import buy_layer

    regime = (
        {
            "date": regime_row.date,
            "label": regime_row.regime_label,
            "confidence": round(float(regime_row.confidence or 0), 3),
            # The one renderer of this number (§25.2) -- the page used to print
            # "Độ tin cậy 85%", which is neither what it measures nor validated.
            "phrase": confidence_phrase(regime_row.confidence),
        }
        if regime_row else None
    )
    stealth_count = sum(1 for c in sector_ctx.values() if (c.get("accumulation_age") or 0) > 0)
    buy_count = sum(1 for s in sig_rows if s.action in ("BUY", "ACCUMULATE"))
    sell_count = sum(1 for s in sig_rows if s.action == "SELL")

    market_context = {
        "regime": regime,
        # SECTOR counts from the ranker / §16.1 gate -- not the ticker list.
        "stealth_count": stealth_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "sectors_covered": len(sector_ctx),
        # What none of the above has: an out-of-sample test (review 2026-09-24
        # §8 P0-6). The page prints these beside the numbers.
        "unverified": verification.as_dict(),
        # The buy rule's own context (2026-09-28, services/buy_layer.py): the
        # same three sentences the email and the 17:30 bulletin print.
        "buy_layer": {
            "market": getattr(snapshot, "market", None) or {},
            "rule_sentence": buy_layer.rule_sentence(),
            "market_sentence": buy_layer.market_sentence(getattr(snapshot, "market", None)),
            "book_sentence": buy_layer.book_sentence(),
            # 2026-09-29: how to read the priority, and the per-position sell rule.
            "priority_sentence": buy_layer.priority_sentence(),
            "sell_rule_sentence": buy_layer.sell_rule_sentence(),
        },
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
