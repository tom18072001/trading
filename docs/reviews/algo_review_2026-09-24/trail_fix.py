import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


import numpy as np, pandas as pd
from picks_eval import load_all, FACTORS, MIN_DV, TOTAL_COST
from scripts.tplus_strategy_bench import run_trail, run, RULES
p, f, vn = load_all()
ent = RULES["swing_prop_obv_top5"](f).fillna(False).astype(bool)
ent.loc[ent.index < pd.Timestamp("2023-01-01")] = False

def run_trail_fixed(entries, lo_atr, max_hold, arm_atr=1.0):
    op, lo, cl = p["open"].values, p["low"].values, p["close"].values
    A = (f["atr_pct"] / 100.0).values
    E = ((f["dv20"] > MIN_DV) & entries & f["atr_pct"].notna()).values
    out = []
    T = len(p["close"])
    for i in range(T - max_hold - 2):
        for j in np.flatnonzero(E[i]):
            e, a = op[i + 1, j], A[i, j]
            if not (np.isfinite(e) and e > 0 and np.isfinite(a) and a > 0):
                continue
            peak, held, px, why = e, max_hold, cl[i + max_hold, j], "time"
            for k in range(1, max_hold + 1):
                armed = peak >= e * (1 + arm_atr * a)       # uses PRIOR peak only
                if armed:
                    band = peak * (1 - lo_atr * a)
                    o_k, l_k = op[i + k, j], lo[i + k, j]
                    if np.isfinite(o_k) and o_k <= band:        # gap through the band
                        held, px, why = k, o_k, "gap"; break
                    if np.isfinite(l_k) and l_k <= band:
                        held, px, why = k, band, "band"; break
                c = cl[i + k, j]
                if np.isfinite(c):
                    peak = max(peak, c)                         # update AFTER the check
            if np.isfinite(px):
                out.append((p["close"].index[i], px / e - 1 - TOTAL_COST, held, why))
    return pd.DataFrame(out, columns=["date", "ret", "held", "exit"])

for h in (20, 40):
    t0 = run(ent, f, p, target_atr=99, stop_atr=99, max_hold=h, min_dv=MIN_DV, cost=TOTAL_COST)
    for lo_a in (3.5, 2.5):
        a = run_trail(ent, f, p, lo_atr=lo_a, max_hold=h, min_dv=MIN_DV, cost=TOTAL_COST, arm_atr=1.0)
        b = run_trail_fixed(ent, lo_a, h)
        per_sess = lambda t: t.ret.mean() / t.held.mean() * 252 * 100
        print(f"h={h} band {lo_a}xATR | repo bench: mean {a.ret.mean()*100:+.2f}%/trade, held {a.held.mean():.1f}, "
              f"~{per_sess(a):+.1f}%/yr per-session | FIXED: mean {b.ret.mean()*100:+.2f}%/trade, held {b.held.mean():.1f}, "
              f"~{per_sess(b):+.1f}%/yr, gap exits {(b.exit=='gap').mean()*100:.1f}%")
    print(f"h={h} time exit | mean {t0.ret.mean()*100:+.2f}%/trade, held {t0.held.mean():.1f}, ~{t0.ret.mean()/t0.held.mean()*252*100:+.1f}%/yr per-session")
