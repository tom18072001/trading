"""Wait for backfill to finish, then rebuild leading features (flow_z20, stealth_score, ...)."""
import sys, os, time
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ.setdefault("STEALTH_SYNTHETIC_CLOSE", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_backfill.log")
DEADLINE = time.time() + 60 * 30  # 30 min max

while time.time() < DEADLINE:
    try:
        txt = open(LOG, "r", encoding="utf-8", errors="ignore").read()
    except FileNotFoundError:
        txt = ""
    if "DONE backfill" in txt or "DONE total=" in txt:
        break
    time.sleep(10)

from database.connection import SessionLocal
from scripts.fix_close_idx import rebuild_leading_features

s = SessionLocal()
try:
    n2 = rebuild_leading_features(s)
    print(f"[fix] leading_features updated: {n2}", flush=True)
finally:
    s.close()
print("REBUILD DONE", flush=True)
