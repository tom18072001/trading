"""Backfill 3 years of sector flow history for all 15 sectors."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.connection import SessionLocal
from services.sector_ingest_service import SectorIngestService
from config import PROXY_BASKETS

def main():
    sess = SessionLocal()
    svc = SectorIngestService(sess)
    total = 0
    for code in PROXY_BASKETS.keys():
        try:
            n = svc.backfill_sector(code, years=3)
            print(f"[{code}] +{n} rows", flush=True)
            total += n
        except Exception as e:
            print(f"[{code}] ERROR {e}", flush=True)
    print(f"DONE backfill total={total}", flush=True)
    # Compute and persist leading features (flow_z20, stealth_score, ...) into sector_flow_daily
    from scripts.fix_close_idx import rebuild_close_idx, rebuild_leading_features
    try:
        n_close = rebuild_close_idx(sess)
        print(f"[fix] close_idx updated: {n_close}", flush=True)
    except Exception as e:
        print(f"[fix] close_idx ERROR {e}", flush=True)
    try:
        n_feat = rebuild_leading_features(sess)
        print(f"[fix] leading_features updated: {n_feat}", flush=True)
    except Exception as e:
        print(f"[fix] leading_features ERROR {e}", flush=True)
    sess.close()

if __name__ == "__main__":
    main()
