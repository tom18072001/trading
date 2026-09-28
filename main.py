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
    """16:00: roll the intraday bars into `sector_flow_daily`, THEN recompute
    the §16.2 leading features over it.

    The second step only ran on the UI Refresh path until 2026-09-25, so every
    scheduled row since 2026-08-25 had flow_z20..accumulation_age NULL on all
    15 sectors, and the 16:45 ranker (which fills NULL with 0) scored zeros
    (review 2026-09-24 §4.1/1). `predict_today` now also refuses to run on a
    session whose feature column is NULL for every sector.
    """
    from services.fast_ingest import rebuild_leading_features
    with get_session() as s:
        n = SectorIngestService(s).rollup_to_daily()
        print(f"[main] sector_flow_daily rows: {n}")
        m = rebuild_leading_features(s)
        print(f"[main] leading features rebuilt on {m} rows")


def cmd_regime() -> None:
    with get_session() as s:
        rec = RotationModelService(s).classify_regime()
        # classify_regime returns the last stored label, unchanged, when it
        # refuses to publish (no session today, or no usable daily VNINDEX).
        print(f"[main] regime ({rec.date or 'none stored'}, {rec.model_version}): "
              f"{rec.regime_label} conf={rec.confidence}")


def cmd_train() -> None:
    with get_session() as s:
        run = RotationModelService(s).train_ranker()
        print(f"[main] ranker trained: id={run.id} active={run.is_active}")


def cmd_rotation_predict() -> None:
    from services.rotation_model_service import FeaturesMissingError
    with get_session() as s:
        try:
            df = RotationModelService(s).predict_today()
        except FeaturesMissingError as e:
            # Exit non-zero so Task Scheduler's "Last Run Result" shows it; the
            # 17:00 publish makes the same check and publishes nothing.
            print(f"[main] rotation_predict REFUSED: {e}")
            raise SystemExit(2) from None
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


def cmd_daily_watch(top_n: int = 8) -> None:
    """Sổ + shortlist, ghi ra report/watch_<date>.md và data/watch_latest.json.

    Không gửi email (Tom 2026-09-16: "tạm thời chưa cần nhận email, để sau").
    Logic ở daily_watch/ — module riêng, skill chỉ gọi lệnh này rồi tóm tắt,
    nó không sinh lại code phân tích.
    """
    from daily_watch import service as daily_watch_service

    payload = daily_watch_service.run(top_n=top_n)
    alerts = payload["alerts"]
    print(f"[main] daily_watch: {len(payload['book']['positions'])} vị thế, "
          f"{len(alerts)} cần quyết định, {len(payload['shortlist'])} ứng viên "
          f"(dữ liệu phiên {payload['data_as_of']})")
    for a in alerts:
        sr = a.get("sell_range") or {}
        print(f"  - {a['kind']}: {a['symbol']} @ {a['last']} "
              f"(cửa sổ bán {sr.get('sell_from')} -> {sr.get('sell_by')})")
    for f in payload.get("_written", []):
        print(f"  -> {f}")


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
    parser.add_argument("--daily-watch", dest="daily_watch", action="store_true",
                        help="Sổ + shortlist ra file (job: daily_watch)")
    parser.add_argument("--top", type=int, default=8,
                        help="Số ứng viên trong --daily-watch (mặc định 8 = cỡ sổ của luật, §28)")
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
    if args.daily_watch:       cmd_daily_watch(args.top); ran = True
    if not ran:
        parser.print_help()


if __name__ == "__main__":
    main()
