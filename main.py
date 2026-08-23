# ============================================
# main.py — Sector Money-Flow CLI
# ============================================
# One CLI flag per scheduled job (§8 of CLAUDE.md). Compound commands
# (--ingest, --all) are kept for ad-hoc use.
#
# Scheduled-job flags (each one maps 1:1 to a job in §8):
#   --macro            hourly macro ingest         (job: macro_ingest)
#   --intraday         intraday 15m sector flow    (job: sector_intraday_flow)
#   --eod-rollup       daily sector flow rollup    (job: sector_eod_rollup)
#   --regime           classify HMM regime         (job: regime_classify)
#   --train            retrain rotation ranker     (job: rotation_train)
#   --rotation-predict next-day sector ranking     (job: rotation_predict)
#   --publish          write signals + stdout      (job: sector_signal_publish,
#                                                   Gmail send happens in
#                                                   generate_report.py after)
#   --risk-sentinel    stop-loss breach scan       (job: sector_risk_sentinel)
#
# Compound flags (ad-hoc only, NOT scheduled):
#   --ingest = --macro + --intraday + --eod-rollup
#   --all    = --init + --ingest + --regime + --train + --publish
#
# Usage:
#   python main.py --init
#   python main.py --macro
#   python main.py --intraday
#   python main.py --eod-rollup
#   python main.py --regime
#   python main.py --train
#   python main.py --rotation-predict
#   python main.py --publish
#   python main.py --risk-sentinel
#   python main.py --backfill --years 5

import argparse

from database.connection import get_session, init_db
from services.macro_service import MacroService
from services.risk_service import SectorRiskService
from services.rotation_model_service import RotationModelService
from services.sector_ingest_service import SectorIngestService
from services.sector_signal_service import SectorSignalService


# ---------- granular commands (one per scheduled job) ----------

def cmd_init() -> None:
    init_db()
    print("[main] DB initialized + sectors seeded.")


# Jobs that spend the shared vnstock/KBS per-minute budget run under one
# cross-process lock (see utils/vnstock_gate.py). Before 2026-08-22 an
# intraday run that overran its 15-minute slot would overlap the next
# firing - and the hourly macro job on top - so three processes each
# assumed they owned the full quota and all three got 429'd.

def cmd_macro() -> None:
    from utils.vnstock_gate import guarded
    with guarded("macro") as ok:
        if not ok:
            return
        with get_session() as s:
            row = MacroService(s).ingest_now()
            print(f"[main] macro row written: {row is not None}")


def cmd_intraday() -> None:
    from utils.vnstock_gate import guarded
    with guarded("intraday") as ok:
        if not ok:
            return
        with get_session() as s:
            n = SectorIngestService(s).ingest_intraday_now()
            print(f"[main] sector_flow_ts rows: {n}")


def cmd_eod_rollup() -> None:
    with get_session() as s:
        n = SectorIngestService(s).rollup_to_daily()
        print(f"[main] sector_flow_daily rows: {n}")


def cmd_regime() -> None:
    with get_session() as s:
        rec = RotationModelService(s).classify_regime()
        print(f"[main] regime: {rec.regime_label} conf={rec.confidence}")


def cmd_train() -> None:
    with get_session() as s:
        run = RotationModelService(s).train_ranker()
        print(f"[main] ranker trained: id={run.id} active={run.is_active}")


def cmd_rotation_predict() -> None:
    with get_session() as s:
        df = RotationModelService(s).predict_today()
        print(f"[main] rotation_predict: {len(df)} sector rows")
        if not df.empty:
            cols = [c for c in ("sector_code", "rank", "score") if c in df.columns]
            if cols:
                print(df[cols])


def cmd_publish() -> None:
    with get_session() as s:
        df = SectorSignalService(s).publish()
        print(f"[main] published {len(df)} signals")
        if not df.empty:
            print(df[["sector_code", "rank", "action", "score"]])


def cmd_risk_sentinel() -> None:
    with get_session() as s:
        breaches = SectorRiskService(s).stoploss_breaches()
        print(f"[main] risk_sentinel: {len(breaches)} breach(es)")
        for b in breaches:
            print(f"  - {b}")


# ---------- compound commands (ad-hoc only) ----------

def cmd_ingest() -> None:
    cmd_macro()
    cmd_intraday()
    cmd_eod_rollup()


def cmd_backfill(years: int = 2) -> None:
    from config import SECTORS
    from utils.vnstock_gate import guarded
    with guarded("backfill") as ok:
        if not ok:
            return
        with get_session() as s:
            svc = SectorIngestService(s)
            for code in SECTORS.keys():
                try:
                    n = svc.backfill_sector(code, years=years)
                    print(f"[backfill] {code}: {n} rows")
                except BaseException as e:
                    print(f"[backfill] {code} error: {e}")


# ---------- dispatch ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="VN Sector Money-Flow CLI")
    # granular (one per scheduled job)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--macro", action="store_true",
                        help="Hourly macro ingest (job: macro_ingest)")
    parser.add_argument("--intraday", action="store_true",
                        help="15m intraday sector flow (job: sector_intraday_flow)")
    parser.add_argument("--eod-rollup", dest="eod_rollup", action="store_true",
                        help="Daily sector flow rollup (job: sector_eod_rollup)")
    parser.add_argument("--regime", action="store_true",
                        help="HMM regime classify (job: regime_classify)")
    parser.add_argument("--train", action="store_true",
                        help="Retrain rotation ranker (job: rotation_train)")
    parser.add_argument("--rotation-predict", dest="rotation_predict", action="store_true",
                        help="Next-day sector ranking (job: rotation_predict)")
    parser.add_argument("--publish", action="store_true",
                        help="Write signals (job: sector_signal_publish)")
    parser.add_argument("--risk-sentinel", dest="risk_sentinel", action="store_true",
                        help="Stop-loss breach scan (job: sector_risk_sentinel)")
    # compound (ad-hoc)
    parser.add_argument("--ingest", action="store_true",
                        help="Shorthand: --macro + --intraday + --eod-rollup")
    parser.add_argument("--all", action="store_true",
                        help="Shorthand: --init + --ingest + --regime + --train + --publish")
    # one-off
    parser.add_argument("--backfill", action="store_true", help="Backfill history per sector")
    parser.add_argument("--years", type=int, default=2)
    args = parser.parse_args()

    if args.all:
        cmd_init(); cmd_ingest(); cmd_regime(); cmd_train(); cmd_publish()
        return

    ran = False
    if args.init:              cmd_init();              ran = True
    if args.macro:             cmd_macro();             ran = True
    if args.intraday:          cmd_intraday();          ran = True
    if args.eod_rollup:        cmd_eod_rollup();        ran = True
    if args.ingest:            cmd_ingest();            ran = True
    if args.backfill:          cmd_backfill(args.years); ran = True
    if args.regime:            cmd_regime();            ran = True
    if args.train:             cmd_train();             ran = True
    if args.rotation_predict:  cmd_rotation_predict();  ran = True
    if args.publish:           cmd_publish();           ran = True
    if args.risk_sentinel:     cmd_risk_sentinel();     ran = True
    if not ran:
        parser.print_help()


if __name__ == "__main__":
    main()
