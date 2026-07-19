# ============================================
# scripts/replay_stealth.py — Replay backtest on ground-truth VN rotations
# ============================================
# Runs StealthDetector day-by-day over the 3 ground-truth cases named in
# CLAUDE.md §16.10:
#   - Banks rally Q4 2023
#   - Steel run Q2 2024
#   - Broker breakout Q1 2025
# For each case, measures §16.11 metrics: lead days, root-capture ratio,
# false-positive rate.
#
# Usage:  python -m scripts.replay_stealth

from __future__ import annotations

import pandas as pd

from database.connection import get_session
from database.models import SectorFlowDaily
from analysis.stealth import compute_leading_features, STEALTH_MIN_SESSIONS


GROUND_TRUTH = [
    # (label, sector_code, window_start, window_end, breakout_date)
    ("Banks Q4'23",    "BANK",   "2023-08-01", "2023-12-31", "2023-11-15"),
    ("Steel Q2'24",    "STEEL",  "2024-02-01", "2024-06-30", "2024-04-15"),
    ("Brokers Q1'25",  "BROKER", "2024-11-01", "2025-03-31", "2025-02-01"),
]


def _load_panel(sector_code: str, start: str, end: str) -> pd.DataFrame:
    session = get_session()
    try:
        rows = (
            session.query(SectorFlowDaily)
            .filter(SectorFlowDaily.sector_code == sector_code)
            .filter(SectorFlowDaily.date >= start)
            .filter(SectorFlowDaily.date <= end)
            .order_by(SectorFlowDaily.date)
            .all()
        )
    finally:
        session.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "sector_code": r.sector_code,
        "date": r.date,
        "net_dollar_flow": r.net_dollar_flow or 0.0,
        "foreign_net": r.foreign_net or 0.0,
        "close_idx": r.close_idx if hasattr(r, "close_idx") else None,
        "breadth_sma20": r.breadth_sma20 or 0.0,
        "atr_pct": r.atr_pct or 0.0,
        "return_1d": r.return_1d or 0.0,
    } for r in rows])


def _replay_one(label: str, sector: str, start: str, end: str, breakout: str) -> dict:
    panel = _load_panel(sector, start, end)
    if panel.empty:
        return {"label": label, "status": "NO DATA"}

    feat = compute_leading_features(panel.copy())
    stealth_days = feat[feat.get("stealth_score", pd.Series()).fillna(0) > 0]
    first_trigger = None
    for _, row in feat.iterrows():
        if row.get("flow_z20", 0) and row["flow_z20"] > 1.0:
            first_trigger = row["date"]
            break

    if first_trigger is None:
        return {
            "label": label, "sector": sector, "status": "NO TRIGGER",
            "rows": len(panel),
        }

    trig_dt = pd.Timestamp(first_trigger)
    bo_dt = pd.Timestamp(breakout)
    lead_days = (bo_dt - trig_dt).days

    # Root capture: price at trigger vs peak in the window
    if "close_idx" in panel.columns and panel["close_idx"].notna().any():
        closes = panel.set_index("date")["close_idx"].dropna()
        peak = closes.max()
        entry = closes.loc[closes.index >= first_trigger].iloc[0] if (closes.index >= first_trigger).any() else None
        rc = (entry / peak) if (entry and peak) else None
    else:
        rc = None

    return {
        "label": label,
        "sector": sector,
        "rows": len(panel),
        "first_trigger": first_trigger,
        "breakout": breakout,
        "lead_days": lead_days,
        "root_capture": rc,
        "stealth_session_count": int(len(stealth_days)),
        "meets_lead_target": lead_days >= 10,
        "meets_root_capture_target": (rc is not None and rc <= 0.85),
    }


def main() -> None:
    print(f"Replay Stealth (STEALTH_MIN_SESSIONS={STEALTH_MIN_SESSIONS})")
    print("=" * 72)
    results = []
    for label, sector, start, end, bo in GROUND_TRUTH:
        r = _replay_one(label, sector, start, end, bo)
        results.append(r)
        print(f"\n[{label}] {sector}")
        for k, v in r.items():
            print(f"  {k}: {v}")

    ok_lead = sum(1 for r in results if r.get("meets_lead_target"))
    ok_rc   = sum(1 for r in results if r.get("meets_root_capture_target"))
    print("\n" + "=" * 72)
    print(f"Lead ≥10d:       {ok_lead}/{len(results)}")
    print(f"Root capture ≤.85: {ok_rc}/{len(results)}")
    print("§16.11 targets: ≥60% lead, median RC ≤ 0.85")


if __name__ == "__main__":
    main()
